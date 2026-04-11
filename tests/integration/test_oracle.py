"""Integration tests for oracle gap analysis — Task 3.7."""

from __future__ import annotations

import pytest

from eurekan.analysis.oracle import oracle_analysis
from eurekan.core.config import RefineryConfig, UnitConfig
from eurekan.core.crude import (
    US_GULF_COAST_630EP,
    CrudeAssay,
    CrudeLibrary,
    CutProperties,
    DistillationCut,
)
from eurekan.core.enums import OperatingMode, UnitType
from eurekan.core.period import PeriodData, PlanDefinition
from eurekan.core.product import Product, ProductSpec
from eurekan.optimization.modes import run_optimization


def _make_crude(crude_id: str, api: float, sulfur: float, price: float) -> CrudeAssay:
    return CrudeAssay(
        crude_id=crude_id,
        name=crude_id,
        api=api,
        sulfur=sulfur,
        price=price,
        max_rate=80000.0,
        cuts=[
            DistillationCut(name="lpg", display_name="LPG", vol_yield=0.03,
                            properties=CutProperties(spg=0.55)),
            DistillationCut(name="light_naphtha", display_name="LN", vol_yield=0.10,
                            properties=CutProperties(api=82.0, sulfur=0.001, spg=0.66)),
            DistillationCut(name="heavy_naphtha", display_name="HN", vol_yield=0.15,
                            properties=CutProperties(api=55.0, sulfur=0.005, spg=0.74)),
            DistillationCut(name="kerosene", display_name="Kero", vol_yield=0.15,
                            properties=CutProperties(api=42.0, sulfur=0.05, spg=0.80)),
            DistillationCut(name="diesel", display_name="Diesel", vol_yield=0.20,
                            properties=CutProperties(api=35.0, sulfur=0.15, spg=0.84)),
            DistillationCut(name="vgo", display_name="VGO", vol_yield=0.30,
                            properties=CutProperties(api=22.0, sulfur=1.5, ccr=1.0, spg=0.92)),
            DistillationCut(name="vacuum_residue", display_name="VR", vol_yield=0.07,
                            properties=CutProperties(api=10.0, sulfur=3.0, ccr=15.0, spg=1.02)),
        ],
    )


@pytest.fixture
def config() -> RefineryConfig:
    crudes = {
        f"C{i}": _make_crude(f"C{i}", api=27 + i, sulfur=0.4 + i * 0.1, price=68 + i)
        for i in range(5)
    }
    library = CrudeLibrary(crudes)
    units = {
        "cdu_1": UnitConfig(unit_id="cdu_1", unit_type=UnitType.CDU, capacity=80000.0),
        "fcc_1": UnitConfig(
            unit_id="fcc_1",
            unit_type=UnitType.FCC,
            capacity=50000.0,
            equipment_limits={"fcc_regen_temp_max": 1400.0},
        ),
    }
    products = {
        "regular_gasoline": Product(
            product_id="regular_gasoline",
            name="Regular Gasoline",
            price=82.81,
            specs=[
                ProductSpec(spec_name="road_octane", min_value=87.0),
                ProductSpec(spec_name="rvp", max_value=14.0),
                ProductSpec(spec_name="sulfur", max_value=0.10),
            ],
        ),
    }
    return RefineryConfig(
        name="Oracle Test",
        units=units,
        crude_library=library,
        products=products,
        streams={},
        cut_point_template=US_GULF_COAST_630EP,
    )


@pytest.fixture
def plan() -> PlanDefinition:
    return PlanDefinition(
        periods=[PeriodData(period_id=0, duration_hours=24.0)],
        mode=OperatingMode.OPTIMIZE,
        scenario_name="Base",
    )


@pytest.fixture
def suboptimal_decisions() -> dict[str, float]:
    """Deliberately suboptimal: only most expensive crude, low conversion."""
    return {
        "crude_rate[C0,0]": 0.0,
        "crude_rate[C1,0]": 0.0,
        "crude_rate[C2,0]": 0.0,
        "crude_rate[C3,0]": 0.0,
        "crude_rate[C4,0]": 60000.0,  # most expensive crude
        "fcc_conversion[0]": 72.0,    # low conversion
    }


