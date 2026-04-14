"""Tests for CokerModel — Sprint 12.2."""

from __future__ import annotations

import pytest

from eurekan.core.config import UnitConfig
from eurekan.core.crude import CutProperties
from eurekan.core.enums import UnitType
from eurekan.models.coker import CokerCalibration, CokerModel


def _make_unit(capacity: float = 50_000.0) -> UnitConfig:
    return UnitConfig(unit_id="coker_1", unit_type=UnitType.COKER, capacity=capacity)


def _typical_vac_resid() -> CutProperties:
    """Typical Gulf Coast vacuum residue."""
    return CutProperties(api=8.0, sulfur=4.0, ccr=20.0)


def _light_vac_resid() -> CutProperties:
    """Lighter, lower-CCR vacuum residue."""
    return CutProperties(api=15.0, sulfur=2.0, ccr=8.0)


def _heavy_vac_resid() -> CutProperties:
    """Very heavy, high-CCR vacuum residue."""
    return CutProperties(api=4.0, sulfur=5.5, ccr=28.0)


class TestBaseCase:
    def test_typical_yields(self):
        """Typical vac resid: yields land in expected ranges."""
        model = CokerModel(_make_unit())
        feed = 30_000.0
        result = model.calculate(feed_rate=feed, feed_properties=_typical_vac_resid())

        # Expected from correlations at api=8, ccr=20:
        # naphtha = 0.12 + 0.002*3 = 0.126
        # gas_oil = 0.25 + 0.003*3 = 0.259
        # coke    = 0.25 - 0.004*3 + 0.015*20 = 0.538
        # gas     = 0.10 + 0.001*3 = 0.103
        # hgo     = remainder (negative -> clipped to 0)
        assert 0.10 <= result.coker_naphtha_volume / feed <= 0.20
        assert 0.20 <= result.coker_gas_oil_volume / feed <= 0.40
        assert 0.05 <= result.gas_volume / feed <= 0.15
        assert result.coke_volume > 0


class TestMassBalance:
    def test_products_sum_to_feed_within_tolerance(self):
        """All products should sum to feed within +/-3%."""
        model = CokerModel(_make_unit())
        feed = 25_000.0
        result = model.calculate(feed_rate=feed, feed_properties=_typical_vac_resid())
        total = (
            result.coker_naphtha_volume
            + result.coker_gas_oil_volume
            + result.coker_hgo_volume
            + result.gas_volume
            + result.coke_volume
        )
        assert abs(total - feed) / feed < 0.03

    def test_zero_feed(self):
        model = CokerModel(_make_unit())
        result = model.calculate(feed_rate=0.0, feed_properties=_typical_vac_resid())
        assert result.coker_naphtha_volume == 0.0
        assert result.coke_volume == 0.0
        assert result.coke_tons_per_day == 0.0


class TestHeavyFeed:
    def test_higher_ccr_more_coke(self):
        """Higher CCR feed should produce more coke per bbl."""
        model = CokerModel(_make_unit())
        light = model.calculate(feed_rate=10_000.0, feed_properties=_light_vac_resid())
        heavy = model.calculate(feed_rate=10_000.0, feed_properties=_heavy_vac_resid())
        assert heavy.coke_volume > light.coke_volume

    def test_heavier_feed_less_liquid(self):
        """Heavier (lower API, higher CCR) feed makes less naphtha."""
        model = CokerModel(_make_unit())
        light = model.calculate(feed_rate=10_000.0, feed_properties=_light_vac_resid())
        heavy = model.calculate(feed_rate=10_000.0, feed_properties=_heavy_vac_resid())
        assert heavy.coker_naphtha_volume < light.coker_naphtha_volume


class TestCokeYield:
    def test_coke_in_typical_range(self):
        """Coke yield should be 20-55% of feed depending on quality."""
        model = CokerModel(_make_unit())
        feed = 20_000.0
        result = model.calculate(feed_rate=feed, feed_properties=_typical_vac_resid())
        coke_frac = result.coke_volume / feed
        # Heavy GC vac resid with CCR 20 will give very high coke (~54%)
        assert 0.20 <= coke_frac <= 0.60

    def test_coke_tons_conversion(self):
        """Coke tons should equal volume * conversion factor."""
        model = CokerModel(_make_unit())
        result = model.calculate(feed_rate=10_000.0, feed_properties=_typical_vac_resid())
        # 1 bbl coke = 0.157 tons
        expected_tons = result.coke_volume * 0.157
        assert abs(result.coke_tons_per_day - expected_tons) < 1e-6


class TestProductProperties:
    def test_coker_naphtha_olefinic(self):
        """Coker naphtha should be high-olefin (dirty)."""
        model = CokerModel(_make_unit())
        result = model.calculate(feed_rate=10_000.0, feed_properties=_typical_vac_resid())
        assert result.coker_naphtha_properties.olefins is not None
        assert result.coker_naphtha_properties.olefins > 20.0

    def test_coker_naphtha_low_octane(self):
        """Coker naphtha is low octane - needs reforming."""
        model = CokerModel(_make_unit())
        result = model.calculate(feed_rate=10_000.0, feed_properties=_typical_vac_resid())
        assert result.coker_naphtha_properties.ron is not None
        assert result.coker_naphtha_properties.ron < 80.0
