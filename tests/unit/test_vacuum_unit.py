"""Tests for VacuumUnitModel — Sprint 12.1."""

from __future__ import annotations

import pytest

from eurekan.core.config import UnitConfig
from eurekan.core.crude import CutProperties
from eurekan.core.enums import UnitType
from eurekan.models.vacuum_unit import VacuumUnitCalibration, VacuumUnitModel


def _make_unit(capacity: float = 50_000.0) -> UnitConfig:
    return UnitConfig(unit_id="vacuum_1", unit_type=UnitType.CDU, capacity=capacity)


def _heavy_resid_props() -> CutProperties:
    return CutProperties(api=8.0, sulfur=4.0, ccr=15.0, nickel=50.0, vanadium=120.0)


class TestMassBalance:
    def test_products_sum_to_feed(self):
        model = VacuumUnitModel(_make_unit())
        feed = 30_000.0
        result = model.calculate(feed_rate=feed, feed_properties=_heavy_resid_props())
        total = result.lvgo_volume + result.hvgo_volume + result.vac_resid_volume
        assert abs(total - feed) < 1e-6

    def test_zero_feed_zero_products(self):
        model = VacuumUnitModel(_make_unit())
        result = model.calculate(feed_rate=0.0, feed_properties=_heavy_resid_props())
        assert result.lvgo_volume == 0.0
        assert result.hvgo_volume == 0.0
        assert result.vac_resid_volume == 0.0


class TestVgoQuality:
    def test_vgo_lighter_than_feed(self):
        model = VacuumUnitModel(_make_unit())
        feed_props = _heavy_resid_props()
        result = model.calculate(feed_rate=20_000.0, feed_properties=feed_props)
        assert result.lvgo_properties.api > feed_props.api
        assert result.hvgo_properties.api > feed_props.api

    def test_vac_resid_heavier_than_feed(self):
        model = VacuumUnitModel(_make_unit())
        feed_props = _heavy_resid_props()
        result = model.calculate(feed_rate=20_000.0, feed_properties=feed_props)
        assert result.vac_resid_properties.api < feed_props.api

    def test_vgo_lower_sulfur_than_resid(self):
        model = VacuumUnitModel(_make_unit())
        feed_props = _heavy_resid_props()
        result = model.calculate(feed_rate=20_000.0, feed_properties=feed_props)
        assert result.lvgo_properties.sulfur < result.vac_resid_properties.sulfur
        assert result.hvgo_properties.sulfur < result.vac_resid_properties.sulfur

    def test_ccr_concentrated_in_resid(self):
        model = VacuumUnitModel(_make_unit())
        feed_props = _heavy_resid_props()
        result = model.calculate(feed_rate=20_000.0, feed_properties=feed_props)
        assert result.vac_resid_properties.ccr is not None
        assert result.vac_resid_properties.ccr > feed_props.ccr


class TestYieldRange:
    def test_total_vgo_in_typical_range(self):
        """Combined LVGO + HVGO should be 40-60% of feed."""
        model = VacuumUnitModel(_make_unit())
        result = model.calculate(feed_rate=10_000.0, feed_properties=_heavy_resid_props())
        total_vgo_frac = (result.lvgo_volume + result.hvgo_volume) / 10_000.0
        assert 0.40 <= total_vgo_frac <= 0.60

    def test_vac_resid_in_typical_range(self):
        """Vacuum residue should be 40-60% of feed."""
        model = VacuumUnitModel(_make_unit())
        result = model.calculate(feed_rate=10_000.0, feed_properties=_heavy_resid_props())
        vr_frac = result.vac_resid_volume / 10_000.0
        assert 0.40 <= vr_frac <= 0.60


class TestCalibration:
    def test_custom_split(self):
        cal = VacuumUnitCalibration(lvgo_fraction=0.30, hvgo_fraction=0.30)
        model = VacuumUnitModel(_make_unit(), calibration=cal)
        result = model.calculate(feed_rate=10_000.0, feed_properties=_heavy_resid_props())
        assert abs(result.lvgo_volume - 3000.0) < 1e-6
        assert abs(result.hvgo_volume - 3000.0) < 1e-6
        assert abs(result.vac_resid_volume - 4000.0) < 1e-6
