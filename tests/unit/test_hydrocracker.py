"""Tests for HydrocrackerModel — Sprint 13.1."""

from __future__ import annotations

import pytest

from eurekan.core.config import UnitConfig
from eurekan.core.crude import CutProperties
from eurekan.core.enums import UnitType
from eurekan.models.hydrocracker import (
    HydrocrackerCalibration,
    HydrocrackerModel,
)


def _make_unit(capacity: float = 20_000.0) -> UnitConfig:
    return UnitConfig(unit_id="hcu_1", unit_type=UnitType.HYDROCRACKER, capacity=capacity)


def _vgo_props() -> CutProperties:
    return CutProperties(api=22.0, sulfur=1.5, nitrogen=800.0, ccr=1.0)


class TestBaseCase:
    def test_typical_yields_at_80(self):
        """At 80% conversion: yields land in expected ranges."""
        model = HydrocrackerModel(_make_unit())
        feed = 15_000.0
        result = model.calculate(feed_rate=feed, feed_properties=_vgo_props(), conversion=80.0)

        assert 0.15 <= result.naphtha_volume / feed <= 0.22
        assert 0.25 <= result.jet_volume / feed <= 0.35
        assert 0.25 <= result.diesel_volume / feed <= 0.35
        assert 0.05 <= result.lpg_volume / feed <= 0.10
        assert 0.05 <= result.unconverted_volume / feed <= 0.20

    def test_conversion_recorded(self):
        model = HydrocrackerModel(_make_unit())
        result = model.calculate(feed_rate=10_000.0, feed_properties=_vgo_props(), conversion=85.0)
        assert result.conversion == 85.0

    def test_has_equipment(self):
        model = HydrocrackerModel(_make_unit())
        result = model.calculate(feed_rate=10_000.0, feed_properties=_vgo_props())
        assert len(result.equipment) >= 1


class TestMassBalance:
    def test_products_sum_to_feed(self):
        """All products + unconverted should equal feed exactly."""
        model = HydrocrackerModel(_make_unit())
        feed = 15_000.0
        for conv in (60.0, 75.0, 80.0, 90.0, 95.0):
            result = model.calculate(feed_rate=feed, feed_properties=_vgo_props(), conversion=conv)
            total = (
                result.naphtha_volume
                + result.jet_volume
                + result.diesel_volume
                + result.lpg_volume
                + result.unconverted_volume
            )
            assert abs(total - feed) < 1e-3, f"Mass imbalance at conv={conv}"

    def test_zero_feed(self):
        model = HydrocrackerModel(_make_unit())
        result = model.calculate(feed_rate=0.0, feed_properties=_vgo_props())
        assert result.jet_volume == 0.0
        assert result.diesel_volume == 0.0
        assert result.hydrogen_consumption_mmscf == 0.0


class TestConversionResponse:
    def test_higher_conversion_less_unconverted(self):
        model = HydrocrackerModel(_make_unit())
        low = model.calculate(feed_rate=10_000.0, feed_properties=_vgo_props(), conversion=65.0)
        high = model.calculate(feed_rate=10_000.0, feed_properties=_vgo_props(), conversion=92.0)
        assert high.unconverted_volume < low.unconverted_volume

    def test_higher_conversion_more_naphtha(self):
        """Higher severity -> more secondary cracking -> more naphtha."""
        model = HydrocrackerModel(_make_unit())
        low = model.calculate(feed_rate=10_000.0, feed_properties=_vgo_props(), conversion=70.0)
        high = model.calculate(feed_rate=10_000.0, feed_properties=_vgo_props(), conversion=92.0)
        assert high.naphtha_volume > low.naphtha_volume

    def test_conversion_clamped(self):
        """Conversion outside [60, 95] clamps to bounds."""
        model = HydrocrackerModel(_make_unit())
        too_low = model.calculate(feed_rate=1_000.0, feed_properties=_vgo_props(), conversion=40.0)
        too_high = model.calculate(feed_rate=1_000.0, feed_properties=_vgo_props(), conversion=120.0)
        assert too_low.conversion == 60.0
        assert too_high.conversion == 95.0


