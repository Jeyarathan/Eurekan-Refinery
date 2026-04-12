"""Near-optimal solution enumeration via strategic hybrid solves.

Each alternative fixes a specific aspect of the plan differently from
the optimal (different crude, different product emphasis) and lets the
optimizer find the best solution subject to that constraint.  Only
plans within *tolerance* of optimal margin are kept.
"""

from __future__ import annotations

import logging
import uuid
from typing import Any, Optional

from pydantic import BaseModel

from eurekan.core.config import RefineryConfig
from eurekan.core.enums import OperatingMode
from eurekan.core.period import PlanDefinition
from eurekan.core.results import PlanningResult, ScenarioComparison
from eurekan.optimization.modes import run_hybrid

logger = logging.getLogger(__name__)


class AlternativePlan(BaseModel):
    """A near-optimal plan with a label explaining how it differs."""

    name: str
    description: str
    axis: str
    result: PlanningResult
    comparison: ScenarioComparison

    model_config = {"arbitrary_types_allowed": True}


def enumerate_near_optimal(
    config: RefineryConfig,
    plan: PlanDefinition,
    optimal_result: PlanningResult,
    tolerance: float = 0.01,
    max_alternatives: int = 10,
) -> list[AlternativePlan]:
    """Find up to *max_alternatives* plans at near-optimal margin."""
    if not optimal_result.periods or optimal_result.total_margin <= 0:
        return []

    optimal_margin = optimal_result.total_margin
    margin_floor = optimal_margin * (1.0 - tolerance)
    opt_p = optimal_result.periods[0]
    opt_slate = opt_p.crude_slate
    opt_products = opt_p.product_volumes
    opt_conv = opt_p.fcc_result.conversion if opt_p.fcc_result else 80.0

    # Top crudes sorted by volume
    top_crudes = sorted(
        [(c, v) for c, v in opt_slate.items() if v > 1000],
        key=lambda x: -x[1],
    )

    # Build exploration strategies: each one fixes specific variables
    strategies: list[dict[str, Any]] = []

    # C1: Reduce top crude by 50%, let optimizer re-optimize
    if len(top_crudes) >= 2:
        top_c, top_v = top_crudes[0]
        strategies.append({
            "name": f"Less {top_c}",
            "axis": "crude",
            "fixed": {f"crude_rate[{top_c},0]": top_v * 0.5},
            "desc_fn": lambda r, c=top_c: _desc_crude(r, opt_slate, c),
        })
        # C2: Zero out second crude
        c2, v2 = top_crudes[1]
        strategies.append({
            "name": f"No {c2}",
            "axis": "crude",
            "fixed": {f"crude_rate[{c2},0]": 0.0},
            "desc_fn": lambda r, c=c2: _desc_crude(r, opt_slate, c),
        })
    # C3: If 3+ crudes, zero out third
    if len(top_crudes) >= 3:
        c3, _ = top_crudes[2]
        strategies.append({
            "name": f"No {c3}",
            "axis": "crude",
            "fixed": {f"crude_rate[{c3},0]": 0.0},
            "desc_fn": lambda r, c=c3: _desc_crude(r, opt_slate, c),
        })

    # P1: Fix higher conversion (push gasoline)
    strategies.append({
        "name": "High Conversion",
        "axis": "product",
        "fixed": {"fcc_conversion[0]": min(opt_conv + 5, 90.0)},
        "desc_fn": lambda r: _desc_conv(r, opt_conv),
    })
    # P2: Fix lower conversion (push distillate/LCO)
    strategies.append({
        "name": "Low Conversion",
        "axis": "product",
        "fixed": {"fcc_conversion[0]": max(opt_conv - 5, 68.0)},
        "desc_fn": lambda r: _desc_conv(r, opt_conv),
    })

    # Solve each strategy via run_hybrid
    found: list[AlternativePlan] = []

    for strat in strategies:
        if len(found) >= max_alternatives:
            break
        try:
            alt = _try_strategy(
                config, plan, optimal_result, margin_floor, strat,
            )
            if alt is None:
                continue
            if not _is_different(alt.result, optimal_result, found):
                continue
            found.append(alt)
        except Exception as exc:
            logger.debug("Strategy %s failed: %s", strat["name"], exc)

    found.sort(key=lambda a: -a.result.total_margin)
    return found[:max_alternatives]


def _try_strategy(
    config: RefineryConfig,
    plan: PlanDefinition,
    optimal_result: PlanningResult,
    margin_floor: float,
    strat: dict[str, Any],
) -> Optional[AlternativePlan]:
    """Run a hybrid solve with the strategy's fixed variables."""
    hybrid_plan = PlanDefinition(
        periods=plan.periods,
        mode=OperatingMode.HYBRID,
        fixed_variables=strat["fixed"],
        scenario_name=strat["name"],
        parent_scenario_id=optimal_result.scenario_id,
    )
    result = run_hybrid(config, hybrid_plan)
    if result.solver_status != "optimal":
        return None

    # Give it a unique ID
    result = result.model_copy(update={"scenario_id": str(uuid.uuid4())})

    # Post-solve margin check
    if result.total_margin < margin_floor - 1.0:
        return None

    desc = strat["desc_fn"](result)
    comparison = _build_comparison(optimal_result, result, desc)

    return AlternativePlan(
        name=strat["name"],
        description=desc,
        axis=strat["axis"],
        result=result,
        comparison=comparison,
    )


def _build_comparison(opt: PlanningResult, alt: PlanningResult, desc: str) -> ScenarioComparison:
    op = opt.periods[0]
    ap = alt.periods[0]
    return ScenarioComparison(
        base_scenario_id=opt.scenario_id,
        comparison_scenario_id=alt.scenario_id,
        margin_delta=alt.total_margin - opt.total_margin,
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


def _is_different(candidate: PlanningResult, optimal: PlanningResult,
                  existing: list[AlternativePlan]) -> bool:
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


def _desc_crude(result, opt_slate, crude_id):
    p = result.periods[0]
    v = p.crude_slate.get(crude_id, 0)
    ov = opt_slate.get(crude_id, 0)
    d = v - ov
    return (
        f"{crude_id} at {v/1000:.1f}k bbl/d ({'+' if d>=0 else ''}{d/1000:.1f}k vs optimal). "
        f"Margin ${result.total_margin/1000:.0f}k/d."
    )


def _desc_conv(result, opt_conv):
    p = result.periods[0]
    conv = p.fcc_result.conversion if p.fcc_result else 0
    d = conv - opt_conv
    return (
        f"Conversion {conv:.1f}% ({'+' if d>=0 else ''}{d:.1f}%). "
        f"Margin ${result.total_margin/1000:.0f}k/d."
    )
