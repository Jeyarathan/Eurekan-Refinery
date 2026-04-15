"""Tests for Gas Plant models — Sprint 14.3."""

from __future__ import annotations

from eurekan.core.config import UnitConfig
from eurekan.core.enums import UnitType
from eurekan.models.gas_plant import SaturatedGasPlant, UnsaturatedGasPlant


def _unit(capacity: float = 10_000.0) -> UnitConfig:
    return UnitConfig(unit_id="ugp_1", unit_type=UnitType.CDU, capacity=capacity)


class TestUnsaturatedGasPlant:
    def test_mass_balance(self):
        """All products sum to feed."""
        ugp = UnsaturatedGasPlant(_unit())
        feed = 8_000.0
        r = ugp.calculate(feed_rate=feed)
        total = (
            r.propylene_volume + r.propane_volume + r.butylene_volume
            + r.isobutane_volume + r.normal_butane_volume + r.fuel_gas_volume
        )
        assert abs(total - feed) < 1e-6

    def test_olefin_paraffin_split(self):
        """UGP produces significant olefins (propylene + butylene)."""
        ugp = UnsaturatedGasPlant(_unit())
        r = ugp.calculate(feed_rate=10_000.0)
        olefins = r.propylene_volume + r.butylene_volume
        paraffins = r.propane_volume + r.isobutane_volume + r.normal_butane_volume
        assert olefins > 0
        assert paraffins > 0
        # Typical FCC light ends: roughly 50/50 olefins/paraffins
        assert 0.4 <= olefins / (olefins + paraffins) <= 0.65

    def test_zero_feed(self):
        r = UnsaturatedGasPlant(_unit()).calculate(feed_rate=0.0)
        assert r.propylene_volume == 0.0
        assert r.butylene_volume == 0.0


class TestSaturatedGasPlant:
    def test_mass_balance(self):
        sgp = SaturatedGasPlant(_unit())
        feed = 4_000.0
        r = sgp.calculate(feed_rate=feed)
        total = (
            r.propane_volume + r.isobutane_volume
            + r.normal_butane_volume + r.fuel_gas_volume
        )
        assert abs(total - feed) < 1e-6

    def test_no_olefins(self):
        """SGP output contains no olefins (saturated streams only)."""
        sgp = SaturatedGasPlant(_unit())
        r = sgp.calculate(feed_rate=5_000.0)
        # SGPResult does not even have propylene/butylene fields by design
        assert not hasattr(r, "propylene_volume")
        assert not hasattr(r, "butylene_volume")

    def test_zero_feed(self):
        r = SaturatedGasPlant(_unit()).calculate(feed_rate=0.0)
        assert r.propane_volume == 0.0
        assert r.isobutane_volume == 0.0
