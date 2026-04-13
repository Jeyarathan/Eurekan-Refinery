"""Pyomo NLP model builder for refinery planning.

Translates a RefineryConfig + PlanDefinition into a complete Pyomo
ConcreteModel ready for IPOPT.

Variable structure (per period p):
  crude_rate[c, p]            crude rates, bbl/d
  fcc_conversion[p]           continuous decision variable [68, 90]
  vgo_to_fcc[p], vgo_to_fo[p]
  ln_to_blend[p], ln_to_sell[p]
  hn_to_blend[p], hn_to_sell[p]
  hcn_to_blend[p], hcn_to_fo[p]
  lco_to_diesel[p], lco_to_fo[p]
  kero_to_jet[p], kero_to_diesel[p]
  nc4_to_blend[p], nc4_to_lpg[p]
  reformate_purchased[p]
  fcc_lcn_vol[p], fcc_hcn_vol[p], fcc_lco_vol[p]
  fcc_coke_vol[p], fcc_c3_vol[p], fcc_c4_vol[p]
  product volumes:  gasoline, naphtha, jet, diesel, fuel_oil, lpg

FCC yield equations are NONLINEAR in conversion (quadratic). IPOPT handles
them directly. Blending specs use the linearized BI / power-law forms
(equivalent to the nonlinear blends but easier on the solver).
"""

from __future__ import annotations

from typing import Any

import pyomo.environ as pyo

from eurekan.core.config import RefineryConfig
from eurekan.core.period import PlanDefinition

# ---------------------------------------------------------------------------
# Defaults — used when the config or period doesn't specify a value
# ---------------------------------------------------------------------------

# Default FCC feed properties (used in yield equations when blended VGO is unknown)
_DEFAULT_FCC_FEED_API = 22.0
_DEFAULT_FCC_FEED_CCR = 1.0
_DEFAULT_FCC_FEED_METALS = 5.0

# Default product prices ($/bbl) — from CLAUDE.md economic objective
_DEFAULT_PRICES: dict[str, float] = {
    "gasoline": 82.81,
    "naphtha": 52.22,
    "jet": 87.59,
    "diesel": 86.53,
    "fuel_oil": 69.63,
    "lpg": 44.24,
}

_REFORMATE_PRICE = 70.0
_CDU_OPEX = 1.0
_FCC_OPEX = 1.5
_DIESEL_HT_COST = 2.0

# Blend component properties — used by the gasoline blender
_BLEND_COMPONENT_PROPS: dict[str, dict[str, float]] = {
    "cdu_ln":   {"ron": 68.0, "rvp": 12.5, "sulfur": 0.02, "spg": 0.66, "benzene": 2.0, "aromatics": 8.0,  "olefins": 1.0},
    "cdu_hn":   {"ron": 55.0, "rvp": 1.5,  "sulfur": 0.05, "spg": 0.74, "benzene": 1.0, "aromatics": 12.0, "olefins": 0.5},
    # FCC naphtha properties AFTER hydrotreating (Scanfiner).  All US refineries
    # hydro-treat FCC naphtha before blending.  Pre-treatment sulfur is 500-3000
    # ppm; post-treatment is 10-50 ppm.  Olefins are partially saturated.
    "fcc_lcn":  {"ron": 92.0, "rvp": 10.5, "sulfur": 0.001, "spg": 0.70, "benzene": 0.5, "aromatics": 25.0, "olefins": 25.0},
    "fcc_hcn":  {"ron": 86.0, "rvp": 2.0,  "sulfur": 0.005, "spg": 0.82, "benzene": 0.8, "aromatics": 45.0, "olefins": 6.0},
    "n_butane": {"ron": 93.8, "rvp": 51.6, "sulfur": 0.0,  "spg": 0.585, "benzene": 0.0, "aromatics": 0.0,  "olefins": 0.0},
    "reformate":{"ron": 98.0, "rvp": 4.0,  "sulfur": 0.001,"spg": 0.79, "benzene": 1.5, "aromatics": 65.0, "olefins": 1.0},
}

# Gasoline specs — defaults if a product doesn't specify them
_DEFAULT_OCTANE_MIN = 87.0
_DEFAULT_RVP_MAX = 14.0
_DEFAULT_SULFUR_MAX = 0.10
_DEFAULT_BENZENE_MAX = 1.0
_DEFAULT_AROMATICS_MAX = 35.0
_DEFAULT_OLEFINS_MAX = 18.0

# RON Blending Index coefficients (Ethyl/ASTM)
_BI_A = 0.0037397
_BI_B = 0.83076
_BI_C = -36.1572

# RVP power-law exponent
_RVP_EXP = 1.25

# Fraction of CDU LPG cut that is n-butane (the rest is C3/iC4 → LPG sales)
_NC4_FRACTION_OF_LPG = 0.5

# Fraction of FCC gasoline that is LCN (rest is HCN)
_LCN_FRACTION = 0.80

_BIG_M = 1.0e6


def _bi(ron: float) -> float:
    """RON → Blending Index (constant for blend components)."""
    return _BI_C + _BI_B * ron + _BI_A * ron * ron


