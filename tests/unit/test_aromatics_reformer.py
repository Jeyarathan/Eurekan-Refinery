"""Tests for AromaticsReformerModel — Sprint 15.1."""

from __future__ import annotations

from eurekan.core.config import UnitConfig
from eurekan.core.crude import CutProperties
from eurekan.core.enums import UnitType
from eurekan.models.aromatics_reformer import (
    AromaticsReformerCalibration,
    AromaticsReformerModel,
)


def _unit(capacity: float = 35_000.0) -> UnitConfig:
    return UnitConfig(unit_id="arom_reformer", unit_type=UnitType.REFORMER, capacity=capacity)


def _hn_props() -> CutProperties:
    """Typical heavy naphtha feed."""
    return CutProperties(api=55.0, sulfur=0.005, ron=42.0, aromatics=12.0)


class TestBTXYield:
    def test_btx_yield_typical(self):
        """40-50 vol% BTX at typical severity."""
        model = AromaticsReformerModel(_unit())
        result = model.calculate(feed_rate=20_000.0, feed_properties=_hn_props())
        yield_frac = result.btx_volume / 20_000.0
        assert 0.40 <= yield_frac <= 0.50

    def test_btx_tons_conversion(self):
        """BTX tons should equal vol * spg * 0.159."""
        model = AromaticsReformerModel(_unit())
        result = model.calculate(feed_rate=10_000.0, feed_properties=_hn_props())
        expected_tons = result.btx_volume * 0.870 * 0.159
        assert abs(result.btx_tons_per_day - expected_tons) < 0.01

    def test_calibration_increases_btx(self):
        cal = AromaticsReformerCalibration(alpha_btx=1.1)
        base = AromaticsReformerModel(_unit())
        boosted = AromaticsReformerModel(_unit(), calibration=cal)
        r_base = base.calculate(feed_rate=10_000.0, feed_properties=_hn_props())
        r_boost = boosted.calculate(feed_rate=10_000.0, feed_properties=_hn_props())
        assert r_boost.btx_volume > r_base.btx_volume


class TestMassBalance:
    def test_products_sum_approx_feed(self):
        """BTX + raffinate + LPG + fuel gas ~= feed (within 5% for H2 wt loss)."""
        model = AromaticsReformerModel(_unit())
        feed = 15_000.0
        r = model.calculate(feed_rate=feed, feed_properties=_hn_props())
        total = r.btx_volume + r.raffinate_volume + r.lpg_production + r.fuel_gas_production
        # Hydrogen leaves as gas (wt basis), so liquid+LPG is ~95% of feed
        assert total <= feed
        assert total / feed >= 0.90

    def test_zero_feed(self):
        model = AromaticsReformerModel(_unit())
        r = model.calculate(feed_rate=0.0, feed_properties=_hn_props())
        assert r.btx_volume == 0.0
        assert r.raffinate_volume == 0.0
        assert r.hydrogen_production_mmscf == 0.0


class TestHydrogenProduction:
    def test_h2_positive(self):
        model = AromaticsReformerModel(_unit())
        r = model.calculate(feed_rate=10_000.0, feed_properties=_hn_props())
        assert r.hydrogen_production_mmscf > 0.0

    def test_h2_scales_with_feed(self):
        model = AromaticsReformerModel(_unit())
        r_low = model.calculate(feed_rate=5_000.0, feed_properties=_hn_props())
        r_high = model.calculate(feed_rate=20_000.0, feed_properties=_hn_props())
        assert r_high.hydrogen_production_mmscf > r_low.hydrogen_production_mmscf


class TestRaffinateProperties:
    def test_raffinate_low_ron(self):
        """Raffinate has low octane after aromatics extraction."""
        model = AromaticsReformerModel(_unit())
        r = model.calculate(feed_rate=10_000.0, feed_properties=_hn_props())
        assert r.raffinate_properties.ron is not None
        assert r.raffinate_properties.ron < 75.0

    def test_raffinate_low_aromatics(self):
        """Aromatics are extracted - raffinate should be paraffinic."""
        model = AromaticsReformerModel(_unit())
        r = model.calculate(feed_rate=10_000.0, feed_properties=_hn_props())
        assert r.raffinate_properties.aromatics is not None
        assert r.raffinate_properties.aromatics < 10.0


class TestEquipment:
    def test_has_throughput_status(self):
        model = AromaticsReformerModel(_unit())
        r = model.calculate(feed_rate=17_500.0, feed_properties=_hn_props())
        assert len(r.equipment) >= 1
        assert abs(r.equipment[0].utilization_pct - 50.0) < 0.1