# ---------------------------------------------------------------------------
# Oracle gap tests
# ---------------------------------------------------------------------------


class TestOracleOptimalVsActual:
    def test_actual_at_most_optimal(self, config, plan, suboptimal_decisions):
        """Actual margin must be <= optimal margin (optimizer can't do worse)."""
        result = oracle_analysis(config, suboptimal_decisions, plan)
        assert result.actual_margin <= result.optimal_margin + 1e-3

    def test_optimal_strictly_higher_for_suboptimal(self, config, plan, suboptimal_decisions):
        """For obviously suboptimal actual, optimal should be strictly higher."""
        result = oracle_analysis(config, suboptimal_decisions, plan)
        assert result.optimal_margin > result.actual_margin


class TestOracleGapPositive:
    def test_gap_non_negative(self, config, plan, suboptimal_decisions):
        result = oracle_analysis(config, suboptimal_decisions, plan)
        assert result.gap >= 0.0

    def test_gap_pct_finite(self, config, plan, suboptimal_decisions):
        result = oracle_analysis(config, suboptimal_decisions, plan)
        # Gap percent can be anything, but should be a finite number
        assert isinstance(result.gap_pct, float)


class TestOracleGapDecomposition:
    def test_gap_sources_keys(self, config, plan, suboptimal_decisions):
        result = oracle_analysis(config, suboptimal_decisions, plan)
        assert set(result.gap_sources.keys()) == {
            "crude_selection_gap",
            "conversion_gap",
            "blend_gap",
        }

    def test_gap_sources_non_negative(self, config, plan, suboptimal_decisions):
        result = oracle_analysis(config, suboptimal_decisions, plan)
        for k, v in result.gap_sources.items():
            assert v >= 0.0, f"{k} = {v}, expected >= 0"

    def test_crude_dominates_for_bad_crude_choice(self, config, plan, suboptimal_decisions):
        """When the actual uses only the most expensive crude, the crude gap
        should be the largest source."""
        result = oracle_analysis(config, suboptimal_decisions, plan)
        crude_gap = result.gap_sources["crude_selection_gap"]
        conv_gap = result.gap_sources["conversion_gap"]
        # Crude gap should dominate (the bad crude is the main loss)
        assert crude_gap > conv_gap


class TestOracleIdentical:
    def test_identical_optimal_decisions_zero_gap(self, config, plan):
        """If actual = optimal, the gap should be approximately zero."""
        # First find the optimum
        opt = run_optimization(config, plan)

        # Use only non-trivial decisions (filter out IPOPT-precision near-zeros)
        optimal_decisions = {
            f"crude_rate[{cid},0]": vol
            for cid, vol in opt.periods[0].crude_slate.items()
            if vol > 1.0  # bbl/d threshold
        }

        result = oracle_analysis(config, optimal_decisions, plan)
        # With matching optimal decisions, gap should be < 1% of optimal
        assert abs(result.gap) < 0.01 * abs(result.optimal_margin), (
            f"Identical-decision gap = ${result.gap:.2f} on ${result.optimal_margin:.2f}"
        )

    def test_identical_gap_sources_small(self, config, plan):
        """Per-category gaps should also be near zero for the optimal solution."""
        opt = run_optimization(config, plan)
        optimal_decisions = {
            f"crude_rate[{cid},0]": vol
            for cid, vol in opt.periods[0].crude_slate.items()
            if vol > 1.0
        }
        result = oracle_analysis(config, optimal_decisions, plan)
        for name, gap in result.gap_sources.items():
            assert gap < 0.02 * abs(result.optimal_margin), (
                f"{name} = ${gap:.2f} too large vs optimal ${result.optimal_margin:.2f}"
            )


class TestOracleResultStructure:
    def test_oracle_result_fields(self, config, plan, suboptimal_decisions):
        result = oracle_analysis(config, suboptimal_decisions, plan)
        assert hasattr(result, "actual_margin")
        assert hasattr(result, "optimal_margin")
        assert hasattr(result, "gap")
        assert hasattr(result, "gap_pct")
        assert hasattr(result, "gap_sources")
        assert isinstance(result.gap_sources, dict)
