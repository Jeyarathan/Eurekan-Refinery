"""Tests for generic HydrotreaterModel — Sprint 11 Task 11.1."""

from __future__ import annotations

import pytest

from eurekan.core.crude import CutProperties
from eurekan.models.hydrotreater import (
    DIESEL_HT_CONFIG, KERO_HT_CONFIG, NAPHTHA_HT_CONFIG,
    HydrotreaterModel,
)


class TestNaphthaHT:
    @pytest.fixture
    def model(self):
        return HydrotreaterModel(NAPHTHA_HT_CONFIG)

    def test_sulfur_below_1ppm(self, model):
        feed = CutProperties(sulfur=0.005, cetane=None)
        r = model.calculate(feed, 12000.0)
        assert r.product_sulfur < 0.001  # <1 ppm wt%

    def test_volume_preserved(self, model):
        r = model.calculate(CutProperties(sulfur=0.005), 12000.0)
        assert r.product_volume / 12000.0 > 0.997

    def test_h2_consumed(self, model):
        r = model.calculate(CutProperties(sulfur=0.005), 12000.0)
        assert r.h2_consumed > 0


class TestKeroHT:
    @pytest.fixture
    def model(self):
        return HydrotreaterModel(KERO_HT_CONFIG)

    def test_sulfur_removal(self, model):
        feed = CutProperties(sulfur=0.05, cetane=None)
        r = model.calculate(feed, 10000.0)
        assert r.product_sulfur < 0.05 * 0.02  # >98% removed

    def test_volume_yield(self, model):
        r = model.calculate(CutProperties(sulfur=0.05), 10000.0)
        assert r.product_volume / 10000.0 >= 0.99


class TestDieselHT:
    @pytest.fixture
    def model(self):
        return HydrotreaterModel(DIESEL_HT_CONFIG)

    def test_sulfur_to_ulsd(self, model):
        feed = CutProperties(sulfur=0.15, cetane=35.0)
        r = model.calculate(feed, 15000.0)
        assert r.product_sulfur < 0.15 * 0.01  # >99% removed

    def test_cetane_improvement(self, model):
        feed = CutProperties(sulfur=0.15, cetane=35.0)
        r = model.calculate(feed, 15000.0)
        assert r.product_cetane >= 38.0  # +3 improvement

    def test_lco_cetane(self, model):
        """LCO fed to DHT: cetane starts ~20, after HT should be ~23."""
        lco = CutProperties(sulfur=0.50, cetane=20.0)
        r = model.calculate(lco, 5000.0)
        assert r.product_cetane >= 23.0

    def test_h2_consumed(self, model):
        r = model.calculate(CutProperties(sulfur=0.15, cetane=35.0), 15000.0)
        assert r.h2_consumed > 0
