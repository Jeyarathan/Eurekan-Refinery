"""Deterministic narrative pipeline for PlanningResult interpretation.

Three steps:
  1. extract_facts  — structured data from the result (deterministic)
  2. apply_domain_rules — flag risks and insights (deterministic)
  3. generate_narrative — build SolutionNarrative from facts + rules
     (no Claude API required; template-based prose)
"""

from __future__ import annotations

from typing import Any

from eurekan.core.config import RefineryConfig
from eurekan.core.results import (
    DecisionExplanation,
    PlanningResult,
    RiskFlag,
    SolutionNarrative,
)


# ---------------------------------------------------------------------------
# Step 1: extract structured facts
# ---------------------------------------------------------------------------


def extract_facts(result: PlanningResult) -> dict[str, Any]:
    """Pull key numbers from the result into a flat dict."""
    period = result.periods[0] if result.periods else None
    if period is None:
        return {"margin": 0, "n_periods": 0}

    fcc = period.fcc_result
    crude_slate = period.crude_slate
    total_crude = sum(crude_slate.values())

    # Top crudes by volume
    sorted_crudes = sorted(crude_slate.items(), key=lambda x: -x[1])
    top_crudes = [(cid, vol) for cid, vol in sorted_crudes if vol > 1]

    # Product split
    products = period.product_volumes

    # Regen utilization
    regen_util = 0.0
    regen_temp = 0.0
    regen_limit = 1400.0
    if fcc and fcc.equipment:
        for eq in fcc.equipment:
            if eq.name == "regen_temp":
                regen_util = eq.utilization_pct
                regen_temp = eq.current_value
                regen_limit = eq.limit

    # Sulfur margin (from blend recipe — rough estimate)
    gasoline_vol = products.get("gasoline", 0)

    # Binding constraints
    binding = [
        d for d in result.constraint_diagnostics if d.binding
    ]

    return {
        "margin": result.total_margin,
        "margin_per_day": period.margin,
        "n_periods": len(result.periods),
        "solver_status": result.solver_status,
        "solve_time": result.solve_time_seconds,
        "cdu_throughput": total_crude,
        "cdu_capacity": 80_000,
        "cdu_utilization_pct": (total_crude / 80_000 * 100) if total_crude > 0 else 0,
        "fcc_conversion": fcc.conversion if fcc else 0,
        "fcc_feed": fcc.yields.get("vgo_to_fcc", 0) if fcc else 0,
        "regen_utilization_pct": regen_util,
        "regen_temp": regen_temp,
        "regen_limit": regen_limit,
        "top_crudes": top_crudes[:5],
        "n_crudes_used": len(top_crudes),
        "products": products,
        "gasoline_volume": gasoline_vol,
        "revenue": period.revenue,
        "crude_cost": period.crude_cost,
        "operating_cost": period.operating_cost,
        "n_binding_constraints": len(binding),
        "binding_constraints": [
            {"name": d.display_name, "score": d.bottleneck_score}
            for d in binding[:5]
        ],
    }


# ---------------------------------------------------------------------------
# Step 2: domain reasoning rules
# ---------------------------------------------------------------------------


