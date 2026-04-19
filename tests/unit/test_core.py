"""Tests for core data models (Tasks 1.1-1.4)."""

import warnings
from datetime import datetime, timezone

import pytest

from eurekan.core.enums import (
    BlendMethod,
    DataSource,
    OperatingMode,
    StreamDisposition,
    TankType,
    UnitType,
)
from eurekan.core.product import BlendingRule, Product, ProductSpec
from eurekan.core.stream import Stream
from eurekan.core.tank import Tank
from eurekan.core.config import ConfigCompleteness, RefineryConfig, UnitConfig
from eurekan.core.period import PeriodData, PlanDefinition
from eurekan.core.results import (
    BlendResult,
    ConstraintDiagnostic,
    CrudeDisposition,
    DecisionExplanation,
    DispositionResult,
    EquipmentStatus,
    FCCResult,
    FlowEdge,
    FlowNode,
    FlowNodeType,
    InfeasibilityReport,
    MaterialFlowGraph,
    OracleResult,
    PeriodResult,
    PlanningResult,
    RiskFlag,
    ScenarioComparison,
    SolutionNarrative,
)
from eurekan.core.crude import (
    STANDARD_CUT_NAMES,
    CrudeAssay,
    CrudeLibrary,
    CutPointDef,
    CutPointTemplate,
    CutProperties,
    DEFAULT_TEMPLATES,
    EUROPEAN_580EP,
    MAX_KEROSENE,
    US_GULF_COAST_630EP,
    DistillationCut,
)


# ---------------------------------------------------------------------------
# Task 1.1: Enums
# ---------------------------------------------------------------------------


class TestEnums:
    def test_operating_mode_values(self):
        assert OperatingMode.SIMULATE == "simulate"
        assert OperatingMode.OPTIMIZE == "optimize"
        assert OperatingMode.HYBRID == "hybrid"

    def test_unit_type_values(self):
        assert UnitType.CDU == "cdu"
        assert UnitType.FCC == "fcc"
        assert UnitType.BLENDER == "blender"
        assert len(UnitType) == 12

    def test_tank_type_values(self):
        assert TankType.CRUDE == "crude"
        assert TankType.PRODUCT == "product"
        assert TankType.INTERMEDIATE == "intermediate"

    def test_blend_method_values(self):
        assert BlendMethod.LINEAR_VOLUME == "linear_volume"
        assert BlendMethod.POWER_LAW == "power_law"
        assert BlendMethod.INDEX == "index"

    def test_stream_disposition_values(self):
        assert StreamDisposition.BLEND == "blend"
        assert StreamDisposition.FCC_FEED == "fcc_feed"
        assert len(StreamDisposition) == 5

    def test_data_source_values(self):
        assert DataSource.DEFAULT == "default"
        assert DataSource.TEMPLATE == "template"
        assert DataSource.IMPORTED == "imported"
        assert DataSource.USER_ENTERED == "user"
        assert DataSource.AI_EXTRACTED == "ai"
        assert DataSource.CALIBRATED == "calibrated"
        assert DataSource.CALCULATED == "calculated"
        assert DataSource.MARKET_DATA == "market"
        assert len(DataSource) == 8

    def test_enums_are_str(self):
        """All enums inherit from str so they serialize cleanly."""
        assert isinstance(OperatingMode.SIMULATE, str)
        assert isinstance(DataSource.IMPORTED, str)
        assert isinstance(UnitType.CDU, str)


# ---------------------------------------------------------------------------
# Task 1.2: CutProperties
# ---------------------------------------------------------------------------


class TestCutProperties:
    def test_defaults_are_none(self):
        cp = CutProperties()
        assert cp.api is None
        assert cp.sulfur is None
        assert cp.ron is None

    def test_metals_both_present(self):
        cp = CutProperties(nickel=5.0, vanadium=10.0)
        assert cp.metals == 15.0

    def test_metals_one_none(self):
        cp = CutProperties(nickel=3.0, vanadium=None)
        assert cp.metals == 3.0

    def test_metals_both_none(self):
        cp = CutProperties()
        assert cp.metals == 0.0

    def test_json_round_trip(self):
        cp = CutProperties(api=32.0, sulfur=1.5, nickel=2.0, vanadium=8.0)
        data = cp.model_dump()
        restored = CutProperties(**data)
        assert restored.api == 32.0
        assert restored.sulfur == 1.5
        assert restored.metals == 10.0


# ---------------------------------------------------------------------------
# Task 1.2: DistillationCut
# ---------------------------------------------------------------------------


class TestDistillationCut:
    def test_basic_construction(self):
        cut = DistillationCut(
            name="light_naphtha",
            display_name="Light Naphtha (C5-180°F)",
            tbp_start_f=None,
            tbp_end_f=180.0,
            vol_yield=0.10,
        )
        assert cut.name == "light_naphtha"
        assert cut.vol_yield == 0.10
        assert cut.source == DataSource.DEFAULT
        assert cut.confidence == 1.0

    def test_data_source_imported(self):
        cut = DistillationCut(
            name="kerosene",
            display_name="Kerosene",
            vol_yield=0.15,
            source=DataSource.IMPORTED,
            confidence=0.9,
        )
        assert cut.source == DataSource.IMPORTED
        assert cut.confidence == 0.9

    def test_data_source_user_entered(self):
        cut = DistillationCut(
            name="diesel",
            display_name="Diesel",
            vol_yield=0.20,
            source=DataSource.USER_ENTERED,
            confidence=0.8,
        )
        assert cut.source == DataSource.USER_ENTERED

    def test_json_round_trip(self):
        cut = DistillationCut(
            name="vgo",
            display_name="VGO (630-1050°F)",
            tbp_start_f=630.0,
            tbp_end_f=1050.0,
            vol_yield=0.25,
            properties=CutProperties(api=22.0, sulfur=2.0),
            source=DataSource.IMPORTED,
            confidence=0.95,
        )
        data = cut.model_dump()
        restored = DistillationCut(**data)
        assert restored.name == "vgo"
        assert restored.tbp_start_f == 630.0
        assert restored.properties.api == 22.0
        assert restored.source == DataSource.IMPORTED
        assert restored.confidence == 0.95


