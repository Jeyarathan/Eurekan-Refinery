"""Tests for DimersolModel — Sprint 15.2."""

from __future__ import annotations

from eurekan.core.config import UnitConfig
from eurekan.core.enums import UnitType
from eurekan.models.dimersol import DimersolCalibration, DimersolModel


def _unit(capacity: float = 6_000.0) -> UnitConfig:
    return UnitConfig(unit_id="dimersol", unit_type=UnitType.ALKYLATION, capacity=capacity)


class TestDimateYield:
    def test_yield_around_90(self):
        """Dimate yield should be ~90 vol% of propylene feed."""
        model = DimersolModel(_unit())
        r = model.calculate(feed_rate=4_000.0)
        yield_frac = r.dimate_volume / 4_000.0
        assert 0.85 <= yield_frac <= 0.95

    def test_mass_balance(self):
        """Dimate volume <= feed."""
        model = DimersolModel(_unit())
        r = model.calculate(feed_rate=3_000.0)
        assert r.dimate_volume <= 3_000.0

    def test_zero_feed(self):
        model = DimersolModel(_unit())
        r = model.calculate(feed_rate=0.0)
        assert r.dimate_volume == 0.0


class TestDimateQuality:
    def test_high_octane(self):
        """Dimate RON 95-97."""
        model = DimersolModel(_unit())
        r = model.calculate(feed_rate=3_000.0)
        assert 95.0 <= r.dimate_ron <= 97.0

    def test_dimate_low_sulfur(self):
        model = DimersolModel(_unit())
        r = model.calculate(feed_rate=3_000.0)
        assert r.dimate_properties.sulfur is not None
        assert r.dimate_properties.sulfur < 0.005

    def test_dimate_high_olefins(self):
        """Dimate is C6 alkenes - HIGH olefin content."""
        model = DimersolModel(_unit())
        r = model.calculate(feed_rate=3_000.0)
        assert r.dimate_properties.olefins is not None
        assert r.dimate_properties.olefins > 50.0


class TestCalibration:
    def test_neutral_default(self):
        default = DimersolModel(_unit())
        explicit = DimersolModel(_unit(), calibration=DimersolCalibration())
        r1 = default.calculate(feed_rate=3_000.0)
        r2 = explicit.calculate(feed_rate=3_000.0)
        assert r1.dimate_volume == r2.dimate_volume

    def test_yield_calibration(self):
        cal = DimersolCalibration(alpha_yield=0.95)
        model = DimersolModel(_unit(), calibration=cal)
        r = model.calculate(feed_rate=3_000.0)
        assert r.dimate_volume < 3_000.0 * 0.90
