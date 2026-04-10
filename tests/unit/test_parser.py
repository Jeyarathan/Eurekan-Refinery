"""Tests for Gulf Coast parser — Tasks 1.7, 1.8, 1.9, 1.10."""

from pathlib import Path

import pytest

from eurekan.core.crude import STANDARD_CUT_NAMES, CutProperties
from eurekan.parsers.gulf_coast import GulfCoastParser, PIMS_PRODUCT_MAP, PIMS_COMPONENT_MAP

DATA_FILE = Path("data/gulf_coast/Gulf_Coast.xlsx")

pytestmark = pytest.mark.skipif(
    not DATA_FILE.exists(), reason="Gulf Coast Excel file not present"
)


@pytest.fixture(scope="module")
def parser() -> GulfCoastParser:
    return GulfCoastParser(DATA_FILE)


@pytest.fixture(scope="module")
def library(parser: GulfCoastParser):
    lib = parser.parse_assays()
    parser.parse_buy(lib)
    return lib


@pytest.fixture(scope="module")
def products(parser: GulfCoastParser):
    prods = parser.parse_sell()
    parser.parse_blnspec(prods)
    parser.parse_blnmix(prods)
    return prods


@pytest.fixture(scope="module")
def blend_properties(parser: GulfCoastParser) -> dict[str, CutProperties]:
    return parser.parse_blnnaph()


@pytest.fixture(scope="module")
def units(parser: GulfCoastParser):
    u = parser.parse_caps()
    parser.parse_proclim(u)
    return u


# ---------------------------------------------------------------------------
# Task 1.7: Assays
# ---------------------------------------------------------------------------


class TestAssaysParsing:
    def test_crude_count(self, library):
        """Should parse at least 40 crudes from the Assays sheet."""
        assert len(library) >= 40

    def test_arl_exists(self, library):
        assert library.get("ARL") is not None

    def test_arl_api(self, library):
        arl = library.get("ARL")
        assert arl is not None
        assert abs(arl.api - 32.84) < 1.0

    def test_arl_light_naphtha_yield(self, library):
        arl = library.get("ARL")
        assert arl is not None
        ln = arl.get_cut("light_naphtha")
        assert ln is not None
        assert abs(ln.vol_yield - 0.0952) < 0.01

    def test_arl_has_all_major_cuts(self, library):
        arl = library.get("ARL")
        assert arl is not None
        expected = ["light_naphtha", "heavy_naphtha", "kerosene", "diesel", "vgo", "vacuum_residue"]
        for name in expected:
            cut = arl.get_cut(name)
            assert cut is not None, f"Missing cut: {name}"
            assert cut.vol_yield > 0, f"Zero yield for {name}"

    def test_yields_sum_in_range(self, library):
        """Every crude's total yield should be between 0.90 and 1.10."""
        for crude_id in library:
            assay = library.get(crude_id)
            assert assay is not None
            total = assay.total_yield
            assert 0.90 <= total <= 1.10, (
                f"Crude {crude_id} total yield {total:.4f} out of range"
            )

    def test_source_is_imported(self, library):
        arl = library.get("ARL")
        assert arl is not None
        for cut in arl.cuts:
            assert cut.source.value == "imported"

    def test_vgo_properties_populated(self, library):
        """VGO should have API, sulfur, and CCR from the Assays sheet."""
        arl = library.get("ARL")
        assert arl is not None
        vgo = arl.get_cut("vgo")
        assert vgo is not None
        assert vgo.properties.api is not None
        assert vgo.properties.sulfur is not None
        assert vgo.properties.ccr is not None

    def test_no_pims_tags_in_cut_names(self, library):
        """No PIMS tags should appear in cut names — only Eurekan names."""
        pims_tags = {"VBALNC3", "VBALIC4", "VBALNC4", "DBALLN1", "DBALMN1",
                     "VBALKE1", "VBALDS1", "VBALLV1", "VBALHV1", "VBALVR1"}
        for crude_id in library:
            assay = library.get(crude_id)
            assert assay is not None
            for cut in assay.cuts:
                assert cut.name not in pims_tags, (
                    f"PIMS tag '{cut.name}' found in {crude_id} cuts"
                )


# ---------------------------------------------------------------------------
# Task 1.8: Buy
# ---------------------------------------------------------------------------


class TestBuyParsing:
    def test_arl_price_loaded(self, library):
        arl = library.get("ARL")
        assert arl is not None
        assert arl.price is not None
        assert arl.price > 0

    def test_arl_max_rate(self, library):
        arl = library.get("ARL")
        assert arl is not None
        assert arl.max_rate is not None
        assert arl.max_rate > 0

    def test_multiple_crudes_have_prices(self, library):
        priced = [cid for cid in library if library.get(cid).price is not None]
        assert len(priced) >= 30


