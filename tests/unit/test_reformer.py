"""Tests for ReformerModel — Sprint 9 Task 9.1."""

from __future__ import annotations

from dataclasses import fields

import pytest

from eurekan.core.config import UnitConfig
from eurekan.core.crude import CutProperties
from eurekan.core.enums import UnitType
from eurekan.models.reformer import ReformerCalibration, ReformerModel


@pytest.fixture
def config() -> UnitConfig:
    return UnitConfig(
        unit_id="reformer_1",
        unit_type=UnitType.REFORMER,
        capacity=15000.0,
        equipment_limits={"heater_duty_max": 1.0},
    )


@pytest.fixture
def model(config) -> ReformerModel:
    return ReformerModel(config)


@pytest.fixture
def hn_feed() -> CutProperties:
    """Typical heavy naphtha feed."""
    return CutProperties(api=55.0, sulfur=0.001, ron=42.0, aromatics=15.0, spg=0.74)


class TestBaseCase:
    """Severity 98: reformate yield ~85%, RON ~98."""

    def test_reformate_yield(self, model, hn_feed):
        r = model.calculate(hn_feed, 10000.0, severity=98.0)
        yield_pct = r.reformate_volume / 10000.0
        assert 0.80 <= yield_pct <= 0.92, f"Yield {yield_pct:.3f} outside 80-92%"

    def test_reformate_ron(self, model, hn_feed):
        r = model.calculate(hn_feed, 10000.0, severity=98.0)
        assert abs(r.reformate_ron - 98.0) < 0.1

    def test_hydrogen_positive(self, model, hn_feed):
        r = model.calculate(hn_feed, 10000.0, severity=98.0)
        assert r.hydrogen_production > 0

    def test_has_equipment(self, model, hn_feed):
        r = model.calculate(hn_feed, 10000.0, severity=98.0)
        assert len(r.equipment) >= 1

    def test_severity_stored(self, model, hn_feed):
        r = model.calculate(hn_feed, 10000.0, severity=98.0)
        assert r.severity == 98.0


class TestSeverityResponse:
    """Higher severity → lower yield, higher RON."""

    def test_higher_severity_lower_yield(self, model, hn_feed):
        r_low = model.calculate(hn_feed, 10000.0, severity=92.0)
        r_high = model.calculate(hn_feed, 10000.0, severity=102.0)
        assert r_high.reformate_volume < r_low.reformate_volume

    def test_higher_severity_higher_ron(self, model, hn_feed):
        r_low = model.calculate(hn_feed, 10000.0, severity=92.0)
        r_high = model.calculate(hn_feed, 10000.0, severity=102.0)
        assert r_high.reformate_ron > r_low.reformate_ron


class TestMassBalance:
    """Reformate + H2 + LPG + fuel gas ≈ feed (±3%)."""

    def test_mass_balance(self, model, hn_feed):
        r = model.calculate(hn_feed, 10000.0, severity=98.0)
        total_out = (
            r.reformate_volume
            + r.hydrogen_production
            + r.lpg_production
            + r.fuel_gas_production
        )
        assert abs(total_out - 10000.0) / 10000.0 < 0.03

    def test_mass_balance_high_severity(self, model, hn_feed):
        r = model.calculate(hn_feed, 10000.0, severity=104.0)
        total_out = (
            r.reformate_volume
            + r.hydrogen_production
            + r.lpg_production
            + r.fuel_gas_production
        )
        assert abs(total_out - 10000.0) / 10000.0 < 0.03


class TestMaxSeverity:
    def test_max_severity_in_range(self, model, hn_feed):
        ms = model.max_severity(hn_feed)
        assert 100.0 <= ms <= 105.0

    def test_high_aromatics_lower_max(self, model):
        """High-aromatics feed should have lower max severity."""
        low_arom = CutProperties(aromatics=5.0)
        high_arom = CutProperties(aromatics=40.0)
        assert model.max_severity(low_arom) >= model.max_severity(high_arom)


class TestHydrogenIncreases:
    def test_hydrogen_increases_with_severity(self, model, hn_feed):
        h2_low = model.calculate(hn_feed, 10000.0, severity=92.0).hydrogen_production
        h2_high = model.calculate(hn_feed, 10000.0, severity=102.0).hydrogen_production
        assert h2_high > h2_low


class TestCalibrationNeutral:
    def test_default_matches_no_calibration(self, config, hn_feed):
        m_default = ReformerModel(config, ReformerCalibration())
        m_none = ReformerModel(config)
        r1 = m_default.calculate(hn_feed, 10000.0, severity=98.0)
        r2 = m_none.calculate(hn_feed, 10000.0, severity=98.0)
        assert abs(r1.reformate_volume - r2.reformate_volume) < 1e-10

    def test_all_defaults_are_neutral(self):
        cal = ReformerCalibration()
        for f in fields(cal):
            val = getattr(cal, f.name)
            if f.name.startswith("alpha_"):
                assert val == 1.0
            elif f.name.startswith("delta_"):
                assert val == 0.0
            elif f.name == "severity_factor":
                assert val == 1.0

    def test_calibration_changes_output(self, config, hn_feed):
        m_default = ReformerModel(config)
        m_tuned = ReformerModel(config, ReformerCalibration(alpha_reformate_yield=1.05))
        r1 = m_default.calculate(hn_feed, 10000.0, severity=98.0)
        r2 = m_tuned.calculate(hn_feed, 10000.0, severity=98.0)
        assert r2.reformate_volume > r1.reformate_volume
