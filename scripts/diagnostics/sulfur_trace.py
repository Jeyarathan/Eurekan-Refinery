"""Sulfur trace diagnostic — Sprint A.1 / Task 2.

Reports, for the current optimum of the Gulf Coast workbook, the full
sulfur balance from crude assay through CDU cuts, HDTs, FCC, Coker,
and finished products. Highlights the residual (where S is disappearing).

Run:
    .venv/Scripts/python.exe scripts/diagnostics/sulfur_trace.py
"""

from __future__ import annotations

import sys
from typing import Any

import pyomo.environ as pyo

from eurekan.core.enums import OperatingMode
from eurekan.core.period import PeriodData, PlanDefinition
from eurekan.optimization.builder import (
    _BLEND_COMPONENT_PROPS,
    _COKER_H2S_LT_PER_BBL,
    _FCC_H2S_LT_PER_BBL,
    _HT_H2S_LT_PER_BBL,
    _S_PER_H2S,
    PyomoModelBuilder,
)
from eurekan.optimization.solver import EurekanSolver
from eurekan.parsers.gulf_coast import GulfCoastParser

# 1 bbl crude mass (LT) computed from specific gravity.  1 bbl = 0.159 m³,
# water = 1000 kg/m³, 1 LT = 1016.047 kg (long ton).
BBL_VOLUME_M3 = 0.158987
WATER_KG_PER_M3 = 1000.0
KG_PER_LT = 1016.047


def _api_to_spg(api: float) -> float:
    """API gravity → specific gravity at 60°F."""
    return 141.5 / (api + 131.5)


def _bbl_to_lt_mass(bbl: float, api: float | None) -> float:
    """Convert volumetric bbl to LT mass given API gravity."""
    spg = _api_to_spg(api if api else 30.0)
    kg = bbl * BBL_VOLUME_M3 * WATER_KG_PER_M3 * spg
    return kg / KG_PER_LT


def _safe_val(v: Any) -> float:
    try:
        out = pyo.value(v)
        return float(out) if out is not None else 0.0
    except Exception:
        return 0.0


def _has(m, name: str) -> bool:
    return hasattr(m, name)


def _v(m, name: str, *idx) -> float:
    if not _has(m, name):
        return 0.0
    try:
        return _safe_val(getattr(m, name)[idx] if len(idx) > 1 else getattr(m, name)[idx[0]])
    except Exception:
        return 0.0


def _hline(title: str) -> None:
    print()
    print("=" * 78)
    print(title)
    print("=" * 78)


