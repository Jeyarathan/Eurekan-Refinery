"""Sprint 12 builder integration tests — Vacuum Unit + Delayed Coker."""

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


def _make_crude(crude_id: str) -> CrudeAssay:
    return CrudeAssay(
        crude_id=crude_id,
        name=crude_id,
        api=30.0,
        sulfur=0.5,
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


def _config_with_units(*unit_ids: str) -> RefineryConfig:
    crudes = {f"CRUDE_{i}": _make_crude(f"CRUDE_{i}") for i in range(2)}
    units = {
        "cdu_1": UnitConfig(unit_id="cdu_1", unit_type=UnitType.CDU, capacity=80000.0),
        "fcc_1": UnitConfig(
            unit_id="fcc_1",
            unit_type=UnitType.FCC,
            capacity=50000.0,
            equipment_limits={"fcc_regen_temp_max": 1400.0},
        ),
    }
    if "vacuum_1" in unit_ids:
        units["vacuum_1"] = UnitConfig(
            unit_id="vacuum_1", unit_type=UnitType.VACUUM, capacity=50000.0
        )
    if "coker_1" in unit_ids:
        units["coker_1"] = UnitConfig(
            unit_id="coker_1", unit_type=UnitType.COKER, capacity=50000.0
        )
    if "dht_1" in unit_ids:
        units["dht_1"] = UnitConfig(
            unit_id="dht_1", unit_type=UnitType.HYDROTREATER, capacity=80000.0
        )
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
        name="Test", units=units, crude_library=CrudeLibrary(crudes),
        products=products, streams={}, cut_point_template=US_GULF_COAST_630EP,
    )


def _plan() -> PlanDefinition:
    return PlanDefinition(
        periods=[
            PeriodData(
                period_id=0,
                duration_hours=24.0,
                demand_min={"gasoline": 1000.0},
                demand_max={"gasoline": 60000.0},
            )
        ],
        mode=OperatingMode.OPTIMIZE,
        scenario_name="Sprint 12 test",
    )


class TestBackwardCompat:
    """Models without vacuum/coker still work identically."""

    def test_baseline_model_builds(self):
        builder = PyomoModelBuilder(_config_with_units(), _plan())
        model = builder.build()
        assert isinstance(model, pyo.ConcreteModel)
        # No vacuum/coker variables should exist
        assert not hasattr(model, "vac_feed")
        assert not hasattr(model, "coker_feed")

    def test_baseline_var_count_unchanged(self):
        """Stage 1 var count: 37/period."""
        builder = PyomoModelBuilder(_config_with_units(), _plan())
        model = builder.build()
        n_vars = sum(1 for _ in model.component_data_objects(pyo.Var))
        assert n_vars == 37


class TestVacuumOnly:
    def test_vacuum_model_builds(self):
        builder = PyomoModelBuilder(_config_with_units("vacuum_1"), _plan())
        model = builder.build()
        assert hasattr(model, "vac_feed")
        assert hasattr(model, "vacuum_lvgo")
        assert hasattr(model, "vacuum_hvgo")
        assert hasattr(model, "vacuum_vr_to_fo")

    def test_vacuum_capacity_constraint(self):
        builder = PyomoModelBuilder(_config_with_units("vacuum_1"), _plan())
        model = builder.build()
        assert hasattr(model, "vacuum_capacity_con")
        assert model.vac_feed[0].ub == 50000.0

    def test_vacuum_yields_defined(self):
        builder = PyomoModelBuilder(_config_with_units("vacuum_1"), _plan())
        model = builder.build()
        assert hasattr(model, "vacuum_lvgo_def")
        assert hasattr(model, "vacuum_hvgo_def")

    def test_vacuum_no_coker_forces_zero(self):
        """Without coker, vacuum_vr_to_coker must be 0."""
        builder = PyomoModelBuilder(_config_with_units("vacuum_1"), _plan())
        model = builder.build()
        assert hasattr(model, "vacuum_vr_no_coker_con")


class TestCokerOnly:
    def test_coker_model_builds(self):
        builder = PyomoModelBuilder(_config_with_units("coker_1"), _plan())
        model = builder.build()
        assert hasattr(model, "coker_feed")
        assert hasattr(model, "coker_naphtha_vol")
        assert hasattr(model, "coker_coke_vol")

    def test_coker_yields_defined(self):
        builder = PyomoModelBuilder(_config_with_units("coker_1"), _plan())
        model = builder.build()
        for name in (
            "coker_naphtha_def",
            "coker_go_def",
            "coker_hgo_def",
            "coker_coke_def",
            "coker_gas_def",
        ):
            assert hasattr(model, name), f"Missing {name}"


class TestVacuumPlusCoker:
    def test_full_heavy_end_builds(self):
        builder = PyomoModelBuilder(_config_with_units("vacuum_1", "coker_1"), _plan())
        model = builder.build()
        assert hasattr(model, "vac_feed")
        assert hasattr(model, "coker_feed")
        # Coker feed source links to vacuum
        assert hasattr(model, "coker_feed_source_con")

    def test_heavy_end_with_dht(self):
        builder = PyomoModelBuilder(
            _config_with_units("vacuum_1", "coker_1", "dht_1"), _plan()
        )
        model = builder.build()
        assert hasattr(model, "coker_go_to_dht")
        # No "no DHT" forcing constraint
        assert not hasattr(model, "coker_go_no_dht_con")

    def test_heavy_end_no_dht_forces_zero(self):
        """Without DHT, coker_go_to_dht must be 0."""
        builder = PyomoModelBuilder(_config_with_units("vacuum_1", "coker_1"), _plan())
        model = builder.build()
        assert hasattr(model, "coker_go_no_dht_con")

    def test_all_variables_have_bounds(self):
        builder = PyomoModelBuilder(
            _config_with_units("vacuum_1", "coker_1", "dht_1"), _plan()
        )
        model = builder.build()
        for v in model.component_data_objects(pyo.Var):
            assert v.lb is not None, f"Variable {v.name} missing lower bound"
            assert v.ub is not None, f"Variable {v.name} missing upper bound"
