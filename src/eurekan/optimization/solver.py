"""Three-tier NLP solver with automatic warm-starting.

  Tier 1 — Heuristic warm-start (always tried first):
    Equal crude split, 80% conversion, proportional blend, dispositions
    routed to highest-value destination.

  Tier 2 — LP relaxation (if Tier 1 fails):
    Discretized FCC into 5 conversion modes; pre-computed yields per mode;
    HiGHS solves the LP in milliseconds; LP solution becomes the NLP start.

  Tier 3 — Multi-start (if Tier 2 fails):
    5 perturbed starts; the best feasible result wins.
"""

from __future__ import annotations

import os
import random
import sys
import time
from typing import Any, Optional

import pyomo.environ as pyo
from pydantic import BaseModel

from eurekan.core.config import RefineryConfig
from eurekan.core.period import PlanDefinition
from eurekan.optimization.builder import (
    _BLEND_COMPONENT_PROPS,
    _DEFAULT_FCC_FEED_API,
    _DEFAULT_FCC_FEED_CCR,
    _DEFAULT_FCC_FEED_METALS,
    _LCN_FRACTION,
    _NC4_FRACTION_OF_LPG,
    PyomoModelBuilder,
)


# ---------------------------------------------------------------------------
# Result model
# ---------------------------------------------------------------------------


class SolveResult(BaseModel):
    """Outcome of a solve attempt."""

    status: str  # "optimal", "infeasible", "error", "unknown"
    objective_value: float = 0.0
    solve_time: float = 0.0
    tier_used: int = 0  # 1, 2, or 3
    iterations: int = 0
    message: str = ""

    @property
    def feasible(self) -> bool:
        return self.status == "optimal"


# ---------------------------------------------------------------------------
# Helpers — locate IPOPT and compute FCC yields at fixed conversion
# ---------------------------------------------------------------------------


def _find_ipopt() -> pyo.SolverFactory:
    """Locate IPOPT, preferring the venv Scripts directory on Windows."""
    ipopt_path = os.path.join(sys.prefix, "Scripts", "ipopt.exe")
    if os.path.exists(ipopt_path):
        solver = pyo.SolverFactory("ipopt", executable=ipopt_path)
    else:
        solver = pyo.SolverFactory("ipopt")
    return solver


def _fcc_yields_at(conversion: float) -> dict[str, float]:
    """Return per-bbl FCC yields at a fixed conversion (default feed)."""
    c = conversion / 100.0
    api = _DEFAULT_FCC_FEED_API
    ccr = _DEFAULT_FCC_FEED_CCR
    metals = _DEFAULT_FCC_FEED_METALS

    gasoline = -0.0833 + 1.3364 * c - 0.7744 * c * c + 0.0024 * (api - 22) - 0.0118 * (ccr - 1)
    lco = 0.37 - 0.2593 * c + 0.0031 * (api - 22)
    coke = 0.040 + 1.1 * ccr / 100.0 + 0.001 * (c * 100.0 - 75) + 0.0002 * metals
    remaining = max(1.0 - gasoline - lco - coke, 0.0)
    return {
        "lcn": gasoline * _LCN_FRACTION,
        "hcn": gasoline * (1.0 - _LCN_FRACTION),
        "lco": lco,
        "coke": coke,
        "c3": 0.30 * remaining,
        "c4": 0.30 * remaining,
        "regen_temp": 1100.0 + 3800.0 * coke,
    }


# ---------------------------------------------------------------------------
# EurekanSolver
# ---------------------------------------------------------------------------


