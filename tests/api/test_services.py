"""Tests for RefineryService — Sprint 5 Task 5.2."""

from __future__ import annotations

from pathlib import Path

import pytest

from eurekan.api.services import RefineryService
from eurekan.core.enums import OperatingMode
from eurekan.core.period import PeriodData
from eurekan.core.results import OracleResult, PlanningResult, ScenarioComparison
from eurekan.parsers.gulf_coast import GulfCoastParser

DATA_FILE = Path("data/gulf_coast/Gulf_Coast.xlsx")

pytestmark = pytest.mark.skipif(
    not DATA_FILE.exists(), reason="Gulf Coast Excel file not present"
)


@pytest.fixture(scope="module")
def config():
    return GulfCoastParser(DATA_FILE).parse()


@pytest.fixture
def service(config) -> RefineryService:
    """Fresh service per test so the scenario store starts empty."""
    return RefineryService(config)


def _profitable_period(period_id: int = 0) -> PeriodData:
    return PeriodData(
        period_id=period_id,
        duration_hours=24.0,
        product_prices={
            "gasoline": 95.0, "diesel": 100.0, "jet": 100.0,
            "naphtha": 60.0, "fuel_oil": 70.0, "lpg": 50.0,
        },
    )


# ---------------------------------------------------------------------------
# Construction
# ---------------------------------------------------------------------------


class TestServiceConstruction:
    def test_service_holds_config(self, service):
        assert service.config is not None
        assert len(service.config.crude_library) >= 40

    def test_initial_scenario_store_empty(self, service):
        assert service.scenarios == {}

    def test_initial_is_stale_true(self, service):
        """A fresh service is stale until the first optimize runs."""
        assert service.is_stale is True


# ---------------------------------------------------------------------------
# optimize / quick_optimize
# ---------------------------------------------------------------------------


class TestOptimize:
    def test_optimize_returns_result(self, service):
        result = service.optimize(
            periods=[_profitable_period()],
            mode=OperatingMode.OPTIMIZE,
            scenario_name="Service base",
        )
        assert isinstance(result, PlanningResult)
        assert result.solver_status == "optimal"
        assert result.scenario_name == "Service base"

    def test_optimize_clears_stale_flag(self, service):
        assert service.is_stale is True
        service.optimize(
            periods=[_profitable_period()],
            mode=OperatingMode.OPTIMIZE,
        )
        assert service.is_stale is False

    def test_quick_optimize_works(self, service):
        result = service.quick_optimize(scenario_name="Quick test")
        assert result.solver_status == "optimal"
        assert result.scenario_name == "Quick test"
        assert result.total_margin > 0

    def test_quick_optimize_with_overrides(self, service):
        result = service.quick_optimize(
            product_prices={"gasoline": 110.0},
            scenario_name="Gas spike",
        )
        assert result.solver_status == "optimal"
        assert result.total_margin > 0


# ---------------------------------------------------------------------------
# Scenario store
# ---------------------------------------------------------------------------


class TestScenarioStore:
    def test_scenario_stored(self, service):
        result = service.optimize(
            periods=[_profitable_period()],
            mode=OperatingMode.OPTIMIZE,
        )
        stored = service.get_scenario(result.scenario_id)
        assert stored is not None
        assert stored.scenario_id == result.scenario_id

    def test_get_scenario_unknown_returns_none(self, service):
        assert service.get_scenario("does-not-exist") is None

    def test_list_scenarios_empty(self, service):
        assert service.list_scenarios() == []

    def test_list_scenarios(self, service):
        service.optimize(
            periods=[_profitable_period()],
            mode=OperatingMode.OPTIMIZE,
            scenario_name="First",
        )
        service.quick_optimize(scenario_name="Second")
        summaries = service.list_scenarios()
        assert len(summaries) == 2
        names = {s["scenario_name"] for s in summaries}
        assert names == {"First", "Second"}
        for s in summaries:
            assert "scenario_id" in s
            assert "total_margin" in s
            assert "created_at" in s
            assert "n_periods" in s


# ---------------------------------------------------------------------------
# Branching and comparison
# ---------------------------------------------------------------------------


class TestBranchAndCompare:
    def test_branch_scenario(self, service):
        base = service.quick_optimize(scenario_name="Branch base")
        branched = service.branch_scenario(
            parent_id=base.scenario_id,
            name="Higher gasoline",
            changes={"product_prices": {"gasoline": 120.0}},
        )
        assert branched.parent_scenario_id == base.scenario_id
        assert branched.scenario_id != base.scenario_id
        assert branched.scenario_name == "Higher gasoline"
        # Higher price → higher margin
        assert branched.total_margin > base.total_margin

    def test_branch_unknown_parent_raises(self, service):
        with pytest.raises(KeyError):
            service.branch_scenario(
                parent_id="missing",
                name="oops",
                changes={},
            )

    def test_compare_scenarios(self, service):
        base = service.quick_optimize(scenario_name="Compare base")
        branched = service.branch_scenario(
            parent_id=base.scenario_id,
            name="Compare branch",
            changes={"product_prices": {"gasoline": 120.0}},
        )
        comparison = service.compare_scenarios(base.scenario_id, branched.scenario_id)
        assert isinstance(comparison, ScenarioComparison)
        assert comparison.base_scenario_id == base.scenario_id
        assert comparison.comparison_scenario_id == branched.scenario_id
        assert comparison.margin_delta > 0  # branched is higher
        assert "more margin" in comparison.key_insight or "margin" in comparison.key_insight

    def test_compare_unknown_scenario_raises(self, service):
        base = service.quick_optimize(scenario_name="Lonely")
        with pytest.raises(KeyError):
            service.compare_scenarios(base.scenario_id, "missing")


# ---------------------------------------------------------------------------
# Stale flag flips on input changes
# ---------------------------------------------------------------------------


class TestStaleFlag:
    def test_update_crude_price_marks_stale(self, service):
        service.quick_optimize(scenario_name="Pre-edit")
        assert service.is_stale is False

        any_crude = next(iter(service.config.crude_library))
        service.update_crude_price(any_crude, 65.0)
        assert service.is_stale is True

    def test_update_product_price_marks_stale(self, service):
        service.quick_optimize(scenario_name="Pre-edit")
        any_product = next(iter(service.config.products))
        service.update_product_price(any_product, 100.0)
        assert service.is_stale is True

    def test_optimize_after_edit_resets_stale(self, service):
        service.quick_optimize(scenario_name="First")
        service.update_crude_price(next(iter(service.config.crude_library)), 65.0)
        assert service.is_stale is True
        service.quick_optimize(scenario_name="After edit")
        assert service.is_stale is False


# ---------------------------------------------------------------------------
# Oracle integration
# ---------------------------------------------------------------------------


class TestOracle:
    def test_run_oracle_returns_result(self, service):
        # Suboptimal: only the most expensive crude
        crudes = list(service.config.crude_library)
        most_expensive = max(
            crudes,
            key=lambda cid: service.config.crude_library.get(cid).price or 0.0,
        )
        actual = {f"crude_rate[{most_expensive},0]": 60_000.0}
        result = service.run_oracle(actual)
        assert isinstance(result, OracleResult)
        assert result.gap >= 0
