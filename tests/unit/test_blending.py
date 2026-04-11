"""Tests for BlendingModel — Task 3.1."""

from __future__ import annotations

import pytest

from eurekan.core.crude import CutProperties
from eurekan.core.enums import BlendMethod
from eurekan.core.product import Product, ProductSpec
from eurekan.models.blending import BlendingModel


@pytest.fixture
def model() -> BlendingModel:
    return BlendingModel()


@pytest.fixture
def reformate() -> CutProperties:
    """High-octane, low-RVP reformate."""
    return CutProperties(
        ron=98.0, mon=88.0, rvp=4.0, sulfur=0.001, spg=0.79,
        benzene=1.0, aromatics=65.0, olefins=1.0,
    )


@pytest.fixture
def n_butane() -> CutProperties:
    """High-RVP n-butane."""
    return CutProperties(
        ron=93.8, mon=89.6, rvp=51.6, sulfur=0.0, spg=0.585,
        benzene=0.0, aromatics=0.0, olefins=0.0,
    )


@pytest.fixture
def lcn() -> CutProperties:
    """FCC light cat naphtha."""
    return CutProperties(
        ron=92.0, mon=80.0, rvp=10.5, sulfur=0.05, spg=0.70,
        benzene=0.5, aromatics=25.0, olefins=30.0,
    )


@pytest.fixture
def hcn() -> CutProperties:
    """FCC heavy cat naphtha — high sulfur."""
    return CutProperties(
        ron=86.0, mon=76.0, rvp=2.0, sulfur=0.30, spg=0.82,
        benzene=0.8, aromatics=45.0, olefins=8.0,
    )


@pytest.fixture
def cdu_ln() -> CutProperties:
    """CDU straight-run light naphtha — low octane."""
    return CutProperties(
        ron=68.0, mon=65.0, rvp=12.5, sulfur=0.02, spg=0.66,
        benzene=2.0, aromatics=8.0, olefins=1.0,
    )


@pytest.fixture
def gasoline_product() -> Product:
    """Regular gasoline with typical specs."""
    return Product(
        product_id="regular_gasoline",
        name="Regular Gasoline",
        price=82.81,
        specs=[
            ProductSpec(spec_name="road_octane", min_value=87.0),
            ProductSpec(spec_name="rvp", max_value=14.0),
            ProductSpec(spec_name="sulfur", max_value=0.10),
            ProductSpec(spec_name="benzene", max_value=1.0),
            ProductSpec(spec_name="aromatics", max_value=35.0),
            ProductSpec(spec_name="olefins", max_value=18.0),
        ],
    )


# ---------------------------------------------------------------------------
# RON blending — non-linear by Blending Index
# ---------------------------------------------------------------------------


class TestRONIndexNonlinear:
    """RON blends via Blending Index, not linear-by-volume."""

    def test_ron_index_differs_from_linear(self, model):
        """50/50 blend of high and low RON: BI method should differ from linear."""
        volumes = {"a": 50.0, "b": 50.0}
        props = {
            "a": CutProperties(ron=93.0),
            "b": CutProperties(ron=42.0),
        }
        bi_blend = model.calculate_blend_property(
            volumes, props, "ron", BlendMethod.INDEX
        )
        linear = (93.0 * 50.0 + 42.0 * 50.0) / 100.0  # = 67.5

        # Blending indices give a different (typically lower) value than linear
        assert abs(bi_blend - linear) > 1.0, (
            f"BI blend {bi_blend:.2f} too close to linear average {linear:.2f}"
        )
        # Result should still be physical (between the components)
        assert 42.0 <= bi_blend <= 93.0

    def test_ron_blend_realistic(self, model, reformate, lcn, cdu_ln):
        """Three-component gasoline blend has reasonable octane."""
        volumes = {"reformate": 30.0, "lcn": 50.0, "cdu_ln": 20.0}
        props = {"reformate": reformate, "lcn": lcn, "cdu_ln": cdu_ln}
        ron = model.calculate_blend_property(
            volumes, props, "ron", BlendMethod.INDEX
        )
        # Should be between 68 (CDU LN) and 98 (reformate)
        assert 80.0 <= ron <= 95.0, f"Blend RON {ron:.2f} unrealistic"

    def test_ron_inverse_round_trip(self, model):
        """Single-component blend → output equals input RON exactly."""
        volumes = {"a": 100.0}
        props = {"a": CutProperties(ron=92.5)}
        ron = model.calculate_blend_property(
            volumes, props, "ron", BlendMethod.INDEX
        )
        assert abs(ron - 92.5) < 1e-6


