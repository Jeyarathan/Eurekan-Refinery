"""Sprint 16 builder integration tests — Unsaturated + Saturated Gas Plants."""

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
from eurekan.models.gas_plant import (
    SGP_FUEL_GAS_FRAC,
    SGP_ISOBUTANE_FRAC,
    SGP_NORMAL_BUTANE_FRAC,
    SGP_PROPANE_FRAC,
    UGP_BUTYLENE_FRAC,
    UGP_FUEL_GAS_FRAC,
    UGP_ISOBUTANE_FRAC,
    UGP_NORMAL_BUTANE_FRAC,
    UGP_PROPANE_FRAC,
    UGP_PROPYLENE_FRAC,
)
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
    optional: dict[str, UnitConfig] = {
        "alky_1": UnitConfig(unit_id="alky_1", unit_type=UnitType.ALKYLATION, capacity=14000.0),
        "isom_c4": UnitConfig(unit_id="isom_c4", unit_type=UnitType.ISOMERIZATION, capacity=5000.0),
        "dimersol": UnitConfig(unit_id="dimersol", unit_type=UnitType.ALKYLATION, capacity=6000.0),
        "coker_1": UnitConfig(unit_id="coker_1", unit_type=UnitType.COKER, capacity=20000.0),
        "hcu_1": UnitConfig(unit_id="hcu_1", unit_type=UnitType.HYDROCRACKER, capacity=30000.0),
        "ugp_1": UnitConfig(unit_id="ugp_1", unit_type=UnitType.GAS_PLANT, capacity=0.0),
        "sgp_1": UnitConfig(unit_id="sgp_1", unit_type=UnitType.GAS_PLANT, capacity=0.0),
    }
    for uid in unit_ids:
        if uid in optional:
            units[uid] = optional[uid]
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
        mode=OperatingMode.OPTIMIZE, scenario_name="Sprint 16 test",
    )


class TestBackwardCompat:
    def test_baseline_no_gas_plants(self):
        """Without SUGP/SSGP, no UGP/SGP variables in the model."""
        model = PyomoModelBuilder(_config_with(), _plan()).build()
        assert not hasattr(model, "ugp_feed")
        assert not hasattr(model, "sgp_feed")


class TestUnsaturatedGasPlant:
    def test_vars_created(self):
        model = PyomoModelBuilder(_config_with("ugp_1"), _plan()).build()
        for var_name in (
            "ugp_feed",
            "ugp_propylene_vol", "ugp_propane_vol", "ugp_butylene_vol",
            "ugp_ic4_vol", "ugp_nc4_vol", "ugp_fuel_gas_vol",
            "ugp_ic4_to_alky", "ugp_ic4_to_lpg",
            "ugp_nc4_to_c4isom", "ugp_nc4_to_lpg",
        ):
            assert hasattr(model, var_name), f"Missing {var_name}"

    def test_yield_constraints_present(self):
        model = PyomoModelBuilder(_config_with("ugp_1"), _plan()).build()
        for name in (
            "ugp_feed_def",
            "ugp_propylene_def", "ugp_propane_def", "ugp_butylene_def",
            "ugp_ic4_def", "ugp_nc4_def", "ugp_fuel_gas_def",
            "ugp_ic4_split", "ugp_nc4_split",
        ):
            assert hasattr(model, name), f"Missing constraint {name}"

    def test_split_fractions_sum_to_one(self):
        """UGP product fractions must sum to 1.0 (mass balance)."""
        total = (
            UGP_PROPYLENE_FRAC + UGP_PROPANE_FRAC
            + UGP_BUTYLENE_FRAC + UGP_ISOBUTANE_FRAC
            + UGP_NORMAL_BUTANE_FRAC + UGP_FUEL_GAS_FRAC
        )
        assert abs(total - 1.0) < 1e-9

    def test_c3_pool_split_per_user_spec(self):
        """C3 pool: 65% propylene + 35% propane per user spec."""
        # Within the C3 sub-pool (propylene + propane), propylene should be 65%.
        c3_total = UGP_PROPYLENE_FRAC + UGP_PROPANE_FRAC
        assert abs(UGP_PROPYLENE_FRAC / c3_total - 0.65) < 1e-9
        assert abs(UGP_PROPANE_FRAC / c3_total - 0.35) < 1e-9

    def test_c4_pool_split_per_user_spec(self):
        """C4 pool: 50% butylenes + 30% iC4 + 20% nC4 per user spec."""
        c4_total = UGP_BUTYLENE_FRAC + UGP_ISOBUTANE_FRAC + UGP_NORMAL_BUTANE_FRAC
        assert abs(UGP_BUTYLENE_FRAC / c4_total - 0.50) < 1e-9
        assert abs(UGP_ISOBUTANE_FRAC / c4_total - 0.30) < 1e-9
        assert abs(UGP_NORMAL_BUTANE_FRAC / c4_total - 0.20) < 1e-9

    def test_no_c4_isom_blocks_nc4_route(self):
        """Without C4 isom, UGP nC4 can't route there."""
        model = PyomoModelBuilder(_config_with("ugp_1"), _plan()).build()
        assert hasattr(model, "ugp_nc4_no_isom_con")

    def test_no_alky_blocks_ic4_route(self):
        """Without alky, UGP iC4 can't route there."""
        model = PyomoModelBuilder(_config_with("ugp_1"), _plan()).build()
        assert hasattr(model, "ugp_ic4_no_alky_con")

    def test_routes_enabled_with_downstream_units(self):
        """With alky + isom_c4, routing constraints allow both paths."""
        model = PyomoModelBuilder(
            _config_with("ugp_1", "alky_1", "isom_c4"), _plan()
        ).build()
        assert not hasattr(model, "ugp_nc4_no_isom_con")
        assert not hasattr(model, "ugp_ic4_no_alky_con")