def apply_domain_rules(facts: dict[str, Any]) -> list[dict[str, Any]]:
    """Deterministic rules that flag risks and insights."""
    flags: list[dict[str, Any]] = []

    if facts.get("regen_utilization_pct", 0) > 95:
        flags.append({
            "severity": "warning",
            "rule": "regen_near_limit",
            "message": (
                f"FCC regenerator at {facts['regen_utilization_pct']:.0f}% of limit "
                f"({facts['regen_temp']:.0f}/{facts['regen_limit']:.0f} °F). "
                "This is the primary equipment bottleneck."
            ),
            "recommendation": "Consider lighter crude or lower conversion to create headroom.",
        })

    conv = facts.get("fcc_conversion", 0)
    if 0 < conv < 74:
        flags.append({
            "severity": "info",
            "rule": "low_conversion",
            "message": f"FCC conversion at {conv:.1f}% is below typical operating range (75-85%).",
            "recommendation": "Check if octane or sulfur constraints are limiting conversion.",
        })

    top = facts.get("top_crudes", [])
    total = facts.get("cdu_throughput", 1)
    if top and total > 0:
        largest_vol = top[0][1] if top else 0
        if largest_vol / total > 0.60:
            flags.append({
                "severity": "warning",
                "rule": "concentrated_slate",
                "message": (
                    f"Crude slate concentrated: {top[0][0]} at "
                    f"{largest_vol / total * 100:.0f}% of throughput."
                ),
                "recommendation": "Single-crude dependency creates supply risk. Consider diversifying.",
            })

    if facts.get("cdu_utilization_pct", 0) < 85:
        flags.append({
            "severity": "info",
            "rule": "underutilized_cdu",
            "message": f"CDU at {facts['cdu_utilization_pct']:.0f}% utilization — spare capacity available.",
            "recommendation": "Check if crude economics limit throughput.",
        })

    return flags


# ---------------------------------------------------------------------------
# Step 3: build narrative (deterministic — no Claude API needed)
# ---------------------------------------------------------------------------


def generate_narrative(
    result: PlanningResult,
    config: RefineryConfig,
) -> SolutionNarrative:
    """Build a SolutionNarrative from deterministic facts and rules."""
    facts = extract_facts(result)
    insights = apply_domain_rules(facts)

    # Executive summary
    top_crude_names = ", ".join(c[0] for c in facts.get("top_crudes", [])[:3])
    summary = (
        f"The optimizer achieved a margin of ${facts['margin']:,.0f}/day "
        f"processing {facts['cdu_throughput']:,.0f} bbl/d of crude "
        f"({facts['n_crudes_used']} crudes; top: {top_crude_names}). "
        f"FCC runs at {facts['fcc_conversion']:.1f}% conversion with "
        f"regenerator at {facts['regen_utilization_pct']:.0f}% of limit. "
        f"Status: {facts['solver_status']}."
    )

    # Decision explanations
    explanations: list[DecisionExplanation] = []
    if facts.get("top_crudes"):
        top = facts["top_crudes"][0]
        explanations.append(DecisionExplanation(
            decision=f"Crude selection: {top[0]} at {top[1]:,.0f} bbl/d",
            reasoning=(
                f"{top[0]} dominates the slate because it offers the best "
                "crack spread (product value minus crude cost) at current prices."
            ),
            alternatives_considered=f"{facts['n_crudes_used']} crudes evaluated; others had lower margins.",
            confidence=0.9,
        ))

    if facts.get("fcc_conversion"):
        explanations.append(DecisionExplanation(
            decision=f"FCC conversion: {facts['fcc_conversion']:.1f}%",
            reasoning=(
                "Conversion balances gasoline yield (increases with conversion) "
                "against coke make (increases regen temp) and LCO yield (decreases)."
            ),
            alternatives_considered="Bounded by equipment limits and octane constraints.",
            confidence=0.85,
        ))

    # Risk flags
    risk_flags = [
        RiskFlag(
            severity=i["severity"],
            message=i["message"],
            recommendation=i["recommendation"],
        )
        for i in insights
    ]

    # Data quality warnings
    warnings: list[str] = []
    if not config.crude_library.list_crudes():
        warnings.append("No crude assays loaded.")

    return SolutionNarrative(
        executive_summary=summary,
        decision_explanations=explanations,
        risk_flags=risk_flags,
        economics_narrative=(
            f"Revenue: ${facts['revenue']:,.0f}/d. "
            f"Crude cost: ${facts['crude_cost']:,.0f}/d. "
            f"Operating cost: ${facts['operating_cost']:,.0f}/d. "
            f"Net margin: ${facts['margin_per_day']:,.0f}/d."
        ),
        data_quality_warnings=warnings,
    )
