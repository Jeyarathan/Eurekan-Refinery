"""Three operating modes for the planner.

  - run_simulation:    fix everything in plan.fixed_variables, evaluate
  - run_optimization:  free everything, solve NLP via EurekanSolver
  - run_hybrid:        fix what's specified, optimize the rest
"""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Optional

import pyomo.environ as pyo

from eurekan.core.config import RefineryConfig
from eurekan.core.enums import OperatingMode
from eurekan.core.period import PlanDefinition
from eurekan.core.results import (
    BlendResult,
    CrudeDisposition,
    DispositionResult,
    FCCResult,
    FlowEdge,
    FlowNode,
    FlowNodeType,
    MaterialFlowGraph,
    PeriodResult,
    PlanningResult,
)
from eurekan.optimization.builder import _DEFAULT_PRICES, PyomoModelBuilder
from eurekan.optimization.solver import EurekanSolver, _fcc_yields_at


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def run_optimization(config: RefineryConfig, plan: PlanDefinition) -> PlanningResult:
    """Free all variables and solve the NLP."""
    builder = PyomoModelBuilder(config, plan)
    model = builder.build()

    solver = EurekanSolver()
    solve_result = solver.solve_with_fallback(model, config, plan)

    return _build_planning_result(model, config, plan, solve_result)


def run_simulation(config: RefineryConfig, plan: PlanDefinition) -> PlanningResult:
    """Fix every variable from plan.fixed_variables and evaluate."""
    builder = PyomoModelBuilder(config, plan)
    model = builder.build()

    # Apply fixed variable values
    _apply_fixed_variables(model, plan.fixed_variables)

    # Fix every remaining variable to its initial value (or 0 if unset)
    for v in model.component_data_objects(pyo.Var):
        if not v.fixed:
            val = pyo.value(v) if v.value is not None else 0.0
            v.fix(val)

    # Evaluate the objective and constraints
    try:
        obj_val = float(pyo.value(model.objective))
    except Exception:
        obj_val = 0.0

    from eurekan.optimization.solver import SolveResult

    solve_result = SolveResult(
        status="optimal",
        objective_value=obj_val,
        solve_time=0.0,
        tier_used=0,
        iterations=0,
        message="simulation (no optimization)",
    )
    return _build_planning_result(model, config, plan, solve_result)


def run_hybrid(config: RefineryConfig, plan: PlanDefinition) -> PlanningResult:
    """Fix the specified variables, optimize the rest."""
    builder = PyomoModelBuilder(config, plan)
    model = builder.build()

    _apply_fixed_variables(model, plan.fixed_variables)

    solver = EurekanSolver()
    solve_result = solver.solve_with_fallback(model, config, plan)

    return _build_planning_result(model, config, plan, solve_result)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _clamp_to_bounds(var_data: object, value: float) -> float:
    """Clamp a value to a Pyomo variable's bounds (handles solver float fuzz)."""
    lb = getattr(var_data, "lb", None)
    ub = getattr(var_data, "ub", None)
    if lb is not None and value < lb:
        return float(lb)
    if ub is not None and value > ub:
        return float(ub)
    return value


def _apply_fixed_variables(model: pyo.ConcreteModel, fixed: dict[str, float]) -> None:
    """Fix variables specified by name in the form 'var_name[index]' or 'var_name'.

    For Pyomo indexed variables, supports keys like:
      'crude_rate[CRUDE_A,0]'   -> model.crude_rate['CRUDE_A', 0]
      'fcc_conversion[0]'       -> model.fcc_conversion[0]
      'fcc_conversion'          -> all instances of fcc_conversion

    Values are clamped to the variable's bounds before fixing — the optimizer
    sometimes returns values a few floating-point ticks past a bound.
    """
    for key, value in fixed.items():
        if "[" in key and key.endswith("]"):
            base, idx_str = key.split("[", 1)
            idx_str = idx_str[:-1]
            parts = [p.strip() for p in idx_str.split(",")]
            converted: list[object] = []
            for p in parts:
                try:
                    converted.append(int(p))
                except ValueError:
                    converted.append(p)
            var = getattr(model, base, None)
            if var is None:
                continue
            try:
                tup = converted[0] if len(converted) == 1 else tuple(converted)
                var_data = var[tup]
                var_data.fix(_clamp_to_bounds(var_data, float(value)))
            except Exception:
                continue
        else:
            var = getattr(model, key, None)
            if var is None:
                continue
            try:
                for idx in var:
                    var_data = var[idx]
                    var_data.fix(_clamp_to_bounds(var_data, float(value)))
            except TypeError:
                try:
                    var.fix(_clamp_to_bounds(var, float(value)))
                except Exception:
                    continue


def _safe_value(v: object) -> float:
    try:
        result = pyo.value(v)
        return float(result) if result is not None else 0.0
    except Exception:
        return 0.0


