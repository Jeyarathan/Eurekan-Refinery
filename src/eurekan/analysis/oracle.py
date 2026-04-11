"""Oracle gap analysis — comparing what the refinery actually did vs what was optimal.

Workflow:
  1. Run a hybrid solve with actual decisions fixed → actual_margin
  2. Run full optimization (no fixes) → optimal_margin
  3. Decompose the gap by independently re-optimizing each decision category
     (crude selection, FCC conversion, blend recipe)

Note: the per-category gaps may not sum exactly to the total gap because of
interactions between decisions. The oracle reports both individual gaps and
the total gap so the engineer can see which decision matters most.
"""

from __future__ import annotations

from eurekan.core.config import RefineryConfig
from eurekan.core.enums import OperatingMode
from eurekan.core.period import PlanDefinition
from eurekan.core.results import OracleResult
from eurekan.optimization.modes import run_hybrid, run_optimization

# Variable name prefixes that count as "blend recipe" decisions
_BLEND_PREFIXES: tuple[str, ...] = (
    "ln_to_blend",
    "ln_to_sell",
    "hn_to_blend",
    "hn_to_sell",
    "hcn_to_blend",
    "hcn_to_fo",
    "lco_to_diesel",
    "lco_to_fo",
    "kero_to_jet",
    "kero_to_diesel",
    "nc4_to_blend",
    "nc4_to_lpg",
    "reformate_purchased",
)


def _category_of(key: str) -> str:
    """Classify a fixed-variable key into 'crude', 'conversion', 'blend', or 'other'."""
    if key.startswith("crude_rate"):
        return "crude"
    if key.startswith("fcc_conversion"):
        return "conversion"
    for prefix in _BLEND_PREFIXES:
        if key.startswith(prefix):
            return "blend"
    return "other"


def _make_hybrid_plan(
    base_plan: PlanDefinition,
    fixed_vars: dict[str, float],
    name: str,
) -> PlanDefinition:
    """Build a PlanDefinition with the given fixed variables in hybrid mode."""
    return PlanDefinition(
        periods=base_plan.periods,
        mode=OperatingMode.HYBRID,
        scenario_name=name,
        fixed_variables=fixed_vars,
        parent_scenario_id=base_plan.scenario_id,
    )


def oracle_analysis(
    config: RefineryConfig,
    actual_decisions: dict[str, float],
    plan_definition: PlanDefinition,
) -> OracleResult:
    """Compare actual vs optimal refinery decisions.

    Args:
        config: The refinery configuration.
        actual_decisions: Variable assignments representing what the refinery
                          actually did. Keys follow the same form as
                          PlanDefinition.fixed_variables (e.g. 'crude_rate[CRUDE_A,0]',
                          'fcc_conversion[0]', 'ln_to_blend[0]').
        plan_definition: The planning context (periods, prices, demand).

    Returns:
        OracleResult with actual_margin, optimal_margin, gap, gap_pct, and
        per-category gap_sources.
    """
    # 1. Actual margin — fix every decision the refinery made and let the
    #    rest follow from the constraints (hybrid mode).
    actual_plan = _make_hybrid_plan(plan_definition, actual_decisions, "Actual")
    actual_result = run_hybrid(config, actual_plan)
    actual_margin = actual_result.total_margin

    # 2. Optimal margin — full optimization, no fixes.
    optimal_plan = PlanDefinition(
        periods=plan_definition.periods,
        mode=OperatingMode.OPTIMIZE,
        scenario_name="Optimal",
    )
    optimal_result = run_optimization(config, optimal_plan)
    optimal_margin = optimal_result.total_margin

    gap = optimal_margin - actual_margin
    gap_pct = (gap / abs(actual_margin) * 100.0) if abs(actual_margin) > 1e-9 else 0.0

    # 3. Per-category decomposition — free one category at a time.
    keys_by_category: dict[str, list[str]] = {"crude": [], "conversion": [], "blend": []}
    for key in actual_decisions:
        cat = _category_of(key)
        if cat in keys_by_category:
            keys_by_category[cat].append(key)

    def _margin_with_freed(category: str, scenario_name: str) -> float:
        """Run hybrid solve with the given category's variables freed."""
        freed_keys = set(keys_by_category[category])
        fixed_subset = {
            k: v for k, v in actual_decisions.items() if k not in freed_keys
        }
        free_plan = _make_hybrid_plan(plan_definition, fixed_subset, scenario_name)
        result = run_hybrid(config, free_plan)
        return result.total_margin

    crude_only_margin = _margin_with_freed("crude", "Crude Optimized Only")
    conv_only_margin = _margin_with_freed("conversion", "Conversion Optimized Only")
    blend_only_margin = _margin_with_freed("blend", "Blend Optimized Only")

    # Gap = how much we'd gain by improving ONLY this category
    crude_gap = max(crude_only_margin - actual_margin, 0.0)
    conv_gap = max(conv_only_margin - actual_margin, 0.0)
    blend_gap = max(blend_only_margin - actual_margin, 0.0)

    return OracleResult(
        actual_margin=actual_margin,
        optimal_margin=optimal_margin,
        gap=gap,
        gap_pct=gap_pct,
        gap_sources={
            "crude_selection_gap": crude_gap,
            "conversion_gap": conv_gap,
            "blend_gap": blend_gap,
        },
    )