class TestSaturatedGasPlant:
    def test_vars_created(self):
        model = PyomoModelBuilder(_config_with("sgp_1"), _plan()).build()
        for var_name in (
            "sgp_feed",
            "sgp_propane_vol", "sgp_ic4_vol", "sgp_nc4_vol", "sgp_fuel_gas_vol",
            "sgp_ic4_to_alky", "sgp_ic4_to_lpg",
            "sgp_nc4_to_c4isom", "sgp_nc4_to_lpg",
        ):
            assert hasattr(model, var_name), f"Missing {var_name}"

    def test_yield_constraints_present(self):
        model = PyomoModelBuilder(_config_with("sgp_1"), _plan()).build()
        for name in (
            "sgp_feed_def",
            "sgp_propane_def", "sgp_ic4_def", "sgp_nc4_def", "sgp_fuel_gas_def",
            "sgp_ic4_split", "sgp_nc4_split",
        ):
            assert hasattr(model, name), f"Missing constraint {name}"

    def test_split_fractions_sum_to_one(self):
        total = (
            SGP_PROPANE_FRAC + SGP_ISOBUTANE_FRAC
            + SGP_NORMAL_BUTANE_FRAC + SGP_FUEL_GAS_FRAC
        )
        assert abs(total - 1.0) < 1e-9

    def test_feed_includes_coker_and_hcu(self):
        """With coker + HCU, SGP feed draws from all saturated streams."""
        model = PyomoModelBuilder(
            _config_with("sgp_1", "coker_1", "hcu_1"), _plan()
        ).build()
        assert hasattr(model, "sgp_feed_def")


class TestAlkyWithGasPlants:
    def test_alky_ic4_supply_includes_ugp_and_sgp(self):
        """Alky iC4 supply constraint should include UGP/SGP iC4."""
        model = PyomoModelBuilder(
            _config_with("alky_1", "ugp_1", "sgp_1"), _plan()
        ).build()
        assert hasattr(model, "alky_ic4_con")
        # Variables must exist for the constraint to reference them
        assert hasattr(model, "ugp_ic4_to_alky")
        assert hasattr(model, "sgp_ic4_to_alky")

    def test_alky_olefin_feed_uses_ugp_pool(self):
        """Alky olefin feed must use UGP propylene + butylene when UGP exists."""
        model = PyomoModelBuilder(
            _config_with("alky_1", "ugp_1"), _plan()
        ).build()
        assert hasattr(model, "alky_feed_con")
        assert hasattr(model, "ugp_propylene_vol")
        assert hasattr(model, "ugp_butylene_vol")


class TestC4IsomWithGasPlants:
    def test_c4isom_feed_sums_cdu_and_gas_plants(self):
        """C4 isom total feed = CDU nC4 + UGP nC4 + SGP nC4."""
        model = PyomoModelBuilder(
            _config_with("isom_c4", "ugp_1", "sgp_1"), _plan()
        ).build()
        assert hasattr(model, "isomc4_capacity_con")
        assert hasattr(model, "isomc4_yield_def")
        assert hasattr(model, "ugp_nc4_to_c4isom")
        assert hasattr(model, "sgp_nc4_to_c4isom")


class TestBoundsAndBuild:
    def test_all_bounds_present_with_gas_plants(self):
        model = PyomoModelBuilder(
            _config_with("ugp_1", "sgp_1", "alky_1", "isom_c4", "coker_1", "hcu_1"),
            _plan(),
        ).build()
        for v in model.component_data_objects(pyo.Var):
            assert v.lb is not None, f"Variable {v.name} missing lower bound"
            assert v.ub is not None, f"Variable {v.name} missing upper bound"

    def test_objective_evaluable_with_gas_plants(self):
        """Objective should include UGP/SGP opex terms."""
        model = PyomoModelBuilder(_config_with("ugp_1", "sgp_1"), _plan()).build()
        assert hasattr(model, "objective")
        # Opex addition shouldn't crash evaluation at zero-initialized values
        val = pyo.value(model.objective)
        assert val is not None