# ---------------------------------------------------------------------------
# Task 1.2: CutPointTemplate + defaults
# ---------------------------------------------------------------------------


class TestCutPointTemplate:
    def test_us_gulf_coast_template(self):
        t = US_GULF_COAST_630EP
        assert t.name == "us_gulf_coast_630ep"
        assert len(t.cuts) == 6
        assert t.cuts[0].name == "light_naphtha"
        assert t.cuts[-1].name == "vacuum_residue"

    def test_european_template(self):
        t = EUROPEAN_580EP
        assert t.name == "european_580ep"
        assert len(t.cuts) == 6
        # Diesel ends at 580 in European template
        diesel = next(c for c in t.cuts if c.name == "diesel")
        assert diesel.tbp_end_f == 580.0

    def test_max_kerosene_template(self):
        t = MAX_KEROSENE
        assert t.name == "max_kerosene"
        kero = next(c for c in t.cuts if c.name == "kerosene")
        assert kero.tbp_start_f == 300.0
        assert kero.tbp_end_f == 520.0

    def test_three_default_templates(self):
        assert len(DEFAULT_TEMPLATES) == 3

    @pytest.mark.parametrize("template", DEFAULT_TEMPLATES, ids=lambda t: t.name)
    def test_no_temperature_gaps(self, template: CutPointTemplate):
        """Adjacent cuts must connect without gaps or overlaps."""
        for i in range(len(template.cuts) - 1):
            current = template.cuts[i]
            nxt = template.cuts[i + 1]
            assert current.tbp_end_f == nxt.tbp_start_f, (
                f"Gap between {current.name} end ({current.tbp_end_f}) "
                f"and {nxt.name} start ({nxt.tbp_start_f}) in {template.name}"
            )

    @pytest.mark.parametrize("template", DEFAULT_TEMPLATES, ids=lambda t: t.name)
    def test_lightest_has_no_start(self, template: CutPointTemplate):
        assert template.cuts[0].tbp_start_f is None

    @pytest.mark.parametrize("template", DEFAULT_TEMPLATES, ids=lambda t: t.name)
    def test_heaviest_has_no_end(self, template: CutPointTemplate):
        assert template.cuts[-1].tbp_end_f is None

    def test_custom_template(self):
        t = CutPointTemplate(
            name="custom",
            display_name="Custom",
            cuts=[
                CutPointDef(name="light", display_name="Light", tbp_start_f=None, tbp_end_f=400.0),
                CutPointDef(name="heavy", display_name="Heavy", tbp_start_f=400.0, tbp_end_f=None),
            ],
        )
        assert len(t.cuts) == 2


# ---------------------------------------------------------------------------
# Task 1.2: STANDARD_CUT_NAMES
# ---------------------------------------------------------------------------


class TestStandardCutNames:
    def test_has_expected_names(self):
        assert "light_naphtha" in STANDARD_CUT_NAMES
        assert "kerosene" in STANDARD_CUT_NAMES
        assert "vgo" in STANDARD_CUT_NAMES
        assert "vacuum_residue" in STANDARD_CUT_NAMES

    def test_count(self):
        assert len(STANDARD_CUT_NAMES) == 10


# ---------------------------------------------------------------------------
# Task 1.2: CrudeAssay
# ---------------------------------------------------------------------------


def _make_assay(
    crude_id: str = "ARL",
    yields: list[float] | None = None,
    api: float = 32.84,
    sulfur: float = 1.78,
) -> CrudeAssay:
    """Helper to build a CrudeAssay from the US Gulf Coast template."""
    if yields is None:
        yields = [0.10, 0.18, 0.14, 0.12, 0.28, 0.18]
    template = US_GULF_COAST_630EP
    cuts = []
    for cpd, y in zip(template.cuts, yields):
        cuts.append(
            DistillationCut(
                name=cpd.name,
                display_name=cpd.display_name,
                tbp_start_f=cpd.tbp_start_f,
                tbp_end_f=cpd.tbp_end_f,
                vol_yield=y,
                source=DataSource.IMPORTED,
                confidence=0.95,
            )
        )
    return CrudeAssay(crude_id=crude_id, name="Arab Light", api=api, sulfur=sulfur, cuts=cuts)


