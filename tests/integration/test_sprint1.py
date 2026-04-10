"""Sprint 1 integration test — full pipeline from Excel to CDU results."""

from pathlib import Path

import pytest

from eurekan.core.crude import STANDARD_CUT_NAMES
from eurekan.core.enums import DataSource
from eurekan.models.cdu import CDUModel
from eurekan.parsers.gulf_coast import GulfCoastParser

DATA_FILE = Path("data/gulf_coast/Gulf_Coast.xlsx")

pytestmark = pytest.mark.skipif(
    not DATA_FILE.exists(), reason="Gulf Coast Excel file not present"
)


@pytest.fixture(scope="module")
def config():
    parser = GulfCoastParser(DATA_FILE)
    return parser.parse()


# ---------------------------------------------------------------------------
# 1. Full pipeline
# ---------------------------------------------------------------------------


class TestFullPipeline:
    def test_crude_count(self, config):
        assert len(config.crude_library) >= 40

    def test_cdu_unit(self, config):
        assert "cdu_1" in config.units
        assert config.units["cdu_1"].capacity == 80000.0

    def test_fcc_unit(self, config):
        assert "fcc_1" in config.units
        assert config.units["fcc_1"].capacity == 60000.0

    def test_gasoline_product(self, config):
        assert "regular_gasoline" in config.products
        crg = config.products["regular_gasoline"]
        spec = crg.get_spec("road_octane")
        assert spec is not None
        assert spec.min_value == 87.0

    def test_cdu_streams(self, config):
        assert "cdu_vgo" in config.streams
        assert "cdu_light_naphtha" in config.streams
        assert "cdu_kerosene" in config.streams

    def test_fcc_streams(self, config):
        assert "fcc_light_naphtha" in config.streams
        assert "fcc_heavy_naphtha" in config.streams

    def test_completeness_ready(self, config):
        comp = config.completeness()
        assert comp.ready_to_optimize is True
        assert comp.overall_pct > 0
        assert comp.margin_uncertainty_pct > 0


# ---------------------------------------------------------------------------
# 2. CDU with real data
# ---------------------------------------------------------------------------


class TestCDUWithRealData:
    def test_cdu_total_crude(self, config):
        cdu = CDUModel(config.units["cdu_1"])
        result = cdu.calculate(
            {"ARL": 45000.0, "BRT": 25000.0, "ESC": 10000.0},
            config.crude_library,
        )
        assert result.total_crude == 80000.0

    def test_cdu_cut_volumes_positive(self, config):
        cdu = CDUModel(config.units["cdu_1"])
        result = cdu.calculate(
            {"ARL": 45000.0, "BRT": 25000.0, "ESC": 10000.0},
            config.crude_library,
        )
        assert all(v >= 0 for v in result.cut_volumes.values())

    def test_cdu_yields_sum(self, config):
        cdu = CDUModel(config.units["cdu_1"])
        result = cdu.calculate(
            {"ARL": 45000.0, "BRT": 25000.0, "ESC": 10000.0},
            config.crude_library,
        )
        total_cuts = sum(result.cut_volumes.values())
        assert abs(total_cuts - 80000.0) / 80000.0 < 0.05

    def test_vgo_feed_api(self, config):
        cdu = CDUModel(config.units["cdu_1"])
        result = cdu.calculate(
            {"ARL": 45000.0, "BRT": 25000.0, "ESC": 10000.0},
            config.crude_library,
        )
        vgo = result.vgo_feed_properties
        assert vgo.api is not None
        assert 15.0 < vgo.api < 30.0

    def test_vgo_feed_sulfur(self, config):
        cdu = CDUModel(config.units["cdu_1"])
        result = cdu.calculate(
            {"ARL": 45000.0, "BRT": 25000.0, "ESC": 10000.0},
            config.crude_library,
        )
        vgo = result.vgo_feed_properties
        assert vgo.sulfur is not None
        assert 0.5 < vgo.sulfur < 5.0


# ---------------------------------------------------------------------------
# 3. All crudes valid
# ---------------------------------------------------------------------------


class TestAllCrudesValid:
    def test_all_yields_in_range(self, config):
        """Every crude's total yield should be between 0.85 and 1.15."""
        for cid in config.crude_library:
            assay = config.crude_library.get(cid)
            assert assay is not None
            assert 0.85 <= assay.total_yield <= 1.15, (
                f"Crude {cid} total yield {assay.total_yield:.4f} out of range"
            )

    def test_cut_names_are_standard(self, config):
        """All cut names must be in STANDARD_CUT_NAMES or be recognized names."""
        allowed = set(STANDARD_CUT_NAMES)
        for cid in config.crude_library:
            assay = config.crude_library.get(cid)
            assert assay is not None
            for cut in assay.cuts:
                assert cut.name in allowed, (
                    f"Crude {cid} has non-standard cut name: '{cut.name}'"
                )

    def test_no_pims_tags_in_cuts(self, config):
        """No PIMS tags in cut names."""
        pims_patterns = {
            "VBALNC3", "VBALIC4", "VBALNC4", "DBALLN1", "DBALMN1",
            "VBALKE1", "VBALDS1", "VBALLV1", "VBALHV1", "VBALVR1",
        }
        for cid in config.crude_library:
            assay = config.crude_library.get(cid)
            assert assay is not None
            for cut in assay.cuts:
                assert cut.name not in pims_patterns

    def test_no_pims_tags_in_products(self, config):
        """No PIMS tags in product IDs."""
        pims_tags = {"CRG", "CPR", "ULS", "JET", "N2O", "LSF", "HSF", "LPG", "CKE"}
        for pid in config.products:
            assert pid not in pims_tags


# ---------------------------------------------------------------------------
# 4. Data provenance
# ---------------------------------------------------------------------------


class TestDataProvenance:
    def test_imported_cuts_have_imported_source(self, config):
        """All parsed cuts should have source=IMPORTED."""
        for cid in config.crude_library:
            assay = config.crude_library.get(cid)
            assert assay is not None
            for cut in assay.cuts:
                assert cut.source == DataSource.IMPORTED, (
                    f"Crude {cid} cut {cut.name} has source={cut.source}"
                )

    def test_units_have_imported_source(self, config):
        for uid, uc in config.units.items():
            assert uc.source == DataSource.IMPORTED

    def test_completeness_tracks_defaults(self, config):
        comp = config.completeness()
        # Should have no defaults since everything is parsed from Excel
        # (all cuts have source=IMPORTED, not DEFAULT)
        default_cuts = [d for d in comp.using_defaults if d.startswith("crude:")]
        assert len(default_cuts) == 0, (
            f"Unexpected defaults: {default_cuts[:5]}"
        )

    def test_completeness_has_valid_fields(self, config):
        comp = config.completeness()
        assert isinstance(comp.overall_pct, float)
        assert isinstance(comp.missing, list)
        assert isinstance(comp.using_defaults, list)
        assert isinstance(comp.ready_to_optimize, bool)
        assert isinstance(comp.margin_uncertainty_pct, float)