# ---------------------------------------------------------------------------
# RVP blending — power law
# ---------------------------------------------------------------------------


class TestRVPPowerLaw:
    """RVP blends with the 1.25 power law."""

    def test_rvp_high_low_blend(self, model, n_butane, reformate):
        """High-RVP n-butane + low-RVP reformate."""
        volumes = {"butane": 5.0, "reformate": 95.0}
        props = {"butane": n_butane, "reformate": reformate}
        rvp = model.calculate_blend_property(
            volumes, props, "rvp", BlendMethod.POWER_LAW
        )
        # Result should be between the components
        assert 4.0 < rvp < 51.6
        # Should be higher than linear-volume average due to power-law shape
        linear = (5.0 * 51.6 + 95.0 * 4.0) / 100.0  # = 6.38
        assert rvp > linear, f"Power-law RVP {rvp:.2f} should exceed linear {linear:.2f}"

    def test_rvp_single_component(self, model, n_butane):
        """Single component → property unchanged."""
        volumes = {"a": 100.0}
        props = {"a": n_butane}
        rvp = model.calculate_blend_property(
            volumes, props, "rvp", BlendMethod.POWER_LAW
        )
        assert abs(rvp - 51.6) < 0.01

    def test_rvp_equal_components(self, model):
        """Two components with same RVP → blend equals component."""
        volumes = {"a": 50.0, "b": 50.0}
        props = {
            "a": CutProperties(rvp=10.0),
            "b": CutProperties(rvp=10.0),
        }
        rvp = model.calculate_blend_property(
            volumes, props, "rvp", BlendMethod.POWER_LAW
        )
        assert abs(rvp - 10.0) < 0.01


# ---------------------------------------------------------------------------
# Sulfur blending — linear by weight
# ---------------------------------------------------------------------------


class TestSulfurByWeight:
    """Sulfur blends linearly on a weight basis (vol × spg)."""

    def test_sulfur_weight_basis(self, model):
        """Two equal-volume components with different SPG."""
        volumes = {"a": 50.0, "b": 50.0}
        props = {
            "a": CutProperties(sulfur=0.10, spg=0.80),  # heavier
            "b": CutProperties(sulfur=0.02, spg=0.60),  # lighter
        }
        sulfur = model.calculate_blend_property(
            volumes, props, "sulfur", BlendMethod.LINEAR_WEIGHT
        )

        # Manual: weight-weighted average
        wt_a = 50.0 * 0.80
        wt_b = 50.0 * 0.60
        expected = (wt_a * 0.10 + wt_b * 0.02) / (wt_a + wt_b)
        assert abs(sulfur - expected) < 1e-6

    def test_sulfur_differs_from_volume_blend(self, model):
        """Weight-blended sulfur differs from naive volume blend when SPGs differ."""
        volumes = {"heavy": 50.0, "light": 50.0}
        props = {
            "heavy": CutProperties(sulfur=0.30, spg=0.85),
            "light": CutProperties(sulfur=0.01, spg=0.60),
        }
        sulfur = model.calculate_blend_property(
            volumes, props, "sulfur", BlendMethod.LINEAR_WEIGHT
        )
        volume_blend = (50.0 * 0.30 + 50.0 * 0.01) / 100.0  # = 0.155
        # Heavy component has more weight, so sulfur should be ABOVE volume blend
        assert sulfur > volume_blend

    def test_sulfur_single_component(self, model, hcn):
        """Single component → sulfur unchanged."""
        volumes = {"a": 100.0}
        props = {"a": hcn}
        sulfur = model.calculate_blend_property(
            volumes, props, "sulfur", BlendMethod.LINEAR_WEIGHT
        )
        assert abs(sulfur - 0.30) < 1e-6


# ---------------------------------------------------------------------------
# Linear-by-volume properties (benzene, aromatics, olefins)
# ---------------------------------------------------------------------------


class TestLinearVolume:
    def test_benzene_linear_blend(self, model):
        volumes = {"a": 60.0, "b": 40.0}
        props = {
            "a": CutProperties(benzene=2.0),
            "b": CutProperties(benzene=0.5),
        }
        benzene = model.calculate_blend_property(
            volumes, props, "benzene", BlendMethod.LINEAR_VOLUME
        )
        expected = (60.0 * 2.0 + 40.0 * 0.5) / 100.0  # = 1.4
        assert abs(benzene - expected) < 1e-9

    def test_aromatics_linear_blend(self, model, reformate, lcn):
        volumes = {"reformate": 30.0, "lcn": 70.0}
        props = {"reformate": reformate, "lcn": lcn}
        aromatics = model.calculate_blend_property(
            volumes, props, "aromatics", BlendMethod.LINEAR_VOLUME
        )
        expected = (30.0 * 65.0 + 70.0 * 25.0) / 100.0  # = 37.0
        assert abs(aromatics - expected) < 1e-9