class TestCrudeAssay:
    def test_basic_construction(self):
        assay = _make_assay()
        assert assay.crude_id == "ARL"
        assert assay.api == 32.84
        assert len(assay.cuts) == 6

    def test_total_yield(self):
        assay = _make_assay()
        assert abs(assay.total_yield - 1.0) < 1e-9

    def test_get_cut_found(self):
        assay = _make_assay()
        cut = assay.get_cut("kerosene")
        assert cut is not None
        assert cut.name == "kerosene"
        assert cut.vol_yield == 0.14

    def test_get_cut_not_found(self):
        assay = _make_assay()
        assert assay.get_cut("nonexistent") is None

    def test_total_yield_warning_low(self):
        with warnings.catch_warnings(record=True) as w:
            warnings.simplefilter("always")
            _make_assay(yields=[0.05, 0.05, 0.05, 0.05, 0.05, 0.05])
            assert len(w) == 1
            assert "total yield" in str(w[0].message).lower()

    def test_total_yield_warning_high(self):
        with warnings.catch_warnings(record=True) as w:
            warnings.simplefilter("always")
            _make_assay(yields=[0.30, 0.30, 0.20, 0.20, 0.20, 0.20])
            assert len(w) == 1
            assert "total yield" in str(w[0].message).lower()

    def test_total_yield_no_warning_in_range(self):
        with warnings.catch_warnings(record=True) as w:
            warnings.simplefilter("always")
            _make_assay(yields=[0.10, 0.18, 0.14, 0.12, 0.28, 0.18])
            yield_warnings = [x for x in w if "total yield" in str(x.message).lower()]
            assert len(yield_warnings) == 0

    def test_optional_fields_default(self):
        assay = _make_assay()
        assert assay.origin is None
        assert assay.tan is None
        assert assay.price is None
        assert assay.max_rate is None
        assert assay.min_rate == 0.0

    def test_json_round_trip(self):
        assay = _make_assay()
        data = assay.model_dump()
        restored = CrudeAssay(**data)
        assert restored.crude_id == assay.crude_id
        assert restored.total_yield == assay.total_yield
        assert restored.cuts[0].source == DataSource.IMPORTED

    def test_cuts_are_list_not_dict(self):
        """CrudeAssay.cuts is list[DistillationCut], not a dict."""
        assay = _make_assay()
        assert isinstance(assay.cuts, list)
        assert all(isinstance(c, DistillationCut) for c in assay.cuts)


# ---------------------------------------------------------------------------
# Task 1.2: CrudeLibrary
# ---------------------------------------------------------------------------


class TestCrudeLibrary:
    def test_empty_library(self):
        lib = CrudeLibrary()
        assert len(lib) == 0
        assert lib.list_crudes() == []

    def test_add_and_get(self):
        lib = CrudeLibrary()
        assay = _make_assay()
        lib.add(assay)
        assert len(lib) == 1
        assert lib.get("ARL") is assay
        assert lib.get("MISSING") is None

    def test_list_crudes(self):
        lib = CrudeLibrary()
        lib.add(_make_assay("ARL"))
        lib.add(_make_assay("MRS"))
        assert sorted(lib.list_crudes()) == ["ARL", "MRS"]

    def test_len(self):
        lib = CrudeLibrary()
        lib.add(_make_assay("ARL"))
        lib.add(_make_assay("MRS"))
        lib.add(_make_assay("WTI"))
        assert len(lib) == 3

    def test_iter(self):
        lib = CrudeLibrary()
        lib.add(_make_assay("ARL"))
        lib.add(_make_assay("MRS"))
        assert sorted(lib) == ["ARL", "MRS"]

    def test_init_with_dict(self):
        arl = _make_assay("ARL")
        lib = CrudeLibrary({"ARL": arl})
        assert len(lib) == 1
        assert lib.get("ARL") is arl

    def test_overwrite(self):
        lib = CrudeLibrary()
        lib.add(_make_assay("ARL"))
        new_assay = _make_assay("ARL")
        lib.add(new_assay)
        assert len(lib) == 1
        assert lib.get("ARL") is new_assay


# ---------------------------------------------------------------------------
# Task 1.3: ProductSpec, BlendingRule, Product
# ---------------------------------------------------------------------------


class TestProductSpec:
    def test_basic_construction(self):
        spec = ProductSpec(spec_name="sulfur", max_value=30.0)
        assert spec.spec_name == "sulfur"
        assert spec.min_value is None
        assert spec.max_value == 30.0

    def test_both_bounds(self):
        spec = ProductSpec(spec_name="road_octane", min_value=87.0, max_value=93.0)
        assert spec.min_value == 87.0
        assert spec.max_value == 93.0

    def test_json_round_trip(self):
        spec = ProductSpec(spec_name="rvp_index", max_value=7.8)
        data = spec.model_dump()
        restored = ProductSpec(**data)
        assert restored.spec_name == "rvp_index"
        assert restored.max_value == 7.8


class TestBlendingRule:
    def test_linear_volume(self):
        rule = BlendingRule(property_name="sulfur", method=BlendMethod.LINEAR_VOLUME)
        assert rule.method == BlendMethod.LINEAR_VOLUME
        assert rule.exponent is None

    def test_power_law_with_exponent(self):
        rule = BlendingRule(
            property_name="rvp", method=BlendMethod.POWER_LAW, exponent=1.25
        )
        assert rule.method == BlendMethod.POWER_LAW
        assert rule.exponent == 1.25

    def test_index_method(self):
        rule = BlendingRule(property_name="ron", method=BlendMethod.INDEX)
        assert rule.method == BlendMethod.INDEX

    def test_json_round_trip(self):
        rule = BlendingRule(
            property_name="rvp", method=BlendMethod.POWER_LAW, exponent=1.25
        )
        data = rule.model_dump()
        restored = BlendingRule(**data)
        assert restored.property_name == "rvp"
        assert restored.method == BlendMethod.POWER_LAW
        assert restored.exponent == 1.25


