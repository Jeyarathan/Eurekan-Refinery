"""Near-optimal solution enumeration.

Explores two axes that planners care about:

  Crude feedstock variations (C1–C5):
    Lean into main crude, reduce main crude, diversify, simplify, minimize cost.

  Product volume variations (P1–P5):
    Max gasoline, max distillate, min fuel oil, max/min FCC conversion.

Each alternative adds a margin-floor constraint to the NLP
(objective >= optimal * (1 - tolerance)) then re-optimizes with a
different secondary objective. Only plans that are *meaningfully
different* from the optimal and from each other are kept.
"""

from __future__ import annotations

import logging
from typing import Any, Optional

import pyomo.environ as pyo
from pydantic import BaseModel

from eurekan.core.config import RefineryConfig
from eurekan.core.period import PlanDefinition
from eurekan.core.results import PlanningResult, ScenarioComparison
from eurekan.optimization.builder import PyomoModelBuilder
from eurekan.optimization.modes import _build_planning_result
from eurekan.optimization.solver import EurekanSolver, SolveResult

logger = logging.getLogger(__name__)


class AlternativePlan(BaseModel):
    """A near-optimal plan with a label explaining how it differs."""

    name: str
    description: str
    axis: str  # "crude" or "product"
    result: PlanningResult
    comparison: ScenarioComparison

    model_config = {"arbitrary_types_allowed": True}


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def enumerate_near_optimal(
    config: RefineryConfig,
    plan: PlanDefinition,
    optimal_result: PlanningResult,
    tolerance: float = 0.02,
    max_alternatives: int = 10,
) -> list[AlternativePlan]:
    """Find up to *max_alternatives* near-optimal plans."""
    if not optimal_result.periods or optimal_result.total_margin <= 0:
        return []

    optimal_margin = optimal_result.total_margin
    margin_floor = optimal_margin * (1.0 - tolerance)
    opt_period = optimal_result.periods[0]
    opt_slate = opt_period.crude_slate
    opt_conv = opt_period.fcc_result.conversion if opt_period.fcc_result else 80.0
    opt_products = opt_period.product_volumes

    # Identify the top crude for C1/C2 objectives
    sorted_crudes = sorted(opt_slate.items(), key=lambda x: -x[1])
    top_crude = sorted_crudes[0][0] if sorted_crudes else None

    # Define the exploration objectives
    objectives: list[dict[str, Any]] = []

    if top_crude:
        objectives.append({
            "name": f"Max {top_crude}",
            "axis": "crude",
            "build": lambda m, tc=top_crude: _obj_max_var(m, f"crude_rate[{tc},0]"),
            "desc_fn": lambda r, tc=top_crude: _describe_crude(r, opt_slate, tc, "max"),
        })
        objectives.append({
            "name": f"Min {top_crude}",
            "axis": "crude",
            "build": lambda m, tc=top_crude: _obj_min_var(m, f"crude_rate[{tc},0]"),
            "desc_fn": lambda r, tc=top_crude: _describe_crude(r, opt_slate, tc, "min"),
        })

    objectives.append({
        "name": "Most Diversified",
        "axis": "crude",
        "build": lambda m: _obj_min_concentration(m),
        "desc_fn": lambda r: _describe_diversity(r, opt_slate),
    })
    objectives.append({
        "name": "Cheapest Crudes",
        "axis": "crude",
        "build": lambda m: _obj_min_crude_cost(m, config),
        "desc_fn": lambda r: _describe_cost(r, opt_period),
    })
    objectives.append({
        "name": "Max Gasoline",
        "axis": "product",
        "build": lambda m: _obj_max_var(m, "gasoline_sales[0]"),
        "desc_fn": lambda r: _describe_product(r, opt_products, "gasoline", "max"),
    })
    objectives.append({
        "name": "Max Distillate",
        "axis": "product",
        "build": lambda m: _obj_max_distillate(m),
        "desc_fn": lambda r: _describe_distillate(r, opt_products),
    })
    objectives.append({
        "name": "Min Fuel Oil",
        "axis": "product",
        "build": lambda m: _obj_min_var(m, "fuel_oil_sales[0]"),
        "desc_fn": lambda r: _describe_product(r, opt_products, "fuel_oil", "min"),
    })
    objectives.append({
        "name": "Max Conversion",
        "axis": "product",
        "build": lambda m: _obj_max_var(m, "fcc_conversion[0]"),
        "desc_fn": lambda r: _describe_conversion(r, opt_conv, "max"),
    })
    objectives.append({
        "name": "Min Conversion",
        "axis": "product",
        "build": lambda m: _obj_min_var(m, "fcc_conversion[0]"),
        "desc_fn": lambda r: _describe_conversion(r, opt_conv, "min"),
    })

    # Solve each alternative
    solver = EurekanSolver()
    found: list[AlternativePlan] = []

    for obj_spec in objectives:
        if len(found) >= max_alternatives:
            break
        try:
            alt = _solve_alternative(
                config, plan, optimal_result, margin_floor,
                obj_spec, solver,
            )
            if alt is None:
                continue
            # Check meaningful difference vs optimal AND all found plans
            if not _is_different(alt.result, optimal_result, found):
                continue
            found.append(alt)
        except Exception as exc:
            logger.debug("Alternative %s failed: %s", obj_spec["name"], exc)

    found.sort(key=lambda a: -a.result.total_margin)
    return found[:max_alternatives]


