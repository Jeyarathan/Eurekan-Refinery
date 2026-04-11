"""Tests for PyomoModelBuilder — Task 3.2."""

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


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_crude(crude_id: str, api: float = 30.0, sulfur: float = 0.5) -> CrudeAssay:
    """Build a CrudeAssay with the standard six-cut profile."""
    return CrudeAssay(
        crude_id=crude_id,
        name=crude_id,
        api=api,
        sulfur=sulfur,
        price=70.0,
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


def _make_config(n_crudes: int = 2) -> RefineryConfig:
    crudes = {f"CRUDE_{i}": _make_crude(f"CRUDE_{i}") for i in range(n_crudes)}
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
        name="Test Refinery",
        units=units,
        crude_library=library,
        products=products,
        streams={},
        cut_point_template=US_GULF_COAST_630EP,
    )


def _make_plan(n_periods: int = 1) -> PlanDefinition:
    periods = [
        PeriodData(
            period_id=i,
            duration_hours=24.0,
            demand_min={"gasoline": 1000.0},
            demand_max={"gasoline": 60000.0},
        )
        for i in range(n_periods)
    ]
    return PlanDefinition(
        periods=periods,
        mode=OperatingMode.OPTIMIZE,
        scenario_name="Base",
    )


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


class TestModelBuilds:
    """Builder produces a valid Pyomo model without error."""

    def test_model_builds(self):
        config = _make_config(n_crudes=2)
        plan = _make_plan(n_periods=1)
        builder = PyomoModelBuilder(config, plan)
        model = builder.build()

        assert isinstance(model, pyo.ConcreteModel)
        assert len(model.PERIODS) == 1
        assert len(model.CRUDES) == 2

    def test_model_has_objective(self):
        builder = PyomoModelBuilder(_make_config(2), _make_plan(1))
        model = builder.build()
        objectives = list(model.component_objects(pyo.Objective))
        assert len(objectives) == 1
        assert objectives[0].sense == pyo.maximize

    def test_model_has_fcc_conversion_var(self):
        builder = PyomoModelBuilder(_make_config(2), _make_plan(1))
        model = builder.build()
        assert hasattr(model, "fcc_conversion")
        assert model.fcc_conversion[0].lb == 68.0
        assert model.fcc_conversion[0].ub == 90.0

    def test_model_has_crude_rate_vars(self):
        builder = PyomoModelBuilder(_make_config(3), _make_plan(1))
        model = builder.build()
        assert hasattr(model, "crude_rate")
        for c in model.CRUDES:
            assert model.crude_rate[c, 0].lb == 0.0
            assert model.crude_rate[c, 0].ub > 0.0

    def test_all_variables_have_bounds(self):
        """IPOPT requirement — every variable must have explicit bounds."""
        builder = PyomoModelBuilder(_make_config(2), _make_plan(1))
        model = builder.build()
        for v in model.component_data_objects(pyo.Var):
            assert v.lb is not None, f"Variable {v.name} missing lower bound"
            assert v.ub is not None, f"Variable {v.name} missing upper bound"


class TestVariableCount:
    """Variable count per period.

    Per-period auxiliary variables (independent of crude count):
      1  fcc_conversion
      2  vgo_to_fcc, vgo_to_fo
      12 stream dispositions (ln/hn/hcn/lco/kero/nc4 × 2 destinations)
      1  reformate_purchased
      6  fcc intermediate volumes (lcn, hcn, lco, coke, c3, c4)
      6  product volumes (gasoline, naphtha, jet, diesel, fuel_oil, lpg)
      6  product sales (added in Sprint 4 — production vs sales split)
      = 34 + N_crudes (no tanks); +N_tanks if tanks present
    """

    def test_variable_count_2_crudes(self):
        builder = PyomoModelBuilder(_make_config(2), _make_plan(1))
        model = builder.build()
        n_vars = sum(1 for _ in model.component_data_objects(pyo.Var))
        # 34 auxiliary + 2 crude_rate = 36
        assert n_vars == 36

    def test_variable_count_scales_with_crudes(self):
        builder_5 = PyomoModelBuilder(_make_config(5), _make_plan(1))
        builder_10 = PyomoModelBuilder(_make_config(10), _make_plan(1))
        n5 = sum(1 for _ in builder_5.build().component_data_objects(pyo.Var))
        n10 = sum(1 for _ in builder_10.build().component_data_objects(pyo.Var))
        assert n10 - n5 == 5  # +5 crudes = +5 variables

    def test_variable_count_gulf_coast_scale(self):
        """At Gulf Coast scale (~35 crudes), per-period vars should be ~69."""
        builder = PyomoModelBuilder(_make_config(35), _make_plan(1))
        model = builder.build()
        n_vars = sum(1 for _ in model.component_data_objects(pyo.Var))
        # 34 + 35 = 69
        assert n_vars == 69