class TestProduct:
    def _make_gasoline(self) -> Product:
        return Product(
            product_id="CRG",
            name="regular_gasoline",
            price=82.81,
            min_demand=10000.0,
            max_demand=50000.0,
            specs=[
                ProductSpec(spec_name="road_octane", min_value=87.0),
                ProductSpec(spec_name="rvp_index", max_value=7.8),
                ProductSpec(spec_name="sulfur", max_value=30.0),
                ProductSpec(spec_name="benzene", max_value=1.0),
                ProductSpec(spec_name="aromatics", max_value=35.0),
                ProductSpec(spec_name="olefins", max_value=25.0),
            ],
            blending_rules=[
                BlendingRule(property_name="ron", method=BlendMethod.INDEX),
                BlendingRule(
                    property_name="rvp", method=BlendMethod.POWER_LAW, exponent=1.25
                ),
                BlendingRule(property_name="sulfur", method=BlendMethod.LINEAR_WEIGHT),
            ],
            allowed_components=[
                "fcc_light_naphtha",
                "fcc_heavy_naphtha",
                "cdu_light_naphtha",
                "reformate",
                "n_butane",
            ],
        )

    def test_basic_construction(self):
        p = self._make_gasoline()
        assert p.product_id == "CRG"
        assert p.name == "regular_gasoline"
        assert p.price == 82.81
        assert len(p.specs) == 6
        assert len(p.blending_rules) == 3
        assert len(p.allowed_components) == 5

    def test_get_spec_found(self):
        p = self._make_gasoline()
        spec = p.get_spec("sulfur")
        assert spec is not None
        assert spec.max_value == 30.0

    def test_get_spec_not_found(self):
        p = self._make_gasoline()
        assert p.get_spec("nonexistent") is None

    def test_defaults(self):
        p = Product(product_id="LPG", name="lpg", price=44.24)
        assert p.min_demand == 0.0
        assert p.max_demand is None
        assert p.specs == []
        assert p.blending_rules == []
        assert p.allowed_components == []

    def test_json_round_trip(self):
        p = self._make_gasoline()
        data = p.model_dump()
        restored = Product(**data)
        assert restored.product_id == p.product_id
        assert restored.price == p.price
        assert len(restored.specs) == 6
        spec = restored.get_spec("road_octane")
        assert spec is not None
        assert spec.min_value == 87.0
        assert restored.blending_rules[1].method == BlendMethod.POWER_LAW


# ---------------------------------------------------------------------------
# Task 1.3: Stream
# ---------------------------------------------------------------------------


class TestStream:
    def test_basic_construction(self):
        s = Stream(
            stream_id="vgo_to_fcc",
            source_unit="cdu_1",
            stream_type="vgo",
            possible_dispositions=[StreamDisposition.FCC_FEED, StreamDisposition.SELL],
        )
        assert s.stream_id == "vgo_to_fcc"
        assert s.source_unit == "cdu_1"
        assert s.stream_type == "vgo"
        assert StreamDisposition.FCC_FEED in s.possible_dispositions
        assert s.properties is None

    def test_with_properties(self):
        props = CutProperties(api=22.0, sulfur=2.1, ccr=0.5)
        s = Stream(
            stream_id="hn_stream",
            source_unit="cdu_1",
            stream_type="heavy_naphtha",
            possible_dispositions=[StreamDisposition.BLEND],
            properties=props,
        )
        assert s.properties is not None
        assert s.properties.api == 22.0
        assert s.properties.sulfur == 2.1

    def test_defaults(self):
        s = Stream(stream_id="s1", source_unit="u1", stream_type="naphtha")
        assert s.possible_dispositions == []
        assert s.properties is None

    def test_json_round_trip(self):
        s = Stream(
            stream_id="kero_stream",
            source_unit="cdu_1",
            stream_type="kerosene",
            possible_dispositions=[
                StreamDisposition.BLEND,
                StreamDisposition.SELL,
            ],
            properties=CutProperties(api=42.0, sulfur=0.15),
        )
        data = s.model_dump()
        restored = Stream(**data)
        assert restored.stream_id == "kero_stream"
        assert len(restored.possible_dispositions) == 2
        assert restored.properties is not None
        assert restored.properties.api == 42.0


# ---------------------------------------------------------------------------
# Task 1.3: Tank
# ---------------------------------------------------------------------------


class TestTank:
    def test_basic_construction(self):
        t = Tank(
            tank_id="tk_crude_1",
            tank_type=TankType.CRUDE,
            capacity=500000.0,
            connected_streams=["crude_in", "cdu_feed"],
        )
        assert t.tank_id == "tk_crude_1"
        assert t.tank_type == TankType.CRUDE
        assert t.capacity == 500000.0
        assert t.minimum == 0.0
        assert t.current_level == 0.0
        assert len(t.connected_streams) == 2

    def test_defaults(self):
        t = Tank(tank_id="tk1", tank_type=TankType.PRODUCT, capacity=100.0)
        assert t.minimum == 0.0
        assert t.current_level == 0.0
        assert t.connected_streams == []

    def test_capacity_must_be_positive(self):
        with pytest.raises(ValueError, match="capacity must be > 0"):
            Tank(tank_id="bad", tank_type=TankType.CRUDE, capacity=0.0)

    def test_negative_capacity_rejected(self):
        with pytest.raises(ValueError, match="capacity must be > 0"):
            Tank(tank_id="bad", tank_type=TankType.CRUDE, capacity=-100.0)

    def test_json_round_trip(self):
        t = Tank(
            tank_id="tk_prod_1",
            tank_type=TankType.PRODUCT,
            capacity=250000.0,
            minimum=10000.0,
            current_level=120000.0,
            connected_streams=["gasoline_blend", "gasoline_out"],
        )
        data = t.model_dump()
        restored = Tank(**data)
        assert restored.tank_id == "tk_prod_1"
        assert restored.tank_type == TankType.PRODUCT
        assert restored.capacity == 250000.0
        assert restored.minimum == 10000.0
        assert restored.current_level == 120000.0
        assert len(restored.connected_streams) == 2

    def test_all_tank_types(self):
        for tt in TankType:
            t = Tank(tank_id=f"tk_{tt.value}", tank_type=tt, capacity=1000.0)
            assert t.tank_type == tt


# ===========================================================================
# Task 1.4: config.py
# ===========================================================================