class TestProductQuality:
    def test_diesel_high_cetane(self):
        """HCU diesel should have cetane >= 50 (FCC LCO is ~20)."""
        model = HydrocrackerModel(_make_unit())
        result = model.calculate(feed_rate=10_000.0, feed_properties=_vgo_props())
        assert result.diesel_properties.cetane is not None
        assert result.diesel_properties.cetane >= 50.0

    def test_jet_meets_specs(self):
        """HCU jet: low sulfur, low aromatics — meets specs without HT."""
        model = HydrocrackerModel(_make_unit())
        result = model.calculate(feed_rate=10_000.0, feed_properties=_vgo_props())
        assert result.jet_properties.sulfur is not None
        assert result.jet_properties.sulfur <= 0.003   # well under 30 ppm jet spec
        assert result.jet_properties.aromatics is not None
        assert result.jet_properties.aromatics <= 25.0  # meets jet aromatics spec

    def test_naphtha_low_sulfur(self):
        model = HydrocrackerModel(_make_unit())
        result = model.calculate(feed_rate=10_000.0, feed_properties=_vgo_props())
        assert result.naphtha_properties.sulfur is not None
        assert result.naphtha_properties.sulfur < 0.005


class TestHydrogenConsumption:
    def test_h2_in_typical_range(self):
        """At 80% conversion, ~1700 SCFB (= 17 MMSCF/100K bbl)."""
        model = HydrocrackerModel(_make_unit())
        result = model.calculate(feed_rate=10_000.0, feed_properties=_vgo_props(), conversion=80.0)
        # 1500 + 30 * (80 - 60) = 2100 SCFB
        # 2100 SCFB * 10000 bbl/d / 1e6 = 21 MMSCFD
        assert 15.0 <= result.hydrogen_consumption_mmscf <= 25.0

    def test_h2_increases_with_conversion(self):
        model = HydrocrackerModel(_make_unit())
        low = model.calculate(feed_rate=10_000.0, feed_properties=_vgo_props(), conversion=65.0)
        high = model.calculate(feed_rate=10_000.0, feed_properties=_vgo_props(), conversion=95.0)
        assert high.hydrogen_consumption_mmscf > low.hydrogen_consumption_mmscf

    def test_h2_at_max_conversion(self):
        """At 95% conversion: 1500 + 30 * 35 = 2550 SCFB - the highest in refinery."""
        model = HydrocrackerModel(_make_unit())
        result = model.calculate(feed_rate=10_000.0, feed_properties=_vgo_props(), conversion=95.0)
        # 2550 SCFB * 10000 bbl/d / 1e6 = 25.5 MMSCFD
        assert 25.0 <= result.hydrogen_consumption_mmscf <= 26.0


class TestCalibration:
    def test_default_calibration_neutral(self):
        cal_default = HydrocrackerCalibration()
        cal_explicit = HydrocrackerCalibration(
            alpha_naphtha=1.0, alpha_jet=1.0, alpha_diesel=1.0, alpha_lpg=1.0
        )
        m1 = HydrocrackerModel(_make_unit(), calibration=cal_default)
        m2 = HydrocrackerModel(_make_unit(), calibration=cal_explicit)
        r1 = m1.calculate(feed_rate=10_000.0, feed_properties=_vgo_props())
        r2 = m2.calculate(feed_rate=10_000.0, feed_properties=_vgo_props())
        assert r1.diesel_volume == r2.diesel_volume

    def test_calibration_changes_output(self):
        cal = HydrocrackerCalibration(alpha_diesel=1.2)
        m_default = HydrocrackerModel(_make_unit())
        m_cal = HydrocrackerModel(_make_unit(), calibration=cal)
        r_default = m_default.calculate(feed_rate=10_000.0, feed_properties=_vgo_props())
        r_cal = m_cal.calculate(feed_rate=10_000.0, feed_properties=_vgo_props())
        assert r_cal.diesel_volume > r_default.diesel_volume
