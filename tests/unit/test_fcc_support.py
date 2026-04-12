"""Tests for FCC support units: GO HT, Scanfiner, Alkylation — Sprint 10."""

from __future__ import annotations

import pytest

from eurekan.core.config import UnitConfig
from eurekan.core.crude import CutProperties
from eurekan.core.enums import UnitType
from eurekan.models.go_hydrotreater import GOHydrotreaterModel
from eurekan.models.scanfiner import ScanfinerModel
from eurekan.models.alkylation import AlkylationModel


# === GO Hydrotreater ===

class TestGOHT:
    @pytest.fixture
    def model(self):
        return GOHydrotreaterModel(UnitConfig(unit_id="goht_1", unit_type=UnitType.HYDROTREATER, capacity=60000))

    @pytest.fixture
    def vgo(self):
        return CutProperties(sulfur=1.5, nitrogen=0.1, nickel=3.0, vanadium=7.0, api=22.0)

    def test_sulfur_removal(self, model, vgo):
        r = model.calculate(vgo, 30000.0)
        assert r.product_sulfur < vgo.sulfur * 0.15  # >85% removed

    def test_metals_removal(self, model, vgo):
        r = model.calculate(vgo, 30000.0)
        assert r.product_metals < vgo.metals * 0.40  # >60% removed

    def test_hydrogen_consumption(self, model, vgo):
        r = model.calculate(vgo, 30000.0)
        assert r.h2_consumed > 0

    def test_volume_nearly_preserved(self, model, vgo):
        r = model.calculate(vgo, 30000.0)
        assert r.product_volume / 30000.0 > 0.99


# === Scanfiner ===

class TestScanfiner:
    @pytest.fixture
    def model(self):
        return ScanfinerModel(UnitConfig(unit_id="scan_1", unit_type=UnitType.HYDROTREATER, capacity=25000))

    @pytest.fixture
    def hcn(self):
        return CutProperties(sulfur=0.30, ron=86.0, spg=0.82)

    def test_sulfur_removal(self, model, hcn):
        r = model.calculate(hcn, 5000.0)
        assert r.product_sulfur < 0.30 * 0.20  # >80% removed

    def test_octane_preservation(self, model, hcn):
        r = model.calculate(hcn, 5000.0)
        assert r.product_ron >= 84.0  # only ~1.5 RON loss

    def test_volume_yield(self, model, hcn):
        r = model.calculate(hcn, 5000.0)
        assert r.product_volume / 5000.0 >= 0.97

    def test_hydrogen_consumed(self, model, hcn):
        r = model.calculate(hcn, 5000.0)
        assert r.h2_consumed > 0


# === Alkylation ===

class TestAlkylation:
    @pytest.fixture
    def model(self):
        return AlkylationModel(UnitConfig(unit_id="alky_1", unit_type=UnitType.ALKYLATION, capacity=14000))

    def test_base_case(self, model):
        r = model.calculate(olefin_feed=5000.0)
        assert r.alkylate_volume > 5000.0  # yield > 1x

    def test_properties(self, model):
        r = model.calculate(olefin_feed=5000.0)
        assert r.alkylate_properties.ron >= 95.0
        assert r.alkylate_properties.sulfur == 0.0
        assert r.alkylate_properties.rvp < 5.0

    def test_ic4_requirement(self, model):
        r = model.calculate(olefin_feed=5000.0)
        assert r.ic4_consumed > 5000.0  # needs more iC4 than olefins

    def test_yield_ratio(self, model):
        r = model.calculate(olefin_feed=5000.0)
        ratio = r.alkylate_volume / 5000.0
        assert 1.5 <= ratio <= 2.0