def main() -> int:
    config = GulfCoastParser("data/gulf_coast/Gulf_Coast.xlsx").parse()
    plan = PlanDefinition(
        periods=[PeriodData(period_id=0, duration_hours=24.0)],
        mode=OperatingMode.OPTIMIZE,
        scenario_name="Sprint A.1 sulfur trace",
    )

    builder = PyomoModelBuilder(config, plan)
    model = builder.build()
    EurekanSolver().solve_with_fallback(model, config, plan)
    p = 0

    # ---------------------------------------------------------------
    # (a) Crude S input
    # ---------------------------------------------------------------
    _hline("(a) Crude S input — computed from assay data")
    print(f"  {'crude':8s} {'bbl/D':>10s} {'API':>6s} {'SPG':>6s} "
          f"{'LT/D':>10s} {'S wt%':>7s} {'LT S/D':>10s}")
    s_crude_total = 0.0
    mass_crude_total = 0.0
    active_crudes: list[str] = []
    for cid in sorted(model.CRUDES):
        rate = _v(model, "crude_rate", cid, p)
        if rate < 1e-6:
            continue
        active_crudes.append(cid)
        assay = config.crude_library.get(cid)
        api = assay.api or 30.0
        sulfur_wt = assay.sulfur or 0.0
        spg = _api_to_spg(api)
        mass_lt = _bbl_to_lt_mass(rate, api)
        s_lt = mass_lt * (sulfur_wt / 100.0)
        s_crude_total += s_lt
        mass_crude_total += mass_lt
        print(f"  {cid:8s} {rate:10.1f} {api:6.2f} {spg:6.4f} "
              f"{mass_lt:10.2f} {sulfur_wt:7.3f} {s_lt:10.3f}")
    print("-" * 78)
    print(f"  {'TOTAL':8s} {'':>10s} {'':>6s} {'':>6s} "
          f"{mass_crude_total:10.2f} {'':>7s} {s_crude_total:10.3f}")
    print(f"\n  S_CRUDE_TOTAL = {s_crude_total:.3f} LT/D")

    # ---------------------------------------------------------------
    # (b) CDU outlet S distribution
    # ---------------------------------------------------------------
    _hline("(b) CDU outlet S distribution — volumetric cuts × assay S wt%")
    # We don't have a Pyomo variable for per-cut sulfur mass — compute it
    # by replaying CDUModel logic on the solved crude slate.
    cut_vol: dict[str, float] = {}
    cut_s: dict[str, float] = {}
    for cid in active_crudes:
        rate = _v(model, "crude_rate", cid, p)
        assay = config.crude_library.get(cid)
        for cut in assay.cuts:
            vol = rate * cut.vol_yield
            cut_vol[cut.name] = cut_vol.get(cut.name, 0.0) + vol
            s_wt = cut.properties.sulfur if cut.properties else None
            if s_wt is None:
                s_wt = 0.0
            cut_mass_lt = _bbl_to_lt_mass(vol, cut.properties.api or assay.api)
            cut_s[cut.name] = cut_s.get(cut.name, 0.0) + cut_mass_lt * (s_wt / 100.0)

    print(f"  {'cut':18s} {'bbl/D':>10s} {'S wt%':>7s} {'LT S/D':>10s}")
    total_cdu_s = 0.0
    for k in ("lpg", "light_naphtha", "heavy_naphtha", "kerosene",
              "diesel", "vgo", "vacuum_residue"):
        vol = cut_vol.get(k, 0.0)
        s = cut_s.get(k, 0.0)
        total_cdu_s += s
        s_wt = (s / _bbl_to_lt_mass(vol, 30.0) * 100.0) if vol > 0 else 0.0
        print(f"  {k:18s} {vol:10.1f} {s_wt:7.3f} {s:10.3f}")
    print("-" * 78)
    print(f"  {'CDU cuts total':18s} {'':>10s} {'':>7s} {total_cdu_s:10.3f}")
    print(f"\n  CDU outlet  = {total_cdu_s:.3f} LT S/D   "
          f"(crude input = {s_crude_total:.3f})   "
          f"delta = {total_cdu_s - s_crude_total:+.3f}")

    # ---------------------------------------------------------------
    # (c) HDT removal — per unit reported S removed as H2S
    # ---------------------------------------------------------------
    _hline("(c) HDT S accounting")
    ht_units = []
    # Hydrotreaters in this model: NHT (naphtha) is implicit; Kero HT (KHT);
    # Diesel HT (DHT) for diesel+LCO+coker_GO; VGO HT (GOHT); Coker naphtha
    # HT; Hydrocracker (HCU).  For each, print volumetric feed and the
    # H2S mass generated by the builder's constant coefficient.
    feeds: list[tuple[str, str, float]] = []
    if builder.has_kht:
        feeds.append(("KHT (kerosene)", "kero_to_kht", _v(model, "kero_to_kht", p)))
    if builder.has_dht:
        d = _v(model, "diesel_to_dht", p) + _v(model, "lco_to_dht", p)
        if builder.has_coker:
            d += _v(model, "coker_go_to_dht", p)
        feeds.append(("DHT (diesel+LCO+coker-GO)", "dht_total", d))
    if builder.has_goht:
        feeds.append(("GOHT (VGO)", "vgo_to_goht", _v(model, "vgo_to_goht", p)))
    if builder.has_scanfiner:
        feeds.append(("Scanfiner (HCN)", "hcn_to_scanfiner", _v(model, "hcn_to_scanfiner", p)))
    if builder.has_coker:
        feeds.append(("Coker NHT (coker naphtha)", "coker_naphtha_vol", _v(model, "coker_naphtha_vol", p)))
    if builder.has_hcu:
        feeds.append(("HCU (VGO)", "vgo_to_hcu", _v(model, "vgo_to_hcu", p)))

    print(f"  {'unit':32s} {'feed bbl/D':>12s} {'H2S LT/D':>10s} {'S-eq LT/D':>10s}")
    total_ht_h2s = 0.0
    total_ht_s_eq = 0.0
    for label, _tag, feed in feeds:
        h2s = feed * _HT_H2S_LT_PER_BBL
        s_eq = h2s * _S_PER_H2S
        total_ht_h2s += h2s
        total_ht_s_eq += s_eq
        print(f"  {label:32s} {feed:12.1f} {h2s:10.4f} {s_eq:10.4f}")
    print("-" * 78)
    print(f"  {'HT total':32s} {'':>12s} {total_ht_h2s:10.4f} {total_ht_s_eq:10.4f}")
    print("\n  NOTE: these H2S flows are builder constants (_HT_H2S_LT_PER_BBL "
          f"= {_HT_H2S_LT_PER_BBL:.1e} LT H2S / bbl feed), independent of "
          "actual feed sulfur content.")

    # ---------------------------------------------------------------
    # (d) FCC + Coker
    # ---------------------------------------------------------------
    _hline("(d) FCC + Coker S accounting")
    fcc_feed = _v(model, "vgo_to_fcc", p)
    fcc_h2s = fcc_feed * _FCC_H2S_LT_PER_BBL
    fcc_s_eq = fcc_h2s * _S_PER_H2S
    print(f"  FCC   feed = {fcc_feed:10.1f} bbl/D  -> H2S = {fcc_h2s:.4f} LT/D  "
          f"(S-eq = {fcc_s_eq:.4f})")
    if builder.has_coker:
        coker_feed = _v(model, "coker_feed", p)
        coker_h2s = coker_feed * _COKER_H2S_LT_PER_BBL
        coker_s_eq = coker_h2s * _S_PER_H2S
        print(f"  Coker feed = {coker_feed:10.1f} bbl/D  -> H2S = {coker_h2s:.4f} LT/D  "
              f"(S-eq = {coker_s_eq:.4f})")
    else:
        coker_feed = 0.0; coker_h2s = 0.0; coker_s_eq = 0.0

    # Compute the S that the FCC LCN/HCN and Coker naphtha properties
    # carry into the mogas blend, plus LCO to diesel/fuel oil pools.
    print(f"\n  FCC LCN vol = {_v(model, 'fcc_lcn_vol', p):10.1f} bbl/D  "
          f"blend S wt% = {_BLEND_COMPONENT_PROPS['fcc_lcn']['sulfur']:.3f}")
    print(f"  FCC HCN vol = {_v(model, 'fcc_hcn_vol', p):10.1f} bbl/D  "
          f"blend S wt% = {_BLEND_COMPONENT_PROPS['fcc_hcn']['sulfur']:.3f}")
    print(f"  FCC LCO vol = {_v(model, 'fcc_lco_vol', p):10.1f} bbl/D  "
          "(goes to diesel / fuel oil pools)")

    # ---------------------------------------------------------------
    # (e) Terminal S sinks
    # ---------------------------------------------------------------
    _hline("(e) Terminal S sinks")
    sulfur_sales = _v(model, "sulfur_sales", p)
    sulfur_produced = _v(model, "sulfur_produced", p)
    s_to_stack = _v(model, "s_to_stack", p)
    amine_slip = _v(model, "amine_slip", p)
    amine_slip_s = amine_slip * _S_PER_H2S
    print(f"  SUP product sold (sulfur_sales):     {sulfur_sales:10.4f} LT/D")
    print(f"  SRU stack emissions (s_to_stack):    {s_to_stack:10.4f} LT/D")
    print(f"  Amine slip to fuel gas (S eq.):      {amine_slip_s:10.4f} LT/D")

    # Gasoline blend S (wt basis)
    gasoline_vol = _v(model, "gasoline_sales", p)
    # Gasoline sulfur is tracked as wt% ratio through sulfur_spec.
    # Approximate finished-gasoline sulfur mass from the pool constituents.
    # (Exact number comes from wt_sulfur / wt_total at the sulfur_spec
    # constraint — here we just print the blend S ceiling.)
    mogas_s_ceiling_wt = 0.10  # max allowable per spec
    # approximate gasoline mass LT/D
    gasoline_mass_lt = _bbl_to_lt_mass(gasoline_vol, 60.0)
    gasoline_s_max = gasoline_mass_lt * (mogas_s_ceiling_wt / 100.0)
    print(f"  Gasoline sold:     {gasoline_vol:10.1f} bbl/D  "
          f"(S <= {gasoline_s_max:.3f} LT/D at {mogas_s_ceiling_wt}% cap)")

    # Diesel, jet, fuel oil: no explicit S mass tracking on those pools.
    for pname in ("diesel_sales", "jet_sales", "fuel_oil_sales", "naphtha_sales", "lpg_sales"):
        v = _v(model, pname, p)
        if v > 0:
            print(f"  {pname:18s} = {v:10.1f} bbl/D  (S not tracked on this pool)")

    # ---------------------------------------------------------------
    # (f) Leak check
    # ---------------------------------------------------------------
    _hline("(f) LEAK CHECK - crude S vs terminal sinks")
    products_s_lt = _v(model, "products_s_lt", p)
    tracked_s_out = (
        sulfur_sales          # to SUP
        + s_to_stack          # stack
        + amine_slip_s        # amine slip to fuel gas
        + products_s_lt       # finished-products bucket (Sprint A.1)
    )
    residual = s_crude_total - tracked_s_out
    pct = (residual / s_crude_total * 100.0) if s_crude_total > 0 else float("nan")
    print(f"  S_CRUDE_TOTAL         = {s_crude_total:10.3f} LT/D")
    print(f"  tracked terminal out  = {tracked_s_out:10.3f} LT/D")
    print(f"    + SUP sales         = {sulfur_sales:10.3f}")
    print(f"    + SRU stack         = {s_to_stack:10.3f}")
    print(f"    + amine slip        = {amine_slip_s:10.3f}")
    print(f"    + products_s_lt     = {products_s_lt:10.3f}  (finished-product S bucket)")
    print(f"  RESIDUAL              = {residual:10.3f} LT/D  ({pct:+.2f}% of crude S)")

    print()
    print("=" * 78)
    print("INTERPRETATION")
    print("=" * 78)
    if abs(pct) < 1.0:
        print(
            "  Balance closes.  Crude-assay S is fully accounted: "
            f"{sulfur_sales:.1f} LT/D exits as merchant sulfur, "
            f"{products_s_lt:.1f} LT/D remains in\n"
            "  finished liquid/solid products (diesel, jet, fuel oil, coke, gasoline,\n"
            "  naphtha, LPG).  The LP now uses assay-driven cut S coefficients rather\n"
            "  than flat volumetric constants, so sulfur complex loading responds to\n"
            "  the active crude slate."
        )
    else:
        print(
            "  Residual > 1%.  Either the crude_s_closure_con constraint is missing\n"
            "  or there is a new accounting path that is not yet routed into it.\n"
            "  Re-check the builder."
        )
    return 0


if __name__ == "__main__":
    sys.exit(main())