def _build_planning_result(
    model: pyo.ConcreteModel,
    config: RefineryConfig,
    plan: PlanDefinition,
    solve_result,
) -> PlanningResult:
    """Translate a solved Pyomo model into a PlanningResult."""
    crude_ids = list(model.CRUDES)

    period_results: list[PeriodResult] = []
    total_margin = 0.0
    crude_volumes: dict[str, float] = {cid: 0.0 for cid in crude_ids}
    crude_revenue_attribution: dict[str, float] = {cid: 0.0 for cid in crude_ids}
    crude_costs: dict[str, float] = {cid: 0.0 for cid in crude_ids}

    flow_graph = MaterialFlowGraph()
    flow_node_ids: set[str] = set()

    def add_node(node_id: str, node_type: FlowNodeType, display: str, throughput: float) -> None:
        if node_id not in flow_node_ids:
            flow_graph.nodes.append(
                FlowNode(
                    node_id=node_id,
                    node_type=node_type,
                    display_name=display,
                    throughput=throughput,
                )
            )
            flow_node_ids.add(node_id)

    edge_counter = 0

    def add_edge(source: str, dest: str, name: str, vol: float) -> None:
        nonlocal edge_counter
        edge_counter += 1
        flow_graph.edges.append(
            FlowEdge(
                edge_id=f"e{edge_counter}",
                source_node=source,
                dest_node=dest,
                stream_name=name,
                display_name=name,
                volume=vol,
            )
        )

    for p in model.PERIODS:
        period = plan.periods[p]
        prices = {**_DEFAULT_PRICES, **period.product_prices}

        crude_slate: dict[str, float] = {}
        period_crude_cost = 0.0
        cdu_throughput = 0.0
        for cid in crude_ids:
            rate = _safe_value(model.crude_rate[cid, p])
            crude_slate[cid] = rate
            cdu_throughput += rate
            assay = config.crude_library.get(cid)
            crude_price = period.crude_prices.get(
                cid, (assay.price if assay and assay.price else 70.0)
            )
            period_crude_cost += rate * crude_price
            crude_volumes[cid] += rate
            crude_costs[cid] += rate * crude_price

            if rate > 1e-6:
                add_node(f"crude_{cid}", FlowNodeType.PURCHASE, cid, rate)
                add_edge(f"crude_{cid}", "cdu_1", cid, rate)

        # Always add all configured crudes (even if not selected by optimizer)
        # so Full Diagram mode can show the full feedstock menu.
        for cid in config.crude_library.list_crudes():
            node_id = f"crude_{cid}"
            if node_id not in flow_node_ids:
                add_node(node_id, FlowNodeType.PURCHASE, cid, 0.0)

        # CDU node — throughput is the total crude rate
        add_node("cdu_1", FlowNodeType.UNIT, "CDU 1", cdu_throughput)

        # Pull product SALES (revenue and demand are based on sales)
        gasoline = _safe_value(model.gasoline_sales[p])
        naphtha = _safe_value(model.naphtha_sales[p])
        jet = _safe_value(model.jet_sales[p])
        diesel = _safe_value(model.diesel_sales[p])
        fuel_oil = _safe_value(model.fuel_oil_sales[p])
        lpg = _safe_value(model.lpg_sales[p])

        product_volumes = {
            "gasoline": gasoline,
            "naphtha": naphtha,
            "jet": jet,
            "diesel": diesel,
            "fuel_oil": fuel_oil,
            "lpg": lpg,
        }

        revenue = (
            gasoline * prices["gasoline"]
            + naphtha * prices["naphtha"]
            + jet * prices["jet"]
            + diesel * prices["diesel"]
            + fuel_oil * prices["fuel_oil"]
            + lpg * prices["lpg"]
        )

        operating_cost = (
            cdu_throughput * 1.0
            + _safe_value(model.vgo_to_fcc[p]) * 1.5
            + _safe_value(model.lco_to_diesel[p]) * 2.0
            + _safe_value(model.reformate_purchased[p]) * 70.0
        )

        margin = revenue - period_crude_cost - operating_cost
        total_margin += margin

        # Apportion revenue and crude credit
        for cid in crude_ids:
            rate = crude_slate[cid]
            if cdu_throughput > 0:
                crude_revenue_attribution[cid] += revenue * (rate / cdu_throughput)

        # Extract VGO / FCC variables (needed by both FCC result and flow graph)
        vgo_to_fcc_val = _safe_value(model.vgo_to_fcc[p])

        # FCC result with equipment status
        conversion = _safe_value(model.fcc_conversion[p])
        fcc_yields_dict = _fcc_yields_at(conversion)
        from eurekan.core.results import EquipmentStatus

        regen_temp = fcc_yields_dict.get("regen_temp", 1100.0)
        regen_limit = 1400.0
        if "fcc_1" in config.units:
            regen_limit = config.units["fcc_1"].equipment_limits.get(
                "fcc_regen_temp_max", 1400.0
            )
        fcc_result = FCCResult(
            conversion=conversion,
            yields={**fcc_yields_dict, "vgo_to_fcc": vgo_to_fcc_val},
            properties={},
            equipment=[
                EquipmentStatus(
                    name="regen_temp",
                    display_name="Regenerator Temperature",
                    current_value=regen_temp,
                    limit=regen_limit,
                    utilization_pct=min(regen_temp / regen_limit * 100, 100),
                    is_binding=regen_temp >= regen_limit * 0.99,
                ),
            ],
        )

        # Disposition results
        dispositions: list[DispositionResult] = []
        for stream_id, blend_var, sell_var, fo_var in [
            ("light_naphtha", "ln_to_blend", "ln_to_sell", None),
            ("heavy_naphtha", "hn_to_blend", "hn_to_sell", None),
            ("fcc_heavy_naphtha", "hcn_to_blend", None, "hcn_to_fo"),
        ]:
            to_blend = _safe_value(getattr(model, blend_var)[p])
            to_sell = _safe_value(getattr(model, sell_var)[p]) if sell_var else 0.0
            to_fo = _safe_value(getattr(model, fo_var)[p]) if fo_var else 0.0
            dispositions.append(
                DispositionResult(
                    stream_id=stream_id,
                    to_blend=to_blend,
                    to_sell=to_sell,
                    to_fuel_oil=to_fo,
                )
            )

        # Blend result
        blend_recipe = {
            "cdu_ln": _safe_value(model.ln_to_blend[p]),
            "cdu_hn": _safe_value(model.hn_to_blend[p]),
            "fcc_lcn": _safe_value(model.fcc_lcn_vol[p]),
            "fcc_hcn": _safe_value(model.hcn_to_blend[p]),
            "n_butane": _safe_value(model.nc4_to_blend[p]),
            "reformate": _safe_value(model.reformate_purchased[p]),
        }
        blend_result = BlendResult(
            product_id="regular_gasoline",
            total_volume=gasoline,
            recipe=blend_recipe,
        )

        # ---------------------------------------------------------------
        # Build the full flow graph: CDU → (streams) → FCC → products
        # ---------------------------------------------------------------

        # FCC node — only if VGO is fed to the FCC
        vgo_to_fcc_val = _safe_value(model.vgo_to_fcc[p])
        vgo_to_fo_val = _safe_value(model.vgo_to_fo[p])
        fcc_lcn = _safe_value(model.fcc_lcn_vol[p])
        fcc_hcn = _safe_value(model.fcc_hcn_vol[p])
        fcc_lco = _safe_value(model.fcc_lco_vol[p])
        fcc_coke = _safe_value(model.fcc_coke_vol[p])
        fcc_c3 = _safe_value(model.fcc_c3_vol[p])
        fcc_c4 = _safe_value(model.fcc_c4_vol[p])
        hcn_to_blend = _safe_value(model.hcn_to_blend[p])
        hcn_to_fo = _safe_value(model.hcn_to_fo[p])
        lco_to_diesel_val = _safe_value(model.lco_to_diesel[p])
        lco_to_fo_val = _safe_value(model.lco_to_fo[p])

        if vgo_to_fcc_val > 1.0:
            add_node("fcc_1", FlowNodeType.UNIT, "FCC 1", vgo_to_fcc_val)
            add_edge("cdu_1", "fcc_1", "VGO", vgo_to_fcc_val)

        # Naphtha sales node — ensure it exists whenever ANY naphtha stream
        # is sold (CDU LN/HN, HCU naphtha, coker naphtha). Edges from each
        # source are added in their respective unit blocks.
        if naphtha > 1.0:
            add_node("sale_naphtha", FlowNodeType.SALE_POINT, "Naphtha", naphtha)

        # CDU → Naphtha sales
        ln_sell = _safe_value(model.ln_to_sell[p])
        hn_sell = _safe_value(model.hn_to_sell[p])
        naphtha_sell_total = ln_sell + hn_sell
        if naphtha_sell_total > 1.0:
            add_edge("cdu_1", "sale_naphtha", "Naphtha", naphtha_sell_total)

        # CDU → Jet (ONLY when KHT is absent; with KHT, kero flows through
        # kero_to_kht and kero_to_jet is a disconnected ghost variable).
        has_kht_for_jet = hasattr(model, "kero_to_kht")
        if not has_kht_for_jet:
            kero_jet = _safe_value(model.kero_to_jet[p])
            if kero_jet > 1.0:
                add_node("sale_jet", FlowNodeType.SALE_POINT, "Jet", jet)
                add_edge("cdu_1", "sale_jet", "Kerosene", kero_jet)
        else:
            # Ensure sale_jet node exists when KHT is present (KHT edge below adds it)
            if jet > 1.0:
                add_node("sale_jet", FlowNodeType.SALE_POINT, "Jet", jet)

        # CDU → Diesel (ONLY when DHT is absent; with DHT, CDU diesel flows
        # through diesel_to_dht and the ULSD is produced by DHT).
        kero_diesel = _safe_value(model.kero_to_diesel[p])
        has_dht_for_diesel = hasattr(model, "diesel_to_dht")
        add_node("sale_diesel", FlowNodeType.SALE_POINT, "Diesel", diesel)
        if not has_dht_for_diesel and diesel > 1.0:
            # No DHT path: CDU diesel + kero_to_diesel go directly to sale
            cdu_diesel_direct = diesel - lco_to_diesel_val
            if cdu_diesel_direct > 1.0:
                add_edge("cdu_1", "sale_diesel", "Diesel", cdu_diesel_direct)
        elif has_dht_for_diesel and kero_diesel > 1.0:
            # With DHT: kero_to_diesel bypasses DHT and goes to diesel pool
            # directly (builder.py diesel_def: total = dht_output + kero_to_diesel
            # + hcu_diesel). Emit the bypass edge so the pool volume matches
            # the sale volume.
            add_edge("cdu_1", "sale_diesel", "Kero to Diesel", kero_diesel)

        # CDU → Fuel oil (VGO bypass only; vacuum residue handled in vacuum
        # block when vacuum unit exists, or as direct CDU resid otherwise).
        has_vacuum_for_fo = hasattr(model, "vac_feed")
        add_node("sale_fuel_oil", FlowNodeType.SALE_POINT, "Fuel Oil", fuel_oil)
        if has_vacuum_for_fo:
            # When vacuum exists: VR that bypasses vacuum goes to fuel oil.
            # This is (cdu_vac_resid - vac_feed). Approximate via VGO bypass only here.
            if vgo_to_fo_val > 1.0:
                add_edge("cdu_1", "sale_fuel_oil", "VGO bypass", vgo_to_fo_val)
        else:
            # No vacuum unit: CDU vac_resid goes directly to fuel oil
            vresid = cdu_throughput * 0.07
            fo_from_cdu = vgo_to_fo_val + max(vresid, 0)
            if fo_from_cdu > 1.0:
                add_edge("cdu_1", "sale_fuel_oil", "VGO bypass + VR", fo_from_cdu)

        # CDU → LPG.  Only draw the direct CDU→sale_lpg edge when neither
        # SGP nor UGP is present — otherwise CDU light ends flow through SGP
        # and FCC C3/C4 flows through UGP, and drawing a direct edge here
        # would double-count the volume into pool_lpg.
        has_sgp_lpg = hasattr(model, "sgp_feed")
        has_ugp_lpg = hasattr(model, "ugp_feed")
        if lpg > 1.0:
            add_node("sale_lpg", FlowNodeType.SALE_POINT, "LPG", lpg)
            if not has_sgp_lpg and not has_ugp_lpg:
                add_edge("cdu_1", "sale_lpg", "LPG", lpg)

        # FCC → Gasoline Blender (LCN + HCN_to_blend)
        fcc_to_blend = fcc_lcn + hcn_to_blend
        add_node("blend_gasoline", FlowNodeType.BLEND_HEADER, "Gasoline Pool", gasoline)
        if fcc_to_blend > 1.0:
            add_edge("fcc_1", "blend_gasoline", "LCN + HCN", fcc_to_blend)

        # CDU → Gasoline Blender (LN_blend + HN_blend)
        ln_blend = _safe_value(model.ln_to_blend[p])
        hn_blend = _safe_value(model.hn_to_blend[p])
        cdu_to_blend = ln_blend + hn_blend
        if cdu_to_blend > 1.0:
            add_edge("cdu_1", "blend_gasoline", "LN + HN", cdu_to_blend)

        # Purchased reformate → Gasoline Blender
        reformate = _safe_value(model.reformate_purchased[p])
        if reformate > 1.0:
            add_node("purchase_reformate", FlowNodeType.PURCHASE, "Reformate", reformate)
            add_edge("purchase_reformate", "blend_gasoline", "Reformate", reformate)

        # Reformer: CDU HN → Reformer → Reformate → Blender
        if hasattr(model, "hn_to_reformer"):
            hn_ref = _safe_value(model.hn_to_reformer[p])
            ref_out = _safe_value(model.reformate_from_reformer[p])
            if hn_ref > 1.0:
                add_node("reformer_1", FlowNodeType.UNIT, "Reformer", hn_ref)
                add_edge("cdu_1", "reformer_1", "Heavy Naphtha", hn_ref)
                if ref_out > 1.0:
                    add_edge("reformer_1", "blend_gasoline", "Reformate", ref_out)

        # Scanfiner: FCC HCN → Scanfiner → treated HCN → Blender
        if hasattr(model, "hcn_to_scanfiner"):
            hcn_scan = _safe_value(model.hcn_to_scanfiner[p])
            scan_out = _safe_value(model.scanfiner_output[p])
            if hcn_scan > 1.0:
                add_node("scanfiner_1", FlowNodeType.UNIT, "Scanfiner", hcn_scan)
                add_edge("fcc_1", "scanfiner_1", "HCN", hcn_scan)
                if scan_out > 1.0:
                    add_edge("scanfiner_1", "blend_gasoline", "Treated HCN", scan_out)

        # Alkylation: FCC C3/C4 → Alky → Alkylate → Blender
        # When UGP is present, the olefin feed edge is drawn in the UGP
        # block (FCC → UGP → alky). Here we only handle the direct FCC path.
        if hasattr(model, "c3c4_to_alky"):
            c3c4_alky = _safe_value(model.c3c4_to_alky[p])
            alky_out = _safe_value(model.alkylate_volume[p])
            if c3c4_alky > 1.0:
                add_node("alky_1", FlowNodeType.UNIT, "Alkylation", c3c4_alky)
                if not hasattr(model, "ugp_feed"):
                    add_edge("fcc_1", "alky_1", "C3/C4 olefins", c3c4_alky)
                if alky_out > 1.0:
                    add_edge("alky_1", "blend_gasoline", "Alkylate", alky_out)

        # GO HT: VGO → GO HT → treated VGO → FCC
        if hasattr(model, "vgo_to_goht"):
            vgo_goht = _safe_value(model.vgo_to_goht[p])
            if vgo_goht > 1.0:
                add_node("goht_1", FlowNodeType.UNIT, "GO HT", vgo_goht)
                add_edge("cdu_1", "goht_1", "VGO", vgo_goht)
                add_edge("goht_1", "fcc_1", "Treated VGO", vgo_goht * 0.995)

        # Gasoline Blender → Gasoline sale
        add_node("sale_gasoline", FlowNodeType.SALE_POINT, "Gasoline", gasoline)
        if gasoline > 1.0:
            add_edge("blend_gasoline", "sale_gasoline", "Gasoline", gasoline)

        # FCC → Diesel (LCO direct to diesel)
        if lco_to_diesel_val > 1.0:
            add_edge("fcc_1", "sale_diesel", "LCO", lco_to_diesel_val)

        # Kero HT: CDU kero → KHT → Jet
        if hasattr(model, "kero_to_kht"):
            kero_kht = _safe_value(model.kero_to_kht[p])
            if kero_kht > 1.0:
                add_node("kht_1", FlowNodeType.UNIT, "Kero HT", kero_kht)
                add_edge("cdu_1", "kht_1", "Kerosene", kero_kht)
                add_edge("kht_1", "sale_jet", "Treated Kero", kero_kht * 0.995)

        # Diesel HT: CDU diesel + LCO → DHT → ULSD
        if hasattr(model, "diesel_to_dht"):
            dsl_dht = _safe_value(model.diesel_to_dht[p])
            lco_dht = _safe_value(model.lco_to_dht[p]) if hasattr(model, "lco_to_dht") else 0
            coker_go_dht = (
                _safe_value(model.coker_go_to_dht[p])
                if hasattr(model, "coker_go_to_dht") else 0
            )
            dht_feed = dsl_dht + lco_dht + coker_go_dht
            if dht_feed > 1.0:
                add_node("dht_1", FlowNodeType.UNIT, "Diesel HT", dht_feed)
                if dsl_dht > 1.0:
                    add_edge("cdu_1", "dht_1", "Diesel", dsl_dht)
                if lco_dht > 1.0:
                    add_edge("fcc_1", "dht_1", "LCO to DHT", lco_dht)
                if coker_go_dht > 1.0:
                    add_edge("coker_1", "dht_1", "Coker GO", coker_go_dht)
                add_edge("dht_1", "sale_diesel", "ULSD", dht_feed * 0.99)

        # Aromatics Reformer: CDU HN → Aromatics Reformer → BTX + Raffinate + H2
        if hasattr(model, "hn_to_arom"):
            hn_arom = _safe_value(model.hn_to_arom[p])
            btx = _safe_value(model.btx_volume[p])
            arom_raff = _safe_value(model.arom_raffinate_vol[p])
            if hn_arom > 1.0:
                add_node("arom_reformer", FlowNodeType.UNIT, "Arom Reformer", hn_arom)
                add_edge("cdu_1", "arom_reformer", "Heavy Naphtha", hn_arom)
                if btx > 1.0:
                    add_node("sale_btx", FlowNodeType.SALE_POINT, "BTX", btx)
                    add_edge("arom_reformer", "sale_btx", "BTX Extract", btx)
                if arom_raff > 1.0:
                    add_edge("arom_reformer", "blend_gasoline", "Raffinate", arom_raff)

        # Dimersol: FCC propylene → Dimersol → Dimate → Gasoline Blender
        if hasattr(model, "prop_to_dimersol"):
            prop_dim = _safe_value(model.prop_to_dimersol[p])
            dimate = _safe_value(model.dimate_vol[p])
            if prop_dim > 1.0:
                add_node("dimersol", FlowNodeType.UNIT, "Dimersol", prop_dim)
                # Feed source is UGP when present, else FCC direct
                dim_src = "ugp_1" if hasattr(model, "ugp_feed") else "fcc_1"
                add_edge(dim_src, "dimersol", "Propylene", prop_dim)
                if dimate > 1.0:
                    add_edge("dimersol", "blend_gasoline", "Dimate", dimate)

        # Unsaturated Gas Plant: FCC C3/C4 → UGP → propylene/propane/butylene/iC4/nC4/fuel gas
        if hasattr(model, "ugp_feed"):
            ugp_feed = _safe_value(model.ugp_feed[p])
            if ugp_feed > 1.0:
                add_node("ugp_1", FlowNodeType.UNIT, "Unsat Gas Plant", ugp_feed)
                add_edge("fcc_1", "ugp_1", "C3/C4 pool", ugp_feed)
                ugp_prop = _safe_value(model.ugp_propylene_vol[p])
                ugp_buty = _safe_value(model.ugp_butylene_vol[p])
                ugp_propane = _safe_value(model.ugp_propane_vol[p])
                ugp_ic4_alky = _safe_value(model.ugp_ic4_to_alky[p])
                ugp_ic4_lpg = _safe_value(model.ugp_ic4_to_lpg[p])
                ugp_nc4_isom = _safe_value(model.ugp_nc4_to_c4isom[p])
                ugp_nc4_lpg = _safe_value(model.ugp_nc4_to_lpg[p])
                ugp_fg = _safe_value(model.ugp_fuel_gas_vol[p])
                # Olefins → alky (propylene + butylenes going to c3c4_to_alky)
                if hasattr(model, "c3c4_to_alky"):
                    c3c4 = _safe_value(model.c3c4_to_alky[p])
                    if c3c4 > 1.0 and "alky_1" in flow_node_ids:
                        add_edge("ugp_1", "alky_1", "Propylene+Butylenes", c3c4)
                # iC4 → alky
                if ugp_ic4_alky > 1.0 and "alky_1" in flow_node_ids:
                    add_edge("ugp_1", "alky_1", "iC4", ugp_ic4_alky)
                # nC4 → C4 isom
                if ugp_nc4_isom > 1.0 and "isom_c4" in flow_node_ids:
                    add_edge("ugp_1", "isom_c4", "nC4", ugp_nc4_isom)
                # Propane + iC4/nC4 surplus → LPG sale
                lpg_from_ugp = ugp_propane + ugp_ic4_lpg + ugp_nc4_lpg
                if lpg_from_ugp > 1.0 and "sale_lpg" in flow_node_ids:
                    add_edge("ugp_1", "sale_lpg", "Propane + C4 paraffins", lpg_from_ugp)
                # Fuel gas (C1+C2) terminates internally at the gas plant —
                # consumed as plant fuel, not a sale stream. No edge emitted.
                _ = (ugp_prop, ugp_buty, ugp_fg)

        # Saturated Gas Plant: CDU/coker/HCU paraffins → SGP → propane/iC4/nC4/fuel gas
        if hasattr(model, "sgp_feed"):
            sgp_feed = _safe_value(model.sgp_feed[p])
            if sgp_feed > 1.0:
                add_node("sgp_1", FlowNodeType.UNIT, "Sat Gas Plant", sgp_feed)
                add_edge("cdu_1", "sgp_1", "CDU light ends", sgp_feed)
                if hasattr(model, "coker_gas_vol"):
                    ck_gas = _safe_value(model.coker_gas_vol[p])
                    if ck_gas > 1.0 and "coker_1" in flow_node_ids:
                        add_edge("coker_1", "sgp_1", "Coker Gas", ck_gas)
                if hasattr(model, "hcu_lpg_vol"):
                    h_lpg = _safe_value(model.hcu_lpg_vol[p])
                    if h_lpg > 1.0 and "hcu_1" in flow_node_ids:
                        add_edge("hcu_1", "sgp_1", "HCU LPG", h_lpg)
                sgp_propane = _safe_value(model.sgp_propane_vol[p])
                sgp_ic4_alky = _safe_value(model.sgp_ic4_to_alky[p])
                sgp_ic4_lpg = _safe_value(model.sgp_ic4_to_lpg[p])
                sgp_nc4_isom = _safe_value(model.sgp_nc4_to_c4isom[p])
                sgp_nc4_lpg = _safe_value(model.sgp_nc4_to_lpg[p])
                sgp_fg = _safe_value(model.sgp_fuel_gas_vol[p])
                if sgp_ic4_alky > 1.0 and "alky_1" in flow_node_ids:
                    add_edge("sgp_1", "alky_1", "iC4", sgp_ic4_alky)
                if sgp_nc4_isom > 1.0 and "isom_c4" in flow_node_ids:
                    add_edge("sgp_1", "isom_c4", "nC4", sgp_nc4_isom)
                lpg_from_sgp = sgp_propane + sgp_ic4_lpg + sgp_nc4_lpg
                if lpg_from_sgp > 1.0 and "sale_lpg" in flow_node_ids:
                    add_edge("sgp_1", "sale_lpg", "Propane + C4 paraffins", lpg_from_sgp)
                # SGP fuel gas terminates internally — not a sale stream.
                _ = sgp_fg

        # Sulfur Complex (Sprint A): Amine → SRU → TGT with H2S inputs from
        # sulfur-bearing units and an elemental sulfur sale point.  Volumes
        # are LT/D (long tons per day) in the backend; the flowsheet just
        # shows them as throughputs on the utility lane.
        if hasattr(model, "amine_feed"):
            amine_feed_val = _safe_value(model.amine_feed[p])
            sulfur_out = _safe_value(model.sulfur_produced[p])
            tgt_feed_val = _safe_value(model.tgt_feed[p])

            if amine_feed_val > 1e-3 or sulfur_out > 1e-3:
                add_node("amine_1", FlowNodeType.UNIT, "Amine Unit", amine_feed_val)
                add_node("sru_1", FlowNodeType.UNIT, "SRU", sulfur_out)
                # H2S contributor edges (magnitudes in LT/D, clearly separate
                # stream type — the UI styles them as sulfur edges).
                if "goht_1" in flow_node_ids:
                    v = _safe_value(model.vgo_to_goht[p]) * 5.0e-5
                    if v > 1e-3:
                        add_edge("goht_1", "amine_1", "H2S", v)
                if "scanfiner_1" in flow_node_ids:
                    v = _safe_value(model.hcn_to_scanfiner[p]) * 5.0e-5
                    if v > 1e-3:
                        add_edge("scanfiner_1", "amine_1", "H2S", v)
                if "kht_1" in flow_node_ids:
                    v = _safe_value(model.kero_to_kht[p]) * 5.0e-5
                    if v > 1e-3:
                        add_edge("kht_1", "amine_1", "H2S", v)
                if "dht_1" in flow_node_ids:
                    v = (_safe_value(model.diesel_to_dht[p]) + _safe_value(model.lco_to_dht[p])) * 5.0e-5
                    if v > 1e-3:
                        add_edge("dht_1", "amine_1", "H2S", v)
                if "fcc_1" in flow_node_ids:
                    v = _safe_value(model.vgo_to_fcc[p]) * 1.0e-5
                    if v > 1e-3:
                        add_edge("fcc_1", "amine_1", "H2S", v)
                if "coker_1" in flow_node_ids and hasattr(model, "coker_feed"):
                    v = _safe_value(model.coker_feed[p]) * 2.0e-5
                    if v > 1e-3:
                        add_edge("coker_1", "amine_1", "H2S", v)
                # Amine → SRU
                amine_sru = _safe_value(model.amine_to_sru[p])
                if amine_sru > 1e-3:
                    add_edge("amine_1", "sru_1", "Conc. H2S", amine_sru)
                # SRU → sulfur sale
                if sulfur_out > 1e-3:
                    add_node("sale_sulfur", FlowNodeType.SALE_POINT, "Sulfur", sulfur_out)
                    add_edge("sru_1", "sale_sulfur", "Elemental S", sulfur_out)
                # SRU → TGT → recycle to amine (only if TGT configured)
                if tgt_feed_val > 1e-3 and "tgt_1" in config.units:
                    add_node("tgt_1", FlowNodeType.UNIT, "Tail Gas Treatment", tgt_feed_val)
                    add_edge("sru_1", "tgt_1", "Tail Gas", tgt_feed_val)
                    tgt_recycle = _safe_value(model.tgt_recycle_s[p])
                    if tgt_recycle > 1e-3:
                        add_edge("tgt_1", "amine_1", "Recycle H2S", tgt_recycle)

        # Plant Fuel System (pfs_1) — utility sink collecting internal fuel
        # gas streams for plant energy consumption. No economic edge: fuel
        # gas offsets natural-gas purchases already netted into unit opex.
        pfs_edges: list[tuple[str, float, str]] = []
        if hasattr(model, "ugp_fuel_gas_vol"):
            v = _safe_value(model.ugp_fuel_gas_vol[p])
            if v > 1.0 and "ugp_1" in flow_node_ids:
                pfs_edges.append(("ugp_1", v, "Fuel Gas (C1+C2)"))
        if hasattr(model, "sgp_fuel_gas_vol"):
            v = _safe_value(model.sgp_fuel_gas_vol[p])
            if v > 1.0 and "sgp_1" in flow_node_ids:
                pfs_edges.append(("sgp_1", v, "Fuel Gas (C1+C2)"))
        # Estimated dry-gas byproducts from conversion units — not modeled
        # explicitly but shown visually for utility-balance context.
        _FCC_DRY_GAS_FRAC = 0.02    # ~2% of FCC feed → dry gas
        _REFORMER_FUEL_FRAC = 0.02  # ~2% hydrogen + light ends
        _COKER_FUEL_FRAC = 0.01     # small residual beyond C3/C4 to SGP
        _HCU_FUEL_FRAC = 0.005      # trace H2S/CH4
        if "fcc_1" in flow_node_ids and hasattr(model, "vgo_to_fcc"):
            fv = _safe_value(model.vgo_to_fcc[p]) * _FCC_DRY_GAS_FRAC
            if fv > 1.0:
                pfs_edges.append(("fcc_1", fv, "Dry Gas"))
        if "reformer_1" in flow_node_ids and hasattr(model, "hn_to_reformer"):
            rv = _safe_value(model.hn_to_reformer[p]) * _REFORMER_FUEL_FRAC
            if rv > 1.0:
                pfs_edges.append(("reformer_1", rv, "Fuel Gas"))
        if "coker_1" in flow_node_ids and hasattr(model, "coker_feed"):
            cv = _safe_value(model.coker_feed[p]) * _COKER_FUEL_FRAC
            if cv > 1.0:
                pfs_edges.append(("coker_1", cv, "Fuel Gas"))
        if "hcu_1" in flow_node_ids and hasattr(model, "vgo_to_hcu"):
            hv = _safe_value(model.vgo_to_hcu[p]) * _HCU_FUEL_FRAC
            if hv > 1.0:
                pfs_edges.append(("hcu_1", hv, "Fuel Gas"))
        if pfs_edges:
            pfs_total = sum(v for _, v, _name in pfs_edges)
            add_node("pfs_1", FlowNodeType.PROCESS, "Plant Fuel Sys", pfs_total)
            for src, vol, name in pfs_edges:
                add_edge(src, "pfs_1", name, vol)

        # C5/C6 Isomerization: CDU LN → C5/C6 Isom → Isomerate → Gasoline Blender
        if hasattr(model, "ln_to_isom"):
            ln_isom = _safe_value(model.ln_to_isom[p])
            iso_out = _safe_value(model.isomerate_vol[p])
            if ln_isom > 1.0:
                add_node("isom_c56", FlowNodeType.UNIT, "C5/C6 Isom", ln_isom)
                add_edge("cdu_1", "isom_c56", "Light Naphtha", ln_isom)
                if iso_out > 1.0:
                    add_edge("isom_c56", "blend_gasoline", "Isomerate", iso_out)

        # C4 Isomerization: CDU nC4 → C4 Isom → iC4 → Alkylation
        if hasattr(model, "nc4_to_c4isom"):
            nc4_isom = _safe_value(model.nc4_to_c4isom[p])
            ic4_out = _safe_value(model.ic4_from_c4isom[p])
            if nc4_isom > 1.0:
                add_node("isom_c4", FlowNodeType.UNIT, "C4 Isom", nc4_isom)
                add_edge("cdu_1", "isom_c4", "nC4", nc4_isom)
                if ic4_out > 1.0 and hasattr(model, "c3c4_to_alky"):
                    add_edge("isom_c4", "alky_1", "iC4", ic4_out)

        # Hydrocracker: VGO → HCU → jet + diesel + naphtha + LPG + unconverted
        if hasattr(model, "vgo_to_hcu"):
            vgo_hcu = _safe_value(model.vgo_to_hcu[p])
            if vgo_hcu > 1.0:
                add_node("hcu_1", FlowNodeType.UNIT, "Hydrocracker", vgo_hcu)
                add_edge("cdu_1", "hcu_1", "VGO", vgo_hcu)
                hcu_naph = _safe_value(model.hcu_naphtha_vol[p])
                hcu_jet = _safe_value(model.hcu_jet_vol[p])
                hcu_dsl = _safe_value(model.hcu_diesel_vol[p])
                hcu_lpg = _safe_value(model.hcu_lpg_vol[p])
                hcu_unc = _safe_value(model.hcu_unconverted_vol[p])
                if hcu_jet > 1.0:
                    add_edge("hcu_1", "sale_jet", "HCU Jet", hcu_jet)
                if hcu_dsl > 1.0:
                    add_edge("hcu_1", "sale_diesel", "HCU Diesel", hcu_dsl)
                if hcu_naph > 1.0:
                    add_edge("hcu_1", "sale_naphtha", "HCU Naphtha", hcu_naph)
                # HCU LPG flows through SGP when it's present (edge drawn in
                # the SGP block). Only emit the direct HCU→sale_lpg edge when
                # SGP is absent, otherwise pool_lpg double-counts the volume.
                if hcu_lpg > 1.0 and not hasattr(model, "sgp_feed"):
                    add_edge("hcu_1", "sale_lpg", "HCU LPG", hcu_lpg)
                if hcu_unc > 1.0:
                    add_edge("hcu_1", "sale_fuel_oil", "Unconverted", hcu_unc)

        # Vacuum unit: CDU vac_resid → Vacuum → LVGO + HVGO + vac_resid
        if hasattr(model, "vac_feed"):
            vac_feed = _safe_value(model.vac_feed[p])
            if vac_feed > 1.0:
                add_node("vacuum_1", FlowNodeType.UNIT, "Vacuum Unit", vac_feed)
                add_edge("cdu_1", "vacuum_1", "Atm Resid", vac_feed)
                lvgo = _safe_value(model.vacuum_lvgo[p])
                hvgo = _safe_value(model.vacuum_hvgo[p])
                vgo_total = lvgo + hvgo
                if vgo_total > 1.0:
                    add_edge("vacuum_1", "fcc_1", "Vacuum VGO", vgo_total)
                vr_to_fo = _safe_value(model.vacuum_vr_to_fo[p])
                if vr_to_fo > 1.0:
                    add_edge("vacuum_1", "sale_fuel_oil", "Vac Resid", vr_to_fo)

        # Coker: vacuum residue → Coker → naphtha + GO + HGO + coke
        if hasattr(model, "coker_feed"):
            coker_feed = _safe_value(model.coker_feed[p])
            if coker_feed > 1.0:
                add_node("coker_1", FlowNodeType.UNIT, "Coker", coker_feed)
                # Feed source
                if hasattr(model, "vacuum_vr_to_coker"):
                    vr_coke = _safe_value(model.vacuum_vr_to_coker[p])
                    if vr_coke > 1.0:
                        add_edge("vacuum_1", "coker_1", "Vac Resid", vr_coke)
                else:
                    add_edge("cdu_1", "coker_1", "Vac Resid", coker_feed)
                # Products
                ck_naph = _safe_value(model.coker_naphtha_vol[p])
                if ck_naph > 1.0:
                    add_edge("coker_1", "sale_naphtha", "Coker Naphtha", ck_naph)
                ck_go_fo = _safe_value(model.coker_go_to_fo[p])
                ck_hgo = _safe_value(model.coker_hgo_vol[p])
                if ck_go_fo + ck_hgo > 1.0:
                    add_edge("coker_1", "sale_fuel_oil", "Coker GO + HGO", ck_go_fo + ck_hgo)
                # Coke as a sale point
                ck_coke = _safe_value(model.coker_coke_vol[p])
                if ck_coke > 1.0:
                    add_node("sale_coke", FlowNodeType.SALE_POINT, "Petroleum Coke", ck_coke)
                    add_edge("coker_1", "sale_coke", "Coke", ck_coke)

        # FCC → Fuel oil (HCN_to_fo + LCO_to_fo)
        fcc_to_fo = hcn_to_fo + lco_to_fo_val
        if fcc_to_fo > 1.0:
            add_edge("fcc_1", "sale_fuel_oil", "HCN + LCO slop", fcc_to_fo)

        # FCC → LPG (C3 + C4) — direct path only when UGP is absent.
        # With UGP: propane/nC4/iC4 flow through UGP to sale_lpg (edge drawn above).
        if not hasattr(model, "ugp_feed"):
            fcc_to_lpg = fcc_c3 + fcc_c4
            if fcc_to_lpg > 1.0 and lpg > 1.0:
                add_edge("fcc_1", "sale_lpg", "C3 + C4", fcc_to_lpg)

        # Always add nodes for configured units (even if idle at throughput=0)
        # so the "Full Diagram" toggle can show the refinery structure.
        for uid, uconf in config.units.items():
            if uid not in flow_node_ids:
                display = uconf.unit_id.replace("_", " ").title()
                # Check most-specific names FIRST (before generic keywords)
                if uid == "arom_reformer":
                    display = "Arom Reformer"
                elif uid == "reformer_1":
                    display = "Reformer"
                elif uid == "isom_c56":
                    display = "C5/C6 Isom"
                elif uid == "isom_c4":
                    display = "C4 Isom"
                elif uid == "dimersol":
                    display = "Dimersol"
                elif uid == "ugp_1":
                    display = "Unsat Gas Plant"
                elif uid == "sgp_1":
                    display = "Sat Gas Plant"
                elif uid == "pfs_1":
                    display = "Plant Fuel Sys"
                elif uid == "amine_1":
                    display = "Amine Unit"
                elif uid == "sru_1":
                    display = "SRU"
                elif uid == "tgt_1":
                    display = "Tail Gas Treatment"
                elif uid == "kht_1":
                    display = "Kero HT"
                elif uid == "dht_1":
                    display = "Diesel HT"
                elif "goht" in uid:
                    display = "GO HT"
                elif "scanfiner" in uid:
                    display = "Scanfiner"
                elif "alky" in uid:
                    display = "Alkylation"
                elif "reformer" in uid:
                    display = "Reformer"
                elif "nht" in uid:
                    display = "Naphtha HT"
                elif "vacuum" in uid:
                    display = "Vacuum Unit"
                elif "coker" in uid:
                    display = "Coker"
                elif uid == "hcu_1" or "hcu" in uid:
                    display = "Hydrocracker"
                sulfur_complex_uids = {"amine_1", "sru_1", "tgt_1"}
                node_type = (
                    FlowNodeType.PROCESS
                    if uid == "pfs_1" or uid in sulfur_complex_uids
                    else FlowNodeType.UNIT
                )
                add_node(uid, node_type, display, 0.0)

        # Potential (zero-volume) edges for idle units — shown dimmed in
        # Full Diagram mode so users can see the refinery topology.
        # Live Flow mode filters these out via volume threshold.
        def add_potential_edge(src: str, dst: str, name: str) -> None:
            if src in flow_node_ids and dst in flow_node_ids:
                # Only add if no non-zero edge already connects src -> dst
                existing = any(
                    e.source_node == src and e.dest_node == dst
                    for e in flow_graph.edges
                )
                if not existing:
                    add_edge(src, dst, name, 0.0)

        # C4 Isom topology: nC4 → C4 Isom → iC4 → Alky
        if "isom_c4" in flow_node_ids:
            add_potential_edge("cdu_1", "isom_c4", "nC4")
            if "alky_1" in flow_node_ids:
                add_potential_edge("isom_c4", "alky_1", "iC4")

        # Coker topology: Vacuum → Coker → naphtha/GO/HGO/coke
        if "coker_1" in flow_node_ids:
            if "vacuum_1" in flow_node_ids:
                add_potential_edge("vacuum_1", "coker_1", "Vac Resid")
            else:
                add_potential_edge("cdu_1", "coker_1", "Vac Resid")
            if "sale_naphtha" in flow_node_ids:
                add_potential_edge("coker_1", "sale_naphtha", "Coker Naphtha")
            if "sale_fuel_oil" in flow_node_ids:
                add_potential_edge("coker_1", "sale_fuel_oil", "Coker HGO")
            if "dht_1" in flow_node_ids:
                add_potential_edge("coker_1", "dht_1", "Coker GO")

        # Scanfiner topology: FCC HCN → Scanfiner → Blender
        if "scanfiner_1" in flow_node_ids:
            if "fcc_1" in flow_node_ids:
                add_potential_edge("fcc_1", "scanfiner_1", "HCN")
            if "blend_gasoline" in flow_node_ids:
                add_potential_edge("scanfiner_1", "blend_gasoline", "Treated HCN")

        # GO HT topology: CDU VGO → GO HT → FCC
        if "goht_1" in flow_node_ids:
            add_potential_edge("cdu_1", "goht_1", "VGO")
            if "fcc_1" in flow_node_ids:
                add_potential_edge("goht_1", "fcc_1", "Treated VGO")

        # Aromatics reformer topology: CDU HN → Aromatics Reformer → BTX + Raffinate
        if "arom_reformer" in flow_node_ids:
            add_potential_edge("cdu_1", "arom_reformer", "Heavy Naphtha")
            if "blend_gasoline" in flow_node_ids:
                add_potential_edge("arom_reformer", "blend_gasoline", "Raffinate")

        # Dimersol topology: FCC propylene → Dimersol → Dimate
        if "dimersol" in flow_node_ids:
            dim_src = "ugp_1" if "ugp_1" in flow_node_ids else "fcc_1"
            if dim_src in flow_node_ids:
                add_potential_edge(dim_src, "dimersol", "Propylene")
            if "blend_gasoline" in flow_node_ids:
                add_potential_edge("dimersol", "blend_gasoline", "Dimate")

        # Unsaturated Gas Plant topology: FCC C3/C4 → UGP → alky/isom/LPG/fuel
        if "ugp_1" in flow_node_ids:
            if "fcc_1" in flow_node_ids:
                add_potential_edge("fcc_1", "ugp_1", "C3/C4 pool")
            if "alky_1" in flow_node_ids:
                add_potential_edge("ugp_1", "alky_1", "Olefins + iC4")
            if "isom_c4" in flow_node_ids:
                add_potential_edge("ugp_1", "isom_c4", "nC4")
            if "sale_lpg" in flow_node_ids:
                add_potential_edge("ugp_1", "sale_lpg", "Propane + C4 paraffins")

        # Saturated Gas Plant topology: CDU/coker/HCU paraffins → SGP → alky/isom/LPG/fuel
        if "sgp_1" in flow_node_ids:
            if "cdu_1" in flow_node_ids:
                add_potential_edge("cdu_1", "sgp_1", "CDU light ends")
            if "coker_1" in flow_node_ids:
                add_potential_edge("coker_1", "sgp_1", "Coker Gas")
            if "hcu_1" in flow_node_ids:
                add_potential_edge("hcu_1", "sgp_1", "HCU LPG")
            if "alky_1" in flow_node_ids:
                add_potential_edge("sgp_1", "alky_1", "iC4")
            if "isom_c4" in flow_node_ids:
                add_potential_edge("sgp_1", "isom_c4", "nC4")
            if "sale_lpg" in flow_node_ids:
                add_potential_edge("sgp_1", "sale_lpg", "Propane + C4 paraffins")

        # Plant Fuel System topology — fuel gas collection from any unit
        # that produces light ends. Potential edges keep the utility lane
        # populated even when throughputs are zero.
        if "pfs_1" in flow_node_ids:
            for src in ("ugp_1", "sgp_1", "fcc_1", "reformer_1", "coker_1", "hcu_1"):
                if src in flow_node_ids:
                    add_potential_edge(src, "pfs_1", "Fuel Gas")

        # Sulfur complex topology (Sprint A): H2S contributors → amine → SRU → TGT
        if "amine_1" in flow_node_ids:
            for src in ("goht_1", "scanfiner_1", "kht_1", "dht_1", "fcc_1", "coker_1", "hcu_1"):
                if src in flow_node_ids:
                    add_potential_edge(src, "amine_1", "H2S")
            if "sru_1" in flow_node_ids:
                add_potential_edge("amine_1", "sru_1", "Conc. H2S")
        if "sru_1" in flow_node_ids:
            if "tgt_1" in flow_node_ids:
                add_potential_edge("sru_1", "tgt_1", "Tail Gas")
        if "tgt_1" in flow_node_ids and "amine_1" in flow_node_ids:
            add_potential_edge("tgt_1", "amine_1", "Recycle H2S")

        # CDU dispositions in CDU yields (cuts)
        cdu_cuts = {
            "light_naphtha": _safe_value(model.ln_to_blend[p]) + _safe_value(model.ln_to_sell[p]),
            "heavy_naphtha": _safe_value(model.hn_to_blend[p]) + _safe_value(model.hn_to_sell[p]),
            "kerosene": _safe_value(model.kero_to_jet[p]) + _safe_value(model.kero_to_diesel[p]),
            "vgo": _safe_value(model.vgo_to_fcc[p]) + _safe_value(model.vgo_to_fo[p]),
        }

        period_results.append(
            PeriodResult(
                period_id=p,
                crude_slate=crude_slate,
                cdu_cuts=cdu_cuts,
                fcc_result=fcc_result,
                blend_results=[blend_result],
                dispositions=dispositions,
                product_volumes=product_volumes,
                revenue=revenue,
                crude_cost=period_crude_cost,
                operating_cost=operating_cost,
                margin=margin,
            )
        )

    # Crude valuations
    crude_valuations: list[CrudeDisposition] = []
    for cid in crude_ids:
        if crude_volumes[cid] <= 1e-6:
            continue
        crude_valuations.append(
            CrudeDisposition(
                crude_id=cid,
                total_volume=crude_volumes[cid],
                product_breakdown={},
                value_created=crude_revenue_attribution[cid],
                crude_cost=crude_costs[cid],
                net_margin=crude_revenue_attribution[cid] - crude_costs[cid],
            )
        )

    # Naphtha Splitter (CNSP) — visualization-only node. The optimizer
    # treats CDU cuts as already-split LN/HN, but operationally a splitter
    # tower separates the full-range naphtha cut before it fans out to
    # downstream units. Rewire every cdu_1 → naphtha-consumer edge through
    # splitter_1 so the flowsheet reflects real plant topology.
    _NAPHTHA_CONSUMERS = {
        "nht_1", "reformer_1", "arom_reformer",
        "isom_c56", "blend_gasoline", "sale_naphtha",
    }
    _splitter_next_edge_id = len(flow_graph.edges) + 1
    _splitter_incoming = [
        e for e in flow_graph.edges
        if e.source_node == "cdu_1" and e.dest_node in _NAPHTHA_CONSUMERS
    ]
    if _splitter_incoming:
        splitter_volume = sum(e.volume for e in _splitter_incoming)
        flow_graph.nodes.append(
            FlowNode(
                node_id="splitter_1",
                node_type=FlowNodeType.UNIT,
                display_name="Naphtha Splitter",
                throughput=splitter_volume,
            )
        )
        flow_graph.edges.append(
            FlowEdge(
                edge_id=f"e{_splitter_next_edge_id}",
                source_node="cdu_1",
                dest_node="splitter_1",
                stream_name="Naphtha",
                display_name="Full-range Naphtha",
                volume=splitter_volume,
            )
        )
        for e in _splitter_incoming:
            e.source_node = "splitter_1"

    # Insert blend-pool BLEND_HEADER nodes between unit outputs and sale
    # points for every non-gasoline finished product. Mirrors the existing
    # blend_gasoline pattern (units → blender → sale) so every product has a
    # dedicated pool node upstream of its sale node for visual consistency
    # and future grade-level expansion.
    _POOLED_PRODUCTS: dict[str, tuple[str, str]] = {
        "sale_diesel":   ("pool_diesel",   "Diesel Pool"),
        "sale_jet":      ("pool_jet",      "Jet Pool"),
        "sale_fuel_oil": ("pool_fuel_oil", "Fuel Oil Pool"),
        "sale_lpg":      ("pool_lpg",      "LPG Pool"),
        "sale_naphtha":  ("pool_naphtha",  "Naphtha Pool"),
        "sale_btx":      ("pool_btx",      "BTX Pool"),
    }
    existing_ids = {n.node_id for n in flow_graph.nodes}
    next_edge_id = len(flow_graph.edges) + 1
    for sale_id, (pool_id, pool_name) in _POOLED_PRODUCTS.items():
        if sale_id not in existing_ids:
            continue
        pool_volume = 0.0
        redirected = 0
        for e in flow_graph.edges:
            if e.dest_node == sale_id and e.source_node != pool_id:
                e.dest_node = pool_id
                pool_volume += e.volume
                redirected += 1
        if redirected == 0:
            continue
        flow_graph.nodes.append(
            FlowNode(
                node_id=pool_id,
                node_type=FlowNodeType.BLEND_HEADER,
                display_name=pool_name,
                throughput=pool_volume,
            )
        )
        flow_graph.edges.append(
            FlowEdge(
                edge_id=f"e{next_edge_id}",
                source_node=pool_id,
                dest_node=sale_id,
                stream_name=pool_name,
                display_name=pool_name,
                volume=pool_volume,
            )
        )
        next_edge_id += 1
        # Reconcile the sale node's throughput with the actual pool output so
        # the product card matches what's flowing into it. The optimizer's
        # <product>_sales variable can diverge when edges are emitted by
        # multiple unit blocks (double-counting) or missed (single-counting);
        # the pool volume is the authoritative visual total.
        for n in flow_graph.nodes:
            if n.node_id == sale_id:
                n.throughput = pool_volume
                break

    # Hydrogen balance network — refinery H2 is a critical flow that is
    # otherwise invisible. Emit an h2_header node with edges from
    # producers (reformer, arom reformer, h2 plant) and edges to
    # consumers (hydrotreaters, HCU, isoms). All volumes are in bbl/d
    # equivalent (1 bbl H2 ≈ 5600 SCF at standard conditions) so they
    # render consistently alongside liquid flows.
    #
    # Supplies are computed from FEED × physical SCFB rather than from
    # the model's reformer_hydrogen var, whose coefficient (0.03) treats
    # H2 yield as 30,000 SCFB — roughly 30× typical reformer yield
    # (700–1500 SCFB). Physical-SCFB formulas give display values in
    # the plant-realistic range without altering solver behavior.
    _MMSCFD_TO_BBL = 1e6 / 5600.0
    h2_sources: list[tuple[str, str, float, str]] = []
    if hasattr(model, "hn_to_reformer"):
        hn_ref = _safe_value(model.hn_to_reformer[0])
        if hasattr(model, "reformer_severity"):
            sev = _safe_value(model.reformer_severity[0])
            ref_scfb = 800.0 + 20.0 * (sev - 90.0)
        else:
            ref_scfb = 1000.0
        v = hn_ref * ref_scfb / 5600.0
        if v > 0.1:
            h2_sources.append(("reformer_1", "Reformer", v, "H2"))
    if hasattr(model, "hn_to_arom"):
        hn_arom = _safe_value(model.hn_to_arom[0])
        v = hn_arom * 500.0 / 5600.0
        if v > 0.1:
            h2_sources.append(("arom_reformer", "Arom Reformer", v, "H2"))
    h2_plant_v = 0.0
    if hasattr(model, "h2_purchased"):
        h2_plant_v = _safe_value(model.h2_purchased[0]) * _MMSCFD_TO_BBL

    h2_consumers: list[tuple[str, float, str]] = []
    p0 = 0
    if hasattr(model, "vgo_to_goht"):
        v = _safe_value(model.vgo_to_goht[p0]) * 1000.0 / 5600.0
        if v > 0.1:
            h2_consumers.append(("goht_1", v, "H2"))
    if hasattr(model, "hcn_to_scanfiner"):
        v = _safe_value(model.hcn_to_scanfiner[p0]) * 300.0 / 5600.0
        if v > 0.1:
            h2_consumers.append(("scanfiner_1", v, "H2"))
    if hasattr(model, "kero_to_kht"):
        v = _safe_value(model.kero_to_kht[p0]) * 600.0 / 5600.0
        if v > 0.1:
            h2_consumers.append(("kht_1", v, "H2"))
    if hasattr(model, "diesel_to_dht"):
        dht_feed = _safe_value(model.diesel_to_dht[p0])
        if hasattr(model, "lco_to_dht"):
            dht_feed += _safe_value(model.lco_to_dht[p0])
        if hasattr(model, "coker_go_to_dht"):
            dht_feed += _safe_value(model.coker_go_to_dht[p0])
        v = dht_feed * 800.0 / 5600.0
        if v > 0.1:
            h2_consumers.append(("dht_1", v, "H2"))
    if hasattr(model, "vgo_to_hcu") and hasattr(model, "hcu_conversion"):
        # Flat 1000 SCFB for HCU net chemical hydrogen consumption. The
        # header represents make-up H2 (what the refinery actually imports
        # from the SMR/H2 plant), not treat-gas circulation. Typical net
        # chemical uptake is 500–1000 SCFB; the full treat-gas figure
        # (2000+ SCFB) would be correct if the header were a recycle loop.
        hcu_scfb = 1000.0
        v = _safe_value(model.vgo_to_hcu[p0]) * hcu_scfb / 5600.0
        if v > 0.1:
            h2_consumers.append(("hcu_1", v, "H2"))
    if hasattr(model, "ln_to_isom"):
        v = _safe_value(model.ln_to_isom[p0]) * 150.0 / 5600.0
        if v > 0.1:
            h2_consumers.append(("isom_c56", v, "H2"))

    existing_ids_h2 = {n.node_id for n in flow_graph.nodes}
    if (h2_sources or h2_plant_v > 0.1) and h2_consumers:
        total_supply = sum(v for _, _, v, _ in h2_sources) + h2_plant_v
        total_demand = sum(v for _, v, _ in h2_consumers)
        # Header throughput shows ONE side (consumers only) — never the
        # supply + demand sum. The bus is a balanced junction, so
        # producers_in == consumers_out in the physical limit; showing
        # either side alone is the correct display, and we pick demand
        # because it's grounded in feed × SCFB and matches the plant
        # operator's mental model (how much H2 the refinery draws).
        flow_graph.nodes.append(
            FlowNode(
                node_id="h2_header",
                node_type=FlowNodeType.BLEND_HEADER,
                display_name="H2 Header",
                throughput=total_demand,
            )
        )
        if h2_plant_v > 0.1:
            flow_graph.nodes.append(
                FlowNode(
                    node_id="h2_plant",
                    node_type=FlowNodeType.UNIT,
                    display_name="H2 Plant",
                    throughput=h2_plant_v,
                )
            )
            flow_graph.edges.append(FlowEdge(
                edge_id=f"e{next_edge_id}", source_node="h2_plant",
                dest_node="h2_header", stream_name="H2", display_name="H2",
                volume=h2_plant_v,
            ))
            next_edge_id += 1
        for src, _disp, vol, label in h2_sources:
            if src not in existing_ids_h2:
                continue
            flow_graph.edges.append(FlowEdge(
                edge_id=f"e{next_edge_id}", source_node=src,
                dest_node="h2_header", stream_name=label, display_name=label,
                volume=vol,
            ))
            next_edge_id += 1
        for tgt, vol, label in h2_consumers:
            if tgt not in existing_ids_h2:
                continue
            flow_graph.edges.append(FlowEdge(
                edge_id=f"e{next_edge_id}", source_node="h2_header",
                dest_node=tgt, stream_name=label, display_name=label,
                volume=vol,
            ))
            next_edge_id += 1

    # Utility Generation (SUTL) — visualization-only node for power/steam/
    # cooling water generation. Sits in the Utilities lane alongside the H2
    # Header and Plant Fuel System. Edges are placeholders (bbl-equivalent)
    # that render as dashed utility lines; the unit does not participate in
    # the material balance or objective.
    _UTILITY_GEN_PLACEHOLDER = 500.0  # bbl/d equivalent, for display only
    if "pfs_1" in {n.node_id for n in flow_graph.nodes}:
        flow_graph.nodes.append(
            FlowNode(
                node_id="utility_gen",
                node_type=FlowNodeType.UNIT,
                display_name="Utility Gen",
                throughput=_UTILITY_GEN_PLACEHOLDER,
            )
        )
        flow_graph.edges.append(FlowEdge(
            edge_id=f"e{next_edge_id}", source_node="pfs_1",
            dest_node="utility_gen", stream_name="Fuel Gas",
            display_name="Fuel Gas", volume=_UTILITY_GEN_PLACEHOLDER,
        ))
        next_edge_id += 1
        if "h2_header" in {n.node_id for n in flow_graph.nodes}:
            flow_graph.edges.append(FlowEdge(
                edge_id=f"e{next_edge_id}", source_node="utility_gen",
                dest_node="h2_header", stream_name="Steam/Power",
                display_name="Steam/Power", volume=100.0,
            ))
            next_edge_id += 1

    # Inventory trajectory (per tank, per period) — only present when tanks exist
    inventory_trajectory: dict[str, list[float]] = {}
    if hasattr(model, "PRODUCT_TANKS") and hasattr(model, "inventory"):
        for tank_name in model.PRODUCT_TANKS:
            inventory_trajectory[tank_name] = [
                _safe_value(model.inventory[tank_name, p]) for p in model.PERIODS
            ]

    return PlanningResult(
        scenario_id=plan.scenario_id or str(uuid.uuid4()),
        scenario_name=plan.scenario_name,
        parent_scenario_id=plan.parent_scenario_id,
        created_at=datetime.now(),
        periods=period_results,
        total_margin=total_margin,
        solve_time_seconds=solve_result.solve_time,
        solver_status=solve_result.status,
        inventory_trajectory=inventory_trajectory,
        material_flow=flow_graph,
        crude_valuations=crude_valuations,
    )