# ---------------------------------------------------------------------------
# Task 1.8: Sell
# ---------------------------------------------------------------------------


class TestSellParsing:
    def test_regular_gasoline_exists(self, products):
        assert "regular_gasoline" in products

    def test_regular_gasoline_price(self, products):
        crg = products["regular_gasoline"]
        assert crg.price > 0
        assert abs(crg.price - 82.81) < 1.0

    def test_jet_fuel_exists(self, products):
        assert "jet_fuel" in products
        assert products["jet_fuel"].price > 0

    def test_ulsd_exists(self, products):
        assert "ulsd" in products
        assert products["ulsd"].price > 0

    def test_product_ids_are_eurekan_names(self, products):
        """Product IDs should be Eurekan names, not PIMS tags."""
        pims_tags = set(PIMS_PRODUCT_MAP.keys())
        for pid in products:
            assert pid not in pims_tags, f"PIMS tag '{pid}' used as product ID"

    def test_no_pims_tags_in_product_ids(self, products):
        """No PIMS tags like CRG, ULS, JET in product keys."""
        for pid in products:
            assert pid.upper() not in {"CRG", "CPR", "ULS", "JET", "N2O", "LSF", "HSF"}

    def test_multiple_products(self, products):
        assert len(products) >= 10


# ---------------------------------------------------------------------------
# Task 1.9: Blnspec
# ---------------------------------------------------------------------------


class TestBlnspecParsing:
    def test_gasoline_has_specs(self, products):
        crg = products["regular_gasoline"]
        assert len(crg.specs) > 0

    def test_gasoline_road_octane_min(self, products):
        crg = products["regular_gasoline"]
        spec = crg.get_spec("road_octane")
        assert spec is not None
        assert spec.min_value == 87.0

    def test_gasoline_rvp_index_max(self, products):
        crg = products["regular_gasoline"]
        spec = crg.get_spec("rvp_index")
        assert spec is not None
        assert spec.max_value is not None
        assert spec.max_value > 0

    def test_gasoline_sulfur_max(self, products):
        crg = products["regular_gasoline"]
        spec = crg.get_spec("sulfur")
        assert spec is not None
        assert spec.max_value is not None

    def test_gasoline_benzene_max(self, products):
        crg = products["regular_gasoline"]
        spec = crg.get_spec("benzene")
        assert spec is not None
        assert spec.max_value == 2.0

    def test_gasoline_aromatics_max(self, products):
        crg = products["regular_gasoline"]
        spec = crg.get_spec("aromatics")
        assert spec is not None
        assert spec.max_value == 55.0

    def test_gasoline_olefins_max(self, products):
        crg = products["regular_gasoline"]
        spec = crg.get_spec("olefins")
        assert spec is not None
        assert spec.max_value == 25.0

    def test_spec_names_are_eurekan(self, products):
        """Spec names should be Eurekan property names, not PIMS tags."""
        pims_tags = {"NDON", "XRVI", "XSUL", "XBNZ", "XARO", "XOLF"}
        crg = products["regular_gasoline"]
        for spec in crg.specs:
            assert spec.spec_name not in pims_tags


# ---------------------------------------------------------------------------
# Task 1.9: Blnmix
# ---------------------------------------------------------------------------


class TestBlnmixParsing:
    def test_gasoline_has_components(self, products):
        crg = products["regular_gasoline"]
        assert len(crg.allowed_components) > 0

    def test_fcc_light_naphtha_in_gasoline(self, products):
        crg = products["regular_gasoline"]
        assert "fcc_light_naphtha" in crg.allowed_components

    def test_fcc_heavy_naphtha_in_gasoline(self, products):
        crg = products["regular_gasoline"]
        assert "fcc_heavy_naphtha" in crg.allowed_components

    def test_n_butane_in_gasoline(self, products):
        crg = products["regular_gasoline"]
        assert "n_butane" in crg.allowed_components

    def test_reformate_in_gasoline(self, products):
        crg = products["regular_gasoline"]
        assert "reformate" in crg.allowed_components

    def test_component_names_are_eurekan(self, products):
        """Component names should be Eurekan stream names, not PIMS tags."""
        pims_tags = set(PIMS_COMPONENT_MAP.keys())
        crg = products["regular_gasoline"]
        for comp in crg.allowed_components:
            assert comp not in pims_tags, f"PIMS tag '{comp}' in components"


# ---------------------------------------------------------------------------
# Task 1.9: Blnnaph
# ---------------------------------------------------------------------------


