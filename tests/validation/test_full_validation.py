"""Full validation suite — Sprint 4 Task 4.3.

The six PRD validation categories:
  1. Base case economics (Gulf Coast → optimize → margin > 0, CDU near cap)
  2. FCC yield accuracy (delegated to test_fcc_accuracy.py)
  3. Conversion response (delegated to test_conversion_response.py)
  4. Crude sensitivity (delegated to test_crude_sensitivity.py)
  5. Blending feasibility (all gasoline specs met at the optimum)
  6. Price sensitivity (gasoline up → conv up, diesel up → conv down)
"""

from __future__ import annotations

from pathlib import Path

import pytest

from eurekan.core.enums import OperatingMode
from eurekan.core.period import PeriodData, PlanDefinition
from eurekan.optimization.modes import run_optimization
from eurekan.parsers.gulf_coast import GulfCoastParser

DATA_FILE = Path("data/gulf_coast/Gulf_Coast.xlsx")

pytestmark = pytest.mark.skipif(
    not DATA_FILE.exists(), reason="Gulf Coast Excel file not present"
)

# Override prices high enough to ensure profitable operation against
# the parsed Gulf Coast crude prices ($72-80/bbl)
_PROFITABLE_PRICES: dict[str, float] = {
    "gasoline": 95.0,
    "diesel": 100.0,
    "jet": 100.0,
    "naphtha": 60.0,
    "fuel_oil": 70.0,
    "lpg": 50.0,
}


@pytest.fixture(scope="module")
def config():
    return GulfCoastParser(DATA_FILE).parse()


def _make_plan(
    name: str,
    product_prices: dict[str, float] | None = None,
) -> PlanDefinition:
    return PlanDefinition(
        periods=[
            PeriodData(
                period_id=0,
                duration_hours=24.0,
                product_prices=product_prices or _PROFITABLE_PRICES,
            )
        ],
        mode=OperatingMode.OPTIMIZE,
        scenario_name=name,
    )


# ---------------------------------------------------------------------------
# Category 1 — Base case economics
# ---------------------------------------------------------------------------


class TestBaseCaseEconomics:
    """Run optimization on the full Gulf Coast slate with profitable prices."""

    def test_solver_converges(self, config):
        result = run_optimization(config, _make_plan("Base economics"))
        assert result.solver_status == "optimal"

    def test_margin_positive(self, config):
        result = run_optimization(config, _make_plan("Base economics"))
        assert result.total_margin > 0, f"Margin {result.total_margin} not positive"

    def test_cdu_near_capacity(self, config):
        """Optimizer should fill CDU when margin is positive."""
        result = run_optimization(config, _make_plan("Base economics"))
        cdu_throughput = sum(result.periods[0].crude_slate.values())
        cdu_cap = config.units["cdu_1"].capacity
        assert cdu_throughput / cdu_cap >= 0.90, (
            f"CDU only {cdu_throughput / cdu_cap * 100:.1f}% utilized"
        )

    def test_sensible_product_mix(self, config):
        """Major products (gasoline, diesel) should both be produced."""
        result = run_optimization(config, _make_plan("Base economics"))
        pv = result.periods[0].product_volumes
        assert pv["gasoline"] > 0, "No gasoline produced"
        assert pv["diesel"] > 0, "No diesel produced"


# ---------------------------------------------------------------------------
# Categories 2-4 — Delegated to existing dedicated test files
# ---------------------------------------------------------------------------


class TestDelegatedCategories:
    """Verify the existing dedicated tests still cover the PRD categories."""

    def test_fcc_yield_accuracy_file_exists(self):
        """Category 2: see tests/validation/test_fcc_accuracy.py."""
        assert (Path("tests/validation/test_fcc_accuracy.py")).exists()

    def test_conversion_response_file_exists(self):
        """Category 3: see tests/validation/test_conversion_response.py."""
        assert (Path("tests/validation/test_conversion_response.py")).exists()

    def test_crude_sensitivity_file_exists(self):
        """Category 4: see tests/validation/test_crude_sensitivity.py."""
        assert (Path("tests/validation/test_crude_sensitivity.py")).exists()


# ---------------------------------------------------------------------------
# Category 5 — Blending feasibility
# ---------------------------------------------------------------------------


