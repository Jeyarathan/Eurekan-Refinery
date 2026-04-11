"""Report formatters for PlanningResult.

Three formats:
  - format_console:   human-readable text for the terminal
  - format_json:      complete PlanningResult serialised to JSON
  - format_summary:   one-paragraph deterministic executive summary
"""

from __future__ import annotations

from eurekan.core.results import PlanningResult


# ---------------------------------------------------------------------------
# Console
# ---------------------------------------------------------------------------


def format_console(result: PlanningResult) -> str:
    """Format a PlanningResult as a human-readable text report."""
    lines: list[str] = []
    lines.append("=" * 78)
    lines.append(f" EUREKAN PLANNING RESULT — {result.scenario_name}")
    lines.append("=" * 78)
    lines.append(f" Scenario ID:    {result.scenario_id}")
    if result.parent_scenario_id:
        lines.append(f" Parent ID:      {result.parent_scenario_id}")
    lines.append(f" Solver status:  {result.solver_status}")
    lines.append(f" Solve time:     {result.solve_time_seconds:.3f}s")
    lines.append(f" Periods:        {len(result.periods)}")
    lines.append(f" Total margin:   ${result.total_margin:,.0f}")
    lines.append("")

    for period in result.periods:
        lines.append("-" * 78)
        lines.append(f" PERIOD {period.period_id}")
        lines.append("-" * 78)

        # Crude slate (only crudes with >0 rate)
        active_crudes = [
            (cid, vol) for cid, vol in period.crude_slate.items() if vol > 1e-3
        ]
        if active_crudes:
            lines.append(" Crude Slate:")
            active_crudes.sort(key=lambda x: -x[1])
            cdu_throughput = sum(v for _, v in active_crudes)
            for cid, vol in active_crudes:
                pct = vol / cdu_throughput * 100 if cdu_throughput else 0
                lines.append(f"   {cid:<10s} {vol:>10,.0f} bbl/d  ({pct:>5.1f}%)")
            lines.append(f"   {'TOTAL':<10s} {cdu_throughput:>10,.0f} bbl/d")
            lines.append("")

        # FCC operation
        if period.fcc_result is not None:
            fcc = period.fcc_result
            lines.append(" FCC Operation:")
            lines.append(f"   Conversion:  {fcc.conversion:>6.2f}%")
            regen = fcc.yields.get("regen_temp")
            if regen is not None:
                util = regen / 1400.0 * 100.0
                lines.append(
                    f"   Regen temp:  {regen:>6.1f} °F  ({util:>5.1f}% of limit)"
                )
            lines.append(
                f"   Yields:      gasoline={fcc.yields.get('lcn', 0) + fcc.yields.get('hcn', 0):.3f}  "
                f"LCO={fcc.yields.get('lco', 0):.3f}  coke={fcc.yields.get('coke', 0):.3f}"
            )
            lines.append("")

        # Blend recipe
        if period.blend_results:
            blend = period.blend_results[0]
            lines.append(f" Blend Recipe ({blend.product_id}, {blend.total_volume:,.0f} bbl/d):")
            for component, vol in blend.recipe.items():
                if vol > 1e-3:
                    pct = vol / blend.total_volume * 100 if blend.total_volume else 0
                    lines.append(
                        f"   {component:<14s} {vol:>10,.0f} bbl/d  ({pct:>5.1f}%)"
                    )
            lines.append("")

        # Product volumes
        lines.append(" Product Volumes (bbl/d):")
        for prod, vol in period.product_volumes.items():
            lines.append(f"   {prod:<12s} {vol:>10,.0f}")
        lines.append("")

        # Economics
        lines.append(" Economics:")
        lines.append(f"   Revenue:        ${period.revenue:>13,.0f}")
        lines.append(f"   Crude cost:     ${period.crude_cost:>13,.0f}")
        lines.append(f"   Operating cost: ${period.operating_cost:>13,.0f}")
        lines.append(f"   {'─' * 30}")
        lines.append(f"   Margin:         ${period.margin:>13,.0f}")
        lines.append("")

    # Inventory trajectory across periods
    if result.inventory_trajectory:
        lines.append("-" * 78)
        lines.append(" INVENTORY TRAJECTORY")
        lines.append("-" * 78)
        for tank, traj in result.inventory_trajectory.items():
            lines.append(f"   {tank}:")
            for p, level in enumerate(traj):
                lines.append(f"     period {p}:  {level:>10,.0f} bbl")
        lines.append("")

    # Top bottlenecks
    if result.constraint_diagnostics:
        lines.append("-" * 78)
        lines.append(" TOP BOTTLENECKS (binding constraints, by shadow price)")
        lines.append("-" * 78)
        binding = [d for d in result.constraint_diagnostics if d.binding][:5]
        for d in binding:
            sp = d.shadow_price if d.shadow_price is not None else 0
            lines.append(
                f"   {d.display_name:<35s} score={d.bottleneck_score:>5.1f}  "
                f"shadow=${sp:>10.2f}"
            )
        lines.append("")

    lines.append("=" * 78)
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# JSON
# ---------------------------------------------------------------------------


def format_json(result: PlanningResult) -> str:
    """Serialize a PlanningResult to JSON via Pydantic."""
    return result.model_dump_json(indent=2)


# ---------------------------------------------------------------------------
# Executive summary
# ---------------------------------------------------------------------------


def format_summary(result: PlanningResult) -> str:
    """One-paragraph deterministic executive summary."""
    n_periods = len(result.periods)
    period_word = "period" if n_periods == 1 else "periods"
    margin = result.total_margin

    if not result.periods:
        return (
            f"Scenario '{result.scenario_name}' produced no period results "
            f"(solver status: {result.solver_status})."
        )

    # Per-period averages
    total_throughput = sum(
        sum(p.crude_slate.values()) for p in result.periods
    )
    avg_throughput = total_throughput / n_periods

    # Average FCC conversion
    convs = [
        p.fcc_result.conversion
        for p in result.periods
        if p.fcc_result is not None
    ]
    avg_conv = sum(convs) / len(convs) if convs else 0.0

    # Major product totals
    gasoline = sum(p.product_volumes.get("gasoline", 0.0) for p in result.periods)
    diesel = sum(p.product_volumes.get("diesel", 0.0) for p in result.periods)

    # Top crude
    crude_totals: dict[str, float] = {}
    for p in result.periods:
        for cid, vol in p.crude_slate.items():
            crude_totals[cid] = crude_totals.get(cid, 0.0) + vol
    top_crude = (
        max(crude_totals.items(), key=lambda x: x[1])[0] if crude_totals else "n/a"
    )

    return (
        f"Scenario '{result.scenario_name}' achieves a total margin of "
        f"${margin:,.0f} across {n_periods} {period_word}, processing an "
        f"average of {avg_throughput:,.0f} bbl/d of crude (top crude: "
        f"{top_crude}). FCC averages {avg_conv:.1f}% conversion, producing "
        f"{gasoline:,.0f} bbl total gasoline and {diesel:,.0f} bbl total "
        f"diesel. Solver status: {result.solver_status}."
    )
