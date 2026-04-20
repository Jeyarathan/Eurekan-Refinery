"""Tests for TailGasModel — Sprint A sulfur complex."""

from __future__ import annotations

from eurekan.core.config import UnitConfig
from eurekan.core.enums import UnitType
from eurekan.models.tail_gas import TailGasCalibration, TailGasModel


def _unit(capacity: float = 0.2) -> UnitConfig:
    return UnitConfig(unit_id="tgt_1", unit_type=UnitType.UTILITY, capacity=capacity)


class TestTailGasRecovery:
    def test_default_90_percent_recovery(self):
        model = TailGasModel(_unit())
        r = model.calculate(tail_gas_s=0.1)
        assert abs(r.s_recovered - 0.1 * 0.90) < 1e-9

    def test_recovered_plus_stack_equals_in(self):
        model = TailGasModel(_unit())
        r = model.calculate(tail_gas_s=0.15)
        assert abs((r.s_recovered + r.s_to_stack) - 0.15) < 1e-9

    def test_zero_feed(self):
        model = TailGasModel(_unit())
        r = model.calculate(tail_gas_s=0.0)
        assert r.s_recovered == 0.0
        assert r.s_to_stack == 0.0


class TestTailGasCalibration:
    def test_lower_alpha_reduces_capture(self):
        cal = TailGasCalibration(alpha_recovery=0.8)
        model = TailGasModel(_unit(), calibration=cal)
        r = model.calculate(tail_gas_s=0.1)
        # Effective recovery = 0.8 × 0.9 = 0.72
        assert abs(r.s_recovered - 0.1 * 0.72) < 1e-9
