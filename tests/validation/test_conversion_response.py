"""Task 2.3 — Conversion sweep test.

Sweep 72-88% in 2% steps on ARL VGO and verify:
  - Gasoline INCREASES then PEAKS (overcracking)
  - LCO monotonically DECREASES
  - Coke monotonically INCREASES
  - Regen temp INCREASES with conversion
  - max_conversion() returns value where regen hits limit
"""

from __future__ import annotations

import pytest

from eurekan.core.config import UnitConfig
from eurekan.core.crude import CutProperties
from eurekan.core.enums import UnitType
from eurekan.models.fcc import FCCModel

_CONVERSIONS = list(range(72, 90, 2))  # [72, 74, 76, ..., 88]


@pytest.fixture
def fcc_model() -> FCCModel:
    config = UnitConfig(
        unit_id="fcc_1",
        unit_type=UnitType.FCC,
        capacity=50000.0,
        equipment_limits={"fcc_regen_temp_max": 1400.0},
    )
    return FCCModel(config)


@pytest.fixture
def arl_vgo() -> CutProperties:
    """ARL VGO at SCCU conditions."""
    return CutProperties(api=21.8, ccr=0.5, sulfur=1.1, nickel=0.5, vanadium=0.5)


@pytest.fixture
def moderate_vgo() -> CutProperties:
    """Moderate VGO where regen actually limits conversion."""
    return CutProperties(api=20.0, ccr=2.5, sulfur=2.0, nickel=3.0, vanadium=7.0)


class TestGasolineOvercracking:
    """Gasoline yield should INCREASE then PEAK at high conversion."""

    def test_gasoline_peaks_then_declines(self, fcc_model, arl_vgo):
        gasolines = []
        for conv in _CONVERSIONS:
            r = fcc_model.calculate(arl_vgo, float(conv))
            gasolines.append(r.yields["gasoline"])

        peak_idx = gasolines.index(max(gasolines))
        # Peak should NOT be at the last conversion tested
        assert peak_idx < len(gasolines) - 1, (
            f"Gasoline peak at highest conversion ({_CONVERSIONS[peak_idx]}%) "
            "— no overcracking observed"
        )
        # Gasoline should decline after the peak
        assert gasolines[peak_idx + 1] < gasolines[peak_idx], (
            "Gasoline should decline after peak"
        )

    def test_gasoline_increases_before_peak(self, fcc_model, arl_vgo):
        """Gasoline should increase from 72% up to the peak."""
        gasolines = []
        for conv in _CONVERSIONS:
            r = fcc_model.calculate(arl_vgo, float(conv))
            gasolines.append(r.yields["gasoline"])

        peak_idx = gasolines.index(max(gasolines))
        # At least the first 3 points should show increasing gasoline
        for i in range(min(3, peak_idx)):
            assert gasolines[i + 1] > gasolines[i], (
                f"Gasoline not increasing at {_CONVERSIONS[i+1]}%: "
                f"{gasolines[i+1]:.4f} <= {gasolines[i]:.4f}"
            )


class TestLCOResponse:
    """LCO yield should monotonically DECREASE with conversion."""

    def test_lco_monotonically_decreases(self, fcc_model, arl_vgo):
        prev_lco = float("inf")
        for conv in _CONVERSIONS:
            r = fcc_model.calculate(arl_vgo, float(conv))
            lco = r.yields["lco"]
            assert lco < prev_lco, (
                f"LCO not decreasing at {conv}%: {lco:.4f} >= {prev_lco:.4f}"
            )
            prev_lco = lco


class TestCokeResponse:
    """Coke yield should monotonically INCREASE with conversion."""

    def test_coke_monotonically_increases(self, fcc_model, arl_vgo):
        prev_coke = 0.0
        for conv in _CONVERSIONS:
            r = fcc_model.calculate(arl_vgo, float(conv))
            coke = r.yields["coke"]
            assert coke > prev_coke, (
                f"Coke not increasing at {conv}%: {coke:.4f} <= {prev_coke:.4f}"
            )
            prev_coke = coke


class TestRegenTempResponse:
    """Regenerator temperature should INCREASE with conversion."""

    def test_regen_temp_monotonically_increases(self, fcc_model, arl_vgo):
        prev_temp = 0.0
        for conv in _CONVERSIONS:
            r = fcc_model.calculate(arl_vgo, float(conv))
            regen = next(e for e in r.equipment if e.name == "regen_temp")
            assert regen.current_value > prev_temp, (
                f"Regen temp not increasing at {conv}%: "
                f"{regen.current_value:.1f} <= {prev_temp:.1f}"
            )
            prev_temp = regen.current_value


class TestMaxConversionRegenLimit:
    """max_conversion() should return the value where regen hits its limit.

    Uses a moderate VGO (CCR=2.5) where regen actually constrains conversion.
    For very light feeds (ARL VGO, CCR=0.5), regen never limits and
    max_conversion returns the bisection ceiling (95%).
    """

    def test_max_conversion_at_regen_limit(self, fcc_model, moderate_vgo):
        max_conv = fcc_model.max_conversion(moderate_vgo)
        result = fcc_model.calculate(moderate_vgo, max_conv)
        regen = next(e for e in result.equipment if e.name == "regen_temp")
        assert abs(regen.current_value - regen.limit) < 5.0, (
            f"At max conversion {max_conv}%, regen temp {regen.current_value:.1f}°F "
            f"not near limit {regen.limit:.1f}°F"
        )

    def test_max_conversion_below_90_for_moderate_feed(self, fcc_model, moderate_vgo):
        max_conv = fcc_model.max_conversion(moderate_vgo)
        assert max_conv < 90.0, (
            f"Moderate VGO max conversion {max_conv}% should be < 90%"
        )

    def test_light_feed_max_higher_than_moderate(self, fcc_model, arl_vgo, moderate_vgo):
        max_light = fcc_model.max_conversion(arl_vgo)
        max_mod = fcc_model.max_conversion(moderate_vgo)
        assert max_light > max_mod, (
            f"Light feed max {max_light}% should exceed moderate {max_mod}%"
        )