class TestConstraintCount:
    """Constraint count per period.

    Per-period constraints:
      1  CDU capacity
      1  FCC capacity
      6  FCC yield definitions (lcn, hcn, lco, coke, c3, c4)
      3  FCC equipment (regen temp, gas compressor, air blower)
      7  Stream dispositions (ln, hn, kero, vgo, nc4, hcn, lco)
      6  Product volume definitions
      6  Blending specs (octane, rvp, sulfur, benzene, aromatics, olefins)
      12 Demand (6 min + 6 max)
      6  Sales == production (Sprint 4, only when no product tanks)
      = 48 per period (no tanks)
    """

    def test_constraint_count_per_period(self):
        builder = PyomoModelBuilder(_make_config(2), _make_plan(1))
        model = builder.build()
        n_cons = sum(1 for _ in model.component_data_objects(pyo.Constraint))
        assert n_cons == 48

    def test_constraints_independent_of_crude_count(self):
        n5 = sum(
            1
            for _ in PyomoModelBuilder(_make_config(5), _make_plan(1))
            .build()
            .component_data_objects(pyo.Constraint)
        )
        n20 = sum(
            1
            for _ in PyomoModelBuilder(_make_config(20), _make_plan(1))
            .build()
            .component_data_objects(pyo.Constraint)
        )
        assert n5 == n20

    def test_has_fcc_yield_constraints(self):
        model = PyomoModelBuilder(_make_config(2), _make_plan(1)).build()
        for name in ("fcc_lcn_def", "fcc_hcn_def", "fcc_lco_def", "fcc_coke_def"):
            assert hasattr(model, name), f"Missing FCC constraint {name}"

    def test_has_blending_specs(self):
        model = PyomoModelBuilder(_make_config(2), _make_plan(1)).build()
        for name in (
            "octane_spec", "rvp_spec", "sulfur_spec",
            "benzene_spec", "aromatics_spec", "olefins_spec",
        ):
            assert hasattr(model, name), f"Missing spec constraint {name}"

    def test_has_capacity_constraints(self):
        model = PyomoModelBuilder(_make_config(2), _make_plan(1)).build()
        assert hasattr(model, "cdu_capacity_con")
        assert hasattr(model, "fcc_capacity_con")
        assert hasattr(model, "fcc_regen_temp_con")


class TestModelBuildsMultiperiod:
    """Multi-period model creates without error and scales correctly."""

    def test_4_period_model_builds(self):
        config = _make_config(n_crudes=2)
        plan = _make_plan(n_periods=4)
        model = PyomoModelBuilder(config, plan).build()

        assert len(model.PERIODS) == 4
        assert len(model.CRUDES) == 2

    def test_4_period_variable_count(self):
        builder = PyomoModelBuilder(_make_config(2), _make_plan(4))
        model = builder.build()
        n_vars = sum(1 for _ in model.component_data_objects(pyo.Var))
        # 36 vars per period × 4 periods
        assert n_vars == 144

    def test_4_period_constraint_count(self):
        builder = PyomoModelBuilder(_make_config(2), _make_plan(4))
        model = builder.build()
        n_cons = sum(1 for _ in model.component_data_objects(pyo.Constraint))
        # 48 cons per period × 4 periods
        assert n_cons == 192

    def test_per_period_variables_distinct(self):
        """Each period has its own variable instances."""
        model = PyomoModelBuilder(_make_config(2), _make_plan(4)).build()
        # fcc_conversion[0] and fcc_conversion[3] should be different objects
        v0 = model.fcc_conversion[0]
        v3 = model.fcc_conversion[3]
        assert v0 is not v3


class TestObjectiveStructure:
    """Objective is finite and well-formed."""

    def test_objective_evaluable(self):
        """The objective expression can be evaluated when variables are fixed."""
        model = PyomoModelBuilder(_make_config(2), _make_plan(1)).build()

        # Fix all variables to feasible values
        for c in model.CRUDES:
            model.crude_rate[c, 0].fix(20000.0)
        model.fcc_conversion[0].fix(80.0)
        model.vgo_to_fcc[0].fix(0.0)
        model.vgo_to_fo[0].fix(0.0)
        for var in [
            "ln_to_blend", "ln_to_sell", "hn_to_blend", "hn_to_sell",
            "hcn_to_blend", "hcn_to_fo", "lco_to_diesel", "lco_to_fo",
            "kero_to_jet", "kero_to_diesel", "nc4_to_blend", "nc4_to_lpg",
        ]:
            getattr(model, var)[0].fix(0.0)
        model.reformate_purchased[0].fix(0.0)
        for var in [
            "fcc_lcn_vol", "fcc_hcn_vol", "fcc_lco_vol",
            "fcc_coke_vol", "fcc_c3_vol", "fcc_c4_vol",
        ]:
            getattr(model, var)[0].fix(0.0)
        for var in [
            "gasoline_volume", "naphtha_volume", "jet_volume",
            "diesel_volume", "fuel_oil_volume", "lpg_volume",
            "gasoline_sales", "naphtha_sales", "jet_sales",
            "diesel_sales", "fuel_oil_sales", "lpg_sales",
        ]:
            getattr(model, var)[0].fix(0.0)

        val = pyo.value(model.objective)
        assert isinstance(val, float)
