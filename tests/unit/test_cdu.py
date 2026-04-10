"""Tests for CDU model — Task 1.14."""

from pathlib import Path

import pytest

from eurekan.core.config import UnitConfig
from eurekan.core.enums import DataSource, UnitType
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


@pytest.fixture(scope="module")
def cdu_model(config) -> CDUModel:
    return CDUModel(config.units["cdu_1"])


@pytest.fixture(scope="module")
def library(config):
    return config.crude_library


class TestCDUSingleCrude:
    def test_single_crude_ln_volume(self, cdu_model, library):
        """80K ARL → LN volume ≈ 80000 × 0.095."""
        result = cdu_model.calculate({"ARL": 80000.0}, library)
        arl = library.get("ARL")
        ln_cut = arl.get_cut("light_naphtha")
        expected = 80000.0 * ln_cut.vol_yield
        assert abs(result.cut_volumes["light_naphtha"] - expected) < 1.0

    def test_single_crude_total(self, cdu_model, library):
        result = cdu_model.calculate({"ARL": 80000.0}, library)
        assert result.total_crude == 80000.0

    def test_single_crude_properties_match_assay(self, cdu_model, library):
        """With one crude, cut properties should match the assay exactly."""
        result = cdu_model.calculate({"ARL": 80000.0}, library)
        arl = library.get("ARL")
        vgo_cut = arl.get_cut("vgo")
        if vgo_cut.properties.sulfur is not None:
            assert abs(
                result.cut_properties["vgo"].sulfur - vgo_cut.properties.sulfur
            ) < 0.001


class TestCDUMixedCrudes:
    def test_mixed_crudes_total(self, cdu_model, library):
        rates = {"ARL": 45000.0, "BRT": 25000.0, "ESC": 10000.0}
        result = cdu_model.calculate(rates, library)
        assert result.total_crude == 80000.0

    def test_mixed_crudes_ln_volume(self, cdu_model, library):
        """45K ARL + 25K BRT + 10K ESC — verify LN volume manually."""
        rates = {"ARL": 45000.0, "BRT": 25000.0, "ESC": 10000.0}
        result = cdu_model.calculate(rates, library)

        # Compute expected LN volume by hand
        expected = 0.0
        for cid, rate in rates.items():
            assay = library.get(cid)
            ln = assay.get_cut("light_naphtha")
            expected += rate * ln.vol_yield

        assert abs(result.cut_volumes["light_naphtha"] - expected) < 0.1

    def test_mixed_crudes_yields_sum(self, cdu_model, library):
        """Sum of all cut volumes ≈ total crude (±5%).

        Tolerance is 5% because swing cuts (naphtha/kero, kero/diesel) are
        not captured in the main yield map — they sit between defined cuts.
        """
        rates = {"ARL": 45000.0, "BRT": 25000.0, "ESC": 10000.0}
        result = cdu_model.calculate(rates, library)
        total_cuts = sum(result.cut_volumes.values())
        assert abs(total_cuts - 80000.0) / 80000.0 < 0.05


class TestCDUVGOProperties:
    def test_vgo_properties_blended(self, cdu_model, library):
        """VGO API should be between lightest and heaviest crude VGO API."""
        rates = {"ARL": 45000.0, "BRT": 25000.0, "ESC": 10000.0}
        result = cdu_model.calculate(rates, library)

        vgo_apis = []
        for cid in rates:
            assay = library.get(cid)
            vgo = assay.get_cut("vgo")
            if vgo.properties.api is not None:
                vgo_apis.append(vgo.properties.api)

        if vgo_apis and result.vgo_feed_properties.api is not None:
            assert min(vgo_apis) <= result.vgo_feed_properties.api <= max(vgo_apis)

    def test_vgo_feed_properties_populated(self, cdu_model, library):
        result = cdu_model.calculate({"ARL": 80000.0}, library)
        assert result.vgo_feed_properties.api is not None or result.vgo_feed_properties.sulfur is not None


class TestCDUEdgeCases:
    def test_zero_crude(self, cdu_model, library):
        """Empty dict → all zeros."""
        result = cdu_model.calculate({}, library)
        assert result.total_crude == 0.0
        assert result.cut_volumes == {}

    def test_capacity_info(self, cdu_model):
        assert cdu_model.capacity == 80000.0

    def test_yields_sum_single_crude(self, cdu_model, library):
        """Single crude yields should sum close to total."""
        result = cdu_model.calculate({"ARL": 50000.0}, library)
        total_cuts = sum(result.cut_volumes.values())
        assert abs(total_cuts - 50000.0) / 50000.0 < 0.05