# ---------------------------------------------------------------------------
# Edge cases
# ---------------------------------------------------------------------------


class TestEdgeCases:
    def test_single_component_each_method(self, model, lcn):
        """Single-component blend returns the component value for every method."""
        volumes = {"a": 100.0}
        props = {"a": lcn}

        ron = model.calculate_blend_property(volumes, props, "ron", BlendMethod.INDEX)
        rvp = model.calculate_blend_property(volumes, props, "rvp", BlendMethod.POWER_LAW)
        sulfur = model.calculate_blend_property(
            volumes, props, "sulfur", BlendMethod.LINEAR_WEIGHT
        )
        benzene = model.calculate_blend_property(
            volumes, props, "benzene", BlendMethod.LINEAR_VOLUME
        )

        assert abs(ron - 92.0) < 1e-6
        assert abs(rvp - 10.5) < 1e-6
        assert abs(sulfur - 0.05) < 1e-6
        assert abs(benzene - 0.5) < 1e-9

    def test_zero_volumes(self, model, lcn):
        """All-zero volumes → 0.0 (no division by zero)."""
        volumes = {"a": 0.0, "b": 0.0}
        props = {"a": lcn, "b": lcn}
        for method in (
            BlendMethod.INDEX,
            BlendMethod.POWER_LAW,
            BlendMethod.LINEAR_WEIGHT,
            BlendMethod.LINEAR_VOLUME,
        ):
            val = model.calculate_blend_property(volumes, props, "ron", method)
            assert val == 0.0

    def test_unknown_method_raises(self, model, lcn):
        with pytest.raises(ValueError):
            model.calculate_blend_property(
                {"a": 100.0}, {"a": lcn}, "ron", "made_up_method"  # type: ignore[arg-type]
            )


# ---------------------------------------------------------------------------
# Spec checking
# ---------------------------------------------------------------------------


class TestSpecCheck:
    def test_spec_pass(self, model, gasoline_product):
        """Blend that meets all gasoline specs is feasible."""
        blend_props = {
            "road_octane": 89.0,
            "rvp": 12.5,
            "sulfur": 0.05,
            "benzene": 0.6,
            "aromatics": 30.0,
            "olefins": 12.0,
        }
        results = model.check_specs(blend_props, gasoline_product)
        assert len(results) == 6
        for r in results:
            assert r.feasible, f"Spec {r.spec_name} should pass: {r.value} vs {r.limit}"

    def test_spec_fail_sulfur(self, model, gasoline_product):
        """Blend that violates the sulfur spec."""
        blend_props = {
            "road_octane": 89.0,
            "rvp": 12.5,
            "sulfur": 0.25,  # exceeds 0.10 max
            "benzene": 0.6,
            "aromatics": 30.0,
            "olefins": 12.0,
        }
        results = model.check_specs(blend_props, gasoline_product)
        sulfur_result = next(r for r in results if r.spec_name == "sulfur")
        assert not sulfur_result.feasible
        assert sulfur_result.margin < 0  # negative margin = violation
        # Other specs should still be feasible
        for r in results:
            if r.spec_name != "sulfur":
                assert r.feasible

    def test_spec_fail_octane(self, model, gasoline_product):
        """Blend below the minimum octane spec."""
        blend_props = {
            "road_octane": 85.0,  # below 87 min
            "rvp": 12.5,
            "sulfur": 0.05,
            "benzene": 0.6,
            "aromatics": 30.0,
            "olefins": 12.0,
        }
        results = model.check_specs(blend_props, gasoline_product)
        octane = next(r for r in results if r.spec_name == "road_octane")
        assert not octane.feasible
        assert octane.margin < 0
        assert octane.value == 85.0
        assert octane.limit == 87.0

    def test_spec_margin_positive_when_feasible(self, model, gasoline_product):
        """Feasible specs have positive margin."""
        blend_props = {
            "road_octane": 90.0,  # 3.0 above min
            "rvp": 13.0,  # 1.0 below max
            "sulfur": 0.04,  # 0.06 below max
            "benzene": 0.5,
            "aromatics": 30.0,
            "olefins": 12.0,
        }
        results = model.check_specs(blend_props, gasoline_product)
        for r in results:
            assert r.margin > 0
            assert r.feasible