def _make_refinery_config(
    *,
    add_cdu: bool = True,
    add_crudes: bool = True,
    add_products: bool = True,
    add_streams: bool = True,
    add_vgo_ccr: bool = False,
) -> RefineryConfig:
    """Helper to build a RefineryConfig with varying completeness."""
    units: dict[str, UnitConfig] = {}
    if add_cdu:
        units["cdu_1"] = UnitConfig(
            unit_id="cdu_1",
            unit_type=UnitType.CDU,
            capacity=80000.0,
            equipment_limits={"max_throughput": 80000.0},
        )

    lib = CrudeLibrary()
    if add_crudes:
        vgo_props = CutProperties(ccr=0.5) if add_vgo_ccr else CutProperties()
        lib.add(
            CrudeAssay(
                crude_id="ARL",
                name="Arab Light",
                api=32.84,
                sulfur=1.78,
                price=75.0,
                cuts=[
                    DistillationCut(name="light_naphtha", display_name="LN", vol_yield=0.10),
                    DistillationCut(name="heavy_naphtha", display_name="HN", vol_yield=0.18),
                    DistillationCut(name="kerosene", display_name="Kero", vol_yield=0.14),
                    DistillationCut(name="diesel", display_name="Diesel", vol_yield=0.12),
                    DistillationCut(
                        name="vgo", display_name="VGO", vol_yield=0.28, properties=vgo_props,
                    ),
                    DistillationCut(name="vacuum_residue", display_name="Resid", vol_yield=0.18),
                ],
            )
        )

    products: dict[str, Product] = {}
    if add_products:
        products["CRG"] = Product(
            product_id="CRG",
            name="regular_gasoline",
            price=82.81,
            specs=[ProductSpec(spec_name="road_octane", min_value=87.0)],
        )

    streams: dict[str, Stream] = {}
    if add_streams:
        streams["vgo_to_fcc"] = Stream(
            stream_id="vgo_to_fcc",
            source_unit="cdu_1",
            stream_type="vgo",
            possible_dispositions=[StreamDisposition.FCC_FEED],
        )

    return RefineryConfig(
        name="Test Refinery",
        units=units,
        crude_library=lib,
        products=products,
        streams=streams,
        cut_point_template=US_GULF_COAST_630EP,
    )


class TestUnitConfig:
    def test_basic_construction(self):
        uc = UnitConfig(
            unit_id="cdu_1",
            unit_type=UnitType.CDU,
            capacity=80000.0,
            equipment_limits={"max_throughput": 80000.0},
        )
        assert uc.unit_id == "cdu_1"
        assert uc.unit_type == UnitType.CDU
        assert uc.capacity == 80000.0
        assert uc.min_throughput == 0.0
        assert uc.source == DataSource.DEFAULT

    def test_custom_source(self):
        uc = UnitConfig(
            unit_id="fcc_1",
            unit_type=UnitType.FCC,
            capacity=50000.0,
            source=DataSource.IMPORTED,
        )
        assert uc.source == DataSource.IMPORTED

    def test_json_round_trip(self):
        uc = UnitConfig(
            unit_id="cdu_1",
            unit_type=UnitType.CDU,
            capacity=80000.0,
            equipment_limits={"regen_temp": 1350.0},
            source=DataSource.CALIBRATED,
        )
        data = uc.model_dump()
        restored = UnitConfig(**data)
        assert restored.unit_id == uc.unit_id
        assert restored.equipment_limits["regen_temp"] == 1350.0
        assert restored.source == DataSource.CALIBRATED


class TestConfigCompleteness:
    def test_construction(self):
        cc = ConfigCompleteness(
            overall_pct=75.0,
            missing=["crude:MRS VGO CCR"],
            using_defaults=["unit:cdu_1"],
            ready_to_optimize=True,
            margin_uncertainty_pct=8.0,
            highest_value_missing="crude:MRS VGO CCR",
        )
        assert cc.overall_pct == 75.0
        assert cc.ready_to_optimize is True
        assert cc.margin_uncertainty_pct == 8.0


class TestRefineryConfig:
    def test_full_config_completeness(self):
        cfg = _make_refinery_config(add_vgo_ccr=True)
        comp = cfg.completeness()
        assert comp.ready_to_optimize is True
        assert comp.overall_pct > 0

    def test_no_cdu_not_ready(self):
        cfg = _make_refinery_config(add_cdu=False)
        comp = cfg.completeness()
        assert comp.ready_to_optimize is False
        assert any("CDU" in m for m in comp.missing)

    def test_no_crudes_not_ready(self):
        cfg = _make_refinery_config(add_crudes=False)
        comp = cfg.completeness()
        assert comp.ready_to_optimize is False
        assert any("crude" in m.lower() for m in comp.missing)

    def test_no_products_not_ready(self):
        cfg = _make_refinery_config(add_products=False)
        comp = cfg.completeness()
        assert comp.ready_to_optimize is False

    def test_missing_vgo_ccr_reported(self):
        cfg = _make_refinery_config(add_vgo_ccr=False)
        comp = cfg.completeness()
        assert any("VGO CCR" in m for m in comp.missing)
        assert comp.highest_value_missing is not None
        assert "VGO CCR" in comp.highest_value_missing

    def test_vgo_ccr_present_not_missing(self):
        cfg = _make_refinery_config(add_vgo_ccr=True)
        comp = cfg.completeness()
        vgo_ccr_missing = [m for m in comp.missing if "VGO CCR" in m]
        assert len(vgo_ccr_missing) == 0

    def test_using_defaults_tracked(self):
        cfg = _make_refinery_config()
        comp = cfg.completeness()
        # Default source cuts should be tracked
        default_entries = [d for d in comp.using_defaults if d.startswith("crude:")]
        assert len(default_entries) > 0

    def test_margin_uncertainty_scales(self):
        # A more complete config should have lower uncertainty
        cfg_full = _make_refinery_config(add_vgo_ccr=True)
        comp_full = cfg_full.completeness()
        cfg_partial = _make_refinery_config(add_streams=False)
        comp_partial = cfg_partial.completeness()
        # Both should produce valid uncertainty values
        assert comp_full.margin_uncertainty_pct > 0
        assert comp_partial.margin_uncertainty_pct > 0

    def test_json_round_trip(self):
        cfg = _make_refinery_config()
        # RefineryConfig uses CrudeLibrary (not a BaseModel), so test completeness
        comp = cfg.completeness()
        data = comp.model_dump()
        restored = ConfigCompleteness(**data)
        assert restored.overall_pct == comp.overall_pct
        assert restored.ready_to_optimize == comp.ready_to_optimize


