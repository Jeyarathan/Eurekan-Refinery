"""Integration tests for ConstraintDiagnostician — Task 3.6."""

from __future__ import annotations

import pytest

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
from eurekan.optimization.builder import PyomoModelBuilder
from eurekan.optimization.diagnostics import ConstraintDiagnostician
from eurekan.optimization.solver import EurekanSolver


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
        name="Diagnostics Test",
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
def solved_model(config, plan):
    """A solved Pyomo model with the dual suffix attached."""
    model = PyomoModelBuilder(config, plan).build()
    solver = EurekanSolver()
    result = solver.solve_with_fallback(model, config, plan)
    assert result.feasible
    return model


@pytest.fixture
def diagnostician() -> ConstraintDiagnostician:
    return ConstraintDiagnostician()


# ---------------------------------------------------------------------------
# Feasible diagnostics
# ---------------------------------------------------------------------------


class TestFeasibleDiagnostics:
    def test_diagnose_feasible_returns_list(self, solved_model, diagnostician):
        diagnostics = diagnostician.diagnose_feasible(solved_model)
        assert len(diagnostics) > 0

    def test_binding_constraints(self, solved_model, diagnostician):
        """At least one constraint should be binding after optimization."""
        diagnostics = diagnostician.diagnose_feasible(solved_model)
        binding = [d for d in diagnostics if d.binding]
        assert len(binding) > 0, "Expected at least one binding constraint"

    def test_bottleneck_scores(self, solved_model, diagnostician):
        """All bottleneck scores in [0, 100], at least one > 0."""
        diagnostics = diagnostician.diagnose_feasible(solved_model)
        for d in diagnostics:
            assert 0 <= d.bottleneck_score <= 100, (
                f"Score {d.bottleneck_score} for {d.constraint_name} out of range"
            )
        assert any(d.bottleneck_score > 0 for d in diagnostics)

    def test_shadow_prices(self, solved_model, diagnostician):
        """Binding constraints should have non-zero shadow prices."""
        diagnostics = diagnostician.diagnose_feasible(solved_model)
        for d in diagnostics:
            if d.binding:
                assert d.shadow_price is not None
                assert abs(d.shadow_price) > 0

    def test_diagnostics_sorted_by_bottleneck(self, solved_model, diagnostician):
        """Diagnostics should be sorted by bottleneck score, highest first."""
        diagnostics = diagnostician.diagnose_feasible(solved_model)
        scores = [d.bottleneck_score for d in diagnostics]
        assert scores == sorted(scores, reverse=True)

    def test_top_constraint_has_suggestion(self, solved_model, diagnostician):
        """The top binding constraint should have a relaxation_suggestion."""
        diagnostics = diagnostician.diagnose_feasible(solved_model)
        binding = [d for d in diagnostics if d.binding]
        if binding:
            top = binding[0]
            assert top.relaxation_suggestion is not None
            assert len(top.relaxation_suggestion) > 10


# ---------------------------------------------------------------------------
# Infeasibility detection
# ---------------------------------------------------------------------------


class TestInfeasibilityDetection:
    def _build_infeasible_config(self) -> RefineryConfig:
        """Tight 1ppm sulfur spec — impossible with reformate (10ppm) blend."""
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
                    ProductSpec(spec_name="sulfur", max_value=0.0001),  # 1 ppm
                ],
            ),
        }
        return RefineryConfig(
            name="Infeasible",
            units=units,
            crude_library=library,
            products=products,
            streams={},
            cut_point_template=US_GULF_COAST_630EP,
        )

    def _infeasible_plan(self) -> PlanDefinition:
        # Force production so the slack model can't trivially zero everything out
        return PlanDefinition(
            periods=[
                PeriodData(
                    period_id=0,
                    duration_hours=24.0,
                    demand_min={"gasoline": 50000.0},
                )
            ],
            mode=OperatingMode.OPTIMIZE,
            scenario_name="Infeasible Sulfur",
        )

    def test_infeasibility_detected(self, diagnostician):
        config = self._build_infeasible_config()
        plan = self._infeasible_plan()
        report = diagnostician.diagnose_infeasible(config, plan)
        assert not report.is_feasible
        assert len(report.violated_constraints) > 0

    def test_sulfur_in_violations(self, diagnostician):
        config = self._build_infeasible_config()
        plan = self._infeasible_plan()
        report = diagnostician.diagnose_infeasible(config, plan)
        sulfur_violations = [
            v for v in report.violated_constraints if "sulfur" in v.constraint_name
        ]
        assert len(sulfur_violations) > 0, "Sulfur spec should be violated"

    def test_cheapest_fix(self, diagnostician):
        """The infeasibility report should have a cheapest_fix suggestion."""
        config = self._build_infeasible_config()
        plan = self._infeasible_plan()
        report = diagnostician.diagnose_infeasible(config, plan)
        assert report.cheapest_fix is not None
        assert len(report.cheapest_fix) > 0

    def test_violations_sorted_by_cost(self, diagnostician):
        """Violations should be sorted cheapest fix first."""
        config = self._build_infeasible_config()
        plan = self._infeasible_plan()
        report = diagnostician.diagnose_infeasible(config, plan)
        if len(report.violated_constraints) >= 2:
            costs = [
                v.relaxation_cost or float("inf") for v in report.violated_constraints
            ]
            assert costs == sorted(costs)

    def test_suggestions_present(self, diagnostician):
        config = self._build_infeasible_config()
        plan = self._infeasible_plan()
        report = diagnostician.diagnose_infeasible(config, plan)
        assert len(report.suggestions) > 0
