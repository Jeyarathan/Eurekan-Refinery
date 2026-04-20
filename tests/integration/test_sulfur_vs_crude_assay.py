"""Sprint A.1 / Task 5 — crude-assay-basis sulfur integrity test.

The Sprint A mass-balance test (``tests/unit/test_sulfur_balance.py``) is
necessary but not sufficient: it balances the H2S inventory the LP already
tracks, regardless of whether that inventory reflects real feed sulfur.

This integration test enforces the real invariant: **the sulfur accounted
for in the solved LP must match the sulfur entering with the crude feed,
computed independently from crude-assay data.** If the LP silently drops
crude S anywhere (e.g. liquid products with untracked S), this test fails.
"""

from __future__ import annotations

import pyomo.environ as pyo
import pytest

from eurekan.core.enums import OperatingMode
from eurekan.core.period import PeriodData, PlanDefinition
from eurekan.optimization.builder import PyomoModelBuilder, _S_PER_H2S
from eurekan.optimization.solver import EurekanSolver
from eurekan.parsers.gulf_coast import GulfCoastParser


# Conversion constants — do not depend on the LP's internal S accounting.
_BBL_M3 = 0.158987
_WATER_KG_M3 = 1000.0
_KG_PER_LT = 1016.047


def _api_to_spg(api: float) -> float:
    return 141.5 / (api + 131.5)


def _bbl_to_lt_mass(bbl: float, api: float) -> float:
    return bbl * _BBL_M3 * _WATER_KG_M3 * _api_to_spg(api) / _KG_PER_LT


def _crude_s_lt_per_day(config, model, p: int = 0) -> float:
    """Total LT/D of elemental S entering CDU, from crude assay data."""
    total = 0.0
    for cid in model.CRUDES:
        rate = pyo.value(model.crude_rate[cid, p])
        if rate is None or rate < 1e-9:
            continue
        assay = config.crude_library.get(cid)
        api = assay.api or 30.0
        s_wt = (assay.sulfur or 0.0) / 100.0
        total += _bbl_to_lt_mass(rate, api) * s_wt
    return total


def _lp_tracked_s_out_lt_per_day(model, p: int = 0) -> float:
    """S leaving the LP through all terminal sinks, per solved model.

    This aggregates every stream the builder mass-tracks as elemental S
    or H2S-equivalent S. If the builder silently drops crude S at any
    unit, the sum here will be less than the crude input.
    """
    def v(name: str) -> float:
        if not hasattr(model, name):
            return 0.0
        try:
            return float(pyo.value(getattr(model, name)[p]))
        except Exception:
            return 0.0

    sulfur_sales = v("sulfur_sales")
    s_to_stack = v("s_to_stack")
    amine_slip_s = v("amine_slip") * _S_PER_H2S
    # Remaining S that leaves with finished liquid / solid products —
    # must be explicitly tracked by the builder on a per-pool basis.
    # These variable names are introduced in the Task 4 fix.
    product_s = (
        v("gasoline_s_lt")
        + v("diesel_s_lt")
        + v("jet_s_lt")
        + v("fuel_oil_s_lt")
        + v("naphtha_s_lt")
        + v("lpg_s_lt")
        + v("coke_s_lt")
    )
    return sulfur_sales + s_to_stack + amine_slip_s + product_s


@pytest.fixture(scope="module")
def solved_gulf_coast():
    config = GulfCoastParser("data/gulf_coast/Gulf_Coast.xlsx").parse()
    plan = PlanDefinition(
        periods=[PeriodData(period_id=0, duration_hours=24.0)],
        mode=OperatingMode.OPTIMIZE,
        scenario_name="crude-assay S integrity",
    )
    builder = PyomoModelBuilder(config, plan)
    model = builder.build()
    EurekanSolver().solve_with_fallback(model, config, plan)
    return config, model


class TestCrudeSulfurIntegrity:
    def test_tracked_s_matches_crude_assay_within_1pct(self, solved_gulf_coast):
        """Sum of LP terminal S sinks must equal crude-assay S within 1%.

        Red on sprint-a1 branch head before Task 4; green after the fix.
        """
        config, model = solved_gulf_coast
        s_crude = _crude_s_lt_per_day(config, model)
        assert s_crude > 50.0, (
            "Active slate is expected to be heavy/sour (>50 LT/D crude S). "
            f"Got {s_crude:.3f} — did the optimizer pick a sweet slate?"
        )
        s_tracked = _lp_tracked_s_out_lt_per_day(model)
        residual = s_crude - s_tracked
        pct = abs(residual) / s_crude
        assert pct < 0.01, (
            f"Crude S ({s_crude:.2f} LT/D) vs tracked terminal S "
            f"({s_tracked:.2f} LT/D) differ by {residual:+.2f} LT/D "
            f"({pct*100:.1f}% of crude S). The LP is dropping crude "
            "sulfur at a process unit without accounting for it."
        )

    def test_sru_sulfur_scales_with_crude_s(self, solved_gulf_coast):
        """SRU elemental sulfur output must scale with crude S input.

        With ~300 LT/D of crude S, the SRU should produce order-100 LT/D
        sulfur (fraction that routes to H2S vs stays in liquid products).
        A post-fix SRU output of ~1 LT/D on a heavy-sour slate would mean
        H2S generation is not wired to crude S — the original leak.
        """
        _, model = solved_gulf_coast
        sulfur_produced = float(pyo.value(model.sulfur_produced[0]))
        # Should be at least 10 LT/D on a heavy-sour slate — well above
        # the pre-fix phantom value of ~0.9 LT/D.
        assert sulfur_produced >= 10.0, (
            f"SRU produced only {sulfur_produced:.3f} LT/D elemental S on a "
            "heavy-sour slate. H2S generation is not scaling with crude "
            "feed sulfur."
        )