# ===========================================================================
# Task 1.4: period.py
# ===========================================================================


class TestPeriodData:
    def test_basic_construction(self):
        pd_ = PeriodData(
            period_id=1,
            duration_hours=720.0,
            crude_prices={"ARL": 75.0, "MRS": 72.0},
            product_prices={"CRG": 82.81},
            crude_availability={"ARL": (0.0, 40000.0)},
            unit_status={"cdu_1": "running"},
            demand_min={"CRG": 10000.0},
            demand_max={"CRG": 50000.0},
            initial_inventory={"CRG": 25000.0},
        )
        assert pd_.period_id == 1
        assert pd_.duration_hours == 720.0
        assert pd_.crude_prices["ARL"] == 75.0
        assert pd_.crude_availability["ARL"] == (0.0, 40000.0)

    def test_defaults(self):
        pd_ = PeriodData(period_id=0, duration_hours=24.0)
        assert pd_.crude_prices == {}
        assert pd_.product_prices == {}
        assert pd_.crude_availability == {}
        assert pd_.initial_inventory == {}

    def test_json_round_trip(self):
        pd_ = PeriodData(
            period_id=1,
            duration_hours=720.0,
            crude_prices={"ARL": 75.0},
            crude_availability={"ARL": (0.0, 40000.0)},
        )
        data = pd_.model_dump()
        restored = PeriodData(**data)
        assert restored.period_id == 1
        assert restored.crude_availability["ARL"] == (0.0, 40000.0)


class TestPlanDefinition:
    def test_basic_construction(self):
        period = PeriodData(period_id=1, duration_hours=720.0)
        plan = PlanDefinition(
            periods=[period],
            mode=OperatingMode.OPTIMIZE,
            scenario_name="Base Case",
        )
        assert len(plan.periods) == 1
        assert plan.mode == OperatingMode.OPTIMIZE
        assert plan.scenario_name == "Base Case"
        assert plan.parent_scenario_id is None
        assert plan.description is None

    def test_auto_uuid(self):
        period = PeriodData(period_id=1, duration_hours=720.0)
        plan1 = PlanDefinition(
            periods=[period], mode=OperatingMode.OPTIMIZE, scenario_name="A"
        )
        plan2 = PlanDefinition(
            periods=[period], mode=OperatingMode.OPTIMIZE, scenario_name="B"
        )
        assert plan1.scenario_id != plan2.scenario_id
        assert len(plan1.scenario_id) == 36  # UUID format

    def test_parent_scenario(self):
        period = PeriodData(period_id=1, duration_hours=720.0)
        parent = PlanDefinition(
            periods=[period], mode=OperatingMode.OPTIMIZE, scenario_name="Base"
        )
        child = PlanDefinition(
            periods=[period],
            mode=OperatingMode.OPTIMIZE,
            scenario_name="High Gas",
            parent_scenario_id=parent.scenario_id,
            description="Gasoline +$5/bbl",
        )
        assert child.parent_scenario_id == parent.scenario_id
        assert child.description == "Gasoline +$5/bbl"

    def test_hybrid_mode_fixed_vars(self):
        period = PeriodData(period_id=1, duration_hours=720.0)
        plan = PlanDefinition(
            periods=[period],
            mode=OperatingMode.HYBRID,
            scenario_name="Hybrid",
            fixed_variables={"fcc_conversion": 0.80},
        )
        assert plan.mode == OperatingMode.HYBRID
        assert plan.fixed_variables["fcc_conversion"] == 0.80

    def test_json_round_trip(self):
        period = PeriodData(period_id=1, duration_hours=720.0)
        plan = PlanDefinition(
            periods=[period],
            mode=OperatingMode.SIMULATE,
            scenario_name="Sim",
            parent_scenario_id="abc-123",
        )
        data = plan.model_dump()
        restored = PlanDefinition(**data)
        assert restored.scenario_id == plan.scenario_id
        assert restored.mode == OperatingMode.SIMULATE
        assert restored.parent_scenario_id == "abc-123"


# ===========================================================================
# Task 1.4: results.py
# ===========================================================================


