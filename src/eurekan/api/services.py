"""RefineryService — bridge between API routes and the Stage 1 engine.

Holds the loaded RefineryConfig plus an in-memory scenario store. All
business logic lives here so routes stay thin and easy to test.
"""

from __future__ import annotations

import copy
from datetime import datetime
from typing import Any, Optional

from eurekan.analysis.oracle import oracle_analysis
from eurekan.core.config import RefineryConfig
from eurekan.core.enums import OperatingMode
from eurekan.core.period import PeriodData, PlanDefinition
from eurekan.core.results import OracleResult, PlanningResult, ScenarioComparison
from eurekan.optimization.modes import run_hybrid, run_optimization, run_simulation


class RefineryService:
    """Stateful wrapper around the planning engine.

    The service owns:
      - the RefineryConfig (mutable: prices and demand can be edited)
      - an in-memory dict of solved scenarios keyed by scenario_id
      - an `is_stale` flag flipped to True when any input changes after a
        solve, and reset to False every time `optimize` runs
    """

    def __init__(self, config: RefineryConfig) -> None:
        self.config = config
        self.scenarios: dict[str, PlanningResult] = {}
        self.is_stale: bool = True

    # ------------------------------------------------------------------
    # Optimization
    # ------------------------------------------------------------------

    def optimize(
        self,
        periods: list[PeriodData],
        mode: OperatingMode,
        fixed_variables: Optional[dict[str, float]] = None,
        scenario_name: str = "Untitled",
        parent_scenario_id: Optional[str] = None,
    ) -> PlanningResult:
        """Build a PlanDefinition, run the requested mode, store the result."""
        plan = PlanDefinition(
            periods=periods,
            mode=mode,
            fixed_variables=fixed_variables or {},
            scenario_name=scenario_name,
            parent_scenario_id=parent_scenario_id,
        )

        if mode == OperatingMode.OPTIMIZE:
            result = run_optimization(self.config, plan)
        elif mode == OperatingMode.SIMULATE:
            result = run_simulation(self.config, plan)
        else:
            result = run_hybrid(self.config, plan)

        self.scenarios[result.scenario_id] = result
        self.is_stale = False
        return result

    def quick_optimize(
        self,
        crude_prices: Optional[dict[str, float]] = None,
        product_prices: Optional[dict[str, float]] = None,
        scenario_name: str = "Quick Plan",
    ) -> PlanningResult:
        """Single-period optimization with optional price overrides.

        Falls back to default prices that yield positive margin against the
        Gulf Coast crude prices ($72-80/bbl).
        """
        defaults: dict[str, float] = {
            "gasoline": 95.0,
            "diesel": 100.0,
            "jet": 100.0,
            "naphtha": 60.0,
            "fuel_oil": 55.0,
            "lpg": 50.0,
        }
        merged_product_prices = {**defaults, **(product_prices or {})}

        # Apply a $10 crude discount when no crude_prices are supplied.
        # The Gulf Coast parsed prices ($72-80) leave razor-thin margins
        # against product prices — a realistic discount (e.g. pipeline
        # vs posted, or index lag) keeps the demo profitable.
        if not crude_prices:
            crude_prices = {
                cid: max((self.config.crude_library.get(cid).price or 70.0) - 10.0, 55.0)
                for cid in self.config.crude_library
            }

        period = PeriodData(
            period_id=0,
            duration_hours=24.0,
            crude_prices=crude_prices,
            product_prices=merged_product_prices,
        )
        return self.optimize(
            periods=[period],
            mode=OperatingMode.OPTIMIZE,
            scenario_name=scenario_name,
        )

    # ------------------------------------------------------------------
    # Scenario store
    # ------------------------------------------------------------------

    def get_scenario(self, scenario_id: str) -> Optional[PlanningResult]:
        return self.scenarios.get(scenario_id)

    def list_scenarios(self) -> list[dict[str, Any]]:
        """Return scenario summaries (id, name, margin, parent, created_at)."""
        summaries: list[dict[str, Any]] = []
        for scenario in self.scenarios.values():
            summaries.append(
                {
                    "scenario_id": scenario.scenario_id,
                    "scenario_name": scenario.scenario_name,
                    "parent_scenario_id": scenario.parent_scenario_id,
                    "total_margin": scenario.total_margin,
                    "created_at": scenario.created_at.isoformat(),
                    "solver_status": scenario.solver_status,
                    "n_periods": len(scenario.periods),
                }
            )
        # Newest first
        summaries.sort(key=lambda s: s["created_at"], reverse=True)
        return summaries

    def branch_scenario(
        self,
        parent_id: str,
        name: str,
        changes: dict[str, Any],
    ) -> PlanningResult:
        """Branch from an existing scenario, applying price/availability changes.

        ``changes`` may contain ``crude_prices`` and/or ``product_prices`` dicts.
        The branched run reuses the parent's period structure but applies the
        overrides on top, then sets ``parent_scenario_id`` accordingly.
        """
        parent = self.scenarios.get(parent_id)
        if parent is None:
            raise KeyError(f"Unknown parent scenario: {parent_id}")

        crude_overrides = changes.get("crude_prices", {}) or {}
        product_overrides = changes.get("product_prices", {}) or {}

        # Build new periods carrying parent prices + overrides
        new_periods: list[PeriodData] = []
        for orig_period in parent.periods:
            # parent.periods is a list of PeriodResult; we need PeriodData.
            # PeriodResult has period_id but not duration / prices, so use
            # sensible defaults that match quick_optimize behavior.
            base_crude_prices: dict[str, float] = {
                cid: max((self.config.crude_library.get(cid).price or 70.0) - 10.0, 55.0)
                for cid in self.config.crude_library
            }
            base_product_prices: dict[str, float] = {
                "gasoline": 95.0, "diesel": 100.0, "jet": 100.0,
                "naphtha": 60.0, "fuel_oil": 55.0, "lpg": 50.0,
            }
            new_periods.append(
                PeriodData(
                    period_id=orig_period.period_id,
                    duration_hours=24.0,
                    crude_prices={**base_crude_prices, **crude_overrides},
                    product_prices={**base_product_prices, **product_overrides},
                )
            )

        return self.optimize(
            periods=new_periods,
            mode=OperatingMode.OPTIMIZE,
            scenario_name=name,
            parent_scenario_id=parent_id,
        )

    def compare_scenarios(
        self, base_id: str, comparison_id: str
    ) -> ScenarioComparison:
        """Diff two stored scenarios."""
        base = self.scenarios.get(base_id)
        comparison = self.scenarios.get(comparison_id)
        if base is None:
            raise KeyError(f"Unknown base scenario: {base_id}")
        if comparison is None:
            raise KeyError(f"Unknown comparison scenario: {comparison_id}")

        margin_delta = comparison.total_margin - base.total_margin

        # Crude slate changes from period 0
        base_slate = base.periods[0].crude_slate if base.periods else {}
        comp_slate = (
            comparison.periods[0].crude_slate if comparison.periods else {}
        )
        all_crudes = set(base_slate) | set(comp_slate)
        slate_changes = {
            cid: comp_slate.get(cid, 0.0) - base_slate.get(cid, 0.0)
            for cid in all_crudes
            if abs(comp_slate.get(cid, 0.0) - base_slate.get(cid, 0.0)) > 1.0
        }

        # FCC conversion delta
        base_conv = (
            base.periods[0].fcc_result.conversion
            if base.periods and base.periods[0].fcc_result
            else 0.0
        )
        comp_conv = (
            comparison.periods[0].fcc_result.conversion
            if comparison.periods and comparison.periods[0].fcc_result
            else 0.0
        )
        conversion_delta = comp_conv - base_conv

        # Product volume deltas
        base_vols = base.periods[0].product_volumes if base.periods else {}
        comp_vols = (
            comparison.periods[0].product_volumes if comparison.periods else {}
        )
        all_products = set(base_vols) | set(comp_vols)
        product_deltas = {
            prod: comp_vols.get(prod, 0.0) - base_vols.get(prod, 0.0)
            for prod in all_products
        }

        if margin_delta > 0:
            insight = (
                f"Comparison earns ${margin_delta:,.0f} more margin than base."
            )
        elif margin_delta < 0:
            insight = (
                f"Comparison loses ${-margin_delta:,.0f} of margin vs base."
            )
        else:
            insight = "Margins are identical."

        return ScenarioComparison(
            base_scenario_id=base_id,
            comparison_scenario_id=comparison_id,
            margin_delta=margin_delta,
            crude_slate_changes=slate_changes,
            conversion_delta=conversion_delta,
            product_volume_deltas=product_deltas,
            constraint_changes=[],
            key_insight=insight,
        )

    # ------------------------------------------------------------------
    # Oracle
    # ------------------------------------------------------------------

    def run_oracle(self, actual_decisions: dict[str, float]) -> OracleResult:
        """Run gap analysis comparing the supplied actual decisions to the optimum."""
        plan = PlanDefinition(
            periods=[
                PeriodData(
                    period_id=0,
                    duration_hours=24.0,
                    product_prices={
                        "gasoline": 95.0, "diesel": 100.0, "jet": 100.0,
                        "naphtha": 60.0, "fuel_oil": 55.0, "lpg": 50.0,
                    },
                )
            ],
            mode=OperatingMode.OPTIMIZE,
            scenario_name="Oracle context",
        )
        return oracle_analysis(self.config, actual_decisions, plan)

    # ------------------------------------------------------------------
    # Mutation helpers (called by config-edit endpoints in Sprint 5.4)
    # ------------------------------------------------------------------

    def update_crude_price(self, crude_id: str, price: float) -> None:
        """Update a crude price in-memory and mark the service stale."""
        assay = self.config.crude_library.get(crude_id)
        if assay is None:
            raise KeyError(f"Unknown crude: {crude_id}")
        # CrudeAssay is a Pydantic model — use model_copy with update
        new_assay = assay.model_copy(update={"price": price})
        self.config.crude_library._crudes[crude_id] = new_assay
        self.is_stale = True

    def update_product_price(self, product_id: str, price: float) -> None:
        """Update a product price in-memory and mark the service stale."""
        product = self.config.products.get(product_id)
        if product is None:
            raise KeyError(f"Unknown product: {product_id}")
        new_product = product.model_copy(update={"price": price})
        self.config.products[product_id] = new_product
        self.is_stale = True
