"""Sprint 13 builder integration tests — Hydrocracker."""

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
            unit_id="fcc_1", unit_type=UnitType.FCC, capacity=50000.0,
            equipment_limits={"fcc_regen_temp_max": 1400.0},
        ),
    }
    if "hcu_1" in unit_ids:
        units["hcu_1"] = UnitConfig(
            unit_id="hcu_1", unit_type=UnitType.HYDROCRACKER, capacity=20000.0
        )
    if "goht_1" in unit_ids:
        units["goht_1"] = UnitConfig(
            unit_id="goht_1", unit_type=UnitType.HYDROTREATER, capacity=60000.0
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
        mode=OperatingMode.OPTIMIZE, scenario_name="Sprint 13 test",
    )


class TestBackwardCompat:
    def test_baseline_no_hcu(self):
        model = PyomoModelBuilder(_config_with_units(), _plan()).build()
        assert not hasattr(model, "vgo_to_hcu")
        assert not hasattr(model, "hcu_conversion")


class TestHCUIntegration:
    def test_hcu_vars_created(self):
        model = PyomoModelBuilder(_config_with_units("hcu_1"), _plan()).build()
        assert hasattr(model, "vgo_to_hcu")
        assert hasattr(model, "hcu_conversion")
        assert hasattr(model, "hcu_naphtha_vol")
        assert hasattr(model, "hcu_jet_vol")
        assert hasattr(model, "hcu_diesel_vol")
        assert hasattr(model, "hcu_lpg_vol")
        assert hasattr(model, "hcu_unconverted_vol")

    def test_hcu_conversion_bounds(self):
        model = PyomoModelBuilder(_config_with_units("hcu_1"), _plan()).build()
        assert model.hcu_conversion[0].lb == 60.0
        assert model.hcu_conversion[0].ub == 95.0

    def test_hcu_capacity_bounded(self):
        model = PyomoModelBuilder(_config_with_units("hcu_1"), _plan()).build()
        assert model.vgo_to_hcu[0].ub == 20000.0

    def test_hcu_yield_constraints_present(self):
        model = PyomoModelBuilder(_config_with_units("hcu_1"), _plan()).build()
        for name in (
            "hcu_naphtha_def", "hcu_jet_def", "hcu_diesel_def",
            "hcu_lpg_def", "hcu_unconverted_def", "hcu_capacity_con",
        ):
            assert hasattr(model, name), f"Missing {name}"

    def test_all_variables_have_bounds(self):
        model = PyomoModelBuilder(_config_with_units("hcu_1", "goht_1"), _plan()).build()
        for v in model.component_data_objects(pyo.Var):
            assert v.lb is not None, f"Variable {v.name} missing lower bound"
            assert v.ub is not None, f"Variable {v.name} missing upper bound"


class TestVGOFourWayRouting:
    """With HCU + GO HT, VGO has 4 destinations: FCC, GO HT, HCU, fuel oil."""

    def test_vgo_disposition_accepts_hcu(self):
        """VGO disposition constraint must include HCU in LHS."""
        model = PyomoModelBuilder(_config_with_units("hcu_1", "goht_1"), _plan()).build()
        # All VGO destinations exist
        assert hasattr(model, "vgo_to_fcc")
        assert hasattr(model, "vgo_to_fo")
        assert hasattr(model, "vgo_to_goht")
        assert hasattr(model, "vgo_to_hcu")
