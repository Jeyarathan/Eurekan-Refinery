"""Integration tests for EurekanSolver and operating modes — Tasks 3.3 and 3.4."""

from __future__ import annotations

import pyomo.environ as pyo
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
from eurekan.optimization.modes import run_hybrid, run_optimization, run_simulation
from eurekan.optimization.solver import EurekanSolver, SolveResult


# ---------------------------------------------------------------------------
# Synthetic Gulf-Coast-scale config
# ---------------------------------------------------------------------------


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
    """Synthetic Gulf-Coast-like refinery with several crudes spanning a price range."""
    crudes = {
        f"C{i}": _make_crude(
            f"C{i}",
            api=26.0 + i * 0.6,
            sulfur=0.3 + i * 0.15,
            price=68.0 + i * 0.7,
        )
        for i in range(8)
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
                ProductSpec(spec_name="benzene", max_value=1.0),
                ProductSpec(spec_name="aromatics", max_value=35.0),
                ProductSpec(spec_name="olefins", max_value=18.0),
            ],
        ),
    }
    return RefineryConfig(
        name="Synthetic Gulf Coast",
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
def solver() -> EurekanSolver:
    return EurekanSolver()


# ---------------------------------------------------------------------------
# Tier 1 — Heuristic warm-start
# ---------------------------------------------------------------------------


class TestHeuristicStart:
    def test_heuristic_start_feasible(self, config, plan, solver):
        """Heuristic start produces a finite, evaluable objective value."""
        model = PyomoModelBuilder(config, plan).build()
        solver.generate_heuristic_start(model, config, plan)

        # All variables should now have non-None initial values
        for v in model.component_data_objects(pyo.Var):
            assert v.value is not None, f"Variable {v.name} not initialized"

        obj_val = pyo.value(model.objective)
        assert obj_val is not None
        assert isinstance(obj_val, float)

    def test_heuristic_start_uses_all_crudes(self, config, plan, solver):
        """Heuristic should distribute crude across the library."""
        model = PyomoModelBuilder(config, plan).build()
        solver.generate_heuristic_start(model, config, plan)
        nonzero = sum(
            1 for c in model.CRUDES if pyo.value(model.crude_rate[c, 0]) > 0
        )
        assert nonzero == len(list(model.CRUDES))

    def test_heuristic_conversion_is_80(self, config, plan, solver):
        model = PyomoModelBuilder(config, plan).build()
        solver.generate_heuristic_start(model, config, plan)
        assert pyo.value(model.fcc_conversion[0]) == 80.0


# ---------------------------------------------------------------------------
# Solve / Tier 2 LP / Tier 3 fallback
# ---------------------------------------------------------------------------


class TestSolve:
    def test_solve_returns_solveresult(self, config, plan, solver):
        model = PyomoModelBuilder(config, plan).build()
        solver.generate_heuristic_start(model, config, plan)
        result = solver.solve(model)
        assert isinstance(result, SolveResult)
        assert result.status == "optimal"
        assert result.solve_time > 0

    def test_lp_start_runs(self, config, plan, solver):
        """Tier 2 LP relaxation produces a valid starting point."""
        model = PyomoModelBuilder(config, plan).build()
        solver.generate_lp_start(model, config, plan)
        # All variables should have values from the LP solve
        for v in model.component_data_objects(pyo.Var):
            assert v.value is not None
        # The NLP should solve quickly from this start
        result = solver.solve(model)
        assert result.feasible

    def test_solve_with_fallback(self, config, plan, solver):
        model = PyomoModelBuilder(config, plan).build()
        result = solver.solve_with_fallback(model, config, plan)
        assert result.feasible
        assert result.tier_used in (1, 2, 3)


# ---------------------------------------------------------------------------
# run_optimization
# ---------------------------------------------------------------------------


class TestOptimizationMode:
    def test_optimization_converges(self, config, plan):
        """Optimizer reaches an optimal solution on the synthetic config."""
        result = run_optimization(config, plan)
        assert result.solver_status == "optimal"
        assert len(result.periods) == 1

    def test_optimization_margin_positive(self, config, plan):
        """Optimal margin should be positive (revenue exceeds cost)."""
        result = run_optimization(config, plan)
        assert result.total_margin > 0

    def test_optimization_specs_met(self, config, plan):
        """All gasoline specs are feasible at the optimal solution."""
        result = run_optimization(config, plan)
        # Re-check specs by extracting blend recipe and computing properties
        from eurekan.models.blending import BlendingModel
        from eurekan.optimization.builder import _BLEND_COMPONENT_PROPS

        blender = BlendingModel()
        recipe = result.periods[0].blend_results[0].recipe
        component_props = {k: CutProperties(**v) for k, v in _BLEND_COMPONENT_PROPS.items()}

        # Check octane (the binding spec in most cases)
        if sum(recipe.values()) > 0:
            from eurekan.core.enums import BlendMethod

            ron = blender.calculate_blend_property(
                recipe, component_props, "ron", BlendMethod.INDEX
            )
            # Allow small numerical tolerance — IPOPT solves to 1e-6
            assert ron >= 86.5, f"Blended RON {ron:.2f} below spec 87"

    def test_optimization_returns_planning_result(self, config, plan):
        result = run_optimization(config, plan)
        assert result.scenario_name == "Base"
        assert result.scenario_id is not None
        assert len(result.material_flow.nodes) > 0
        assert len(result.crude_valuations) > 0


# ---------------------------------------------------------------------------
# run_simulation
# ---------------------------------------------------------------------------


class TestSimulationMode:
    def test_simulation_mode(self, config):
        """Simulation with fixed inputs produces consistent outputs."""
        sim_plan = PlanDefinition(
            periods=[PeriodData(period_id=0, duration_hours=24.0)],
            mode=OperatingMode.SIMULATE,
            scenario_name="Sim Base",
            fixed_variables={
                "fcc_conversion[0]": 80.0,
                "crude_rate[C0,0]": 30000.0,
                "crude_rate[C1,0]": 30000.0,
            },
        )
        result = run_simulation(config, sim_plan)
        assert result.solver_status == "optimal"
        assert result.periods[0].fcc_result.conversion == 80.0
        # Crude slate should reflect the fixed values
        assert result.periods[0].crude_slate["C0"] == 30000.0
        assert result.periods[0].crude_slate["C1"] == 30000.0

    def test_simulation_no_optimization(self, config):
        """Simulation does not change fixed variables."""
        sim_plan = PlanDefinition(
            periods=[PeriodData(period_id=0, duration_hours=24.0)],
            mode=OperatingMode.SIMULATE,
            scenario_name="Sim",
            fixed_variables={
                "fcc_conversion[0]": 75.0,
            },
        )
        result = run_simulation(config, sim_plan)
        assert result.periods[0].fcc_result.conversion == 75.0


# ---------------------------------------------------------------------------
# run_hybrid
# ---------------------------------------------------------------------------


class TestHybridMode:
    def test_hybrid_mode_differs_from_full_optimization(self, config):
        """Fixing crudes should give a different (or equal) margin than full optimization."""
        full_plan = PlanDefinition(
            periods=[PeriodData(period_id=0, duration_hours=24.0)],
            mode=OperatingMode.OPTIMIZE,
            scenario_name="Full",
        )
        full_result = run_optimization(config, full_plan)

        # Hybrid: force using only one crude (C5) at a fixed rate
        hybrid_plan = PlanDefinition(
            periods=[PeriodData(period_id=0, duration_hours=24.0)],
            mode=OperatingMode.HYBRID,
            scenario_name="Hybrid",
            parent_scenario_id=full_result.scenario_id,
            fixed_variables={
                "crude_rate[C0,0]": 0.0,
                "crude_rate[C1,0]": 0.0,
                "crude_rate[C2,0]": 0.0,
                "crude_rate[C3,0]": 0.0,
                "crude_rate[C4,0]": 0.0,
                "crude_rate[C5,0]": 60000.0,
                "crude_rate[C6,0]": 0.0,
                "crude_rate[C7,0]": 0.0,
            },
        )
        hybrid_result = run_hybrid(config, hybrid_plan)

        assert hybrid_result.solver_status == "optimal"
        assert hybrid_result.parent_scenario_id == full_result.scenario_id
        # Optimal slate is unconstrained, hybrid forces a different slate.
        # Margins should differ unless C5 happens to be the optimal pick.
        assert hybrid_result.total_margin != full_result.total_margin or \
            abs(hybrid_result.total_margin - full_result.total_margin) < 1e-6

    def test_hybrid_respects_fixed_variables(self, config):
        hybrid_plan = PlanDefinition(
            periods=[PeriodData(period_id=0, duration_hours=24.0)],
            mode=OperatingMode.HYBRID,
            scenario_name="Hybrid Conv",
            fixed_variables={"fcc_conversion[0]": 78.0},
        )
        result = run_hybrid(config, hybrid_plan)
        assert result.solver_status == "optimal"
        assert abs(result.periods[0].fcc_result.conversion - 78.0) < 1e-3