class TestBlnnaphParsing:
    def test_n_butane_properties(self, blend_properties):
        assert "n_butane" in blend_properties
        nc4 = blend_properties["n_butane"]
        assert nc4.ron is not None
        assert abs(nc4.ron - 93.8) < 0.1

    def test_n_butane_mon(self, blend_properties):
        nc4 = blend_properties["n_butane"]
        assert nc4.mon is not None
        assert abs(nc4.mon - 89.6) < 0.1

    def test_n_butane_spg(self, blend_properties):
        nc4 = blend_properties["n_butane"]
        assert nc4.spg is not None
        assert abs(nc4.spg - 0.5844) < 0.01

    def test_isobutane_properties(self, blend_properties):
        assert "isobutane" in blend_properties
        ic4 = blend_properties["isobutane"]
        assert ic4.ron is not None
        assert abs(ic4.ron - 98.6) < 0.1

    def test_multiple_components(self, blend_properties):
        assert len(blend_properties) >= 5


# ---------------------------------------------------------------------------
# Task 1.10: Caps
# ---------------------------------------------------------------------------


class TestCapsParsing:
    def test_cdu_capacity(self, units):
        assert "cdu_1" in units
        cdu = units["cdu_1"]
        assert cdu.capacity == 80000.0

    def test_fcc_capacity(self, units):
        assert "fcc_1" in units
        fcc = units["fcc_1"]
        assert fcc.capacity == 60000.0

    def test_cdu_unit_type(self, units):
        assert units["cdu_1"].unit_type.value == "cdu"

    def test_fcc_unit_type(self, units):
        assert units["fcc_1"].unit_type.value == "fcc"

    def test_fcc_min_throughput(self, units):
        fcc = units["fcc_1"]
        assert fcc.min_throughput == 18000.0

    def test_source_is_imported(self, units):
        for uid, uc in units.items():
            assert uc.source.value == "imported"


# ---------------------------------------------------------------------------
# Task 1.10: ProcLim
# ---------------------------------------------------------------------------


class TestProcLimParsing:
    def test_fcc_conversion_limits(self, units):
        fcc = units["fcc_1"]
        assert "fcc_conversion_min" in fcc.equipment_limits
        assert "fcc_conversion_max" in fcc.equipment_limits
        assert fcc.equipment_limits["fcc_conversion_min"] == 70.0
        assert fcc.equipment_limits["fcc_conversion_max"] == 90.0

    def test_fcc_riser_temp_limits(self, units):
        fcc = units["fcc_1"]
        assert "fcc_riser_temp_min" in fcc.equipment_limits
        assert "fcc_riser_temp_max" in fcc.equipment_limits
        assert fcc.equipment_limits["fcc_riser_temp_min"] == 990.0
        assert fcc.equipment_limits["fcc_riser_temp_max"] == 1015.0

    def test_fcc_regen_temp_max(self, units):
        fcc = units["fcc_1"]
        assert "fcc_regen_temp_max" in fcc.equipment_limits
        assert fcc.equipment_limits["fcc_regen_temp_max"] == 1400.0

    def test_cdu_limits(self, units):
        cdu = units["cdu_1"]
        assert "cdu1_api_max" in cdu.equipment_limits
        assert cdu.equipment_limits["cdu1_api_max"] == 35.0


# ---------------------------------------------------------------------------
# Task 1.11: RefineryConfig assembly
# ---------------------------------------------------------------------------


@pytest.fixture(scope="module")
def config(parser: GulfCoastParser):
    return parser.parse()


class TestRefineryConfigAssembly:
    def test_config_name(self, config):
        assert config.name == "Gulf Coast Refinery"

    def test_config_has_units(self, config):
        assert "cdu_1" in config.units
        assert "fcc_1" in config.units

    def test_config_crude_library(self, config):
        assert len(config.crude_library) >= 40

    def test_config_products(self, config):
        assert "regular_gasoline" in config.products
        assert "jet_fuel" in config.products

    def test_config_streams(self, config):
        assert len(config.streams) > 0
        assert "cdu_vgo" in config.streams
        assert "fcc_light_naphtha" in config.streams

    def test_config_cut_point_template(self, config):
        assert config.cut_point_template.name == "us_gulf_coast_630ep"

    def test_completeness_works(self, config):
        comp = config.completeness()
        assert comp.overall_pct > 0
        assert comp.ready_to_optimize is True
        assert isinstance(comp.missing, list)
        assert isinstance(comp.using_defaults, list)

    def test_products_have_specs(self, config):
        crg = config.products["regular_gasoline"]
        assert len(crg.specs) > 0
        assert crg.get_spec("road_octane") is not None

    def test_products_have_components(self, config):
        crg = config.products["regular_gasoline"]
        assert len(crg.allowed_components) > 0
        assert "fcc_light_naphtha" in crg.allowed_components
