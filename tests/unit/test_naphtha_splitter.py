"""Tests for NaphthaSplitterModel — Sprint 9 Task 9.0."""

from __future__ import annotations

import pytest

from eurekan.core.crude import CutProperties
from eurekan.models.naphtha_splitter import NaphthaSplitterModel


@pytest.fixture
def model() -> NaphthaSplitterModel:
    return NaphthaSplitterModel(default_cut_point_f=180.0)


@pytest.fixture
def naphtha_props() -> CutProperties:
    return CutProperties(api=65.0, sulfur=0.003, ron=55.0, aromatics=12.0, spg=0.70)


class TestSplitRatio:
    def test_default_split(self, model, naphtha_props):
        """At 180 deg F default, LN fraction should be ~35% of total naphtha."""
        r = model.calculate(25000.0, naphtha_props)
        ln_frac = r.ln_volume / 25000.0
        assert 0.25 <= ln_frac <= 0.55, f"LN fraction {ln_frac:.3f} outside range"

    def test_higher_cut_more_ln(self, model, naphtha_props):
        """Higher cut point → more goes to LN."""
        r_low = model.calculate(25000.0, naphtha_props, cut_point_f=150.0)
        r_high = model.calculate(25000.0, naphtha_props, cut_point_f=250.0)
        assert r_high.ln_volume > r_low.ln_volume


class TestPropertiesDiffer:
    def test_ln_lighter_than_hn(self, model, naphtha_props):
        r = model.calculate(25000.0, naphtha_props)
        assert r.ln_properties.api > r.hn_properties.api

    def test_ln_lower_sulfur(self, model, naphtha_props):
        r = model.calculate(25000.0, naphtha_props)
        assert r.ln_properties.sulfur < r.hn_properties.sulfur

    def test_hn_has_low_ron(self, model, naphtha_props):
        """HN straight-run has very low RON — needs reformer."""
        r = model.calculate(25000.0, naphtha_props)
        assert r.hn_properties.ron < 50


class TestMassBalance:
    def test_volumes_sum(self, model, naphtha_props):
        r = model.calculate(25000.0, naphtha_props)
        assert abs(r.ln_volume + r.hn_volume - 25000.0) < 0.01

    def test_cut_point_stored(self, model, naphtha_props):
        r = model.calculate(25000.0, naphtha_props, cut_point_f=200.0)
        assert r.cut_point_f == 200.0


class TestCutPointVariation:
    def test_sweep(self, model, naphtha_props):
        """LN fraction should increase monotonically with cut point."""
        prev_ln = 0.0
        for cp in [100, 150, 200, 250, 300]:
            r = model.calculate(25000.0, naphtha_props, cut_point_f=float(cp))
            assert r.ln_volume >= prev_ln
            prev_ln = r.ln_volume


class TestHNSuitableForReformer:
    def test_hn_ron_below_50(self, model, naphtha_props):
        """HN RON should be low enough that reforming is necessary."""
        r = model.calculate(25000.0, naphtha_props)
        assert r.hn_properties.ron < 50

    def test_hn_has_aromatics(self, model, naphtha_props):
        r = model.calculate(25000.0, naphtha_props)
        assert r.hn_properties.aromatics is not None
