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

        # CDU → Naphtha sales
        ln_sell = _safe_value(model.ln_to_sell[p])
        hn_sell = _safe_value(model.hn_to_sell[p])
        naphtha_sell_total = ln_sell + hn_sell
        if naphtha_sell_total > 1.0:
            add_node("sale_naphtha", FlowNodeType.SALE_POINT, "Naphtha", naphtha)
            add_edge("cdu_1", "sale_naphtha", "Naphtha", naphtha_sell_total)

        # CDU → Jet
        kero_jet = _safe_value(model.kero_to_jet[p])
        if kero_jet > 1.0:
            add_node("sale_jet", FlowNodeType.SALE_POINT, "Jet", jet)
            add_edge("cdu_1", "sale_jet", "Kerosene", kero_jet)

        # CDU → Diesel (CDU diesel portion + kero_to_diesel)
        kero_diesel = _safe_value(model.kero_to_diesel[p])
        add_node("sale_diesel", FlowNodeType.SALE_POINT, "Diesel", diesel)
        if diesel > 1.0:
            # CDU diesel + kero → diesel
            cdu_diesel_direct = diesel - lco_to_diesel_val
            if cdu_diesel_direct > 1.0:
                add_edge("cdu_1", "sale_diesel", "Diesel", cdu_diesel_direct)

        # CDU → Fuel oil (VGO bypass + vacuum residue)
        vresid = cdu_throughput * 0.07  # approximate; real value from constraints
        fo_from_cdu = vgo_to_fo_val + max(vresid, 0)
        add_node("sale_fuel_oil", FlowNodeType.SALE_POINT, "Fuel Oil", fuel_oil)
        if fo_from_cdu > 1.0:
            add_edge("cdu_1", "sale_fuel_oil", "VGO bypass + VR", fo_from_cdu)

        # CDU → LPG
        if lpg > 1.0:
            add_node("sale_lpg", FlowNodeType.SALE_POINT, "LPG", lpg)
            add_edge("cdu_1", "sale_lpg", "LPG", lpg)

        # FCC → Gasoline Blender (LCN + HCN_to_blend)
        fcc_to_blend = fcc_lcn + hcn_to_blend
        add_node("blend_gasoline", FlowNodeType.BLEND_HEADER, "Gasoline Blender", gasoline)
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

        # Gasoline Blender → Gasoline sale
        add_node("sale_gasoline", FlowNodeType.SALE_POINT, "Gasoline", gasoline)
        if gasoline > 1.0:
            add_edge("blend_gasoline", "sale_gasoline", "Gasoline", gasoline)

        # FCC → Diesel (LCO to diesel)
        if lco_to_diesel_val > 1.0:
            add_edge("fcc_1", "sale_diesel", "LCO", lco_to_diesel_val)

        # FCC → Fuel oil (HCN_to_fo + LCO_to_fo)
        fcc_to_fo = hcn_to_fo + lco_to_fo_val
        if fcc_to_fo > 1.0:
            add_edge("fcc_1", "sale_fuel_oil", "HCN + LCO slop", fcc_to_fo)

        # FCC → LPG (C3 + C4)
        fcc_to_lpg = fcc_c3 + fcc_c4
        if fcc_to_lpg > 1.0 and lpg > 1.0:
            add_edge("fcc_1", "sale_lpg", "C3 + C4", fcc_to_lpg)

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