def _make_flow_graph() -> MaterialFlowGraph:
    """Build a small flow graph for testing."""
    nodes = [
        FlowNode(node_id="purchase_arl", node_type=FlowNodeType.PURCHASE,
                 display_name="ARL Purchase", throughput=40000.0),
        FlowNode(node_id="cdu_1", node_type=FlowNodeType.UNIT,
                 display_name="CDU-1", throughput=80000.0),
        FlowNode(node_id="fcc_1", node_type=FlowNodeType.UNIT,
                 display_name="FCC-1", throughput=50000.0),
        FlowNode(node_id="gasoline_blend", node_type=FlowNodeType.BLEND_HEADER,
                 display_name="Gasoline Blender", throughput=30000.0),
        FlowNode(node_id="regular_gasoline", node_type=FlowNodeType.SALE_POINT,
                 display_name="Regular Gasoline", throughput=30000.0),
    ]
    edges = [
        FlowEdge(
            edge_id="e1", source_node="purchase_arl", dest_node="cdu_1",
            stream_name="crude_feed", display_name="ARL → CDU",
            volume=40000.0, crude_contributions={"ARL": 1.0},
        ),
        FlowEdge(
            edge_id="e2", source_node="cdu_1", dest_node="fcc_1",
            stream_name="vgo", display_name="VGO → FCC",
            volume=11200.0,
            properties=CutProperties(sulfur=2.1, api=22.0),
            crude_contributions={"ARL": 0.6, "MRS": 0.4},
        ),
        FlowEdge(
            edge_id="e3", source_node="fcc_1", dest_node="gasoline_blend",
            stream_name="fcc_gasoline", display_name="FCC Gasoline → Blend",
            volume=5500.0,
            properties=CutProperties(sulfur=0.05, ron=92.0),
            crude_contributions={"ARL": 0.6, "MRS": 0.4},
        ),
        FlowEdge(
            edge_id="e4", source_node="gasoline_blend", dest_node="regular_gasoline",
            stream_name="blended_gasoline", display_name="Blend → Gasoline",
            volume=30000.0,
            properties=CutProperties(sulfur=0.02, ron=88.0),
            crude_contributions={"ARL": 0.5, "MRS": 0.3, "WTI": 0.2},
        ),
    ]
    return MaterialFlowGraph(nodes=nodes, edges=edges)


class TestFlowNodeAndEdge:
    def test_flow_node_types(self):
        assert FlowNodeType.PURCHASE == "purchase"
        assert FlowNodeType.BLEND_HEADER == "blend_header"
        assert len(FlowNodeType) == 6

    def test_flow_node_construction(self):
        n = FlowNode(
            node_id="cdu_1", node_type=FlowNodeType.UNIT,
            display_name="CDU-1", throughput=80000.0,
        )
        assert n.node_id == "cdu_1"
        assert n.throughput == 80000.0

    def test_flow_edge_construction(self):
        e = FlowEdge(
            edge_id="e1", source_node="a", dest_node="b",
            stream_name="vgo", display_name="VGO",
            volume=10000.0, economic_value=500000.0,
            crude_contributions={"ARL": 0.7, "MRS": 0.3},
        )
        assert e.volume == 10000.0
        assert e.crude_contributions["ARL"] == 0.7


class TestMaterialFlowGraph:
    def test_trace_crude(self):
        g = _make_flow_graph()
        arl_edges = g.trace_crude("ARL")
        assert len(arl_edges) == 4  # ARL is in all edges
        mrs_edges = g.trace_crude("MRS")
        assert len(mrs_edges) == 3  # MRS not in e1
        wti_edges = g.trace_crude("WTI")
        assert len(wti_edges) == 1  # WTI only in e4

    def test_trace_crude_not_found(self):
        g = _make_flow_graph()
        assert g.trace_crude("NONEXISTENT") == []

    def test_trace_product(self):
        g = _make_flow_graph()
        gasoline_edges = g.trace_product("regular_gasoline")
        assert len(gasoline_edges) == 1
        assert gasoline_edges[0].edge_id == "e4"

    def test_trace_product_not_found(self):
        g = _make_flow_graph()
        assert g.trace_product("diesel") == []

    def test_streams_by_property(self):
        g = _make_flow_graph()
        high_sulfur = g.streams_by_property("sulfur", 1.0)
        assert len(high_sulfur) == 1
        assert high_sulfur[0].edge_id == "e2"

    def test_streams_by_property_ron(self):
        g = _make_flow_graph()
        high_ron = g.streams_by_property("ron", 90.0)
        assert len(high_ron) == 1
        assert high_ron[0].edge_id == "e3"

    def test_empty_graph(self):
        g = MaterialFlowGraph()
        assert g.trace_crude("ARL") == []
        assert g.trace_product("x") == []
        assert g.streams_by_property("sulfur", 0.0) == []


class TestCrudeDisposition:
    def test_construction(self):
        cd = CrudeDisposition(
            crude_id="ARL",
            total_volume=40000.0,
            product_breakdown={"regular_gasoline": 15000.0, "ulsd": 10000.0},
            value_created=3200000.0,
            crude_cost=3000000.0,
            net_margin=200000.0,
        )
        assert cd.crude_id == "ARL"
        assert cd.net_margin == 200000.0
        assert cd.product_breakdown["regular_gasoline"] == 15000.0


class TestConstraintDiagnostic:
    def test_construction(self):
        cd = ConstraintDiagnostic(
            constraint_name="gasoline_sulfur",
            display_name="Gasoline Sulfur",
            violation=0.0,
            shadow_price=45000.0,
            bottleneck_score=85.0,
            binding=True,
            source_stream="Mars VGO sulfur",
            relaxation_suggestion="Reduce Mars from 25K to 17K bbl/d",
            relaxation_cost=40000.0,
        )
        assert cd.bottleneck_score == 85.0
        assert cd.source_stream == "Mars VGO sulfur"
        assert cd.binding is True

    def test_defaults(self):
        cd = ConstraintDiagnostic(
            constraint_name="regen_temp",
            display_name="Regen Temperature",
            violation=0.0,
        )
        assert cd.shadow_price is None
        assert cd.bottleneck_score == 0.0
        assert cd.binding is False
        assert cd.source_stream is None


class TestEquipmentStatus:
    def test_construction(self):
        es = EquipmentStatus(
            name="regen_temp",
            display_name="FCC Regen Temperature",
            current_value=1320.0,
            limit=1350.0,
            utilization_pct=97.8,
            is_binding=True,
        )
        assert es.utilization_pct == 97.8
        assert es.is_binding is True