# ---------------------------------------------------------------------------
# Solver core
# ---------------------------------------------------------------------------


def _solve_alternative(
    config: RefineryConfig,
    plan: PlanDefinition,
    optimal_result: PlanningResult,
    margin_floor: float,
    obj_spec: dict[str, Any],
    solver: EurekanSolver,
) -> Optional[AlternativePlan]:
    """Build model, add margin floor, set alt objective, solve."""
    builder = PyomoModelBuilder(config, plan)
    model = builder.build()

    # 1. Add margin floor: original objective expression >= floor
    obj_expr = model.objective.expr
    model.margin_floor_con = pyo.Constraint(expr=obj_expr >= margin_floor)

    # 2. Deactivate original objective
    model.objective.deactivate()

    # 3. Set alternative objective
    alt_expr, alt_sense = obj_spec["build"](model)
    model.alt_objective = pyo.Objective(expr=alt_expr, sense=alt_sense)

    # 4. Warm-start from optimal
    _warm_start_from_result(model, optimal_result)

    # 5. Solve
    result = solver.solve(model)
    if not result.feasible:
        return None

    # 6. Check margin is actually within tolerance
    try:
        actual_margin = float(pyo.value(obj_expr))
    except Exception:
        return None
    if actual_margin < margin_floor - 1.0:
        return None

    # 7. Build PlanningResult
    fake_solve = SolveResult(
        status="optimal",
        objective_value=actual_margin,
        solve_time=result.solve_time,
        tier_used=0,
    )
    planning_result = _build_planning_result(model, config, plan, fake_solve)
    planning_result = planning_result.model_copy(update={
        "scenario_name": obj_spec["name"],
        "total_margin": actual_margin,
    })

    # 8. Build comparison vs optimal
    opt_p = optimal_result.periods[0]
    alt_p = planning_result.periods[0]
    comparison = ScenarioComparison(
        base_scenario_id=optimal_result.scenario_id,
        comparison_scenario_id=planning_result.scenario_id,
        margin_delta=actual_margin - optimal_result.total_margin,
        crude_slate_changes={
            c: alt_p.crude_slate.get(c, 0) - opt_p.crude_slate.get(c, 0)
            for c in set(opt_p.crude_slate) | set(alt_p.crude_slate)
            if abs(alt_p.crude_slate.get(c, 0) - opt_p.crude_slate.get(c, 0)) > 500
        },
        conversion_delta=(
            (alt_p.fcc_result.conversion if alt_p.fcc_result else 0)
            - (opt_p.fcc_result.conversion if opt_p.fcc_result else 0)
        ),
        product_volume_deltas={
            p: alt_p.product_volumes.get(p, 0) - opt_p.product_volumes.get(p, 0)
            for p in set(opt_p.product_volumes) | set(alt_p.product_volumes)
        },
        key_insight=obj_spec["desc_fn"](planning_result),
    )

    return AlternativePlan(
        name=obj_spec["name"],
        description=obj_spec["desc_fn"](planning_result),
        axis=obj_spec["axis"],
        result=planning_result,
        comparison=comparison,
    )


def _warm_start_from_result(model: pyo.ConcreteModel, result: PlanningResult) -> None:
    """Set model variable values from an existing PlanningResult."""
    p = result.periods[0]
    for c in model.CRUDES:
        val = p.crude_slate.get(c, 0.0)
        v = model.crude_rate[c, 0]
        lb = v.lb if v.lb is not None else 0.0
        ub = v.ub if v.ub is not None else 1e6
        model.crude_rate[c, 0].set_value(max(lb, min(ub, val)))

    if p.fcc_result:
        conv = max(68.0, min(90.0, p.fcc_result.conversion))
        model.fcc_conversion[0].set_value(conv)


# ---------------------------------------------------------------------------
# Objective builders — each returns (expression, sense)
# ---------------------------------------------------------------------------


def _obj_max_var(model: pyo.ConcreteModel, var_path: str) -> tuple:
    base, idx = var_path.split("[")
    idx = idx.rstrip("]")
    try:
        idx_val: Any = int(idx)
    except ValueError:
        parts = idx.split(",")
        idx_val = tuple(int(p) if p.strip().isdigit() else p.strip() for p in parts)
    var = getattr(model, base)
    return var[idx_val], pyo.maximize


