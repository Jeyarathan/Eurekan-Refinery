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
                add_node("cdu_1", FlowNodeType.UNIT, "CDU 1", cdu_throughput)
                add_edge(f"crude_{cid}", "cdu_1", cid, rate)

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

        # FCC result
        conversion = _safe_value(model.fcc_conversion[p])
        fcc_yields_dict = _fcc_yields_at(conversion)
        fcc_result = FCCResult(
            conversion=conversion,
            yields=fcc_yields_dict,
            properties={},
            equipment=[],
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

        # Add product nodes/edges to the flow graph
        add_node("blend_gasoline", FlowNodeType.BLEND_HEADER, "Gasoline Blender", gasoline)
        add_node("sale_gasoline", FlowNodeType.SALE_POINT, "Gasoline", gasoline)
        if gasoline > 1e-6:
            add_edge("blend_gasoline", "sale_gasoline", "gasoline", gasoline)
        for prod, vol in product_volumes.items():
            if prod == "gasoline" or vol <= 1e-6:
                continue
            sale_id = f"sale_{prod}"
            add_node(sale_id, FlowNodeType.SALE_POINT, prod, vol)
            add_edge("cdu_1", sale_id, prod, vol)

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