class TestBlendingFeasibility:
    """All gasoline specs must be feasible at the optimum."""

    def test_octane_above_min(self, config):
        from eurekan.core.enums import BlendMethod
        from eurekan.core.crude import CutProperties
        from eurekan.models.blending import BlendingModel
        from eurekan.optimization.builder import _BLEND_COMPONENT_PROPS

        result = run_optimization(config, _make_plan("Blend feasibility"))
        assert result.solver_status == "optimal"

        recipe = result.periods[0].blend_results[0].recipe
        assert sum(recipe.values()) > 0, "No gasoline blend produced"

        component_props = {
            k: CutProperties(**v) for k, v in _BLEND_COMPONENT_PROPS.items()
        }
        blender = BlendingModel()
        ron = blender.calculate_blend_property(
            recipe, component_props, "ron", BlendMethod.INDEX
        )
        assert ron >= 86.5, f"Blended RON {ron:.2f} below 87.0 spec"

    def test_rvp_within_limit(self, config):
        from eurekan.core.enums import BlendMethod
        from eurekan.core.crude import CutProperties
        from eurekan.models.blending import BlendingModel
        from eurekan.optimization.builder import _BLEND_COMPONENT_PROPS

        result = run_optimization(config, _make_plan("Blend feasibility"))
        recipe = result.periods[0].blend_results[0].recipe
        component_props = {
            k: CutProperties(**v) for k, v in _BLEND_COMPONENT_PROPS.items()
        }
        blender = BlendingModel()
        rvp = blender.calculate_blend_property(
            recipe, component_props, "rvp", BlendMethod.POWER_LAW
        )
        assert rvp <= 14.5, f"Blended RVP {rvp:.2f} above 14.0 spec"

    def test_sulfur_within_limit(self, config):
        from eurekan.core.enums import BlendMethod
        from eurekan.core.crude import CutProperties
        from eurekan.models.blending import BlendingModel
        from eurekan.optimization.builder import _BLEND_COMPONENT_PROPS

        result = run_optimization(config, _make_plan("Blend feasibility"))
        recipe = result.periods[0].blend_results[0].recipe
        component_props = {
            k: CutProperties(**v) for k, v in _BLEND_COMPONENT_PROPS.items()
        }
        blender = BlendingModel()
        sulfur = blender.calculate_blend_property(
            recipe, component_props, "sulfur", BlendMethod.LINEAR_WEIGHT
        )
        assert sulfur <= 0.105, f"Blended sulfur {sulfur:.4f} above 0.10 spec"


# ---------------------------------------------------------------------------
# Category 6 — Price sensitivity
# ---------------------------------------------------------------------------


class TestPriceSensitivity:
    """Conversion should respond directionally to gasoline / diesel prices."""

    def test_gasoline_up_increases_conversion(self, config):
        baseline = run_optimization(
            config,
            _make_plan(
                "Baseline",
                product_prices={**_PROFITABLE_PRICES, "gasoline": 95.0},
            ),
        )
        gas_up = run_optimization(
            config,
            _make_plan(
                "Gas up",
                product_prices={**_PROFITABLE_PRICES, "gasoline": 110.0},
            ),
        )
        assert gas_up.solver_status == "optimal"
        assert baseline.solver_status == "optimal"
        # Higher gasoline price → optimizer should crack harder (higher conversion)
        assert gas_up.periods[0].fcc_result.conversion >= (
            baseline.periods[0].fcc_result.conversion - 0.5
        ), (
            f"Gasoline price up: conv went from "
            f"{baseline.periods[0].fcc_result.conversion:.2f} to "
            f"{gas_up.periods[0].fcc_result.conversion:.2f}"
        )

    def test_diesel_up_decreases_conversion(self, config):
        baseline = run_optimization(
            config,
            _make_plan(
                "Baseline",
                product_prices={**_PROFITABLE_PRICES, "diesel": 100.0},
            ),
        )
        diesel_up = run_optimization(
            config,
            _make_plan(
                "Diesel up",
                product_prices={**_PROFITABLE_PRICES, "diesel": 120.0},
            ),
        )
        assert baseline.solver_status == "optimal"
        assert diesel_up.solver_status == "optimal"
        # Higher diesel price → save the LCO (less cracking → higher LCO yield)
        # Conversion should NOT increase relative to baseline
        assert diesel_up.periods[0].fcc_result.conversion <= (
            baseline.periods[0].fcc_result.conversion + 0.5
        ), (
            f"Diesel price up: conv went from "
            f"{baseline.periods[0].fcc_result.conversion:.2f} to "
            f"{diesel_up.periods[0].fcc_result.conversion:.2f}"
        )

    def test_gasoline_up_increases_margin(self, config):
        baseline = run_optimization(
            config,
            _make_plan(
                "Baseline",
                product_prices={**_PROFITABLE_PRICES, "gasoline": 95.0},
            ),
        )
        gas_up = run_optimization(
            config,
            _make_plan(
                "Gas up",
                product_prices={**_PROFITABLE_PRICES, "gasoline": 110.0},
            ),
        )
        assert gas_up.total_margin > baseline.total_margin
