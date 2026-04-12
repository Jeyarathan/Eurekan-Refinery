"""Integration tests for near-optimal enumeration."""

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
    return enumerate_near_optimal(config, plan, optimal, tolerance=0.05, max_alternatives=10)


class TestFindsAlternatives:
    def test_finds_at_least_3(self, alternatives):
        assert len(alternatives) >= 3, (
            f"Only {len(alternatives)} alternatives found, expected >= 3"
        )

    def test_all_are_alternative_plans(self, alternatives):
        for alt in alternatives:
            assert isinstance(alt, AlternativePlan)


class TestMarginWithinTolerance:
    def test_all_within_tolerance(self, optimal, alternatives):
        floor = optimal.total_margin * 0.95  # 5% tolerance
        for alt in alternatives:
            assert alt.result.total_margin >= floor - 1.0, (
                f"{alt.name}: margin {alt.result.total_margin:,.0f} "
                f"below floor {floor:,.0f}"
            )


class TestPlansAreDifferent:
    def test_each_pair_differs(self, optimal, alternatives):
        """Each pair of plans has at least one crude >2000 or product >1000 apart."""
        all_plans = [optimal] + [a.result for a in alternatives]
        for i in range(len(all_plans)):
            for j in range(i + 1, len(all_plans)):
                pi = all_plans[i].periods[0]
                pj = all_plans[j].periods[0]
                crude_diff = any(
                    abs(pi.crude_slate.get(c, 0) - pj.crude_slate.get(c, 0)) > 2000
                    for c in set(pi.crude_slate) | set(pj.crude_slate)
                )
                product_diff = any(
                    abs(pi.product_volumes.get(p, 0) - pj.product_volumes.get(p, 0)) > 1000
                    for p in set(pi.product_volumes) | set(pj.product_volumes)
                )
                assert crude_diff or product_diff, (
                    f"Plans {i} and {j} are not meaningfully different"
                )


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