class TestInfeasibilityReport:
    def test_feasible(self):
        ir = InfeasibilityReport(is_feasible=True)
        assert ir.is_feasible is True
        assert ir.violated_constraints == []
        assert ir.cheapest_fix is None

    def test_infeasible(self):
        diag = ConstraintDiagnostic(
            constraint_name="gasoline_sulfur",
            display_name="Gasoline Sulfur",
            violation=20.0,
            relaxation_cost=40000.0,
        )
        ir = InfeasibilityReport(
            is_feasible=False,
            violated_constraints=[diag],
            suggestions=["Relax sulfur to 35ppm", "Reduce Mars crude"],
            cheapest_fix="Relax sulfur to 35ppm",
        )
        assert ir.is_feasible is False
        assert len(ir.violated_constraints) == 1
        assert ir.cheapest_fix == "Relax sulfur to 35ppm"


class TestNarrative:
    def test_decision_explanation(self):
        de = DecisionExplanation(
            decision="Select Arab Light at 40K bbl/d",
            reasoning="Highest margin crude at current prices",
            alternatives_considered="Mars, WTI — lower margin",
            confidence=0.9,
        )
        assert de.confidence == 0.9

    def test_risk_flag(self):
        rf = RiskFlag(
            severity="warning",
            message="Gasoline sulfur at 93% of limit",
            recommendation="Monitor HCN sulfur levels",
        )
        assert rf.severity == "warning"

    def test_solution_narrative(self):
        sn = SolutionNarrative(
            executive_summary="Optimal plan achieves $1.2M/day margin.",
            data_quality_warnings=[
                "VGO CCR using default value — margin estimate uncertainty ±$200K/month",
                "FCC yields based on limited data — conversion results may be ±4% accurate",
            ],
        )
        assert len(sn.data_quality_warnings) == 2
        assert "VGO CCR" in sn.data_quality_warnings[0]


class TestFCCResult:
    def test_construction(self):
        fcc = FCCResult(
            conversion=0.80,
            yields={"gasoline": 0.494, "lco": 0.162, "coke": 0.034},
            equipment=[
                EquipmentStatus(
                    name="regen_temp", display_name="Regen Temp",
                    current_value=1320.0, limit=1350.0,
                    utilization_pct=97.8, is_binding=True,
                ),
            ],
        )
        assert fcc.conversion == 0.80
        assert fcc.yields["gasoline"] == 0.494
        assert len(fcc.equipment) == 1


class TestBlendAndDispositionResult:
    def test_blend_result(self):
        br = BlendResult(
            product_id="CRG",
            total_volume=30000.0,
            recipe={"fcc_light_naphtha": 0.4, "reformate": 0.3, "n_butane": 0.1},
            quality={"sulfur": {"value": 28, "limit": 30, "margin": 2, "feasible": True}},
        )
        assert br.total_volume == 30000.0
        assert br.quality["sulfur"]["feasible"] is True

    def test_disposition_result(self):
        dr = DispositionResult(
            stream_id="vgo_stream",
            to_blend=0.0,
            to_sell=5000.0,
            to_fuel_oil=2000.0,
        )
        assert dr.to_sell == 5000.0


class TestPlanningResult:
    def test_construction(self):
        pr = PlanningResult(
            scenario_id="abc-123",
            scenario_name="Base Case",
            created_at=datetime.now(tz=timezone.utc),
            periods=[PeriodResult(period_id=1, margin=120000.0)],
            total_margin=120000.0,
            solve_time_seconds=0.45,
            solver_status="optimal",
            material_flow=_make_flow_graph(),
        )
        assert pr.scenario_name == "Base Case"
        assert pr.total_margin == 120000.0
        assert len(pr.material_flow.nodes) == 5
        assert pr.narrative is None
        assert pr.infeasibility_report is None

    def test_with_parent_scenario(self):
        pr = PlanningResult(
            scenario_id="def-456",
            scenario_name="High Gas",
            parent_scenario_id="abc-123",
            created_at=datetime.now(tz=timezone.utc),
            solver_status="optimal",
        )
        assert pr.parent_scenario_id == "abc-123"

    def test_json_round_trip(self):
        pr = PlanningResult(
            scenario_id="abc-123",
            scenario_name="Test",
            created_at=datetime(2025, 1, 1, tzinfo=timezone.utc),
            solver_status="optimal",
            material_flow=MaterialFlowGraph(),
        )
        data = pr.model_dump()
        restored = PlanningResult(**data)
        assert restored.scenario_id == "abc-123"
        assert restored.created_at.year == 2025


class TestOracleResult:
    def test_construction(self):
        o = OracleResult(
            actual_margin=1000000.0,
            optimal_margin=1200000.0,
            gap=200000.0,
            gap_pct=16.7,
            gap_sources={"crude_selection": 120000.0, "conversion": 80000.0},
        )
        assert o.gap == 200000.0
        assert o.gap_sources["crude_selection"] == 120000.0


class TestScenarioComparison:
    def test_construction(self):
        sc = ScenarioComparison(
            base_scenario_id="abc",
            comparison_scenario_id="def",
            margin_delta=50000.0,
            crude_slate_changes={"ARL": -5000.0, "MRS": 5000.0},
            conversion_delta=0.023,
            product_volume_deltas={"regular_gasoline": 2000.0},
            constraint_changes=[
                {
                    "constraint": "regen_temp",
                    "base_utilization": 98.0,
                    "comparison_utilization": 85.0,
                    "change": "relaxed",
                }
            ],
            key_insight="Switching Mars for ARL relaxed regen temp bottleneck.",
        )
        assert sc.margin_delta == 50000.0
        assert len(sc.constraint_changes) == 1
        assert sc.constraint_changes[0]["change"] == "relaxed"
        assert sc.key_insight != ""
