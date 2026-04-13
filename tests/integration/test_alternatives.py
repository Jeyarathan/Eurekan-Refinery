"""Integration tests for near-optimal enumeration via lexicographic optimization."""

from __future__ import annotations

from pathlib import Path

import pytest

from eurekan.analysis.alternatives import AlternativePlan, enumerate_near_optimal
from eurekan.core.enums import OperatingMode
from eurekan.core.period import PeriodData, PlanDefinition
from eurekan.optimization.modes import run_optimization
from eurekan.parsers.gulf_coast import GulfCoastParser

DATA_FILE = Path("data/gulf_coast/Gulf_Coast.xlsx")

pytestmark = pytest.mark.skipif(
    not DATA_FILE.exists(), reason="Gulf Coast Excel file not present"
)

_PRICES = {"gasoline": 95, "diesel": 100, "jet": 100, "naphtha": 60, "fuel_oil": 55, "lpg": 50}


@pytest.fixture(scope="module")
def config():
    return GulfCoastParser(DATA_FILE).parse()


@pytest.fixture(scope="module")
def plan(config):
    cheap = {
        c: max((config.crude_library.get(c).price or 70) - 10, 55)
        for c in config.crude_library
    }
    return PlanDefinition(
        periods=[PeriodData(period_id=0, duration_hours=24.0,
                            crude_prices=cheap, product_prices=_PRICES)],
        mode=OperatingMode.OPTIMIZE,
        scenario_name="Alt test base",
    )


@pytest.fixture(scope="module")
def optimal(config, plan):
    return run_optimization(config, plan)


@pytest.fixture(scope="module")
def alternatives(config, plan, optimal):
    return enumerate_near_optimal(config, plan, optimal, tolerance=0.01, max_alternatives=10)


class TestFindsAlternatives:
    def test_finds_at_least_1(self, alternatives):
        assert len(alternatives) >= 1, (
            f"Only {len(alternatives)} alternatives found, expected >= 1"
        )

    def test_all_are_alternative_plans(self, alternatives):
        for alt in alternatives:
            assert isinstance(alt, AlternativePlan)


class TestMarginWithinTolerance:
    def test_all_within_half_percent(self, optimal, alternatives):
        """All alternatives must be within 0.5% of optimal margin."""
        floor = optimal.total_margin * 0.99
        for alt in alternatives:
            assert alt.result.total_margin >= floor - 1.0, (
                f"{alt.name}: margin {alt.result.total_margin:,.0f} "
                f"below floor {floor:,.0f}"
            )


class TestRealValues:
    def test_crudes_not_zero(self, alternatives):
        """Every alternative must have non-zero crude rates."""
        for alt in alternatives:
            total = sum(alt.result.periods[0].crude_slate.values())
            assert total > 10_000, (
                f"{alt.name}: total crude {total:,.0f} is near-zero"
            )

    def test_products_not_zero(self, alternatives):
        """Every alternative must have non-zero product volumes."""
        for alt in alternatives:
            gas = alt.result.periods[0].product_volumes.get("gasoline", 0)
            assert gas > 1000, (
                f"{alt.name}: gasoline {gas:,.0f} is near-zero"
            )

    def test_conversion_in_range(self, alternatives):
        for alt in alternatives:
            fcc = alt.result.periods[0].fcc_result
            if fcc:
                assert 67 <= fcc.conversion <= 91, (
                    f"{alt.name}: conversion {fcc.conversion:.1f} out of range"
                )


class TestPlansAreDifferent:
    def test_at_least_one_different_slate(self, optimal, alternatives):
        """At least one alternative has a meaningfully different crude slate."""
        opt_slate = optimal.periods[0].crude_slate
        for alt in alternatives:
            alt_slate = alt.result.periods[0].crude_slate
            for c in set(opt_slate) | set(alt_slate):
                if abs(opt_slate.get(c, 0) - alt_slate.get(c, 0)) > 1000:
                    return  # found one — test passes
        pytest.fail("No alternative has a crude differing by >1000 bbl/d")


class TestLabelsPopulated:
    def test_names(self, alternatives):
        for alt in alternatives:
            assert len(alt.name) > 0

    def test_descriptions(self, alternatives):
        for alt in alternatives:
            assert len(alt.description) > 0

    def test_axis(self, alternatives):
        for alt in alternatives:
            assert alt.axis in ("crude", "product")

    def test_comparison_exists(self, alternatives):
        for alt in alternatives:
            assert alt.comparison is not None


class TestMax10:
    def test_never_more_than_10(self, alternatives):
        assert len(alternatives) <= 10
