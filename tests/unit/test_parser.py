"""Tests for Gulf Coast parser — Tasks 1.7 and 1.8."""

from pathlib import Path

import pytest

from eurekan.core.crude import STANDARD_CUT_NAMES
from eurekan.parsers.gulf_coast import GulfCoastParser, PIMS_PRODUCT_MAP

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
    return parser.parse_sell()


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
