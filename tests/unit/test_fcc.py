"""Tests for FCC model — Task 2.1."""

from __future__ import annotations

from dataclasses import fields

import pytest

from eurekan.core.config import UnitConfig
from eurekan.core.crude import CutProperties
from eurekan.core.enums import UnitType
from eurekan.models.fcc import FCCCalibration, FCCModel


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def fcc_config() -> UnitConfig:
    """Standard FCC unit config — 50K bbl/d, regen limit 1400°F."""
    return UnitConfig(
        unit_id="fcc_1",
        unit_type=UnitType.FCC,
        capacity=50000.0,
        equipment_limits={"fcc_regen_temp_max": 1400.0},
    )


@pytest.fixture
def fcc_model(fcc_config) -> FCCModel:
    return FCCModel(fcc_config)


@pytest.fixture
def arl_vgo() -> CutProperties:
    """ARL-like VGO feed properties — light, easy to crack."""
    return CutProperties(api=21.8, ccr=1.0, sulfur=1.1, nickel=0.5, vanadium=0.5)


@pytest.fixture
def heavy_vgo() -> CutProperties:
    """Heavy crude VGO — high CCR, high metals, hard to crack."""
    return CutProperties(api=15.0, ccr=4.0, sulfur=3.5, nickel=8.0, vanadium=15.0)


@pytest.fixture
def light_vgo() -> CutProperties:
    """Light crude VGO — low CCR, easy to crack."""
    return CutProperties(api=28.0, ccr=0.3, sulfur=0.3, nickel=0.1, vanadium=0.1)


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

class TestBaseCase:
    """80% conversion on ARL VGO — gasoline should be 45-54%."""

    def test_base_case_gasoline_in_range(self, fcc_model, arl_vgo):
        result = fcc_model.calculate(arl_vgo, 80.0)
        gasoline = result.yields["gasoline"]
        assert 0.45 <= gasoline <= 0.54, f"Gasoline yield {gasoline:.4f} outside 0.45-0.54"

    def test_base_case_lco_positive(self, fcc_model, arl_vgo):
        result = fcc_model.calculate(arl_vgo, 80.0)
        lco = result.yields["lco"]
        assert lco > 0.10, f"LCO yield {lco:.4f} should be > 0.10"

    def test_base_case_coke_reasonable(self, fcc_model, arl_vgo):
        result = fcc_model.calculate(arl_vgo, 80.0)
        coke = result.yields["coke"]
        assert 0.01 < coke < 0.10, f"Coke yield {coke:.4f} outside 0.01-0.10"

    def test_base_case_conversion_stored(self, fcc_model, arl_vgo):
        result = fcc_model.calculate(arl_vgo, 80.0)
        assert result.conversion == 80.0

    def test_base_case_has_properties(self, fcc_model, arl_vgo):
        result = fcc_model.calculate(arl_vgo, 80.0)
        assert "lcn" in result.properties
        assert "hcn" in result.properties
        assert result.properties["lcn"].ron is not None
        assert result.properties["hcn"].ron is not None

    def test_base_case_has_equipment(self, fcc_model, arl_vgo):
        result = fcc_model.calculate(arl_vgo, 80.0)
        assert len(result.equipment) >= 1
        regen = next(e for e in result.equipment if e.name == "regen_temp")
        assert regen.current_value > _REGEN_BASE_APPROX