class PyomoModelBuilder:
    """Builds a complete Pyomo NLP from RefineryConfig + PlanDefinition."""

    PRODUCT_NAMES: list[str] = [
        "gasoline", "naphtha", "jet", "diesel", "fuel_oil", "lpg",
    ]

    def __init__(self, config: RefineryConfig, plan: PlanDefinition) -> None:
        self.config = config
        self.plan = plan

        # Cache yields by crude
        self._yields: dict[str, dict[str, float]] = {}
        for cid in config.crude_library.list_crudes():
            assay = config.crude_library.get(cid)
            if assay is None:
                continue
            self._yields[cid] = {c.name: c.vol_yield for c in assay.cuts}

        # Unit capacities
        self.cdu_capacity = (
            config.units["cdu_1"].capacity if "cdu_1" in config.units else 80000.0
        )
        fcc_unit = config.units.get("fcc_1")
        self.fcc_capacity = fcc_unit.capacity if fcc_unit else 50000.0
        self.regen_limit = (
            fcc_unit.equipment_limits.get("fcc_regen_temp_max", 1400.0)
            if fcc_unit
            else 1400.0
        )

        self.crude_ids = list(self._yields.keys())
        self.n_periods = len(plan.periods)

        # Optional units
        reformer_unit = config.units.get("reformer_1")
        self.has_reformer = reformer_unit is not None
        self.reformer_capacity = reformer_unit.capacity if reformer_unit else 0.0

        goht_unit = config.units.get("goht_1")
        self.has_goht = goht_unit is not None
        self.goht_capacity = goht_unit.capacity if goht_unit else 0.0

        scan_unit = config.units.get("scanfiner_1")
        self.has_scanfiner = scan_unit is not None
        self.scanfiner_capacity = scan_unit.capacity if scan_unit else 0.0

        alky_unit = config.units.get("alky_1")
        self.has_alky = alky_unit is not None
        self.alky_capacity = alky_unit.capacity if alky_unit else 0.0

        kht_unit = config.units.get("kht_1")
        self.has_kht = kht_unit is not None
        self.kht_capacity = kht_unit.capacity if kht_unit else 0.0

        dht_unit = config.units.get("dht_1")
        self.has_dht = dht_unit is not None
        self.dht_capacity = dht_unit.capacity if dht_unit else 0.0

        # Identify product tanks: any tank whose tank_id contains a product name
        self.product_tanks: dict[str, Any] = {}
        for tank_id, tank in config.tanks.items():
            for prod in self.PRODUCT_NAMES:
                if prod in tank_id:
                    self.product_tanks[prod] = tank
                    break

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def build(self) -> pyo.ConcreteModel:
        """Construct the complete model."""
        m = pyo.ConcreteModel(name="EurekanRefinery")
        m.PERIODS = pyo.Set(initialize=list(range(self.n_periods)), ordered=True)
        m.CRUDES = pyo.Set(initialize=self.crude_ids)

        self._add_variables(m)
        self._add_cdu_constraints(m)
        self._add_fcc_constraints(m)
        if self.has_reformer:
            self._add_reformer_constraints(m)
        if self.has_alky:
            self._add_alkylation_constraints(m)
        self._add_hydrogen_balance(m)
        self._add_disposition_constraints(m)
        self._add_product_volume_constraints(m)
        self._add_blending_constraints(m)
        self._add_inventory_constraints(m)
        self._add_demand_constraints(m)
        self._add_objective(m)
        self._apply_unit_status(m)

        return m

    # ------------------------------------------------------------------
    # Variables
    # ------------------------------------------------------------------

    def _add_variables(self, m: pyo.ConcreteModel) -> None:
        """Add all decision variables with explicit bounds (IPOPT requirement)."""

        # Crude rates — bounded per period by either crude_availability or
        # the assay's overall max_rate
        def crude_bounds(_m: Any, c: str, p: int) -> tuple[float, float]:
            period = self.plan.periods[p]
            if c in period.crude_availability:
                lo, hi = period.crude_availability[c]
                return (float(lo), float(hi))
            assay = self.config.crude_library.get(c)
            max_rate = (assay.max_rate if assay and assay.max_rate else self.cdu_capacity)
            return (0.0, max_rate)

        m.crude_rate = pyo.Var(m.CRUDES, m.PERIODS, bounds=crude_bounds, initialize=0.0)

        # FCC operating variables
        m.fcc_conversion = pyo.Var(m.PERIODS, bounds=(68.0, 90.0), initialize=80.0)
        m.vgo_to_fcc = pyo.Var(m.PERIODS, bounds=(0.0, self.fcc_capacity), initialize=0.0)
        m.vgo_to_fo = pyo.Var(m.PERIODS, bounds=(0.0, _BIG_M), initialize=0.0)

        # Stream dispositions
        for var_name in [
            "ln_to_blend", "ln_to_sell",
            "hn_to_blend", "hn_to_sell",
            "hcn_to_blend", "hcn_to_fo",
            "lco_to_diesel", "lco_to_fo",
            "kero_to_jet", "kero_to_diesel",
            "nc4_to_blend", "nc4_to_lpg",
        ]:
            setattr(m, var_name, pyo.Var(m.PERIODS, bounds=(0.0, _BIG_M), initialize=0.0))

        # Reformate purchase — capped at 10K bbl/d (scarce purchased product;
        # in a refinery without a reformer, reformate is a specialty buy).
        # This forces the FCC to fill the gasoline pool, not unlimited reformate.
        m.reformate_purchased = pyo.Var(m.PERIODS, bounds=(0.0, 10_000.0), initialize=0.0)

        # FCC product volumes (intermediate variables — defined by yield constraints)
        for var_name in [
            "fcc_lcn_vol", "fcc_hcn_vol", "fcc_lco_vol",
            "fcc_coke_vol", "fcc_c3_vol", "fcc_c4_vol",
        ]:
            setattr(m, var_name, pyo.Var(m.PERIODS, bounds=(0.0, _BIG_M), initialize=0.0))

        # --- Reformer variables (only if reformer exists in config) ---
        if self.has_reformer:
            m.hn_to_reformer = pyo.Var(m.PERIODS, bounds=(0.0, self.reformer_capacity), initialize=0.0)
            m.reformer_severity = pyo.Var(m.PERIODS, bounds=(90.0, 105.0), initialize=98.0)
            m.reformate_from_reformer = pyo.Var(m.PERIODS, bounds=(0.0, _BIG_M), initialize=0.0)
            m.reformer_hydrogen = pyo.Var(m.PERIODS, bounds=(0.0, _BIG_M), initialize=0.0)
            m.reformer_lpg = pyo.Var(m.PERIODS, bounds=(0.0, _BIG_M), initialize=0.0)

        # --- GO HT variables ---
        if self.has_goht:
            m.vgo_to_goht = pyo.Var(m.PERIODS, bounds=(0.0, self.goht_capacity), initialize=0.0)

        # --- Scanfiner variables ---
        if self.has_scanfiner:
            m.hcn_to_scanfiner = pyo.Var(m.PERIODS, bounds=(0.0, self.scanfiner_capacity), initialize=0.0)
            m.scanfiner_output = pyo.Var(m.PERIODS, bounds=(0.0, _BIG_M), initialize=0.0)

        # --- Alkylation variables ---
        if self.has_alky:
            m.c3c4_to_alky = pyo.Var(m.PERIODS, bounds=(0.0, self.alky_capacity), initialize=0.0)
            m.alkylate_volume = pyo.Var(m.PERIODS, bounds=(0.0, _BIG_M), initialize=0.0)
            m.ic4_purchased = pyo.Var(m.PERIODS, bounds=(0.0, _BIG_M), initialize=0.0)

        # --- Kero HT variables ---
        if self.has_kht:
            m.kero_to_kht = pyo.Var(m.PERIODS, bounds=(0.0, self.kht_capacity), initialize=0.0)

        # --- Diesel HT variables ---
        if self.has_dht:
            m.diesel_to_dht = pyo.Var(m.PERIODS, bounds=(0.0, self.dht_capacity), initialize=0.0)
            m.lco_to_dht = pyo.Var(m.PERIODS, bounds=(0.0, _BIG_M), initialize=0.0)

        # --- Hydrogen balance ---
        m.h2_purchased = pyo.Var(m.PERIODS, bounds=(0.0, 0.15), initialize=0.0)  # MMSCFD

        # Product PRODUCTION volumes (computed from blends and dispositions)
        for var_name in [
            "gasoline_volume", "naphtha_volume", "jet_volume",
            "diesel_volume", "fuel_oil_volume", "lpg_volume",
        ]:
            setattr(m, var_name, pyo.Var(m.PERIODS, bounds=(0.0, _BIG_M), initialize=0.0))

        # Product SALES volumes — what's actually sold (= production minus
        # net inventory build for tanked products)
        for prod in self.PRODUCT_NAMES:
            setattr(
                m,
                f"{prod}_sales",
                pyo.Var(m.PERIODS, bounds=(0.0, _BIG_M), initialize=0.0),
            )

        # Inventory variables — only for products that have a tank in the config
        if self.product_tanks:
            m.PRODUCT_TANKS = pyo.Set(initialize=list(self.product_tanks.keys()))

            def inv_bounds(_m: Any, prod: str, p: int) -> tuple[float, float]:
                tank = self.product_tanks[prod]
                return (float(tank.minimum), float(tank.capacity))

            m.inventory = pyo.Var(
                m.PRODUCT_TANKS, m.PERIODS, bounds=inv_bounds, initialize=0.0
            )

    # ------------------------------------------------------------------
    # CDU constraints
    # ------------------------------------------------------------------

    def _y(self, crude_id: str, cut_name: str) -> float:
        return self._yields.get(crude_id, {}).get(cut_name, 0.0)

    def _cdu_cut_volume(self, m: pyo.ConcreteModel, cut_name: str, p: int) -> Any:
        return sum(m.crude_rate[c, p] * self._y(c, cut_name) for c in m.CRUDES)

    def _add_cdu_constraints(self, m: pyo.ConcreteModel) -> None:
        cdu_cap = self.cdu_capacity

        def cdu_cap_rule(m: Any, p: int) -> Any:
            return sum(m.crude_rate[c, p] for c in m.CRUDES) <= cdu_cap

        m.cdu_capacity_con = pyo.Constraint(m.PERIODS, rule=cdu_cap_rule)

    # ------------------------------------------------------------------
    # FCC constraints
    # ------------------------------------------------------------------

    def _fcc_gasoline_yield_expr(self, m: pyo.ConcreteModel, p: int) -> Any:
        c = m.fcc_conversion[p] / 100.0
        return (
            -0.0833
            + 1.3364 * c
            - 0.7744 * c * c
            + 0.0024 * (_DEFAULT_FCC_FEED_API - 22.0)
            - 0.0118 * (_DEFAULT_FCC_FEED_CCR - 1.0)
        )

    def _fcc_lco_yield_expr(self, m: pyo.ConcreteModel, p: int) -> Any:
        c = m.fcc_conversion[p] / 100.0
        return 0.37 - 0.2593 * c + 0.0031 * (_DEFAULT_FCC_FEED_API - 22.0)

    def _fcc_coke_yield_expr(self, m: pyo.ConcreteModel, p: int) -> Any:
        c = m.fcc_conversion[p] / 100.0
        return (
            0.040
            + 1.1 * _DEFAULT_FCC_FEED_CCR / 100.0
            + 0.001 * (c * 100.0 - 75.0)
            + 0.0002 * _DEFAULT_FCC_FEED_METALS
        )

    def _add_fcc_constraints(self, m: pyo.ConcreteModel) -> None:
        fcc_cap = self.fcc_capacity
        regen_limit = self.regen_limit

        def fcc_cap_rule(m: Any, p: int) -> Any:
            return m.vgo_to_fcc[p] <= fcc_cap

        m.fcc_capacity_con = pyo.Constraint(m.PERIODS, rule=fcc_cap_rule)

        # FCC LCN volume (NONLINEAR — bilinear vgo × yield(conversion))
        def lcn_def_rule(m: Any, p: int) -> Any:
            gasoline_yield = self._fcc_gasoline_yield_expr(m, p)
            return m.fcc_lcn_vol[p] == m.vgo_to_fcc[p] * _LCN_FRACTION * gasoline_yield

        m.fcc_lcn_def = pyo.Constraint(m.PERIODS, rule=lcn_def_rule)

        def hcn_def_rule(m: Any, p: int) -> Any:
            gasoline_yield = self._fcc_gasoline_yield_expr(m, p)
            return (
                m.fcc_hcn_vol[p]
                == m.vgo_to_fcc[p] * (1.0 - _LCN_FRACTION) * gasoline_yield
            )

        m.fcc_hcn_def = pyo.Constraint(m.PERIODS, rule=hcn_def_rule)

        def lco_def_rule(m: Any, p: int) -> Any:
            return m.fcc_lco_vol[p] == m.vgo_to_fcc[p] * self._fcc_lco_yield_expr(m, p)

        m.fcc_lco_def = pyo.Constraint(m.PERIODS, rule=lco_def_rule)

        def coke_def_rule(m: Any, p: int) -> Any:
            return m.fcc_coke_vol[p] == m.vgo_to_fcc[p] * self._fcc_coke_yield_expr(m, p)

        m.fcc_coke_def = pyo.Constraint(m.PERIODS, rule=coke_def_rule)

        # C3 + C4 from mass balance: remaining = 1 - gasoline - lco - coke; c3 = c4 = 0.30 × remaining
        def c3_def_rule(m: Any, p: int) -> Any:
            remaining = (
                1.0
                - self._fcc_gasoline_yield_expr(m, p)
                - self._fcc_lco_yield_expr(m, p)
                - self._fcc_coke_yield_expr(m, p)
            )
            return m.fcc_c3_vol[p] == m.vgo_to_fcc[p] * 0.30 * remaining

        m.fcc_c3_def = pyo.Constraint(m.PERIODS, rule=c3_def_rule)

        def c4_def_rule(m: Any, p: int) -> Any:
            remaining = (
                1.0
                - self._fcc_gasoline_yield_expr(m, p)
                - self._fcc_lco_yield_expr(m, p)
                - self._fcc_coke_yield_expr(m, p)
            )
            return m.fcc_c4_vol[p] == m.vgo_to_fcc[p] * 0.30 * remaining

        m.fcc_c4_def = pyo.Constraint(m.PERIODS, rule=c4_def_rule)

        # Regen temperature limit (NONLINEAR in conversion)
        def regen_rule(m: Any, p: int) -> Any:
            coke_yield = self._fcc_coke_yield_expr(m, p)
            regen_temp = 1100.0 + 3800.0 * coke_yield
            return regen_temp <= regen_limit

        m.fcc_regen_temp_con = pyo.Constraint(m.PERIODS, rule=regen_rule)

        # Gas compressor: roughly proportional to (conversion × feed). Constrain
        # the normalized load to <= 1.0 (full capacity).
        def gas_comp_rule(m: Any, p: int) -> Any:
            return (m.fcc_conversion[p] / 100.0) * m.vgo_to_fcc[p] <= fcc_cap

        m.fcc_gas_compressor_con = pyo.Constraint(m.PERIODS, rule=gas_comp_rule)

        # Air blower: proportional to coke burn rate (coke_yield × feed). The 8%
        # coke yield calibration in equipment_status corresponds to ~max blower load.
        def air_blower_rule(m: Any, p: int) -> Any:
            coke_yield = self._fcc_coke_yield_expr(m, p)
            return coke_yield * m.vgo_to_fcc[p] <= 0.08 * fcc_cap

        m.fcc_air_blower_con = pyo.Constraint(m.PERIODS, rule=air_blower_rule)

    # ------------------------------------------------------------------
    # Reformer constraints (only when reformer exists)
    # ------------------------------------------------------------------

    def _add_reformer_constraints(self, m: pyo.ConcreteModel) -> None:
        """Reformer yield equations: HN → reformate + H2 + LPG."""
        ref_cap = self.reformer_capacity

        # Reformer capacity
        def ref_cap_rule(m: Any, p: int) -> Any:
            return m.hn_to_reformer[p] <= ref_cap

        m.reformer_capacity_con = pyo.Constraint(m.PERIODS, rule=ref_cap_rule)

        # Reformate yield: 0.95 - 0.0125 × (severity - 90) (nonlinear in severity)
        def ref_yield_rule(m: Any, p: int) -> Any:
            sev = m.reformer_severity[p]
            yield_frac = 0.95 - 0.0125 * (sev - 90.0)
            return m.reformate_from_reformer[p] == m.hn_to_reformer[p] * yield_frac

        m.reformer_yield_def = pyo.Constraint(m.PERIODS, rule=ref_yield_rule)

        # Hydrogen yield: 0.03 + 0.001 × (severity - 90)
        def ref_h2_rule(m: Any, p: int) -> Any:
            sev = m.reformer_severity[p]
            h2_frac = 0.03 + 0.001 * (sev - 90.0)
            return m.reformer_hydrogen[p] == m.hn_to_reformer[p] * h2_frac

        m.reformer_h2_def = pyo.Constraint(m.PERIODS, rule=ref_h2_rule)

        # LPG from mass balance: remainder × 0.6 (rest is fuel gas)
        def ref_lpg_rule(m: Any, p: int) -> Any:
            sev = m.reformer_severity[p]
            yield_frac = 0.95 - 0.0125 * (sev - 90.0)
            h2_frac = 0.03 + 0.001 * (sev - 90.0)
            remainder = 1.0 - yield_frac - h2_frac
            return m.reformer_lpg[p] == m.hn_to_reformer[p] * 0.6 * remainder

        m.reformer_lpg_def = pyo.Constraint(m.PERIODS, rule=ref_lpg_rule)

    # ------------------------------------------------------------------
    # Alkylation constraints
    # ------------------------------------------------------------------

    def _add_alkylation_constraints(self, m: pyo.ConcreteModel) -> None:
        """Alkylation: olefins → alkylate at 1.75× yield, requires iC4."""
        def alky_yield_rule(m: Any, p: int) -> Any:
            return m.alkylate_volume[p] == m.c3c4_to_alky[p] * 1.75

        m.alky_yield_def = pyo.Constraint(m.PERIODS, rule=alky_yield_rule)

        # iC4 requirement: 1.1× olefin feed
        def alky_ic4_rule(m: Any, p: int) -> Any:
            return m.ic4_purchased[p] >= m.c3c4_to_alky[p] * 1.1

        m.alky_ic4_con = pyo.Constraint(m.PERIODS, rule=alky_ic4_rule)

        # Feed limit: can't send more C3/C4 than FCC produces
        def alky_feed_rule(m: Any, p: int) -> Any:
            return m.c3c4_to_alky[p] <= m.fcc_c3_vol[p] + m.fcc_c4_vol[p]

        m.alky_feed_con = pyo.Constraint(m.PERIODS, rule=alky_feed_rule)

    # ------------------------------------------------------------------
    # Hydrogen balance
    # ------------------------------------------------------------------

    def _add_hydrogen_balance(self, m: pyo.ConcreteModel) -> None:
        """H2 supply >= H2 demand.  Reformer produces H2; HTs consume it."""
        def h2_rule(m: Any, p: int) -> Any:
            supply = m.h2_purchased[p]
            if self.has_reformer:
                supply += m.reformer_hydrogen[p]

            demand = 0.0
            if self.has_goht:
                demand += m.vgo_to_goht[p] * 1000.0 / 1e6  # 1000 SCFB → MMSCFD
            if self.has_scanfiner:
                demand += m.hcn_to_scanfiner[p] * 300.0 / 1e6
            if self.has_kht:
                demand += m.kero_to_kht[p] * 600.0 / 1e6
            if self.has_dht:
                demand += (m.diesel_to_dht[p] + m.lco_to_dht[p]) * 800.0 / 1e6

            return supply >= demand

        m.h2_balance_con = pyo.Constraint(m.PERIODS, rule=h2_rule)

    # ------------------------------------------------------------------
    # Disposition constraints
    # ------------------------------------------------------------------

    def _add_disposition_constraints(self, m: pyo.ConcreteModel) -> None:
        # CDU light naphtha
        def ln_disp_rule(m: Any, p: int) -> Any:
            return m.ln_to_blend[p] + m.ln_to_sell[p] == self._cdu_cut_volume(m, "light_naphtha", p)

        m.ln_disposition = pyo.Constraint(m.PERIODS, rule=ln_disp_rule)

        # CDU heavy naphtha — 2 or 3 destinations depending on reformer
        has_ref = self.has_reformer

        def hn_disp_rule(m: Any, p: int) -> Any:
            lhs = m.hn_to_blend[p] + m.hn_to_sell[p]
            if has_ref:
                lhs += m.hn_to_reformer[p]
            return lhs == self._cdu_cut_volume(m, "heavy_naphtha", p)

        m.hn_disposition = pyo.Constraint(m.PERIODS, rule=hn_disp_rule)

        # CDU kerosene
        # When Kero HT exists: kerosene for jet MUST go through KHT (mandatory).
        # kero_to_jet is still used for the non-KHT path (direct jet sale when no KHT).
        has_kht = self.has_kht

        def kero_disp_rule(m: Any, p: int) -> Any:
            if has_kht:
                # All kero goes to KHT (for jet) or to diesel pool
                return m.kero_to_kht[p] + m.kero_to_diesel[p] == self._cdu_cut_volume(m, "kerosene", p)
            return m.kero_to_jet[p] + m.kero_to_diesel[p] == self._cdu_cut_volume(m, "kerosene", p)

        m.kero_disposition = pyo.Constraint(m.PERIODS, rule=kero_disp_rule)

        # CDU VGO — 2 or 3 destinations depending on GO HT
        has_goht = self.has_goht

        def vgo_disp_rule(m: Any, p: int) -> Any:
            lhs = m.vgo_to_fcc[p] + m.vgo_to_fo[p]
            if has_goht:
                lhs += m.vgo_to_goht[p]
            return lhs == self._cdu_cut_volume(m, "vgo", p)

        m.vgo_disposition = pyo.Constraint(m.PERIODS, rule=vgo_disp_rule)

        # NC4 — fraction of CDU LPG cut
        def nc4_disp_rule(m: Any, p: int) -> Any:
            nc4_avail = _NC4_FRACTION_OF_LPG * self._cdu_cut_volume(m, "lpg", p)
            return m.nc4_to_blend[p] + m.nc4_to_lpg[p] == nc4_avail

        m.nc4_disposition = pyo.Constraint(m.PERIODS, rule=nc4_disp_rule)

        # FCC HCN — 2 or 3 destinations depending on Scanfiner
        has_scan = self.has_scanfiner

        def hcn_disp_rule(m: Any, p: int) -> Any:
            lhs = m.hcn_to_blend[p] + m.hcn_to_fo[p]
            if has_scan:
                lhs += m.hcn_to_scanfiner[p]
            return lhs == m.fcc_hcn_vol[p]

        m.hcn_disposition = pyo.Constraint(m.PERIODS, rule=hcn_disp_rule)

        # Scanfiner output: 98% volume yield
        if has_scan:
            def scan_yield_rule(m: Any, p: int) -> Any:
                return m.scanfiner_output[p] == m.hcn_to_scanfiner[p] * 0.98
            m.scanfiner_yield_def = pyo.Constraint(m.PERIODS, rule=scan_yield_rule)

        # FCC LCO — diesel/FO/DHT
        has_dht = self.has_dht

        def lco_disp_rule(m: Any, p: int) -> Any:
            lhs = m.lco_to_diesel[p] + m.lco_to_fo[p]
            if has_dht:
                lhs += m.lco_to_dht[p]
            return lhs == m.fcc_lco_vol[p]

        m.lco_disposition = pyo.Constraint(m.PERIODS, rule=lco_disp_rule)

        # CDU diesel disposition — when DHT exists, ALL CDU diesel → DHT (mandatory)
        if has_dht:
            def diesel_disp_rule(m: Any, p: int) -> Any:
                return m.diesel_to_dht[p] == self._cdu_cut_volume(m, "diesel", p)
            m.diesel_disposition = pyo.Constraint(m.PERIODS, rule=diesel_disp_rule)

    # ------------------------------------------------------------------
    # Product volume constraints
    # ------------------------------------------------------------------

    def _add_product_volume_constraints(self, m: pyo.ConcreteModel) -> None:
        # Gasoline = LN + HN + LCN + HCN + NC4 + reformate + scanfiner_output + alkylate
        has_ref = self.has_reformer
        has_scan = self.has_scanfiner
        has_alky = self.has_alky

        def gasoline_def(m: Any, p: int) -> Any:
            total = (
                m.ln_to_blend[p]
                + m.hn_to_blend[p]
                + m.fcc_lcn_vol[p]
                + m.hcn_to_blend[p]
                + m.nc4_to_blend[p]
                + m.reformate_purchased[p]
            )
            if has_ref:
                total += m.reformate_from_reformer[p]
            if has_scan:
                total += m.scanfiner_output[p]
            if has_alky:
                total += m.alkylate_volume[p]
            return m.gasoline_volume[p] == total

        m.gasoline_def = pyo.Constraint(m.PERIODS, rule=gasoline_def)

        # Naphtha sales = LN_sell + HN_sell
        def naphtha_def(m: Any, p: int) -> Any:
            return m.naphtha_volume[p] == m.ln_to_sell[p] + m.hn_to_sell[p]

        m.naphtha_def = pyo.Constraint(m.PERIODS, rule=naphtha_def)

        # Jet: when KHT exists, ALL jet comes from KHT (mandatory).
        # When no KHT, jet = direct kero_to_jet.
        has_kht_ = self.has_kht

        def jet_def(m: Any, p: int) -> Any:
            if has_kht_:
                return m.jet_volume[p] == m.kero_to_kht[p] * 0.995
            return m.jet_volume[p] == m.kero_to_jet[p]

        m.jet_def = pyo.Constraint(m.PERIODS, rule=jet_def)

        # Diesel pool:
        # When DHT exists: ALL diesel must go through DHT (mandatory for ULSD spec).
        #   Feed to DHT = diesel_to_dht + lco_to_dht + kero_to_diesel
        #   Diesel volume = DHT output × 99% yield
        # When no DHT: direct CDU diesel + kero_to_diesel + lco_to_diesel.
        has_dht_ = self.has_dht

        def diesel_def(m: Any, p: int) -> Any:
            if has_dht_:
                dht_output = (m.diesel_to_dht[p] + m.lco_to_dht[p]) * 0.99
                # kero_to_diesel bypasses DHT (it's a lighter cut, lower sulfur)
                total = dht_output + m.kero_to_diesel[p]
                return m.diesel_volume[p] == total
            cdu_diesel = self._cdu_cut_volume(m, "diesel", p)
            total = cdu_diesel + m.kero_to_diesel[p] + m.lco_to_diesel[p]
            return m.diesel_volume[p] == total

        m.diesel_def = pyo.Constraint(m.PERIODS, rule=diesel_def)

        # Fuel oil pool = vgo_to_fo + hcn_to_fo + lco_to_fo + vacuum_residue
        def fuel_oil_def(m: Any, p: int) -> Any:
            vresid = self._cdu_cut_volume(m, "vacuum_residue", p)
            return m.fuel_oil_volume[p] == m.vgo_to_fo[p] + m.hcn_to_fo[p] + m.lco_to_fo[p] + vresid

        m.fuel_oil_def = pyo.Constraint(m.PERIODS, rule=fuel_oil_def)

        # LPG pool = CDU LPG + nc4_to_lpg + FCC C3/C4 + reformer LPG - C3/C4 to alky
        def lpg_def(m: Any, p: int) -> Any:
            cdu_non_nc4 = (1.0 - _NC4_FRACTION_OF_LPG) * self._cdu_cut_volume(m, "lpg", p)
            total = cdu_non_nc4 + m.nc4_to_lpg[p] + m.fcc_c3_vol[p] + m.fcc_c4_vol[p]
            if has_ref:
                total += m.reformer_lpg[p]
            if has_alky:
                total -= m.c3c4_to_alky[p]
            return m.lpg_volume[p] == total

        m.lpg_def = pyo.Constraint(m.PERIODS, rule=lpg_def)

    # ------------------------------------------------------------------
    # Blending constraints (gasoline)
    # ------------------------------------------------------------------

    def _gasoline_spec_value(self, p: int, name: str, kind: str) -> float:
        """Look up a gasoline spec from the product, falling back to defaults."""
        gasoline = self.config.products.get("regular_gasoline") or self.config.products.get(
            "gasoline"
        )
        if gasoline is not None:
            for spec in gasoline.specs:
                if spec.spec_name == name:
                    if kind == "min" and spec.min_value is not None:
                        return spec.min_value
                    if kind == "max" and spec.max_value is not None:
                        return spec.max_value
        # Defaults
        return {
            ("road_octane", "min"): _DEFAULT_OCTANE_MIN,
            ("ron", "min"): _DEFAULT_OCTANE_MIN,
            ("rvp", "max"): _DEFAULT_RVP_MAX,
            ("sulfur", "max"): _DEFAULT_SULFUR_MAX,
            ("benzene", "max"): _DEFAULT_BENZENE_MAX,
            ("aromatics", "max"): _DEFAULT_AROMATICS_MAX,
            ("olefins", "max"): _DEFAULT_OLEFINS_MAX,
        }.get((name, kind), 0.0)

    def _add_blending_constraints(self, m: pyo.ConcreteModel) -> None:
        # Convert blend properties to per-component constants
        bi = {k: _bi(v["ron"]) for k, v in _BLEND_COMPONENT_PROPS.items()}
        rvp_pow = {k: v["rvp"] ** _RVP_EXP for k, v in _BLEND_COMPONENT_PROPS.items()}

        def _blend_terms(m: Any, p: int, attr: str) -> Any:
            return (
                m.ln_to_blend[p] * _BLEND_COMPONENT_PROPS["cdu_ln"][attr]
                + m.hn_to_blend[p] * _BLEND_COMPONENT_PROPS["cdu_hn"][attr]
                + m.fcc_lcn_vol[p] * _BLEND_COMPONENT_PROPS["fcc_lcn"][attr]
                + m.hcn_to_blend[p] * _BLEND_COMPONENT_PROPS["fcc_hcn"][attr]
                + m.nc4_to_blend[p] * _BLEND_COMPONENT_PROPS["n_butane"][attr]
                + m.reformate_purchased[p] * _BLEND_COMPONENT_PROPS["reformate"][attr]
            )

        # --- Octane (RON via Blending Index) ---
        # Σ(vol × BI_i) ≥ BI(min_RON) × gasoline_volume
        has_ref = self.has_reformer

        def octane_rule(m: Any, p: int) -> Any:
            ron_min = self._gasoline_spec_value(p, "road_octane", "min")
            bi_min = _bi(ron_min)
            bi_total = (
                m.ln_to_blend[p] * bi["cdu_ln"]
                + m.hn_to_blend[p] * bi["cdu_hn"]
                + m.fcc_lcn_vol[p] * bi["fcc_lcn"]
                + m.hcn_to_blend[p] * bi["fcc_hcn"]
                + m.nc4_to_blend[p] * bi["n_butane"]
                + m.reformate_purchased[p] * bi["reformate"]
            )
            if has_ref:
                # Reformer reformate BI is nonlinear in severity:
                # BI(severity) = _BI_C + _BI_B*sev + _BI_A*sev²
                sev = m.reformer_severity[p]
                ref_bi = _BI_C + _BI_B * sev + _BI_A * sev * sev
                bi_total += m.reformate_from_reformer[p] * ref_bi
            return bi_total >= bi_min * m.gasoline_volume[p]

        m.octane_spec = pyo.Constraint(m.PERIODS, rule=octane_rule)

        # --- RVP (power-law) ---
        # Σ(vol × RVP_i^1.25) ≤ RVP_max^1.25 × gasoline_volume
        def rvp_rule(m: Any, p: int) -> Any:
            rvp_max = self._gasoline_spec_value(p, "rvp", "max")
            rvp_max_pow = rvp_max**_RVP_EXP
            rvp_total = (
                m.ln_to_blend[p] * rvp_pow["cdu_ln"]
                + m.hn_to_blend[p] * rvp_pow["cdu_hn"]
                + m.fcc_lcn_vol[p] * rvp_pow["fcc_lcn"]
                + m.hcn_to_blend[p] * rvp_pow["fcc_hcn"]
                + m.nc4_to_blend[p] * rvp_pow["n_butane"]
                + m.reformate_purchased[p] * rvp_pow["reformate"]
            )
            return rvp_total <= rvp_max_pow * m.gasoline_volume[p]

        m.rvp_spec = pyo.Constraint(m.PERIODS, rule=rvp_rule)

        # --- Sulfur (linear by weight) ---
        # Σ(vol × spg × S) ≤ S_max × Σ(vol × spg)
        def sulfur_rule(m: Any, p: int) -> Any:
            s_max = self._gasoline_spec_value(p, "sulfur", "max")

            def spg_s(c: str) -> float:
                return _BLEND_COMPONENT_PROPS[c]["spg"] * _BLEND_COMPONENT_PROPS[c]["sulfur"]

            def spg(c: str) -> float:
                return _BLEND_COMPONENT_PROPS[c]["spg"]

            wt_sulfur = (
                m.ln_to_blend[p] * spg_s("cdu_ln")
                + m.hn_to_blend[p] * spg_s("cdu_hn")
                + m.fcc_lcn_vol[p] * spg_s("fcc_lcn")
                + m.hcn_to_blend[p] * spg_s("fcc_hcn")
                + m.nc4_to_blend[p] * spg_s("n_butane")
                + m.reformate_purchased[p] * spg_s("reformate")
            )
            wt_total = (
                m.ln_to_blend[p] * spg("cdu_ln")
                + m.hn_to_blend[p] * spg("cdu_hn")
                + m.fcc_lcn_vol[p] * spg("fcc_lcn")
                + m.hcn_to_blend[p] * spg("fcc_hcn")
                + m.nc4_to_blend[p] * spg("n_butane")
                + m.reformate_purchased[p] * spg("reformate")
            )
            return wt_sulfur <= s_max * wt_total

        m.sulfur_spec = pyo.Constraint(m.PERIODS, rule=sulfur_rule)

        # --- Benzene, aromatics, olefins (linear by volume) ---
        def benzene_rule(m: Any, p: int) -> Any:
            limit = self._gasoline_spec_value(p, "benzene", "max")
            return _blend_terms(m, p, "benzene") <= limit * m.gasoline_volume[p]

        m.benzene_spec = pyo.Constraint(m.PERIODS, rule=benzene_rule)

        def aromatics_rule(m: Any, p: int) -> Any:
            limit = self._gasoline_spec_value(p, "aromatics", "max")
            return _blend_terms(m, p, "aromatics") <= limit * m.gasoline_volume[p]

        m.aromatics_spec = pyo.Constraint(m.PERIODS, rule=aromatics_rule)

        def olefins_rule(m: Any, p: int) -> Any:
            limit = self._gasoline_spec_value(p, "olefins", "max")
            return _blend_terms(m, p, "olefins") <= limit * m.gasoline_volume[p]

        m.olefins_spec = pyo.Constraint(m.PERIODS, rule=olefins_rule)

    # ------------------------------------------------------------------
    # Inventory constraints
    # ------------------------------------------------------------------

    def _add_inventory_constraints(self, m: pyo.ConcreteModel) -> None:
        """Tank balance: inv[t,p] = inv[t,p-1] + production[p] - sales[p]

        For products without a tank: sales == production (no inventory).
        For products with a tank: inventory variable carries volume across periods.
        """
        # Sales == production for non-tanked products
        non_tanked = [p for p in self.PRODUCT_NAMES if p not in self.product_tanks]

        def sales_eq_production_rule(model: Any, p: int, prod: str) -> Any:
            return getattr(model, f"{prod}_sales")[p] == getattr(model, f"{prod}_volume")[p]

        if non_tanked:
            m.NON_TANKED_PRODUCTS = pyo.Set(initialize=non_tanked)
            m.sales_eq_production_con = pyo.Constraint(
                m.PERIODS, m.NON_TANKED_PRODUCTS, rule=sales_eq_production_rule
            )

        # Tank inventory balance for tanked products
        if not self.product_tanks:
            return

        def inventory_balance_rule(model: Any, prod: str, p: int) -> Any:
            tank = self.product_tanks[prod]
            production = getattr(model, f"{prod}_volume")[p]
            sales = getattr(model, f"{prod}_sales")[p]
            if p == 0:
                initial = self.plan.periods[0].initial_inventory.get(
                    prod, float(tank.current_level)
                )
                return model.inventory[prod, 0] == initial + production - sales
            return (
                model.inventory[prod, p]
                == model.inventory[prod, p - 1] + production - sales
            )

        m.inventory_balance_con = pyo.Constraint(
            m.PRODUCT_TANKS, m.PERIODS, rule=inventory_balance_rule
        )

    # ------------------------------------------------------------------
    # Unit status
    # ------------------------------------------------------------------

    def _apply_unit_status(self, m: pyo.ConcreteModel) -> None:
        """Fix unit throughputs to zero for periods where status == 'offline'."""
        for p in range(self.n_periods):
            period = self.plan.periods[p]
            if period.unit_status.get("fcc_1") == "offline":
                m.vgo_to_fcc[p].fix(0.0)
            if period.unit_status.get("cdu_1") == "offline":
                for c in self.crude_ids:
                    m.crude_rate[c, p].fix(0.0)

    # ------------------------------------------------------------------
    # Demand constraints
    # ------------------------------------------------------------------

    def _add_demand_constraints(self, m: pyo.ConcreteModel) -> None:
        product_keys = ["gasoline", "naphtha", "jet", "diesel", "fuel_oil", "lpg"]

        def demand_min_rule(m: Any, p: int, prod: str) -> Any:
            period = self.plan.periods[p]
            min_d = period.demand_min.get(prod, 0.0)
            return getattr(m, f"{prod}_sales")[p] >= min_d

        def demand_max_rule(m: Any, p: int, prod: str) -> Any:
            period = self.plan.periods[p]
            max_d = period.demand_max.get(prod, _BIG_M)
            return getattr(m, f"{prod}_sales")[p] <= max_d

        m.PRODUCTS = pyo.Set(initialize=product_keys)
        m.demand_min_con = pyo.Constraint(m.PERIODS, m.PRODUCTS, rule=demand_min_rule)
        m.demand_max_con = pyo.Constraint(m.PERIODS, m.PRODUCTS, rule=demand_max_rule)

    # ------------------------------------------------------------------
    # Objective
    # ------------------------------------------------------------------

    def _add_objective(self, m: pyo.ConcreteModel) -> None:
        def obj_rule(m: Any) -> Any:
            total = 0.0
            for p in m.PERIODS:
                period = self.plan.periods[p]
                prices = {**_DEFAULT_PRICES, **period.product_prices}

                revenue = (
                    m.gasoline_sales[p] * prices["gasoline"]
                    + m.naphtha_sales[p] * prices["naphtha"]
                    + m.jet_sales[p] * prices["jet"]
                    + m.diesel_sales[p] * prices["diesel"]
                    + m.fuel_oil_sales[p] * prices["fuel_oil"]
                    + m.lpg_sales[p] * prices["lpg"]
                )

                crude_cost = sum(
                    m.crude_rate[c, p]
                    * period.crude_prices.get(
                        c,
                        (self.config.crude_library.get(c).price or 70.0)
                        if self.config.crude_library.get(c)
                        else 70.0,
                    )
                    for c in m.CRUDES
                )

                cdu_throughput = sum(m.crude_rate[c, p] for c in m.CRUDES)
                cdu_opex = cdu_throughput * _CDU_OPEX
                fcc_opex = m.vgo_to_fcc[p] * _FCC_OPEX
                diesel_ht_cost = m.lco_to_diesel[p] * _DIESEL_HT_COST
                reformate_cost = m.reformate_purchased[p] * _REFORMATE_PRICE

                # Optional unit costs
                extra_opex = 0.0
                extra_credit = 0.0
                if self.has_reformer:
                    extra_opex += m.hn_to_reformer[p] * 3.0      # $3/bbl reformer feed
                    extra_credit += m.reformer_hydrogen[p] * 1.5  # $1.50/MSCF H2
                if self.has_goht:
                    extra_opex += m.vgo_to_goht[p] * 2.5          # $2.50/bbl GO HT
                if self.has_scanfiner:
                    extra_opex += m.hcn_to_scanfiner[p] * 1.5     # $1.50/bbl Scanfiner
                if self.has_alky:
                    extra_opex += m.c3c4_to_alky[p] * 4.0         # $4/bbl alky feed
                    extra_opex += m.ic4_purchased[p] * 50.0       # $50/bbl iC4
                if self.has_kht:
                    extra_opex += m.kero_to_kht[p] * 2.0           # $2/bbl kero HT
                if self.has_dht:
                    extra_opex += (m.diesel_to_dht[p] + m.lco_to_dht[p]) * 2.5  # $2.50/bbl diesel HT
                extra_opex += m.h2_purchased[p] * 1500.0           # $1.50/MSCF × 1000

                margin = (
                    revenue - crude_cost - cdu_opex - fcc_opex - diesel_ht_cost
                    - reformate_cost - extra_opex + extra_credit
                )

                # Period weight by duration (days)
                duration_days = max(period.duration_hours / 24.0, 1.0)
                total += margin * duration_days

            return total

        m.objective = pyo.Objective(rule=obj_rule, sense=pyo.maximize)
