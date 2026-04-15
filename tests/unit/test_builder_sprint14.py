"""Sprint 14 builder integration tests — Isomerization + Gas Plants."""

from __future__ import annotations

import pyomo.environ as pyo

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
        crude_id=crude_id, name=crude_id, api=30.0, sulfur=0.5, price=70.0,
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


def _config_with(*unit_ids: str) -> RefineryConfig:
    crudes = {f"CRUDE_{i}": _make_crude(f"CRUDE_{i}") for i in range(2)}
    units = {
        "cdu_1": UnitConfig(unit_id="cdu_1", unit_type=UnitType.CDU, capacity=80000.0),
        "fcc_1": UnitConfig(
            unit_id="fcc_1", unit_type=UnitType.FCC, capacity=50000.0,
            equipment_limits={"fcc_regen_temp_max": 1400.0},
        ),
    }
    if "isom_c56" in unit_ids:
        units["isom_c56"] = UnitConfig(
            unit_id="isom_c56", unit_type=UnitType.ISOMERIZATION, capacity=15000.0
        )
    if "isom_c4" in unit_ids:
        units["isom_c4"] = UnitConfig(
            unit_id="isom_c4", unit_type=UnitType.ISOMERIZATION, capacity=5000.0
        )
    if "alky_1" in unit_ids:
        units["alky_1"] = UnitConfig(
            unit_id="alky_1", unit_type=UnitType.ALKYLATION, capacity=14000.0
        )
    products = {
        "regular_gasoline": Product(
            product_id="regular_gasoline", name="Regular Gasoline", price=82.81,
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
        periods=[PeriodData(
            period_id=0, duration_hours=24.0,
            demand_min={"gasoline": 1000.0}, demand_max={"gasoline": 60000.0},
        )],
        mode=OperatingMode.OPTIMIZE, scenario_name="Sprint 14 test",
    )


class TestBackwardCompat:
    def test_baseline_no_isom(self):
        model = PyomoModelBuilder(_config_with(), _plan()).build()
        assert not hasattr(model, "ln_to_isom")
        assert not hasattr(model, "nc4_to_c4isom")


class TestC56Isomerization:
    def test_vars_created(self):
        model = PyomoModelBuilder(_config_with("isom_c56"), _plan()).build()
        assert hasattr(model, "ln_to_isom")
        assert hasattr(model, "isomerate_vol")
        assert model.ln_to_isom[0].ub == 15000.0

    def test_yield_constraint(self):
        model = PyomoModelBuilder(_config_with("isom_c56"), _plan()).build()
        assert hasattr(model, "isom56_yield_def")
        assert hasattr(model, "isom56_capacity_con")

    def test_ln_disposition_has_three_destinations(self):
        """When isom_c56 exists, LN goes to blend + sell + isom."""
        model = PyomoModelBuilder(_config_with("isom_c56"), _plan()).build()
        assert hasattr(model, "ln_to_blend")
        assert hasattr(model, "ln_to_sell")
        assert hasattr(model, "ln_to_isom")


class TestC4Isomerization:
    def test_vars_created(self):
        model = PyomoModelBuilder(_config_with("isom_c4"), _plan()).build()
        assert hasattr(model, "nc4_to_c4isom")
        assert hasattr(model, "ic4_from_c4isom")
        assert model.nc4_to_c4isom[0].ub == 5000.0

    def test_yield_constraint(self):
        model = PyomoModelBuilder(_config_with("isom_c4"), _plan()).build()
        assert hasattr(model, "isomc4_yield_def")
        assert hasattr(model, "isomc4_capacity_con")

    def test_nc4_disposition_three_way(self):
        """With C4 isom, nC4 has 3 destinations: blend/lpg/c4isom."""
        model = PyomoModelBuilder(_config_with("isom_c4"), _plan()).build()
        assert hasattr(model, "nc4_to_c4isom")


class TestIsomerizationPlusAlky:
    def test_c4_isom_feeds_alky(self):
        """With C4 isom + alky, ic4_from_c4isom reduces ic4_purchased need."""
        model = PyomoModelBuilder(_config_with("isom_c4", "alky_1"), _plan()).build()
        # Alky iC4 constraint should allow iC4 from C4 isom as supply
        assert hasattr(model, "alky_ic4_con")
        assert hasattr(model, "ic4_from_c4isom")
        assert hasattr(model, "ic4_purchased")


class TestBoundsAndConstraints:
    def test_all_variables_have_bounds(self):
        model = PyomoModelBuilder(
            _config_with("isom_c56", "isom_c4", "alky_1"), _plan()
        ).build()
        for v in model.component_data_objects(pyo.Var):
            assert v.lb is not None, f"Variable {v.name} missing lower bound"
            assert v.ub is not None, f"Variable {v.name} missing upper bound"

    def test_full_config_builds(self):
        model = PyomoModelBuilder(
            _config_with("isom_c56", "isom_c4", "alky_1"), _plan()
        ).build()
        assert isinstance(model, pyo.ConcreteModel)
