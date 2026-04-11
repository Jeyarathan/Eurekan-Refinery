"""Task 2.4 — Crude sensitivity test.

Verify that feed quality drives max conversion in the right direction:
  - Light crude VGO (high API, low CCR): highest max conversion
  - Heavy crude VGO (low API, high CCR, high metals): lowest max conversion
  - Mars-like crude VGO (CCR ~2.8): limited to ~80-82% by regen
"""

from __future__ import annotations

import pytest

from eurekan.core.config import UnitConfig
from eurekan.core.crude import CutProperties
from eurekan.core.enums import UnitType
from eurekan.models.fcc import FCCModel


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
def light_vgo() -> CutProperties:
    """Light crude VGO — highest API, lowest CCR in a typical library."""
    return CutProperties(api=28.0, ccr=0.3, sulfur=0.3, nickel=0.1, vanadium=0.1)


@pytest.fixture
def heavy_vgo() -> CutProperties:
    """Heavy crude VGO — lowest API, highest CCR, high metals."""
    return CutProperties(api=15.0, ccr=4.0, sulfur=3.5, nickel=8.0, vanadium=15.0)


@pytest.fixture
def mars_vgo() -> CutProperties:
    """Mars-like crude VGO — moderate-heavy, CCR ~2.8."""
    return CutProperties(api=18.0, ccr=2.8, sulfur=2.5, nickel=5.0, vanadium=10.0)


class TestLightVsHeavy:
    """Light crude VGO should allow higher conversion than heavy."""

    def test_light_higher_than_heavy(self, fcc_model, light_vgo, heavy_vgo):
        max_light = fcc_model.max_conversion(light_vgo)
        max_heavy = fcc_model.max_conversion(heavy_vgo)
        assert max_light > max_heavy, (
            f"Light VGO max {max_light}% should exceed heavy VGO {max_heavy}%"
        )

    def test_heavy_limited_below_85(self, fcc_model, heavy_vgo):
        max_heavy = fcc_model.max_conversion(heavy_vgo)
        assert max_heavy < 85.0, (
            f"Heavy VGO max conversion {max_heavy}% should be < 85%"
        )

    def test_heavy_regen_binding(self, fcc_model, heavy_vgo):
        """At max conversion, regen should be at or near the limit."""
        max_conv = fcc_model.max_conversion(heavy_vgo)
        result = fcc_model.calculate(heavy_vgo, max_conv)
        regen = next(e for e in result.equipment if e.name == "regen_temp")
        assert abs(regen.current_value - regen.limit) < 5.0, (
            f"Heavy VGO at max conv {max_conv}%: regen {regen.current_value:.1f}°F "
            f"not near limit {regen.limit:.1f}°F"
        )


class TestMarsConversion:
    """Mars-like crude (CCR ~2.8) should be limited to ~80-82% by regen."""

    def test_mars_max_conversion_range(self, fcc_model, mars_vgo):
        max_conv = fcc_model.max_conversion(mars_vgo)
        assert 76.0 <= max_conv <= 85.0, (
            f"Mars VGO max conversion {max_conv}% outside 76-85% range"
        )

    def test_mars_regen_binding(self, fcc_model, mars_vgo):
        """At max conversion, regen should be near the limit."""
        max_conv = fcc_model.max_conversion(mars_vgo)
        result = fcc_model.calculate(mars_vgo, max_conv)
        regen = next(e for e in result.equipment if e.name == "regen_temp")
        assert abs(regen.current_value - regen.limit) < 5.0, (
            f"Mars at max conv {max_conv}%: regen {regen.current_value:.1f}°F "
            f"not near limit {regen.limit:.1f}°F"
        )

    def test_mars_between_light_and_heavy(self, fcc_model, light_vgo, heavy_vgo, mars_vgo):
        """Mars max conversion should be between light and heavy."""
        max_light = fcc_model.max_conversion(light_vgo)
        max_heavy = fcc_model.max_conversion(heavy_vgo)
        max_mars = fcc_model.max_conversion(mars_vgo)
        assert max_heavy < max_mars < max_light, (
            f"Expected heavy ({max_heavy}%) < Mars ({max_mars}%) < light ({max_light}%)"
        )


class TestConversionOrdering:
    """Overall ordering: light > Mars > heavy."""

    def test_monotonic_with_ccr(self, fcc_model, light_vgo, mars_vgo, heavy_vgo):
        """Higher CCR should mean lower max conversion."""
        feeds = [
            ("light", light_vgo),
            ("mars", mars_vgo),
            ("heavy", heavy_vgo),
        ]
        max_convs = [(name, fcc_model.max_conversion(props)) for name, props in feeds]
        for i in range(len(max_convs) - 1):
            name_a, conv_a = max_convs[i]
            name_b, conv_b = max_convs[i + 1]
            assert conv_a > conv_b, (
                f"{name_a} ({conv_a}%) should have higher max_conv than {name_b} ({conv_b}%)"
            )