class TestMassBalance:
    """All yields should sum to approximately 1.0 (±5%)."""

    def test_mass_balance_80pct(self, fcc_model, arl_vgo):
        result = fcc_model.calculate(arl_vgo, 80.0)
        # Sum all yields except "gasoline" (it's the sum of lcn + hcn)
        total = (
            result.yields["lcn"]
            + result.yields["hcn"]
            + result.yields["lco"]
            + result.yields["coke"]
            + result.yields["c3"]
            + result.yields["c4"]
            + result.yields["fuel_gas"]
            + result.yields["slurry"]
        )
        assert abs(total - 1.0) < 0.05, f"Yields sum to {total:.4f}, expected ~1.0"

    def test_mass_balance_70pct(self, fcc_model, arl_vgo):
        result = fcc_model.calculate(arl_vgo, 70.0)
        total = (
            result.yields["lcn"]
            + result.yields["hcn"]
            + result.yields["lco"]
            + result.yields["coke"]
            + result.yields["c3"]
            + result.yields["c4"]
            + result.yields["fuel_gas"]
            + result.yields["slurry"]
        )
        assert abs(total - 1.0) < 0.05, f"Yields sum to {total:.4f}, expected ~1.0"

    def test_mass_balance_heavy_feed(self, fcc_model, heavy_vgo):
        result = fcc_model.calculate(heavy_vgo, 75.0)
        total = (
            result.yields["lcn"]
            + result.yields["hcn"]
            + result.yields["lco"]
            + result.yields["coke"]
            + result.yields["c3"]
            + result.yields["c4"]
            + result.yields["fuel_gas"]
            + result.yields["slurry"]
        )
        assert abs(total - 1.0) < 0.05, f"Yields sum to {total:.4f}, expected ~1.0"

    def test_gasoline_equals_lcn_plus_hcn(self, fcc_model, arl_vgo):
        result = fcc_model.calculate(arl_vgo, 80.0)
        assert abs(
            result.yields["gasoline"] - result.yields["lcn"] - result.yields["hcn"]
        ) < 1e-10


class TestOvercracking:
    """Gasoline peaks then declines at high conversion."""

    def test_gasoline_peaks_then_declines(self, fcc_model, arl_vgo):
        """Sweep conversion 68-90%; gasoline should peak and then decline."""
        conversions = list(range(68, 92, 2))
        gasolines = []
        for conv in conversions:
            result = fcc_model.calculate(arl_vgo, float(conv))
            gasolines.append(result.yields["gasoline"])

        # Find the peak
        peak_idx = gasolines.index(max(gasolines))
        # Peak should NOT be at the last conversion (otherwise no overcracking)
        assert peak_idx < len(gasolines) - 1, (
            f"Gasoline peak at highest conversion ({conversions[peak_idx]}%) — "
            "no overcracking observed"
        )
        # Gasoline should decline after the peak
        assert gasolines[peak_idx + 1] < gasolines[peak_idx], (
            "Gasoline should decline after peak"
        )

    def test_lco_decreases_with_conversion(self, fcc_model, arl_vgo):
        """LCO should monotonically decrease with conversion."""
        prev_lco = float("inf")
        for conv in range(70, 90, 2):
            result = fcc_model.calculate(arl_vgo, float(conv))
            lco = result.yields["lco"]
            assert lco < prev_lco, f"LCO not decreasing at {conv}%: {lco:.4f} >= {prev_lco:.4f}"
            prev_lco = lco

    def test_coke_increases_with_conversion(self, fcc_model, arl_vgo):
        """Coke should monotonically increase with conversion."""
        prev_coke = 0.0
        for conv in range(70, 90, 2):
            result = fcc_model.calculate(arl_vgo, float(conv))
            coke = result.yields["coke"]
            assert coke > prev_coke, f"Coke not increasing at {conv}%: {coke:.4f} <= {prev_coke:.4f}"
            prev_coke = coke


class TestEquipmentStatus:
    """Regen temp increases with conversion."""

    def test_regen_temp_increases_with_conversion(self, fcc_model, arl_vgo):
        prev_temp = 0.0
        for conv in range(70, 90, 2):
            result = fcc_model.calculate(arl_vgo, float(conv))
            regen = next(e for e in result.equipment if e.name == "regen_temp")
            assert regen.current_value > prev_temp, (
                f"Regen temp not increasing at {conv}%: "
                f"{regen.current_value:.1f} <= {prev_temp:.1f}"
            )
            prev_temp = regen.current_value

    def test_regen_temp_has_limit(self, fcc_model, arl_vgo):
        result = fcc_model.calculate(arl_vgo, 80.0)
        regen = next(e for e in result.equipment if e.name == "regen_temp")
        assert regen.limit == 1400.0

    def test_equipment_status_count(self, fcc_model, arl_vgo):
        result = fcc_model.calculate(arl_vgo, 80.0)
        assert len(result.equipment) == 3  # regen, gas compressor, air blower

    def test_utilization_pct_reasonable(self, fcc_model, arl_vgo):
        result = fcc_model.calculate(arl_vgo, 80.0)
        for equip in result.equipment:
            assert 0 <= equip.utilization_pct <= 100.0


