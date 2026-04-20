"""Tests for SRUModel — Sprint A sulfur complex."""

from __future__ import annotations

from eurekan.core.config import UnitConfig
from eurekan.core.enums import UnitType
from eurekan.models.sru import SRUCalibration, SRUModel


_S_PER_H2S = 32.0 / 34.0


def _unit(capacity: float = 3.0) -> UnitConfig:
    return UnitConfig(unit_id="sru_1", unit_type=UnitType.UTILITY, capacity=capacity)


class TestSRUYield:
    def test_zero_feed(self):
        model = SRUModel(_unit())
        r = model.calculate(h2s_feed=0.0)
        assert r.sulfur_produced == 0.0
        assert r.tail_gas_s == 0.0

    def test_default_recovery_97_percent(self):
        model = SRUModel(_unit())
        r = model.calculate(h2s_feed=1.0)
        expected_s = 1.0 * _S_PER_H2S * 0.97
        assert abs(r.sulfur_produced - expected_s) < 1e-9

    def test_tail_gas_is_3_percent_of_s_in(self):
        model = SRUModel(_unit())
        r = model.calculate(h2s_feed=1.0)
        s_in = 1.0 * _S_PER_H2S
        assert abs(r.tail_gas_s - s_in * 0.03) < 1e-9


class TestSRUMassBalance:
    def test_produced_plus_tail_equals_s_equivalent_in(self):
        model = SRUModel(_unit())
        r = model.calculate(h2s_feed=2.5)
        s_in = 2.5 * _S_PER_H2S
        assert abs((r.sulfur_produced + r.tail_gas_s) - s_in) < 1e-9

    def test_stoichiometry_32_over_34(self):
        """1 LT H2S carries 32/34 LT of S atoms (mass basis)."""
        model = SRUModel(_unit())
        r = model.calculate(h2s_feed=1.7)
        assert abs((r.sulfur_produced + r.tail_gas_s) - 1.7 * _S_PER_H2S) < 1e-9


class TestSRUCalibration:
    def test_calibration_reduces_recovery(self):
        cal = SRUCalibration(alpha_recovery=0.9)
        model = SRUModel(_unit(), calibration=cal)
        r = model.calculate(h2s_feed=1.0)
        expected = 1.0 * _S_PER_H2S * 0.9 * 0.97
        assert abs(r.sulfur_produced - expected) < 1e-9
