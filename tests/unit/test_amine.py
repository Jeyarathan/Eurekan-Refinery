"""Tests for AmineModel — Sprint A sulfur complex."""

from __future__ import annotations

from eurekan.core.config import UnitConfig
from eurekan.core.enums import UnitType
from eurekan.models.amine import AmineCalibration, AmineModel


def _unit(capacity: float = 3.0) -> UnitConfig:
    return UnitConfig(unit_id="amine_1", unit_type=UnitType.UTILITY, capacity=capacity)


class TestAmineMassBalance:
    def test_total_in_is_sum_of_sources(self):
        model = AmineModel(_unit())
        r = model.calculate(hts_h2s=1.0, fcc_h2s=0.5, coker_h2s=0.3)
        assert abs(r.h2s_in - 1.8) < 1e-9

    def test_to_sru_plus_slip_equals_in(self):
        model = AmineModel(_unit())
        r = model.calculate(hts_h2s=1.0, fcc_h2s=0.5, coker_h2s=0.3)
        assert abs((r.h2s_to_sru + r.h2s_slip) - r.h2s_in) < 1e-9

    def test_zero_feed(self):
        model = AmineModel(_unit())
        r = model.calculate(hts_h2s=0.0, fcc_h2s=0.0, coker_h2s=0.0)
        assert r.h2s_in == 0.0
        assert r.h2s_to_sru == 0.0
        assert r.h2s_slip == 0.0


class TestAmineEfficiency:
    def test_default_removal_995_percent(self):
        model = AmineModel(_unit())
        r = model.calculate(hts_h2s=2.0)
        assert abs(r.h2s_to_sru - 2.0 * 0.995) < 1e-9

    def test_slip_is_small_under_default(self):
        model = AmineModel(_unit())
        r = model.calculate(hts_h2s=2.0)
        assert r.h2s_slip < 0.02


class TestAmineCalibration:
    def test_alpha_less_than_one_reduces_recovery(self):
        cal = AmineCalibration(alpha_removal=0.9)
        model = AmineModel(_unit(), calibration=cal)
        r = model.calculate(hts_h2s=2.0)
        # At alpha=0.9, effective eff = 0.9 × 0.995 = 0.8955
        assert abs(r.h2s_to_sru - 2.0 * 0.9 * 0.995) < 1e-9