class TestMaxConversion:
    """Heavy crude has lower max conversion than light crude."""

    def test_heavy_lower_than_light(self, fcc_model, heavy_vgo, light_vgo):
        max_heavy = fcc_model.max_conversion(heavy_vgo)
        max_light = fcc_model.max_conversion(light_vgo)
        assert max_heavy < max_light, (
            f"Heavy VGO max conv ({max_heavy}%) should be < light VGO ({max_light}%)"
        )

    def test_max_conversion_arl_reasonable(self, fcc_model, arl_vgo):
        max_conv = fcc_model.max_conversion(arl_vgo)
        assert 75.0 < max_conv < 95.0, f"ARL max conversion {max_conv}% outside reasonable range"

    def test_max_conversion_heavy_limited(self, fcc_model, heavy_vgo):
        max_conv = fcc_model.max_conversion(heavy_vgo)
        assert max_conv < 85.0, f"Heavy VGO max conversion {max_conv}% should be < 85%"

    def test_regen_at_max_conversion_near_limit(self, fcc_model, arl_vgo):
        """At max conversion, regen temp should be near the limit."""
        max_conv = fcc_model.max_conversion(arl_vgo)
        result = fcc_model.calculate(arl_vgo, max_conv)
        regen = next(e for e in result.equipment if e.name == "regen_temp")
        # Should be within 5°F of the limit
        assert abs(regen.current_value - regen.limit) < 5.0, (
            f"At max conversion {max_conv}%, regen temp {regen.current_value:.1f} "
            f"not near limit {regen.limit:.1f}"
        )


class TestCalibrationNeutral:
    """Default calibration doesn't change yields."""

    def test_default_calibration_matches_no_calibration(self, fcc_config, arl_vgo):
        model_default = FCCModel(fcc_config, FCCCalibration())
        model_none = FCCModel(fcc_config)

        r1 = model_default.calculate(arl_vgo, 80.0)
        r2 = model_none.calculate(arl_vgo, 80.0)

        for key in r1.yields:
            assert abs(r1.yields[key] - r2.yields[key]) < 1e-10, (
                f"Yield '{key}' differs with default vs no calibration"
            )

    def test_all_calibration_defaults_are_neutral(self):
        """Verify all alpha defaults are 1.0 and all delta defaults are 0.0
        (except sulfur multipliers which are 1.0)."""
        cal = FCCCalibration()
        for f in fields(cal):
            val = getattr(cal, f.name)
            if f.name.startswith("alpha_"):
                assert val == 1.0, f"{f.name} default should be 1.0, got {val}"
            elif f.name.startswith("delta_") and "sulfur" in f.name:
                assert val == 1.0, f"{f.name} default should be 1.0, got {val}"
            elif f.name.startswith("delta_"):
                assert val == 0.0, f"{f.name} default should be 0.0, got {val}"

    def test_calibration_changes_yields(self, fcc_config, arl_vgo):
        """Non-neutral calibration should produce different yields."""
        model_default = FCCModel(fcc_config)
        model_tuned = FCCModel(
            fcc_config,
            FCCCalibration(alpha_gasoline=1.05, alpha_coke=0.95),
        )

        r1 = model_default.calculate(arl_vgo, 80.0)
        r2 = model_tuned.calculate(arl_vgo, 80.0)

        assert r2.yields["gasoline"] > r1.yields["gasoline"], (
            "alpha_gasoline=1.05 should increase gasoline yield"
        )
        assert r2.yields["coke"] < r1.yields["coke"], (
            "alpha_coke=0.95 should decrease coke yield"
        )


# Approximate regen base for assertion
_REGEN_BASE_APPROX = 1100.0
