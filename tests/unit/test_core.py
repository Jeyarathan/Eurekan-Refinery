"""Tests for core enums, crude, product, stream, and tank models (Tasks 1.1-1.3)."""

import warnings

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
        assert len(UnitType) == 9

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
