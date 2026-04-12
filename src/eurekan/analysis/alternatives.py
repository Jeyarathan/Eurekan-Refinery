"""Near-optimal solution enumeration via lexicographic optimization.

Finds up to 10 alternative plans at essentially the SAME margin as
the optimal, exploiting the near-optimal feasible region.

Mathematical approach:
  maximize: original_margin + epsilon * secondary_goal
  subject to: original_margin >= optimal_margin * (1 - tolerance)
              all original constraints

With epsilon=0.001 and tolerance=0.005, the primary objective dominates.
The secondary goal only breaks ties, selecting different vertices of the
near-optimal region that offer different operational characteristics.
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

EPSILON = 0.001  # secondary objective weight — small enough to not move margin


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
    tolerance: float = 0.005,
    max_alternatives: int = 10,
) -> list[AlternativePlan]:
    """Find up to *max_alternatives* plans at essentially the same margin."""
    if not optimal_result.periods or optimal_result.total_margin <= 0:
        return []

    optimal_margin = optimal_result.total_margin
    margin_floor = optimal_margin * (1.0 - tolerance)
    opt_period = optimal_result.periods[0]
    opt_slate = opt_period.crude_slate
    opt_products = opt_period.product_volumes
    opt_conv = opt_period.fcc_result.conversion if opt_period.fcc_result else 80.0

    # Identify top crudes (those with significant volume in optimal)
    top_crudes = sorted(
        [(c, v) for c, v in opt_slate.items() if v > 1000],
        key=lambda x: -x[1],
    )

    # Build the list of secondary objectives to try
    objectives: list[dict[str, Any]] = []

    # Crude-axis: push each significant crude up and down
    for crude_id, _ in top_crudes[:3]:
        objectives.append({
            "name": f"Max {crude_id}",
            "axis": "crude",
            "build_secondary": lambda m, c=crude_id: m.crude_rate[c, 0],
            "sense": pyo.maximize,
            "desc_fn": lambda r, c=crude_id: _desc_crude(r, opt_slate, c),
        })
        objectives.append({
            "name": f"Min {crude_id}",
            "axis": "crude",
            "build_secondary": lambda m, c=crude_id: m.crude_rate[c, 0],
            "sense": pyo.minimize,
            "desc_fn": lambda r, c=crude_id: _desc_crude(r, opt_slate, c),
        })

    # Crude-axis: minimize concentration (most diversified)
    objectives.append({
        "name": "Most Diversified",
        "axis": "crude",
        "build_secondary": lambda m: sum(m.crude_rate[c, 0] ** 2 for c in m.CRUDES),
        "sense": pyo.minimize,
        "desc_fn": lambda r: _desc_diversity(r, opt_slate),
    })

    # Crude-axis: cheapest slate
    objectives.append({
        "name": "Cheapest Crudes",
        "axis": "crude",
        "build_secondary": lambda m: sum(
            m.crude_rate[c, 0] * (config.crude_library.get(c).price or 70)
            for c in m.CRUDES if config.crude_library.get(c)
        ),
        "sense": pyo.minimize,
        "desc_fn": lambda r: _desc_cost(r, opt_period),
    })

    # Product-axis objectives
    objectives.append({
        "name": "Max Gasoline",
        "axis": "product",
        "build_secondary": lambda m: m.gasoline_sales[0],
        "sense": pyo.maximize,
        "desc_fn": lambda r: _desc_product(r, opt_products, "gasoline"),
    })
    objectives.append({
        "name": "Max Distillate",
        "axis": "product",
        "build_secondary": lambda m: m.diesel_sales[0] + m.jet_sales[0],
        "sense": pyo.maximize,
        "desc_fn": lambda r: _desc_distillate(r, opt_products),
    })
    objectives.append({
        "name": "Min Fuel Oil",
        "axis": "product",
        "build_secondary": lambda m: m.fuel_oil_sales[0],
        "sense": pyo.minimize,
        "desc_fn": lambda r: _desc_product(r, opt_products, "fuel_oil"),
    })

    # Solve each alternative
    solver = EurekanSolver()
    found: list[AlternativePlan] = []

    for obj_spec in objectives:
        if len(found) >= max_alternatives:
            break
        try:
            alt = _solve_lexicographic(
                config, plan, optimal_result, margin_floor,
                obj_spec, solver,
            )
            if alt is None:
                continue
            if not _is_different(alt.result, optimal_result, found):
                continue
            found.append(alt)
        except Exception as exc:
            logger.debug("Alternative %s failed: %s", obj_spec["name"], exc)

    found.sort(key=lambda a: -a.result.total_margin)
    return found[:max_alternatives]


# ---------------------------------------------------------------------------
# Lexicographic solve
# ---------------------------------------------------------------------------


def _solve_lexicographic(
    config: RefineryConfig,
    plan: PlanDefinition,
    optimal_result: PlanningResult,
    margin_floor: float,
    obj_spec: dict[str, Any],
    solver: EurekanSolver,
) -> Optional[AlternativePlan]:
    """Build model with margin floor + epsilon-weighted secondary objective."""
    builder = PyomoModelBuilder(config, plan)
    model = builder.build()

    # The original objective expression (margin to maximize)
    primary_expr = model.objective.expr

    # 1. Add margin floor constraint
    model.margin_floor_con = pyo.Constraint(expr=primary_expr >= margin_floor)

    # 2. Build lexicographic objective: primary + epsilon * secondary
    model.objective.deactivate()
    secondary_expr = obj_spec["build_secondary"](model)
    alt_sense = obj_spec["sense"]

    # Normalize: if maximizing secondary, add it; if minimizing, subtract it
    if alt_sense == pyo.maximize:
        combined = primary_expr + EPSILON * secondary_expr
    else:
        combined = primary_expr - EPSILON * secondary_expr

    model.lex_objective = pyo.Objective(expr=combined, sense=pyo.maximize)

    # 3. Warm-start from optimal
    _warm_start(model, optimal_result)

    # 4. Solve
    result = solver.solve(model)
    if not result.feasible:
        return None

    # 5. Check margin is within tolerance
    try:
        actual_margin = float(pyo.value(primary_expr))
    except Exception:
        return None
    if actual_margin < margin_floor - 1.0:
        return None

    # 6. Build PlanningResult from the solved model
    solve_info = SolveResult(
        status="optimal", objective_value=actual_margin,
        solve_time=result.solve_time, tier_used=0,
    )
    planning_result = _build_planning_result(model, config, plan, solve_info)
    planning_result = planning_result.model_copy(update={
        "scenario_name": obj_spec["name"],
        "total_margin": actual_margin,
    })

    # 7. Build comparison vs optimal
    desc = obj_spec["desc_fn"](planning_result)
    comparison = _build_comparison(optimal_result, planning_result, desc)

    return AlternativePlan(
        name=obj_spec["name"],
        description=desc,
        axis=obj_spec["axis"],
        result=planning_result,
        comparison=comparison,
    )


def _warm_start(model: pyo.ConcreteModel, result: PlanningResult) -> None:
    """Set variable values from an existing PlanningResult."""
    p = result.periods[0]
    for c in model.CRUDES:
        v = model.crude_rate[c, 0]
        val = max(v.lb or 0, min(v.ub or 1e6, p.crude_slate.get(c, 0)))
        v.set_value(val)
    if p.fcc_result:
        model.fcc_conversion[0].set_value(
            max(68.0, min(90.0, p.fcc_result.conversion))
        )


def _build_comparison(
    optimal: PlanningResult, alt: PlanningResult, desc: str
) -> ScenarioComparison:
    op = optimal.periods[0]
    ap = alt.periods[0]
    return ScenarioComparison(
        base_scenario_id=optimal.scenario_id,
        comparison_scenario_id=alt.scenario_id,
        margin_delta=alt.total_margin - optimal.total_margin,
        crude_slate_changes={
            c: ap.crude_slate.get(c, 0) - op.crude_slate.get(c, 0)
            for c in set(op.crude_slate) | set(ap.crude_slate)
            if abs(ap.crude_slate.get(c, 0) - op.crude_slate.get(c, 0)) > 500
        },
        conversion_delta=(
            (ap.fcc_result.conversion if ap.fcc_result else 0)
            - (op.fcc_result.conversion if op.fcc_result else 0)
        ),
        product_volume_deltas={
            p: ap.product_volumes.get(p, 0) - op.product_volumes.get(p, 0)
            for p in set(op.product_volumes) | set(ap.product_volumes)
        },
        key_insight=desc,
    )


# ---------------------------------------------------------------------------
# Difference check
# ---------------------------------------------------------------------------


def _is_different(
    candidate: PlanningResult,
    optimal: PlanningResult,
    existing: list[AlternativePlan],
) -> bool:
    cp = candidate.periods[0]
    op = optimal.periods[0]
    if not _slates_differ(cp, op):
        return False
    for alt in existing:
        if not _slates_differ(cp, alt.result.periods[0]):
            return False
    return True


def _slates_differ(a, b) -> bool:
    for c in set(a.crude_slate) | set(b.crude_slate):
        if abs(a.crude_slate.get(c, 0) - b.crude_slate.get(c, 0)) > 1000:
            return True
    for p in set(a.product_volumes) | set(b.product_volumes):
        if abs(a.product_volumes.get(p, 0) - b.product_volumes.get(p, 0)) > 500:
            return True
    return False


# ---------------------------------------------------------------------------
# Description generators
# ---------------------------------------------------------------------------


def _desc_crude(result, opt_slate, crude_id):
    p = result.periods[0]
    v = p.crude_slate.get(crude_id, 0)
    ov = opt_slate.get(crude_id, 0)
    d = v - ov
    pct = result.total_margin / max(1, result.total_margin) * 100  # placeholder
    return (
        f"{crude_id} at {v/1000:.1f}k bbl/d ({'+' if d>=0 else ''}{d/1000:.1f}k vs optimal). "
        f"Margin ${result.total_margin/1000:.0f}k/d."
    )


def _desc_diversity(result, opt_slate):
    p = result.periods[0]
    n = sum(1 for v in p.crude_slate.values() if v > 100)
    no = sum(1 for v in opt_slate.values() if v > 100)
    return f"{n} crudes (vs {no} optimal). Margin ${result.total_margin/1000:.0f}k/d."


def _desc_cost(result, opt_period):
    return (
        f"Crude cost ${result.periods[0].crude_cost/1000:.0f}k/d "
        f"(vs ${opt_period.crude_cost/1000:.0f}k/d). "
        f"Margin ${result.total_margin/1000:.0f}k/d."
    )


def _desc_product(result, opt_products, product):
    p = result.periods[0]
    v = p.product_volumes.get(product, 0)
    ov = opt_products.get(product, 0)
    d = v - ov
    return (
        f"{product.replace('_',' ').title()} {v/1000:.1f}k bbl/d "
        f"({'+' if d>=0 else ''}{d/1000:.1f}k). "
        f"Margin ${result.total_margin/1000:.0f}k/d."
    )


def _desc_distillate(result, opt_products):
    p = result.periods[0]
    dist = p.product_volumes.get("diesel", 0) + p.product_volumes.get("jet", 0)
    odist = opt_products.get("diesel", 0) + opt_products.get("jet", 0)
    d = dist - odist
    return (
        f"Distillate {dist/1000:.1f}k bbl/d ({'+' if d>=0 else ''}{d/1000:.1f}k). "
        f"Margin ${result.total_margin/1000:.0f}k/d."
    )