class EurekanSolver:
    """Three-tier IPOPT solver with automatic initialization."""

    LP_FCC_MODES: list[float] = [72.0, 76.0, 80.0, 84.0, 88.0]

    def __init__(self) -> None:
        self._ipopt = _find_ipopt()
        self._highs = pyo.SolverFactory("appsi_highs")

    # ------------------------------------------------------------------
    # Tier 1 — Heuristic warm-start
    # ------------------------------------------------------------------

    @staticmethod
    def _set_if_free(var: Any, value: float) -> None:
        """Set a variable's value, but only if it isn't already fixed."""
        if not var.fixed:
            var.set_value(value)

    def generate_heuristic_start(
        self,
        model: pyo.ConcreteModel,
        config: RefineryConfig,
        plan: PlanDefinition,
    ) -> None:
        """Set initial values on every Pyomo variable to a feasible point.

        Variables that are already fixed (e.g. by hybrid mode) are left alone.
        """
        cdu_cap = config.units["cdu_1"].capacity if "cdu_1" in config.units else 80000.0
        fcc_cap = config.units["fcc_1"].capacity if "fcc_1" in config.units else 50000.0

        crude_ids = list(model.CRUDES)
        n_crudes = len(crude_ids)
        if n_crudes == 0:
            return

        per_crude = cdu_cap / n_crudes
        # Cap individual crude rates by their max_rate
        crude_rates: dict[str, float] = {}
        for cid in crude_ids:
            assay = config.crude_library.get(cid)
            max_rate = assay.max_rate if assay and assay.max_rate else cdu_cap
            crude_rates[cid] = min(per_crude, max_rate)

        # Cache yields by crude
        yields_by_crude: dict[str, dict[str, float]] = {}
        for cid in crude_ids:
            assay = config.crude_library.get(cid)
            if assay is None:
                continue
            yields_by_crude[cid] = {c.name: c.vol_yield for c in assay.cuts}

        def cut_volume(cut_name: str) -> float:
            return sum(
                crude_rates[cid] * yields_by_crude.get(cid, {}).get(cut_name, 0.0)
                for cid in crude_ids
            )

        for p in model.PERIODS:
            # Crude rates
            for cid in crude_ids:
                self._set_if_free(model.crude_rate[cid, p], crude_rates[cid])

            # FCC operating point — use fixed conversion if present, else 80%
            self._set_if_free(model.fcc_conversion[p], 80.0)
            current_conversion = pyo.value(model.fcc_conversion[p])

            vgo_avail = cut_volume("vgo")
            vgo_to_fcc_val = min(vgo_avail, fcc_cap)
            self._set_if_free(model.vgo_to_fcc[p], vgo_to_fcc_val)
            self._set_if_free(model.vgo_to_fo[p], max(vgo_avail - vgo_to_fcc_val, 0.0))

            # CDU disposition: route everything to the higher-value destination
            ln_avail = cut_volume("light_naphtha")
            self._set_if_free(model.ln_to_blend[p], ln_avail)
            self._set_if_free(model.ln_to_sell[p], 0.0)

            hn_avail = cut_volume("heavy_naphtha")
            self._set_if_free(model.hn_to_blend[p], hn_avail)
            self._set_if_free(model.hn_to_sell[p], 0.0)

            kero_avail = cut_volume("kerosene")
            self._set_if_free(model.kero_to_jet[p], kero_avail)
            self._set_if_free(model.kero_to_diesel[p], 0.0)

            # NC4 — half to blend, half to LPG
            nc4_avail = _NC4_FRACTION_OF_LPG * cut_volume("lpg")
            self._set_if_free(model.nc4_to_blend[p], nc4_avail * 0.5)
            self._set_if_free(model.nc4_to_lpg[p], nc4_avail * 0.5)

            # FCC product volumes (computed from yields × vgo_to_fcc)
            yields = _fcc_yields_at(current_conversion)
            actual_vgo = pyo.value(model.vgo_to_fcc[p])
            lcn_vol = actual_vgo * yields["lcn"]
            hcn_vol = actual_vgo * yields["hcn"]
            lco_vol = actual_vgo * yields["lco"]
            coke_vol = actual_vgo * yields["coke"]
            c3_vol = actual_vgo * yields["c3"]
            c4_vol = actual_vgo * yields["c4"]

            self._set_if_free(model.fcc_lcn_vol[p], lcn_vol)
            self._set_if_free(model.fcc_hcn_vol[p], hcn_vol)
            self._set_if_free(model.fcc_lco_vol[p], lco_vol)
            self._set_if_free(model.fcc_coke_vol[p], coke_vol)
            self._set_if_free(model.fcc_c3_vol[p], c3_vol)
            self._set_if_free(model.fcc_c4_vol[p], c4_vol)

            # FCC HCN: split between blend and fuel oil
            self._set_if_free(model.hcn_to_blend[p], hcn_vol * 0.5)
            self._set_if_free(model.hcn_to_fo[p], hcn_vol * 0.5)

            # LCO: route to diesel (higher value than fuel oil)
            self._set_if_free(model.lco_to_diesel[p], lco_vol)
            self._set_if_free(model.lco_to_fo[p], 0.0)

            # Reformate: from reformer if present, otherwise purchased
            reformer_output = 0.0
            if hasattr(model, "hn_to_reformer"):
                hn_ref = hn_avail * 0.5
                self._set_if_free(model.hn_to_reformer[p], hn_ref)
                self._set_if_free(model.reformer_severity[p], 98.0)
                ref_yield = 0.95 - 0.0125 * (98 - 90)
                reformer_output = hn_ref * ref_yield
                self._set_if_free(model.reformate_from_reformer[p], reformer_output)
                self._set_if_free(model.reformer_hydrogen[p], hn_ref * 0.038)
                self._set_if_free(model.reformer_lpg[p], hn_ref * 0.01)
                hn_avail *= 0.5  # remaining HN for blend/sell

            self._set_if_free(model.reformate_purchased[p], 2000.0)

            # Product volumes
            gasoline = (
                ln_avail + hn_avail + lcn_vol + hcn_vol * 0.5 + nc4_avail * 0.5
                + 2000.0 + reformer_output
            )
            naphtha = 0.0
            jet = kero_avail
            diesel = cut_volume("diesel") + lco_vol
            fuel_oil = (
                max(vgo_avail - vgo_to_fcc_val, 0.0)
                + hcn_vol * 0.5
                + cut_volume("vacuum_residue")
            )
            lpg = (
                (1.0 - _NC4_FRACTION_OF_LPG) * cut_volume("lpg")
                + nc4_avail * 0.5
                + c3_vol
                + c4_vol
            )

            self._set_if_free(model.gasoline_volume[p], gasoline)
            self._set_if_free(model.naphtha_volume[p], naphtha)
            self._set_if_free(model.jet_volume[p], jet)
            self._set_if_free(model.diesel_volume[p], diesel)
            self._set_if_free(model.fuel_oil_volume[p], fuel_oil)
            self._set_if_free(model.lpg_volume[p], lpg)

            # Sales = production at the heuristic start (no inventory build)
            self._set_if_free(model.gasoline_sales[p], gasoline)
            self._set_if_free(model.naphtha_sales[p], naphtha)
            self._set_if_free(model.jet_sales[p], jet)
            self._set_if_free(model.diesel_sales[p], diesel)
            self._set_if_free(model.fuel_oil_sales[p], fuel_oil)
            self._set_if_free(model.lpg_sales[p], lpg)

            # Inventory: leave at zero (which is the default initial value).
            # The solver will compute optimal inventory levels.

    # ------------------------------------------------------------------
    # Tier 2 — LP relaxation warm-start
    # ------------------------------------------------------------------

    def generate_lp_start(
        self,
        model: pyo.ConcreteModel,
        config: RefineryConfig,
        plan: PlanDefinition,
    ) -> None:
        """Solve a discretized LP and copy its solution into the NLP model."""
        lp_model = self._build_lp_relaxation(config, plan)
        try:
            self._highs.solve(lp_model, tee=False)
        except Exception:
            # LP failure → fall back to heuristic
            self.generate_heuristic_start(model, config, plan)
            return

        # Copy LP solution into NLP variables (respecting any already-fixed vars)
        crude_ids = list(model.CRUDES)
        for p in model.PERIODS:
            for cid in crude_ids:
                self._set_if_free(model.crude_rate[cid, p], pyo.value(lp_model.crude_rate[cid, p]))

            # FCC mode → effective conversion (convex combination of mode anchors)
            mode_select = [pyo.value(lp_model.fcc_mode[p, m]) for m in range(len(self.LP_FCC_MODES))]
            total_mode = sum(mode_select)
            if total_mode > 1e-9:
                eff_conv = sum(self.LP_FCC_MODES[i] * mode_select[i] for i in range(len(mode_select))) / total_mode
            else:
                eff_conv = 80.0
            self._set_if_free(model.fcc_conversion[p], eff_conv)

            vgo_to_fcc_val = pyo.value(lp_model.vgo_to_fcc[p])
            self._set_if_free(model.vgo_to_fcc[p], vgo_to_fcc_val)
            self._set_if_free(model.vgo_to_fo[p], pyo.value(lp_model.vgo_to_fo[p]))

            # FCC outputs from the LP modes
            yields = _fcc_yields_at(eff_conv)
            for key, attr in [
                ("lcn", "fcc_lcn_vol"),
                ("hcn", "fcc_hcn_vol"),
                ("lco", "fcc_lco_vol"),
                ("coke", "fcc_coke_vol"),
                ("c3", "fcc_c3_vol"),
                ("c4", "fcc_c4_vol"),
            ]:
                self._set_if_free(getattr(model, attr)[p], vgo_to_fcc_val * yields[key])

            # Dispositions
            for var_name in [
                "ln_to_blend", "ln_to_sell",
                "hn_to_blend", "hn_to_sell",
                "hcn_to_blend", "hcn_to_fo",
                "lco_to_diesel", "lco_to_fo",
                "kero_to_jet", "kero_to_diesel",
                "nc4_to_blend", "nc4_to_lpg",
                "reformate_purchased",
            ]:
                lp_var = getattr(lp_model, var_name)
                self._set_if_free(getattr(model, var_name)[p], pyo.value(lp_var[p]))

            # Product volumes (also seed sales = production at warm-start)
            for prod in ("gasoline", "naphtha", "jet", "diesel", "fuel_oil", "lpg"):
                lp_var = getattr(lp_model, f"{prod}_volume")
                val = pyo.value(lp_var[p])
                getattr(model, f"{prod}_volume")[p].set_value(val)
                sales_var = getattr(model, f"{prod}_sales", None)
                if sales_var is not None:
                    sales_var[p].set_value(val)

    def _build_lp_relaxation(
        self, config: RefineryConfig, plan: PlanDefinition
    ) -> pyo.ConcreteModel:
        """Build an LP version of the planning model with discretized FCC modes."""
        m = pyo.ConcreteModel(name="EurekanRefinery_LP")
        modes = list(range(len(self.LP_FCC_MODES)))
        m.PERIODS = pyo.Set(initialize=list(range(len(plan.periods))))
        m.CRUDES = pyo.Set(initialize=config.crude_library.list_crudes())
        m.MODES = pyo.Set(initialize=modes)

        cdu_cap = config.units["cdu_1"].capacity if "cdu_1" in config.units else 80000.0
        fcc_cap = config.units["fcc_1"].capacity if "fcc_1" in config.units else 50000.0

        # Pre-compute FCC yields for each mode
        mode_yields = [_fcc_yields_at(c) for c in self.LP_FCC_MODES]
        regen_limit = (
            config.units["fcc_1"].equipment_limits.get("fcc_regen_temp_max", 1400.0)
            if "fcc_1" in config.units
            else 1400.0
        )

        # Crude rates with bounds
        def crude_bounds(_m: Any, c: str, p: int) -> tuple[float, float]:
            assay = config.crude_library.get(c)
            return (0.0, assay.max_rate if assay and assay.max_rate else cdu_cap)

        m.crude_rate = pyo.Var(m.CRUDES, m.PERIODS, bounds=crude_bounds, initialize=0.0)

        # FCC mode selection (convex combination), and aggregate vgo_to_fcc per mode
        m.fcc_mode = pyo.Var(m.PERIODS, m.MODES, bounds=(0.0, fcc_cap), initialize=0.0)

        m.vgo_to_fcc = pyo.Var(m.PERIODS, bounds=(0.0, fcc_cap), initialize=0.0)
        m.vgo_to_fo = pyo.Var(m.PERIODS, bounds=(0.0, 1e6), initialize=0.0)

        # Reformate capped at 10K to match the NLP
        m.reformate_purchased = pyo.Var(m.PERIODS, bounds=(0.0, 10_000.0), initialize=0.0)

        for var_name in [
            "ln_to_blend", "ln_to_sell", "hn_to_blend", "hn_to_sell",
            "hcn_to_blend", "hcn_to_fo", "lco_to_diesel", "lco_to_fo",
            "kero_to_jet", "kero_to_diesel", "nc4_to_blend", "nc4_to_lpg",
            "gasoline_volume", "naphtha_volume", "jet_volume",
            "diesel_volume", "fuel_oil_volume", "lpg_volume",
        ]:
            setattr(m, var_name, pyo.Var(m.PERIODS, bounds=(0.0, 1e6), initialize=0.0))

        # Yield cache by crude
        yields_by_crude: dict[str, dict[str, float]] = {}
        for cid in config.crude_library.list_crudes():
            assay = config.crude_library.get(cid)
            if assay:
                yields_by_crude[cid] = {c.name: c.vol_yield for c in assay.cuts}

        def cdu_cut(model: Any, cut_name: str, p: int) -> Any:
            return sum(
                model.crude_rate[c, p] * yields_by_crude.get(c, {}).get(cut_name, 0.0)
                for c in model.CRUDES
            )

        # CDU capacity
        m.cdu_capacity_con = pyo.Constraint(
            m.PERIODS, rule=lambda m, p: sum(m.crude_rate[c, p] for c in m.CRUDES) <= cdu_cap
        )

        # FCC capacity (vgo_to_fcc = sum of mode allocations, ≤ cap)
        def fcc_mode_sum_rule(model: Any, p: int) -> Any:
            return model.vgo_to_fcc[p] == sum(model.fcc_mode[p, mi] for mi in model.MODES)

        m.fcc_mode_sum = pyo.Constraint(m.PERIODS, rule=fcc_mode_sum_rule)

        m.fcc_capacity_con = pyo.Constraint(
            m.PERIODS, rule=lambda m, p: m.vgo_to_fcc[p] <= fcc_cap
        )

        # Dispositions
        m.ln_disposition = pyo.Constraint(
            m.PERIODS,
            rule=lambda model, p: model.ln_to_blend[p] + model.ln_to_sell[p]
            == cdu_cut(model, "light_naphtha", p),
        )
        m.hn_disposition = pyo.Constraint(
            m.PERIODS,
            rule=lambda model, p: model.hn_to_blend[p] + model.hn_to_sell[p]
            == cdu_cut(model, "heavy_naphtha", p),
        )
        m.kero_disposition = pyo.Constraint(
            m.PERIODS,
            rule=lambda model, p: model.kero_to_jet[p] + model.kero_to_diesel[p]
            == cdu_cut(model, "kerosene", p),
        )
        m.vgo_disposition = pyo.Constraint(
            m.PERIODS,
            rule=lambda model, p: model.vgo_to_fcc[p] + model.vgo_to_fo[p]
            == cdu_cut(model, "vgo", p),
        )
        m.nc4_disposition = pyo.Constraint(
            m.PERIODS,
            rule=lambda model, p: model.nc4_to_blend[p] + model.nc4_to_lpg[p]
            == _NC4_FRACTION_OF_LPG * cdu_cut(model, "lpg", p),
        )

        # FCC outputs (linear in mode allocations)
        def fcc_hcn_disposition_rule(model: Any, p: int) -> Any:
            hcn_total = sum(
                model.fcc_mode[p, mi] * mode_yields[mi]["hcn"] for mi in model.MODES
            )
            return model.hcn_to_blend[p] + model.hcn_to_fo[p] == hcn_total

        m.hcn_disposition = pyo.Constraint(m.PERIODS, rule=fcc_hcn_disposition_rule)

        def fcc_lco_disposition_rule(model: Any, p: int) -> Any:
            lco_total = sum(
                model.fcc_mode[p, mi] * mode_yields[mi]["lco"] for mi in model.MODES
            )
            return model.lco_to_diesel[p] + model.lco_to_fo[p] == lco_total

        m.lco_disposition = pyo.Constraint(m.PERIODS, rule=fcc_lco_disposition_rule)

        # Regen temperature (linear in modes)
        def regen_rule(model: Any, p: int) -> Any:
            # Each mode contributes (regen_temp_m - 1100) per bbl × vgo allocated to that mode
            # Constraint: max temp at full feed in any mode ≤ limit
            # Simplification: use a convex combination of mode coke yields
            # 1100 + 3800 × Σ(mode_alloc × coke_m) / Σ(mode_alloc) ≤ limit
            # ⟺ 3800 × Σ(mode_alloc × coke_m) ≤ (limit - 1100) × vgo_to_fcc
            coke_total = sum(
                model.fcc_mode[p, mi] * mode_yields[mi]["coke"] for mi in model.MODES
            )
            return 3800.0 * coke_total <= (regen_limit - 1100.0) * model.vgo_to_fcc[p]

        m.fcc_regen_temp_con = pyo.Constraint(m.PERIODS, rule=regen_rule)

        # Product volumes (LCN goes entirely to gasoline, like in the NLP)
        def gasoline_def(model: Any, p: int) -> Any:
            lcn_total = sum(
                model.fcc_mode[p, mi] * mode_yields[mi]["lcn"] for mi in model.MODES
            )
            return model.gasoline_volume[p] == (
                model.ln_to_blend[p] + model.hn_to_blend[p] + lcn_total
                + model.hcn_to_blend[p] + model.nc4_to_blend[p] + model.reformate_purchased[p]
            )

        m.gasoline_def = pyo.Constraint(m.PERIODS, rule=gasoline_def)

        m.naphtha_def = pyo.Constraint(
            m.PERIODS,
            rule=lambda model, p: model.naphtha_volume[p] == model.ln_to_sell[p] + model.hn_to_sell[p],
        )
        m.jet_def = pyo.Constraint(
            m.PERIODS, rule=lambda model, p: model.jet_volume[p] == model.kero_to_jet[p]
        )
        m.diesel_def = pyo.Constraint(
            m.PERIODS,
            rule=lambda model, p: model.diesel_volume[p]
            == cdu_cut(model, "diesel", p) + model.kero_to_diesel[p] + model.lco_to_diesel[p],
        )
        m.fuel_oil_def = pyo.Constraint(
            m.PERIODS,
            rule=lambda model, p: model.fuel_oil_volume[p]
            == model.vgo_to_fo[p] + model.hcn_to_fo[p] + model.lco_to_fo[p]
            + cdu_cut(model, "vacuum_residue", p),
        )

        def lpg_def_rule(model: Any, p: int) -> Any:
            c3_total = sum(model.fcc_mode[p, mi] * mode_yields[mi]["c3"] for mi in model.MODES)
            c4_total = sum(model.fcc_mode[p, mi] * mode_yields[mi]["c4"] for mi in model.MODES)
            return model.lpg_volume[p] == (
                (1.0 - _NC4_FRACTION_OF_LPG) * cdu_cut(model, "lpg", p)
                + model.nc4_to_lpg[p] + c3_total + c4_total
            )

        m.lpg_def = pyo.Constraint(m.PERIODS, rule=lpg_def_rule)

        # Demand min/max
        m.PRODUCTS = pyo.Set(initialize=["gasoline", "naphtha", "jet", "diesel", "fuel_oil", "lpg"])

        def demand_min_rule(model: Any, p: int, prod: str) -> Any:
            return getattr(model, f"{prod}_volume")[p] >= plan.periods[p].demand_min.get(prod, 0.0)

        m.demand_min_con = pyo.Constraint(m.PERIODS, m.PRODUCTS, rule=demand_min_rule)

        # Linear gasoline blend specs (octane via BI is already linear in vols)
        bi_min = -36.1572 + 0.83076 * 87.0 + 0.0037397 * 87.0**2

        def _bi(ron: float) -> float:
            return -36.1572 + 0.83076 * ron + 0.0037397 * ron * ron

        def octane_rule(model: Any, p: int) -> Any:
            lcn_total = sum(model.fcc_mode[p, mi] * mode_yields[mi]["lcn"] for mi in model.MODES)
            return (
                model.ln_to_blend[p] * _bi(_BLEND_COMPONENT_PROPS["cdu_ln"]["ron"])
                + model.hn_to_blend[p] * _bi(_BLEND_COMPONENT_PROPS["cdu_hn"]["ron"])
                + lcn_total * _bi(_BLEND_COMPONENT_PROPS["fcc_lcn"]["ron"])
                + model.hcn_to_blend[p] * _bi(_BLEND_COMPONENT_PROPS["fcc_hcn"]["ron"])
                + model.nc4_to_blend[p] * _bi(_BLEND_COMPONENT_PROPS["n_butane"]["ron"])
                + model.reformate_purchased[p] * _bi(_BLEND_COMPONENT_PROPS["reformate"]["ron"])
                >= bi_min * model.gasoline_volume[p]
            )

        m.octane_spec = pyo.Constraint(m.PERIODS, rule=octane_rule)

        # Objective — same form as NLP
        def obj_rule(model: Any) -> Any:
            from eurekan.optimization.builder import (
                _CDU_OPEX, _DEFAULT_PRICES, _DIESEL_HT_COST, _FCC_OPEX, _REFORMATE_PRICE,
            )

            total = 0.0
            for p in model.PERIODS:
                period = plan.periods[p]
                prices = {**_DEFAULT_PRICES, **period.product_prices}
                revenue = (
                    model.gasoline_volume[p] * prices["gasoline"]
                    + model.naphtha_volume[p] * prices["naphtha"]
                    + model.jet_volume[p] * prices["jet"]
                    + model.diesel_volume[p] * prices["diesel"]
                    + model.fuel_oil_volume[p] * prices["fuel_oil"]
                    + model.lpg_volume[p] * prices["lpg"]
                )
                crude_cost = sum(
                    model.crude_rate[c, p]
                    * period.crude_prices.get(
                        c,
                        (config.crude_library.get(c).price or 70.0)
                        if config.crude_library.get(c)
                        else 70.0,
                    )
                    for c in model.CRUDES
                )
                cdu_throughput = sum(model.crude_rate[c, p] for c in model.CRUDES)
                margin = (
                    revenue
                    - crude_cost
                    - cdu_throughput * _CDU_OPEX
                    - model.vgo_to_fcc[p] * _FCC_OPEX
                    - model.lco_to_diesel[p] * _DIESEL_HT_COST
                    - model.reformate_purchased[p] * _REFORMATE_PRICE
                )
                total += margin
            return total

        m.objective = pyo.Objective(rule=obj_rule, sense=pyo.maximize)
        return m

    # ------------------------------------------------------------------
    # Tier 3 — Multi-start
    # ------------------------------------------------------------------

    def generate_random_start(
        self,
        model: pyo.ConcreteModel,
        config: RefineryConfig,
        plan: PlanDefinition,
        seed: int,
    ) -> None:
        """Perturb the heuristic start with a random multiplier on each variable."""
        self.generate_heuristic_start(model, config, plan)
        rng = random.Random(seed)
        for v in model.component_data_objects(pyo.Var):
            current = pyo.value(v) if v.value is not None else 0.0
            if current <= 0:
                continue
            factor = rng.uniform(0.5, 1.5)
            new_val = current * factor
            if v.lb is not None:
                new_val = max(new_val, v.lb)
            if v.ub is not None:
                new_val = min(new_val, v.ub)
            v.set_value(new_val)

    # ------------------------------------------------------------------
    # Solve
    # ------------------------------------------------------------------

    def solve(self, model: pyo.ConcreteModel) -> SolveResult:
        """Run IPOPT once on the supplied model (variables already initialized)."""
        self._ipopt.options["max_iter"] = 3000
        self._ipopt.options["tol"] = 1e-6

        # Attach a dual suffix so the diagnostician can extract shadow prices
        if not hasattr(model, "dual"):
            model.dual = pyo.Suffix(direction=pyo.Suffix.IMPORT)

        start = time.perf_counter()
        try:
            results = self._ipopt.solve(model, tee=False)
        except Exception as exc:
            return SolveResult(
                status="error",
                solve_time=time.perf_counter() - start,
                tier_used=1,
                message=str(exc),
            )

        elapsed = time.perf_counter() - start
        term = str(results.solver.termination_condition)
        status = "optimal" if term in ("optimal", "locallyOptimal") else term

        try:
            obj_val = float(pyo.value(model.objective))
        except Exception:
            obj_val = 0.0

        # Iteration count is solver-specific; try to extract it
        iterations = 0
        try:
            iterations = int(results.solver.statistics.get("Number of Iterations", 0))
        except Exception:
            pass

        return SolveResult(
            status=status,
            objective_value=obj_val,
            solve_time=elapsed,
            tier_used=1,
            iterations=iterations,
        )

    def solve_with_fallback(
        self,
        model: pyo.ConcreteModel,
        config: RefineryConfig,
        plan: PlanDefinition,
    ) -> SolveResult:
        """Tier 1 → Tier 2 → Tier 3 cascade. Returns as soon as one succeeds."""
        # Tier 1: heuristic warm-start (fast — usually works)
        self.generate_heuristic_start(model, config, plan)
        t1 = self.solve(model)
        t1.tier_used = 1
        if t1.feasible:
            return t1

        # Tier 2: LP relaxation start (if Tier 1 failed)
        try:
            self.generate_lp_start(model, config, plan)
            t2 = self.solve(model)
            t2.tier_used = 2
            if t2.feasible:
                return t2
        except Exception:
            pass

        # Tier 3: Multi-start with 5 random perturbations
        best: Optional[SolveResult] = None
        for seed in range(1, 6):
            try:
                self.generate_random_start(model, config, plan, seed)
                attempt = self.solve(model)
                attempt.tier_used = 3
                if attempt.feasible:
                    if best is None or attempt.objective_value > best.objective_value:
                        best = attempt
            except Exception:
                continue

        if best is not None:
            return best

        return SolveResult(
            status="infeasible",
            tier_used=3,
            message="All three tiers failed to find a feasible solution.",
        )
