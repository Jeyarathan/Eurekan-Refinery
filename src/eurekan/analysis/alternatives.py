"""Near-optimal solution enumeration.

After finding the optimum, check for alternatives within a tolerance
that offer different operational characteristics (e.g., fewer crudes,
lower regen utilization). Present 2-3 plans for the planner to choose.
"""

from __future__ import annotations

from eurekan.core.config import RefineryConfig
from eurekan.core.enums import OperatingMode
from eurekan.core.period import PlanDefinition
from eurekan.core.results import PlanningResult, ScenarioComparison
from eurekan.optimization.modes import run_hybrid


def enumerate_near_optimal(
    config: RefineryConfig,
    plan: PlanDefinition,
    optimal_result: PlanningResult,
    tolerance: float = 0.02,
) -> list[dict]:
    """Return the optimal plan plus up to one alternative within tolerance.

    The alternative fixes a different crude selection to see if a simpler
    slate achieves nearly the same margin.

    Returns a list of dicts: [{name, result, comparison_to_optimal}].
    """
    plans: list[dict] = [
        {"name": "Optimal", "result": optimal_result, "comparison": None}
    ]

    # Plan B: fix only the top crude at full capacity (minimize crude count)
    top_crudes = sorted(
        optimal_result.periods[0].crude_slate.items(),
        key=lambda x: -x[1],
    )
    if len(top_crudes) >= 2:
        top_crude_id = top_crudes[0][0]
        cdu_cap = config.units.get("cdu_1")
        cap = cdu_cap.capacity if cdu_cap else 80_000.0

        fixed = {f"crude_rate[{top_crude_id},0]": cap}
        # Zero out all others
        for cid, _ in top_crudes[1:]:
            fixed[f"crude_rate[{cid},0]"] = 0.0

        alt_plan = PlanDefinition(
            periods=plan.periods,
            mode=OperatingMode.HYBRID,
            fixed_variables=fixed,
            scenario_name=f"Plan B: {top_crude_id} only",
            parent_scenario_id=optimal_result.scenario_id,
        )
        try:
            alt_result = run_hybrid(config, alt_plan)
            # Check if within tolerance
            if optimal_result.total_margin > 0:
                gap_pct = (
                    1.0 - alt_result.total_margin / optimal_result.total_margin
                )
                if gap_pct <= tolerance:
                    comparison = ScenarioComparison(
                        base_scenario_id=optimal_result.scenario_id,
                        comparison_scenario_id=alt_result.scenario_id,
                        margin_delta=alt_result.total_margin - optimal_result.total_margin,
                        key_insight=(
                            f"Single-crude plan ({top_crude_id}) achieves "
                            f"{(1 - gap_pct) * 100:.1f}% of optimal margin "
                            f"with simpler operations."
                        ),
                    )
                    plans.append({
                        "name": alt_result.scenario_name,
                        "result": alt_result,
                        "comparison": comparison,
                    })
        except Exception:
            pass  # Alternative failed — just return optimal

    return plans
