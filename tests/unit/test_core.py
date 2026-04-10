"""Tests for core enums and crude data models (Tasks 1.1 and 1.2)."""

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
