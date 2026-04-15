"""Tests for C5/C6 Isomerization and C4 Isomerization — Sprint 14.1 + 14.2."""

from __future__ import annotations

from eurekan.core.config import UnitConfig
from eurekan.core.crude import CutProperties
from eurekan.core.enums import UnitType
from eurekan.models.c4_isom import C4IsomerizationCalibration, C4IsomerizationModel
from eurekan.models.isomerization import (
    C56IsomerizationModel,
    IsomerizationCalibration,
)


def _ln_props() -> CutProperties:
    """Typical light naphtha: RON 68, C5-C6."""
    return CutProperties(api=82.0, sulfur=0.001, ron=68.0, rvp=12.5, spg=0.66)


class TestC56Isomerization:
    def _model(self, capacity: float = 15_000.0) -> C56IsomerizationModel:
        return C56IsomerizationModel(
            UnitConfig(unit_id="isom_c56", unit_type=UnitType.ISOMERIZATION, capacity=capacity)
        )

    def test_octane_improvement(self):
        """Isomerate RON should be 82-87 (up from 68 LN)."""
        result = self._model().calculate(feed_rate=10_000.0, feed_properties=_ln_props())
        assert 82.0 <= result.isomerate_ron <= 87.0

    def test_volume_yield_near_unity(self):
        """Yield should be 97-99%."""
        result = self._model().calculate(feed_rate=10_000.0, feed_properties=_ln_props())
        yield_frac = result.isomerate_volume / 10_000.0
        assert 0.97 <= yield_frac <= 0.99

    def test_mass_balance(self):
        """Product volume <= feed (no mass gain)."""
        for feed in (5_000.0, 10_000.0, 15_000.0):
            result = self._model().calculate(feed_rate=feed, feed_properties=_ln_props())
            assert result.isomerate_volume <= feed

    def test_h2_consumption_low(self):
        """C5/C6 isom: 100-200 SCFB (very low)."""
        result = self._model().calculate(feed_rate=10_000.0, feed_properties=_ln_props())
        # 150 SCFB * 10000 bbl/d / 1e6 = 1.5 MMSCFD
        assert 1.0 <= result.hydrogen_consumption_mmscf <= 2.0

    def test_zero_feed(self):
        result = self._model().calculate(feed_rate=0.0, feed_properties=_ln_props())
        assert result.isomerate_volume == 0.0
        assert result.hydrogen_consumption_mmscf == 0.0

    def test_calibration_changes_yield(self):
        cal = IsomerizationCalibration(alpha_yield=0.95)
        model = C56IsomerizationModel(
            UnitConfig(unit_id="isom_c56", unit_type=UnitType.ISOMERIZATION, capacity=15_000.0),
            calibration=cal,
        )
        r = model.calculate(feed_rate=10_000.0, feed_properties=_ln_props())
        assert r.isomerate_volume < 10_000.0 * 0.98

    def test_isomerate_properties_low_benzene(self):
        """Isomerate should have near-zero benzene (regulatory benefit)."""
        result = self._model().calculate(feed_rate=10_000.0, feed_properties=_ln_props())
        assert result.isomerate_properties.benzene is not None
        assert result.isomerate_properties.benzene < 0.5


class TestC4Isomerization:
    def _model(self, capacity: float = 5_000.0) -> C4IsomerizationModel:
        return C4IsomerizationModel(
            UnitConfig(unit_id="isom_c4", unit_type=UnitType.ISOMERIZATION, capacity=capacity)
        )

    def test_ic4_yield_95_percent(self):
        """With recycle, iC4 yield ~95% of nC4 feed."""
        result = self._model().calculate(feed_rate=3_000.0)
        yield_frac = result.ic4_volume / 3_000.0
        assert 0.93 <= yield_frac <= 0.97

    def test_mass_balance(self):
        """iC4 + unconverted nC4 = feed."""
        for feed in (1_000.0, 3_000.0, 5_000.0):
            result = self._model().calculate(feed_rate=feed)
            total = result.ic4_volume + result.unconverted_nc4_volume
            assert abs(total - feed) < 1e-6

    def test_zero_feed(self):
        result = self._model().calculate(feed_rate=0.0)
        assert result.ic4_volume == 0.0
        assert result.unconverted_nc4_volume == 0.0

    def test_h2_consumption_minimal(self):
        """C4 isom: very low H2 (equilibrium reaction)."""
        result = self._model().calculate(feed_rate=5_000.0)
        # 50 SCFB * 5000 bbl/d / 1e6 = 0.25 MMSCFD
        assert result.hydrogen_consumption_mmscf < 0.5

    def test_calibration_changes_output(self):
        cal = C4IsomerizationCalibration(alpha_yield=0.9)
        model = C4IsomerizationModel(
            UnitConfig(unit_id="isom_c4", unit_type=UnitType.ISOMERIZATION, capacity=5_000.0),
            calibration=cal,
        )
        r = model.calculate(feed_rate=3_000.0)
        assert r.ic4_volume < 3_000.0 * 0.95
