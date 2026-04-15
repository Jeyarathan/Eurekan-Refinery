"""Sprint 15 builder integration tests — Aromatics Reformer + Dimersol."""

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
    if "arom_reformer" in unit_ids:
        units["arom_reformer"] = UnitConfig(
            unit_id="arom_reformer", unit_type=UnitType.REFORMER, capacity=35000.0
        )
    if "dimersol" in unit_ids:
        units["dimersol"] = UnitConfig(
            unit_id="dimersol", unit_type=UnitType.ALKYLATION, capacity=6000.0
        )
    if "reformer_1" in unit_ids:
        units["reformer_1"] = UnitConfig(
            unit_id="reformer_1", unit_type=UnitType.REFORMER, capacity=35000.0
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
        mode=OperatingMode.OPTIMIZE, scenario_name="Sprint 15 test",
    )


class TestBackwardCompat:
    def test_baseline_no_arom_dimersol(self):
        model = PyomoModelBuilder(_config_with(), _plan()).build()
        assert not hasattr(model, "hn_to_arom")
        assert not hasattr(model, "prop_to_dimersol")


class TestAromaticsReformer:
    def test_vars_created(self):
        model = PyomoModelBuilder(_config_with("arom_reformer"), _plan()).build()
        for var_name in (
            "hn_to_arom", "btx_volume", "arom_raffinate_vol",
            "arom_hydrogen", "arom_lpg",
        ):
            assert hasattr(model, var_name), f"Missing {var_name}"

    def test_capacity_bounded(self):
        model = PyomoModelBuilder(_config_with("arom_reformer"), _plan()).build()
        assert model.hn_to_arom[0].ub == 35000.0

    def test_yield_constraints(self):
        model = PyomoModelBuilder(_config_with("arom_reformer"), _plan()).build()
        for name in ("arom_btx_def", "arom_raffinate_def", "arom_h2_def", "arom_lpg_def"):
            assert hasattr(model, name), f"Missing {name}"


class TestDimersol:
    def test_vars_created(self):
        model = PyomoModelBuilder(_config_with("dimersol"), _plan()).build()
        assert hasattr(model, "prop_to_dimersol")
        assert hasattr(model, "dimate_vol")

    def test_capacity_bounded(self):
        model = PyomoModelBuilder(_config_with("dimersol"), _plan()).build()
        assert model.prop_to_dimersol[0].ub == 6000.0

    def test_yield_constraint(self):
        model = PyomoModelBuilder(_config_with("dimersol"), _plan()).build()
        assert hasattr(model, "dimersol_yield_def")
        assert hasattr(model, "dimersol_capacity_con")
        assert hasattr(model, "dimersol_feed_con")


class TestHNFourWayRouting:
    """With both reformers, HN has 4 destinations: blend/sell/reformer/arom."""

    def test_hn_disposition_four_way(self):
        model = PyomoModelBuilder(
            _config_with("reformer_1", "arom_reformer"), _plan()
        ).build()
        assert hasattr(model, "hn_to_blend")
        assert hasattr(model, "hn_to_sell")
        assert hasattr(model, "hn_to_reformer")
        assert hasattr(model, "hn_to_arom")


class TestPropyleneRouting:
    def test_dimersol_competes_with_alky(self):
        """With alky + dimersol, both consume FCC propylene."""
        model = PyomoModelBuilder(_config_with("alky_1", "dimersol"), _plan()).build()
        assert hasattr(model, "c3c4_to_alky")
        assert hasattr(model, "prop_to_dimersol")


class TestBoundsAndH2:
    def test_all_bounds_present(self):
        model = PyomoModelBuilder(
            _config_with("arom_reformer", "dimersol", "reformer_1", "alky_1"), _plan()
        ).build()
        for v in model.component_data_objects(pyo.Var):
            assert v.lb is not None, f"Variable {v.name} missing lower bound"
            assert v.ub is not None, f"Variable {v.name} missing upper bound"

    def test_arom_supplies_h2_balance(self):
        """Aromatics reformer H2 production should be in the H2 balance."""
        model = PyomoModelBuilder(_config_with("arom_reformer"), _plan()).build()
        assert hasattr(model, "h2_balance_con")
        assert hasattr(model, "arom_hydrogen")