def _obj_min_var(model: pyo.ConcreteModel, var_path: str) -> tuple:
    expr, _ = _obj_max_var(model, var_path)
    return expr, pyo.minimize


def _obj_min_concentration(model: pyo.ConcreteModel) -> tuple:
    """Minimize Σ rate_c² (proxy for Herfindahl index)."""
    expr = sum(model.crude_rate[c, 0] ** 2 for c in model.CRUDES)
    return expr, pyo.minimize


def _obj_min_crude_cost(model: pyo.ConcreteModel, config: RefineryConfig) -> tuple:
    """Minimize Σ(price × rate)."""
    expr = sum(
        model.crude_rate[c, 0] * (config.crude_library.get(c).price or 70.0)
        for c in model.CRUDES
        if config.crude_library.get(c)
    )
    return expr, pyo.minimize


def _obj_max_distillate(model: pyo.ConcreteModel) -> tuple:
    return model.diesel_sales[0] + model.jet_sales[0], pyo.maximize


# ---------------------------------------------------------------------------
# Difference check
# ---------------------------------------------------------------------------


def _is_different(
    candidate: PlanningResult,
    optimal: PlanningResult,
    existing: list[AlternativePlan],
) -> bool:
    """True if the candidate differs meaningfully from optimal AND all existing."""
    cp = candidate.periods[0]
    op = optimal.periods[0]

    # Must differ from optimal
    if not _slates_differ(cp, op):
        return False

    # Must differ from every existing alternative
    for alt in existing:
        ap = alt.result.periods[0]
        if not _slates_differ(cp, ap):
            return False
    return True


def _slates_differ(a_period, b_period) -> bool:
    """True if any crude differs by >2000 or any product by >1000."""
    for c in set(a_period.crude_slate) | set(b_period.crude_slate):
        if abs(a_period.crude_slate.get(c, 0) - b_period.crude_slate.get(c, 0)) > 2000:
            return True
    for p in set(a_period.product_volumes) | set(b_period.product_volumes):
        if abs(a_period.product_volumes.get(p, 0) - b_period.product_volumes.get(p, 0)) > 1000:
            return True
    return False


# ---------------------------------------------------------------------------
# Description generators
# ---------------------------------------------------------------------------


def _describe_crude(result, opt_slate, crude_id, direction):
    p = result.periods[0]
    vol = p.crude_slate.get(crude_id, 0)
    opt_vol = opt_slate.get(crude_id, 0)
    delta = vol - opt_vol
    sign = "+" if delta >= 0 else ""
    return (
        f"{crude_id} at {vol / 1000:.1f}k bbl/d ({sign}{delta / 1000:.1f}k vs optimal). "
        f"Margin ${result.total_margin / 1000:.0f}k/d."
    )


def _describe_diversity(result, opt_slate):
    p = result.periods[0]
    n_used = sum(1 for v in p.crude_slate.values() if v > 100)
    n_opt = sum(1 for v in opt_slate.values() if v > 100)
    return f"{n_used} crudes used (vs {n_opt} in optimal). Margin ${result.total_margin / 1000:.0f}k/d."


def _describe_cost(result, opt_period):
    return (
        f"Crude cost ${result.periods[0].crude_cost / 1000:.0f}k/d "
        f"(vs ${opt_period.crude_cost / 1000:.0f}k/d). "
        f"Margin ${result.total_margin / 1000:.0f}k/d."
    )


def _describe_product(result, opt_products, product, direction):
    p = result.periods[0]
    vol = p.product_volumes.get(product, 0)
    opt_vol = opt_products.get(product, 0)
    delta = vol - opt_vol
    sign = "+" if delta >= 0 else ""
    return (
        f"{product.replace('_', ' ').title()} at {vol / 1000:.1f}k bbl/d "
        f"({sign}{delta / 1000:.1f}k). Margin ${result.total_margin / 1000:.0f}k/d."
    )


def _describe_distillate(result, opt_products):
    p = result.periods[0]
    dist = p.product_volumes.get("diesel", 0) + p.product_volumes.get("jet", 0)
    opt_dist = opt_products.get("diesel", 0) + opt_products.get("jet", 0)
    delta = dist - opt_dist
    sign = "+" if delta >= 0 else ""
    return (
        f"Distillate at {dist / 1000:.1f}k bbl/d ({sign}{delta / 1000:.1f}k). "
        f"Margin ${result.total_margin / 1000:.0f}k/d."
    )


def _describe_conversion(result, opt_conv, direction):
    p = result.periods[0]
    conv = p.fcc_result.conversion if p.fcc_result else 0
    delta = conv - opt_conv
    sign = "+" if delta >= 0 else ""
    return (
        f"Conversion at {conv:.1f}% ({sign}{delta:.1f}%). "
        f"Margin ${result.total_margin / 1000:.0f}k/d."
    )
