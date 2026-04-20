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
from eurekan.models.gas_plant import (
    SGP_FUEL_GAS_FRAC,
    SGP_ISOBUTANE_FRAC,
    SGP_NORMAL_BUTANE_FRAC,
    SGP_PROPANE_FRAC,
    UGP_BUTYLENE_FRAC,
    UGP_FUEL_GAS_FRAC,
    UGP_ISOBUTANE_FRAC,
    UGP_NORMAL_BUTANE_FRAC,
    UGP_PROPANE_FRAC,
    UGP_PROPYLENE_FRAC,
)

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
_VACUUM_OPEX = 1.0    # $/bbl vacuum unit feed
_COKER_OPEX = 4.0     # $/bbl coker feed (high energy)
_COKE_PRICE = 60.0    # $/ton fuel-grade petroleum coke (typical Gulf Coast)
_BBL_TO_TON_COKE = 0.157  # bbl coke -> metric tons
_HCU_OPEX = 5.0       # $/bbl hydrocracker feed (high-pressure operation)
_ISOM56_OPEX = 1.50   # $/bbl C5/C6 isomerization feed
_ISOMC4_OPEX = 2.0    # $/bbl C4 isomerization feed
_ISOM56_VOL_YIELD = 0.98  # 98% volume yield on C5/C6 isom
_ISOMC4_IC4_YIELD = 0.95  # 95% iC4 yield on nC4 feed (with recycle)

# Sprint 15: Aromatics reformer + Dimersol
_AROM_OPEX = 4.0           # $/bbl aromatics reformer feed
_AROM_BTX_YIELD = 0.45     # 45% BTX extract
_AROM_RAFFINATE_YIELD = 0.40  # 40% raffinate (low RON)
_AROM_H2_WT = 0.045        # 4.5 wt% H2
_AROM_LPG_YIELD = 0.6 * (1.0 - 0.45 - 0.40 - 0.045)  # LPG fraction of remainder
_DIMERSOL_OPEX = 2.0       # $/bbl dimersol feed
_DIMERSOL_YIELD = 0.90     # 90% dimate yield

# Sprint 16: Gas plants (Unsaturated + Saturated)
_UGP_OPEX = 0.50           # $/bbl UGP feed (fractionation energy)
_SGP_OPEX = 0.30           # $/bbl SGP feed (fractionation energy)
_BTX_PRICE_PER_TON = 900.0  # $/ton BTX petchem (midpoint of $800-1200)
_BBL_TO_TON_BTX = 0.870 * 0.159  # spg 0.87, 0.159 m3/bbl

# Sprint A: Sulfur complex (Amine + SRU + Tail Gas Treatment).
# H2S generation coefficients (LT H2S per bbl throughput).  Sprint A used
# flat volumetric constants that were independent of crude-assay S; Sprint
# A.1 replaces that with an assay-driven model (see
# ``_compute_sulfur_coefficients`` and ``_HT_S_REMOVAL``).  These legacy
# constants are still imported by the diagnostic script for reference.
_HT_H2S_LT_PER_BBL = 5.0e-5
_FCC_H2S_LT_PER_BBL = 1.0e-5
_COKER_H2S_LT_PER_BBL = 2.0e-5

# Sprint A.1: per-unit S removal / liberation fractions.  These determine
# how much of the feed-cut's elemental S each conversion unit strips into
# H2S (with the balance staying in liquid products / coke and closing
# against the products_s_lt sink).  Values reflect standard industry
# ranges for Gulf Coast hydroprocessing.
_HT_S_REMOVAL: dict[str, float] = {
    "kerosene": 0.92,        # KHT
    "diesel":   0.95,        # DHT (ULSD duty, near-total)
    "vgo":      0.92,        # GO HDT / HCU feed prep
    "heavy_naphtha": 0.95,   # NHT / Scanfiner for FCC naphtha
    "coker_naphtha": 0.95,   # coker naphtha HT
    "hcu":      0.97,        # HCU high-severity
}
_FCC_S_TO_H2S = 0.30         # ~30% of VGO feed S -> H2S at the FCC
_COKER_S_TO_H2S = 0.20       # ~20% of vac-resid S -> H2S in coker gas

# Claus stoichiometry and recovery
_S_PER_H2S = 32.0 / 34.0         # mass ratio elemental S / H2S
_AMINE_H2S_REMOVAL = 0.995       # amine captures 99.5% of inlet H2S
_SRU_RECOVERY = 0.97             # modified Claus 97% S recovery
_TGT_RECOVERY = 0.90             # 90% of SRU slip captured by TGT

# Economics
_SULFUR_PRICE_PER_LT = 150.0     # $/LT elemental sulfur
_AMINE_OPEX_PER_LT = 25.0        # $/LT H2S processed
_SRU_OPEX_PER_LT = 50.0          # $/LT S produced
_TGT_OPEX_PER_LT = 80.0          # $/LT residual S treated

# Vacuum unit yield fractions (LVGO + HVGO + VR = 1.0)
_VAC_LVGO_FRAC = 0.25
_VAC_HVGO_FRAC = 0.25
_VAC_VR_FRAC = 0.50

# Coker yield fractions (typical heavy vacuum residue, api~10, ccr~12)
# Sums to ~1.0 (mass balance). HGO is the remainder.
_COKER_NAPHTHA_FRAC = 0.13
_COKER_GO_FRAC = 0.265
_COKER_COKE_FRAC = 0.41
_COKER_GAS_FRAC = 0.105
_COKER_HGO_FRAC = max(0.0, 1.0 - _COKER_NAPHTHA_FRAC - _COKER_GO_FRAC - _COKER_COKE_FRAC - _COKER_GAS_FRAC)

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
    # Sprint 14: C5/C6 isomerate (RON 83, near-zero benzene/aromatics)
    "isomerate":{"ron": 83.0, "rvp": 14.0, "sulfur": 0.0001,"spg": 0.65, "benzene": 0.0, "aromatics": 0.5, "olefins": 0.5},
    # Sprint 15: Aromatics reformer raffinate (low RON, very clean)
    "raffinate":{"ron": 60.0, "rvp": 3.0,  "sulfur": 0.0005,"spg": 0.72, "benzene": 0.0, "aromatics": 5.0, "olefins": 0.5},
    # Sprint 15: Dimersol dimate (high RON, HIGH olefins - C6 alkenes)
    "dimate":   {"ron": 96.0, "rvp": 3.0,  "sulfur": 0.0001,"spg": 0.72, "benzene": 0.0, "aromatics": 1.0, "olefins": 80.0},
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

        # Sprint 12: Vacuum unit + Delayed coker
        vacuum_unit = config.units.get("vacuum_1")
        self.has_vacuum = vacuum_unit is not None
        self.vacuum_capacity = vacuum_unit.capacity if vacuum_unit else 0.0

        coker_unit = config.units.get("coker_1")
        self.has_coker = coker_unit is not None
        self.coker_capacity = coker_unit.capacity if coker_unit else 0.0

        # Sprint 13: Hydrocracker
        hcu_unit = config.units.get("hcu_1")
        self.has_hcu = hcu_unit is not None
        self.hcu_capacity = hcu_unit.capacity if hcu_unit else 0.0

        # Sprint 14: C5/C6 + C4 Isomerization
        isom56_unit = config.units.get("isom_c56")
        self.has_isom56 = isom56_unit is not None
        self.isom56_capacity = isom56_unit.capacity if isom56_unit else 0.0

        isomc4_unit = config.units.get("isom_c4")
        self.has_isomc4 = isomc4_unit is not None
        self.isomc4_capacity = isomc4_unit.capacity if isomc4_unit else 0.0

        # Sprint 15: Aromatics reformer + Dimersol
        arom_unit = config.units.get("arom_reformer")
        self.has_arom = arom_unit is not None
        self.arom_capacity = arom_unit.capacity if arom_unit else 0.0

        dim_unit = config.units.get("dimersol")
        self.has_dimersol = dim_unit is not None
        self.dimersol_capacity = dim_unit.capacity if dim_unit else 0.0

        # Sprint 16: Gas plants (Unsaturated + Saturated)
        ugp_unit = config.units.get("ugp_1")
        self.has_ugp = ugp_unit is not None
        self.ugp_capacity = ugp_unit.capacity if ugp_unit else 0.0

        sgp_unit = config.units.get("sgp_1")
        self.has_sgp = sgp_unit is not None
        self.sgp_capacity = sgp_unit.capacity if sgp_unit else 0.0

        # Sprint A: Sulfur complex (Amine + SRU + Tail Gas Treatment)
        amine_unit = config.units.get("amine_1")
        self.has_amine = amine_unit is not None
        self.amine_capacity = amine_unit.capacity if amine_unit else 0.0

        sru_unit = config.units.get("sru_1")
        self.has_sru = sru_unit is not None
        self.sru_capacity = sru_unit.capacity if sru_unit else 0.0

        tgt_unit = config.units.get("tgt_1")
        self.has_tgt = tgt_unit is not None
        self.tgt_capacity = tgt_unit.capacity if tgt_unit else 0.0

        # Sprint A.1: per-crude and per-cut elemental-S mass coefficients
        # precomputed from assay data.  These let the LP track sulfur as a
        # linear expression in crude_rate without per-route decisions.
        #
        #   _crude_s_lt_per_bbl[c]     — LT S per bbl of crude c
        #   _cut_s_lt_per_bbl[k]       — LT S per bbl of cut k (library-
        #                                weighted average S content of cut k)
        #
        # Used to replace Sprint A's volumetric H2S constants with
        # assay-driven values, and to close the integrity balance.
        self._crude_s_lt_per_bbl, self._cut_s_lt_per_bbl = (
            self._compute_sulfur_coefficients(config)
        )

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
        if self.has_vacuum:
            self._add_vacuum_constraints(m)
        if self.has_coker:
            self._add_coker_constraints(m)
        if self.has_hcu:
            self._add_hcu_constraints(m)
        if self.has_isom56:
            self._add_isom56_constraints(m)
        if self.has_isomc4:
            self._add_isomc4_constraints(m)
        if self.has_arom:
            self._add_arom_constraints(m)
        if self.has_dimersol:
            self._add_dimersol_constraints(m)
        if self.has_ugp:
            self._add_ugp_constraints(m)
        if self.has_sgp:
            self._add_sgp_constraints(m)
        if self.has_amine or self.has_sru or self.has_tgt:
            self._add_sulfur_complex_constraints(m)
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
    # Sulfur coefficients (Sprint A.1)
    # ------------------------------------------------------------------

    @staticmethod
    def _compute_sulfur_coefficients(
        config: "RefineryConfig",
    ) -> tuple[dict[str, float], dict[str, float]]:
        """Precompute per-crude and per-cut elemental-S mass coefficients.

        Returns:
            crude_s_lt_per_bbl: {crude_id: LT S per bbl of whole crude}
            cut_s_lt_per_bbl:   {cut_name: LT S per bbl of cut k}, weighted
                                over the library by ``max_rate``.

        Basis: 1 bbl = 0.158987 m³, water density 1000 kg/m³, 1 LT = 1016.047
        kg.  Per-cut S content uses the cut's own API (falls back to whole-
        crude API) and its ``properties.sulfur`` wt% (falls back to 0).
        """
        bbl_m3 = 0.158987
        water_kg_m3 = 1000.0
        kg_per_lt = 1016.047
        cut_names = [
            "lpg", "light_naphtha", "heavy_naphtha", "kerosene",
            "diesel", "vgo", "vacuum_residue",
        ]

        def api_to_spg(api: float) -> float:
            return 141.5 / ((api or 30.0) + 131.5)

        crude_s: dict[str, float] = {}
        # Accumulate weighted cut S for library average
        weighted_cut_s_per_bbl_cut: dict[str, float] = {k: 0.0 for k in cut_names}
        total_weight = 0.0
        for cid in config.crude_library.list_crudes():
            assay = config.crude_library.get(cid)
            if assay is None:
                continue
            # Whole-crude S/bbl
            crude_spg = api_to_spg(assay.api or 30.0)
            crude_mass_lt_per_bbl = bbl_m3 * water_kg_m3 * crude_spg / kg_per_lt
            s_wt_frac = (assay.sulfur or 0.0) / 100.0
            crude_s[cid] = crude_mass_lt_per_bbl * s_wt_frac

            weight = max(assay.max_rate or 0.0, 0.0)
            total_weight += weight
            for cut in assay.cuts:
                if cut.name not in weighted_cut_s_per_bbl_cut:
                    continue
                cut_api = (cut.properties.api if cut.properties else None) or assay.api or 30.0
                cut_spg = api_to_spg(cut_api)
                cut_mass_lt_per_bbl = bbl_m3 * water_kg_m3 * cut_spg / kg_per_lt
                cut_s_wt = (
                    (cut.properties.sulfur if cut.properties else None) or 0.0
                ) / 100.0
                weighted_cut_s_per_bbl_cut[cut.name] += (
                    weight * cut_mass_lt_per_bbl * cut_s_wt
                )

        cut_s: dict[str, float] = {}
        for k in cut_names:
            cut_s[k] = (
                weighted_cut_s_per_bbl_cut[k] / total_weight if total_weight > 0 else 0.0
            )
        return crude_s, cut_s

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

        # --- Vacuum unit variables (Sprint 12) ---
        # Feed: CDU vacuum_residue cut. Splits into LVGO + HVGO + heavy vacuum residue.
        if self.has_vacuum:
            m.vac_feed = pyo.Var(m.PERIODS, bounds=(0.0, self.vacuum_capacity), initialize=0.0)
            m.vacuum_lvgo = pyo.Var(m.PERIODS, bounds=(0.0, _BIG_M), initialize=0.0)
            m.vacuum_hvgo = pyo.Var(m.PERIODS, bounds=(0.0, _BIG_M), initialize=0.0)
            m.vacuum_vr_to_coker = pyo.Var(m.PERIODS, bounds=(0.0, _BIG_M), initialize=0.0)
            m.vacuum_vr_to_fo = pyo.Var(m.PERIODS, bounds=(0.0, _BIG_M), initialize=0.0)

        # --- C5/C6 Isomerization variables (Sprint 14) ---
        # LN feed, produces isomerate at 98% vol yield
        if self.has_isom56:
            m.ln_to_isom = pyo.Var(m.PERIODS, bounds=(0.0, self.isom56_capacity), initialize=0.0)
            m.isomerate_vol = pyo.Var(m.PERIODS, bounds=(0.0, _BIG_M), initialize=0.0)

        # --- Aromatics Reformer variables (Sprint 15) ---
        # Competes with mogas reformer for HN feed. Produces BTX (petchem
        # extract), raffinate (low-RON blend stock), H2, LPG.
        if self.has_arom:
            m.hn_to_arom = pyo.Var(m.PERIODS, bounds=(0.0, self.arom_capacity), initialize=0.0)
            m.btx_volume = pyo.Var(m.PERIODS, bounds=(0.0, _BIG_M), initialize=0.0)
            m.arom_raffinate_vol = pyo.Var(m.PERIODS, bounds=(0.0, _BIG_M), initialize=0.0)
            m.arom_hydrogen = pyo.Var(m.PERIODS, bounds=(0.0, _BIG_M), initialize=0.0)
            m.arom_lpg = pyo.Var(m.PERIODS, bounds=(0.0, _BIG_M), initialize=0.0)

        # --- Dimersol variables (Sprint 15) ---
        # Competes with alkylation for FCC propylene. Produces dimate (high
        # RON + high olefins gasoline blend component).
        if self.has_dimersol:
            m.prop_to_dimersol = pyo.Var(m.PERIODS, bounds=(0.0, self.dimersol_capacity), initialize=0.0)
            m.dimate_vol = pyo.Var(m.PERIODS, bounds=(0.0, _BIG_M), initialize=0.0)

        # --- Unsaturated Gas Plant variables (Sprint 16) ---
        # UGP separates FCC C3/C4 pool into individual components. Gives
        # optimizer visibility into propylene/butylenes/iC4/nC4 vs. lumped LPG.
        if self.has_ugp:
            m.ugp_feed = pyo.Var(m.PERIODS, bounds=(0.0, _BIG_M), initialize=0.0)
            for var_name in [
                "ugp_propylene_vol", "ugp_propane_vol", "ugp_butylene_vol",
                "ugp_ic4_vol", "ugp_nc4_vol", "ugp_fuel_gas_vol",
                "ugp_ic4_to_alky", "ugp_ic4_to_lpg",
                "ugp_nc4_to_c4isom", "ugp_nc4_to_lpg",
            ]:
                setattr(m, var_name, pyo.Var(m.PERIODS, bounds=(0.0, _BIG_M), initialize=0.0))

        # --- Saturated Gas Plant variables (Sprint 16) ---
        # SGP separates CDU + coker + HCU paraffin streams. Produces more
        # iC4 and nC4 that previously were lumped into the LPG pool.
        if self.has_sgp:
            m.sgp_feed = pyo.Var(m.PERIODS, bounds=(0.0, _BIG_M), initialize=0.0)
            for var_name in [
                "sgp_propane_vol", "sgp_ic4_vol", "sgp_nc4_vol", "sgp_fuel_gas_vol",
                "sgp_ic4_to_alky", "sgp_ic4_to_lpg",
                "sgp_nc4_to_c4isom", "sgp_nc4_to_lpg",
            ]:
                setattr(m, var_name, pyo.Var(m.PERIODS, bounds=(0.0, _BIG_M), initialize=0.0))

        # --- C4 Isomerization variables (Sprint 14) ---
        # nC4 feed (from CDU + FCC), produces iC4 for alkylation
        if self.has_isomc4:
            m.nc4_to_c4isom = pyo.Var(m.PERIODS, bounds=(0.0, self.isomc4_capacity), initialize=0.0)
            m.ic4_from_c4isom = pyo.Var(m.PERIODS, bounds=(0.0, _BIG_M), initialize=0.0)

        # --- Hydrocracker variables (Sprint 13) ---
        # HCU feeds on VGO (alternative to FCC). Products: jet, diesel, naphtha, LPG.
        if self.has_hcu:
            m.vgo_to_hcu = pyo.Var(m.PERIODS, bounds=(0.0, self.hcu_capacity), initialize=0.0)
            m.hcu_conversion = pyo.Var(m.PERIODS, bounds=(60.0, 95.0), initialize=80.0)
            m.hcu_naphtha_vol = pyo.Var(m.PERIODS, bounds=(0.0, _BIG_M), initialize=0.0)
            m.hcu_jet_vol = pyo.Var(m.PERIODS, bounds=(0.0, _BIG_M), initialize=0.0)
            m.hcu_diesel_vol = pyo.Var(m.PERIODS, bounds=(0.0, _BIG_M), initialize=0.0)
            m.hcu_lpg_vol = pyo.Var(m.PERIODS, bounds=(0.0, _BIG_M), initialize=0.0)
            m.hcu_unconverted_vol = pyo.Var(m.PERIODS, bounds=(0.0, _BIG_M), initialize=0.0)

        # --- Coker variables (Sprint 12) ---
        if self.has_coker:
            m.coker_feed = pyo.Var(m.PERIODS, bounds=(0.0, self.coker_capacity), initialize=0.0)
            m.coker_naphtha_vol = pyo.Var(m.PERIODS, bounds=(0.0, _BIG_M), initialize=0.0)
            m.coker_go_vol = pyo.Var(m.PERIODS, bounds=(0.0, _BIG_M), initialize=0.0)
            m.coker_hgo_vol = pyo.Var(m.PERIODS, bounds=(0.0, _BIG_M), initialize=0.0)
            m.coker_coke_vol = pyo.Var(m.PERIODS, bounds=(0.0, _BIG_M), initialize=0.0)
            m.coker_gas_vol = pyo.Var(m.PERIODS, bounds=(0.0, _BIG_M), initialize=0.0)
            # Routing: coker GO can go to DHT or fuel oil
            m.coker_go_to_dht = pyo.Var(m.PERIODS, bounds=(0.0, _BIG_M), initialize=0.0)
            m.coker_go_to_fo = pyo.Var(m.PERIODS, bounds=(0.0, _BIG_M), initialize=0.0)

        # --- Sulfur complex variables (Sprint A) ---
        # Units are LT/D throughout.  Amine receives H2S from HTs/FCC/coker;
        # SRU converts H2S to elemental sulfur; TGT recycles SRU tail gas.
        if self.has_amine or self.has_sru or self.has_tgt:
            m.amine_feed = pyo.Var(m.PERIODS, bounds=(0.0, _BIG_M), initialize=0.0)
            m.amine_to_sru = pyo.Var(m.PERIODS, bounds=(0.0, _BIG_M), initialize=0.0)
            m.amine_slip = pyo.Var(m.PERIODS, bounds=(0.0, _BIG_M), initialize=0.0)
            m.sru_feed = pyo.Var(m.PERIODS, bounds=(0.0, _BIG_M), initialize=0.0)
            m.sulfur_produced = pyo.Var(m.PERIODS, bounds=(0.0, _BIG_M), initialize=0.0)
            m.sru_tail_gas_s = pyo.Var(m.PERIODS, bounds=(0.0, _BIG_M), initialize=0.0)
            m.tgt_feed = pyo.Var(m.PERIODS, bounds=(0.0, _BIG_M), initialize=0.0)
            m.tgt_recycle_s = pyo.Var(m.PERIODS, bounds=(0.0, _BIG_M), initialize=0.0)
            m.s_to_stack = pyo.Var(m.PERIODS, bounds=(0.0, _BIG_M), initialize=0.0)
            m.sulfur_sales = pyo.Var(m.PERIODS, bounds=(0.0, _BIG_M), initialize=0.0)
            # Sprint A.1: bucket of elemental S leaving the refinery in
            # finished liquid/solid products (gasoline, diesel, jet, fuel
            # oil, naphtha, LPG, coke).  Closed against crude_s_feed so
            # that total S accounting is crude-assay-consistent.
            m.products_s_lt = pyo.Var(m.PERIODS, bounds=(0.0, _BIG_M), initialize=0.0)

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
        has_isomc4 = self.has_isomc4
        has_ugp = self.has_ugp
        has_sgp = self.has_sgp
        has_dim = self.has_dimersol

        def alky_yield_rule(m: Any, p: int) -> Any:
            return m.alkylate_volume[p] == m.c3c4_to_alky[p] * 1.75

        m.alky_yield_def = pyo.Constraint(m.PERIODS, rule=alky_yield_rule)

        # iC4 requirement: 1.1× olefin feed. Supply = ic4_purchased + ic4_from_c4isom
        # plus UGP/SGP iC4 (when gas plants are present, these provide a
        # natural paraffin source that previously was lumped into LPG sales).
        def alky_ic4_rule(m: Any, p: int) -> Any:
            supply = m.ic4_purchased[p]
            if has_isomc4:
                supply += m.ic4_from_c4isom[p]
            if has_ugp:
                supply += m.ugp_ic4_to_alky[p]
            if has_sgp:
                supply += m.sgp_ic4_to_alky[p]
            return supply >= m.c3c4_to_alky[p] * 1.1

        m.alky_ic4_con = pyo.Constraint(m.PERIODS, rule=alky_ic4_rule)

        # Feed limit: olefins available for alky + dimersol.
        # Without UGP: approximated as FCC C3+C4 pool (lumped).
        # With UGP: exact olefin pool = propylene + butylenes (C3/C4 paraffins
        # separated out by the gas plant and routed elsewhere).
        def alky_feed_rule(m: Any, p: int) -> Any:
            if has_ugp:
                olefins = m.ugp_propylene_vol[p] + m.ugp_butylene_vol[p]
                demand = m.c3c4_to_alky[p]
                if has_dim:
                    demand += m.prop_to_dimersol[p]
                return demand <= olefins
            return m.c3c4_to_alky[p] <= m.fcc_c3_vol[p] + m.fcc_c4_vol[p]

        m.alky_feed_con = pyo.Constraint(m.PERIODS, rule=alky_feed_rule)

    # ------------------------------------------------------------------
    # Vacuum unit constraints (Sprint 12)
    # ------------------------------------------------------------------

    def _add_vacuum_constraints(self, m: pyo.ConcreteModel) -> None:
        """Vacuum unit yields: feed -> LVGO + HVGO + vacuum residue."""
        vac_cap = self.vacuum_capacity

        def vac_cap_rule(m: Any, p: int) -> Any:
            return m.vac_feed[p] <= vac_cap
        m.vacuum_capacity_con = pyo.Constraint(m.PERIODS, rule=vac_cap_rule)

        def vac_lvgo_rule(m: Any, p: int) -> Any:
            return m.vacuum_lvgo[p] == m.vac_feed[p] * _VAC_LVGO_FRAC
        m.vacuum_lvgo_def = pyo.Constraint(m.PERIODS, rule=vac_lvgo_rule)

        def vac_hvgo_rule(m: Any, p: int) -> Any:
            return m.vacuum_hvgo[p] == m.vac_feed[p] * _VAC_HVGO_FRAC
        m.vacuum_hvgo_def = pyo.Constraint(m.PERIODS, rule=vac_hvgo_rule)

        # Vacuum residue split: to coker or to fuel oil
        def vac_vr_disp_rule(m: Any, p: int) -> Any:
            return m.vacuum_vr_to_coker[p] + m.vacuum_vr_to_fo[p] == m.vac_feed[p] * _VAC_VR_FRAC
        m.vacuum_vr_disposition = pyo.Constraint(m.PERIODS, rule=vac_vr_disp_rule)

        # When no coker, force vacuum_vr_to_coker == 0 (no destination)
        if not self.has_coker:
            def no_coker_rule(m: Any, p: int) -> Any:
                return m.vacuum_vr_to_coker[p] == 0.0
            m.vacuum_vr_no_coker_con = pyo.Constraint(m.PERIODS, rule=no_coker_rule)

    # ------------------------------------------------------------------
    # Coker constraints (Sprint 12)
    # ------------------------------------------------------------------

    def _add_coker_constraints(self, m: pyo.ConcreteModel) -> None:
        """Coker yield equations: vac residue -> naphtha + GO + HGO + coke + gas."""
        coker_cap = self.coker_capacity
        has_vacuum = self.has_vacuum

        def coker_cap_rule(m: Any, p: int) -> Any:
            return m.coker_feed[p] <= coker_cap
        m.coker_capacity_con = pyo.Constraint(m.PERIODS, rule=coker_cap_rule)

        # Coker feed = either vacuum unit residue (preferred) or CDU vac_resid directly
        def coker_feed_source_rule(m: Any, p: int) -> Any:
            if has_vacuum:
                return m.coker_feed[p] == m.vacuum_vr_to_coker[p]
            # Without vacuum unit, coker takes from CDU vacuum_residue cut directly
            return m.coker_feed[p] <= self._cdu_cut_volume(m, "vacuum_residue", p)
        m.coker_feed_source_con = pyo.Constraint(m.PERIODS, rule=coker_feed_source_rule)

        # Yield definitions (linear in feed)
        def coker_naphtha_rule(m: Any, p: int) -> Any:
            return m.coker_naphtha_vol[p] == m.coker_feed[p] * _COKER_NAPHTHA_FRAC
        m.coker_naphtha_def = pyo.Constraint(m.PERIODS, rule=coker_naphtha_rule)

        def coker_go_rule(m: Any, p: int) -> Any:
            return m.coker_go_vol[p] == m.coker_feed[p] * _COKER_GO_FRAC
        m.coker_go_def = pyo.Constraint(m.PERIODS, rule=coker_go_rule)

        def coker_hgo_rule(m: Any, p: int) -> Any:
            return m.coker_hgo_vol[p] == m.coker_feed[p] * _COKER_HGO_FRAC
        m.coker_hgo_def = pyo.Constraint(m.PERIODS, rule=coker_hgo_rule)

        def coker_coke_rule(m: Any, p: int) -> Any:
            return m.coker_coke_vol[p] == m.coker_feed[p] * _COKER_COKE_FRAC
        m.coker_coke_def = pyo.Constraint(m.PERIODS, rule=coker_coke_rule)

        def coker_gas_rule(m: Any, p: int) -> Any:
            return m.coker_gas_vol[p] == m.coker_feed[p] * _COKER_GAS_FRAC
        m.coker_gas_def = pyo.Constraint(m.PERIODS, rule=coker_gas_rule)

        # Coker GO disposition: to DHT (if exists) or to fuel oil.
        # When no DHT, force coker_go_to_dht == 0 (only fuel oil path available).
        has_dht_local = self.has_dht

        def coker_go_disp_rule(m: Any, p: int) -> Any:
            return m.coker_go_to_dht[p] + m.coker_go_to_fo[p] == m.coker_go_vol[p]
        m.coker_go_disposition = pyo.Constraint(m.PERIODS, rule=coker_go_disp_rule)

        if not has_dht_local:
            def coker_go_no_dht_rule(m: Any, p: int) -> Any:
                return m.coker_go_to_dht[p] == 0.0
            m.coker_go_no_dht_con = pyo.Constraint(m.PERIODS, rule=coker_go_no_dht_rule)

    # ------------------------------------------------------------------
    # Hydrocracker constraints (Sprint 13)
    # ------------------------------------------------------------------

    def _add_hcu_constraints(self, m: pyo.ConcreteModel) -> None:
        """HCU yield equations: VGO -> naphtha + jet + diesel + LPG + unconverted.

        Yields are NONLINEAR (bilinear in feed x conversion-dependent share).
        Shares (sum to 1.0 at any conversion):
          naphtha_share  = 0.25 + 0.002 * (conv - 80)
          jet_share      = 0.32 - 0.001 * (conv - 80)
          diesel_share   = 0.35 - 0.0005 * (conv - 80)
          lpg_share      = 0.08 - 0.0005 * (conv - 80)
          unconv         = (100 - conv) / 100
        """
        hcu_cap = self.hcu_capacity

        def hcu_cap_rule(m: Any, p: int) -> Any:
            return m.vgo_to_hcu[p] <= hcu_cap
        m.hcu_capacity_con = pyo.Constraint(m.PERIODS, rule=hcu_cap_rule)

        def hcu_naphtha_rule(m: Any, p: int) -> Any:
            delta = m.hcu_conversion[p] - 80.0
            share = 0.25 + 0.002 * delta
            conv_frac = m.hcu_conversion[p] / 100.0
            return m.hcu_naphtha_vol[p] == m.vgo_to_hcu[p] * share * conv_frac
        m.hcu_naphtha_def = pyo.Constraint(m.PERIODS, rule=hcu_naphtha_rule)

        def hcu_jet_rule(m: Any, p: int) -> Any:
            delta = m.hcu_conversion[p] - 80.0
            share = 0.32 - 0.001 * delta
            conv_frac = m.hcu_conversion[p] / 100.0
            return m.hcu_jet_vol[p] == m.vgo_to_hcu[p] * share * conv_frac
        m.hcu_jet_def = pyo.Constraint(m.PERIODS, rule=hcu_jet_rule)

        def hcu_diesel_rule(m: Any, p: int) -> Any:
            delta = m.hcu_conversion[p] - 80.0
            share = 0.35 - 0.0005 * delta
            conv_frac = m.hcu_conversion[p] / 100.0
            return m.hcu_diesel_vol[p] == m.vgo_to_hcu[p] * share * conv_frac
        m.hcu_diesel_def = pyo.Constraint(m.PERIODS, rule=hcu_diesel_rule)

        def hcu_lpg_rule(m: Any, p: int) -> Any:
            delta = m.hcu_conversion[p] - 80.0
            share = 0.08 - 0.0005 * delta
            conv_frac = m.hcu_conversion[p] / 100.0
            return m.hcu_lpg_vol[p] == m.vgo_to_hcu[p] * share * conv_frac
        m.hcu_lpg_def = pyo.Constraint(m.PERIODS, rule=hcu_lpg_rule)

        def hcu_unconv_rule(m: Any, p: int) -> Any:
            unconv_frac = (100.0 - m.hcu_conversion[p]) / 100.0
            return m.hcu_unconverted_vol[p] == m.vgo_to_hcu[p] * unconv_frac
        m.hcu_unconverted_def = pyo.Constraint(m.PERIODS, rule=hcu_unconv_rule)

    # ------------------------------------------------------------------
    # C5/C6 Isomerization constraints (Sprint 14)
    # ------------------------------------------------------------------

    def _add_isom56_constraints(self, m: pyo.ConcreteModel) -> None:
        """C5/C6 isom: LN -> isomerate at 98% volume yield."""
        cap = self.isom56_capacity

        def cap_rule(m: Any, p: int) -> Any:
            return m.ln_to_isom[p] <= cap
        m.isom56_capacity_con = pyo.Constraint(m.PERIODS, rule=cap_rule)

        def yield_rule(m: Any, p: int) -> Any:
            return m.isomerate_vol[p] == m.ln_to_isom[p] * _ISOM56_VOL_YIELD
        m.isom56_yield_def = pyo.Constraint(m.PERIODS, rule=yield_rule)

    # ------------------------------------------------------------------
    # C4 Isomerization constraints (Sprint 14)
    # ------------------------------------------------------------------

    def _add_isomc4_constraints(self, m: pyo.ConcreteModel) -> None:
        """C4 isom: nC4 -> iC4 at 95% yield (with recycle).

        Feed sources: CDU nC4 (via nc4_to_c4isom) plus — when gas plants exist —
        UGP nC4 (from FCC C4 pool) and SGP nC4 (from CDU/coker/HCU streams).
        """
        cap = self.isomc4_capacity
        has_ugp = self.has_ugp
        has_sgp = self.has_sgp

        def _total_feed(m: Any, p: int) -> Any:
            total = m.nc4_to_c4isom[p]
            if has_ugp:
                total += m.ugp_nc4_to_c4isom[p]
            if has_sgp:
                total += m.sgp_nc4_to_c4isom[p]
            return total

        def cap_rule(m: Any, p: int) -> Any:
            return _total_feed(m, p) <= cap
        m.isomc4_capacity_con = pyo.Constraint(m.PERIODS, rule=cap_rule)

        def yield_rule(m: Any, p: int) -> Any:
            return m.ic4_from_c4isom[p] == _total_feed(m, p) * _ISOMC4_IC4_YIELD
        m.isomc4_yield_def = pyo.Constraint(m.PERIODS, rule=yield_rule)

    # ------------------------------------------------------------------
    # Aromatics Reformer constraints (Sprint 15)
    # ------------------------------------------------------------------

    def _add_arom_constraints(self, m: pyo.ConcreteModel) -> None:
        """Aromatics reformer: HN -> BTX + raffinate + H2 + LPG."""
        cap = self.arom_capacity

        def cap_rule(m: Any, p: int) -> Any:
            return m.hn_to_arom[p] <= cap
        m.arom_capacity_con = pyo.Constraint(m.PERIODS, rule=cap_rule)

        def btx_rule(m: Any, p: int) -> Any:
            return m.btx_volume[p] == m.hn_to_arom[p] * _AROM_BTX_YIELD
        m.arom_btx_def = pyo.Constraint(m.PERIODS, rule=btx_rule)

        def raff_rule(m: Any, p: int) -> Any:
            return m.arom_raffinate_vol[p] == m.hn_to_arom[p] * _AROM_RAFFINATE_YIELD
        m.arom_raffinate_def = pyo.Constraint(m.PERIODS, rule=raff_rule)

        def h2_rule(m: Any, p: int) -> Any:
            # H2 production in MMSCFD: wt% * feed * 500 SCF/bbl / 1e6
            return m.arom_hydrogen[p] == m.hn_to_arom[p] * _AROM_H2_WT * 500.0 / 1e6
        m.arom_h2_def = pyo.Constraint(m.PERIODS, rule=h2_rule)

        def lpg_rule(m: Any, p: int) -> Any:
            return m.arom_lpg[p] == m.hn_to_arom[p] * _AROM_LPG_YIELD
        m.arom_lpg_def = pyo.Constraint(m.PERIODS, rule=lpg_rule)

    # ------------------------------------------------------------------
    # Dimersol constraints (Sprint 15)
    # ------------------------------------------------------------------

    def _add_dimersol_constraints(self, m: pyo.ConcreteModel) -> None:
        """Dimersol: propylene -> dimate at 90% yield."""
        cap = self.dimersol_capacity

        def cap_rule(m: Any, p: int) -> Any:
            return m.prop_to_dimersol[p] <= cap
        m.dimersol_capacity_con = pyo.Constraint(m.PERIODS, rule=cap_rule)

        def yield_rule(m: Any, p: int) -> Any:
            return m.dimate_vol[p] == m.prop_to_dimersol[p] * _DIMERSOL_YIELD
        m.dimersol_yield_def = pyo.Constraint(m.PERIODS, rule=yield_rule)

        # Propylene feed must come from FCC C3 stream (after alkylation takes its share)
        # Without UGP: approximated by fcc_c3_vol (the propylene pool).
        # With UGP: exact propylene stream from the gas plant. Competition
        # with alkylation for propylene is enforced in alky_feed_con.
        has_ugp = self.has_ugp

        def feed_rule(m: Any, p: int) -> Any:
            if has_ugp:
                return m.prop_to_dimersol[p] <= m.ugp_propylene_vol[p]
            return m.prop_to_dimersol[p] <= m.fcc_c3_vol[p]
        m.dimersol_feed_con = pyo.Constraint(m.PERIODS, rule=feed_rule)

    # ------------------------------------------------------------------
    # Unsaturated Gas Plant constraints (Sprint 16)
    # ------------------------------------------------------------------

    def _add_ugp_constraints(self, m: pyo.ConcreteModel) -> None:
        """UGP: FCC C3/C4 pool → propylene + propane + butylene + iC4 + nC4 + fuel gas."""
        ugp_cap = self.ugp_capacity

        # UGP feed = all FCC C3 + C4 (light ends from the cat cracker)
        def ugp_feed_rule(m: Any, p: int) -> Any:
            return m.ugp_feed[p] == m.fcc_c3_vol[p] + m.fcc_c4_vol[p]
        m.ugp_feed_def = pyo.Constraint(m.PERIODS, rule=ugp_feed_rule)

        # Optional capacity limit — only enforced if capacity > 0
        if ugp_cap > 0.0:
            def ugp_cap_rule(m: Any, p: int) -> Any:
                return m.ugp_feed[p] <= ugp_cap
            m.ugp_capacity_con = pyo.Constraint(m.PERIODS, rule=ugp_cap_rule)

        # Yield constraints — linear split fractions from gas_plant module
        def ugp_propylene_rule(m: Any, p: int) -> Any:
            return m.ugp_propylene_vol[p] == m.ugp_feed[p] * UGP_PROPYLENE_FRAC
        m.ugp_propylene_def = pyo.Constraint(m.PERIODS, rule=ugp_propylene_rule)

        def ugp_propane_rule(m: Any, p: int) -> Any:
            return m.ugp_propane_vol[p] == m.ugp_feed[p] * UGP_PROPANE_FRAC
        m.ugp_propane_def = pyo.Constraint(m.PERIODS, rule=ugp_propane_rule)

        def ugp_butylene_rule(m: Any, p: int) -> Any:
            return m.ugp_butylene_vol[p] == m.ugp_feed[p] * UGP_BUTYLENE_FRAC
        m.ugp_butylene_def = pyo.Constraint(m.PERIODS, rule=ugp_butylene_rule)

        def ugp_ic4_rule(m: Any, p: int) -> Any:
            return m.ugp_ic4_vol[p] == m.ugp_feed[p] * UGP_ISOBUTANE_FRAC
        m.ugp_ic4_def = pyo.Constraint(m.PERIODS, rule=ugp_ic4_rule)

        def ugp_nc4_rule(m: Any, p: int) -> Any:
            return m.ugp_nc4_vol[p] == m.ugp_feed[p] * UGP_NORMAL_BUTANE_FRAC
        m.ugp_nc4_def = pyo.Constraint(m.PERIODS, rule=ugp_nc4_rule)

        def ugp_fuel_gas_rule(m: Any, p: int) -> Any:
            return m.ugp_fuel_gas_vol[p] == m.ugp_feed[p] * UGP_FUEL_GAS_FRAC
        m.ugp_fuel_gas_def = pyo.Constraint(m.PERIODS, rule=ugp_fuel_gas_rule)

        # iC4 disposition: alky feed OR LPG sale
        def ugp_ic4_split_rule(m: Any, p: int) -> Any:
            return m.ugp_ic4_to_alky[p] + m.ugp_ic4_to_lpg[p] == m.ugp_ic4_vol[p]
        m.ugp_ic4_split = pyo.Constraint(m.PERIODS, rule=ugp_ic4_split_rule)

        # nC4 disposition: C4 isom feed OR LPG sale
        def ugp_nc4_split_rule(m: Any, p: int) -> Any:
            return m.ugp_nc4_to_c4isom[p] + m.ugp_nc4_to_lpg[p] == m.ugp_nc4_vol[p]
        m.ugp_nc4_split = pyo.Constraint(m.PERIODS, rule=ugp_nc4_split_rule)

        # If no C4 isom exists, UGP nC4 can't go there
        if not self.has_isomc4:
            def ugp_nc4_no_isom_rule(m: Any, p: int) -> Any:
                return m.ugp_nc4_to_c4isom[p] == 0.0
            m.ugp_nc4_no_isom_con = pyo.Constraint(m.PERIODS, rule=ugp_nc4_no_isom_rule)

        # If no alky exists, UGP iC4 can't go there
        if not self.has_alky:
            def ugp_ic4_no_alky_rule(m: Any, p: int) -> Any:
                return m.ugp_ic4_to_alky[p] == 0.0
            m.ugp_ic4_no_alky_con = pyo.Constraint(m.PERIODS, rule=ugp_ic4_no_alky_rule)

    # ------------------------------------------------------------------
    # Saturated Gas Plant constraints (Sprint 16)
    # ------------------------------------------------------------------

    def _add_sgp_constraints(self, m: pyo.ConcreteModel) -> None:
        """SGP: CDU/coker/HCU paraffin streams → propane + iC4 + nC4 + fuel gas."""
        sgp_cap = self.sgp_capacity
        has_coker = self.has_coker
        has_hcu = self.has_hcu

        # SGP feed = CDU non-nC4 LPG + coker gas + HCU LPG (saturated streams only)
        # The non-nC4 CDU LPG fraction was previously lumped straight into LPG
        # sales; now it gets fractionated into propane/iC4/nC4 for proper
        # allocation (alky feed iC4, C4 isom feed nC4, or LPG sale propane).
        def sgp_feed_rule(m: Any, p: int) -> Any:
            cdu_non_nc4 = (1.0 - _NC4_FRACTION_OF_LPG) * self._cdu_cut_volume(m, "lpg", p)
            total = cdu_non_nc4
            if has_coker:
                total += m.coker_gas_vol[p]
            if has_hcu:
                total += m.hcu_lpg_vol[p]
            return m.sgp_feed[p] == total
        m.sgp_feed_def = pyo.Constraint(m.PERIODS, rule=sgp_feed_rule)

        if sgp_cap > 0.0:
            def sgp_cap_rule(m: Any, p: int) -> Any:
                return m.sgp_feed[p] <= sgp_cap
            m.sgp_capacity_con = pyo.Constraint(m.PERIODS, rule=sgp_cap_rule)

        # Yield constraints — linear splits from gas_plant module
        def sgp_propane_rule(m: Any, p: int) -> Any:
            return m.sgp_propane_vol[p] == m.sgp_feed[p] * SGP_PROPANE_FRAC
        m.sgp_propane_def = pyo.Constraint(m.PERIODS, rule=sgp_propane_rule)

        def sgp_ic4_rule(m: Any, p: int) -> Any:
            return m.sgp_ic4_vol[p] == m.sgp_feed[p] * SGP_ISOBUTANE_FRAC
        m.sgp_ic4_def = pyo.Constraint(m.PERIODS, rule=sgp_ic4_rule)

        def sgp_nc4_rule(m: Any, p: int) -> Any:
            return m.sgp_nc4_vol[p] == m.sgp_feed[p] * SGP_NORMAL_BUTANE_FRAC
        m.sgp_nc4_def = pyo.Constraint(m.PERIODS, rule=sgp_nc4_rule)

        def sgp_fuel_gas_rule(m: Any, p: int) -> Any:
            return m.sgp_fuel_gas_vol[p] == m.sgp_feed[p] * SGP_FUEL_GAS_FRAC
        m.sgp_fuel_gas_def = pyo.Constraint(m.PERIODS, rule=sgp_fuel_gas_rule)

        # iC4 disposition: alky feed OR LPG sale
        def sgp_ic4_split_rule(m: Any, p: int) -> Any:
            return m.sgp_ic4_to_alky[p] + m.sgp_ic4_to_lpg[p] == m.sgp_ic4_vol[p]
        m.sgp_ic4_split = pyo.Constraint(m.PERIODS, rule=sgp_ic4_split_rule)

        # nC4 disposition: C4 isom feed OR LPG sale
        def sgp_nc4_split_rule(m: Any, p: int) -> Any:
            return m.sgp_nc4_to_c4isom[p] + m.sgp_nc4_to_lpg[p] == m.sgp_nc4_vol[p]
        m.sgp_nc4_split = pyo.Constraint(m.PERIODS, rule=sgp_nc4_split_rule)

        if not self.has_isomc4:
            def sgp_nc4_no_isom_rule(m: Any, p: int) -> Any:
                return m.sgp_nc4_to_c4isom[p] == 0.0
            m.sgp_nc4_no_isom_con = pyo.Constraint(m.PERIODS, rule=sgp_nc4_no_isom_rule)

        if not self.has_alky:
            def sgp_ic4_no_alky_rule(m: Any, p: int) -> Any:
                return m.sgp_ic4_to_alky[p] == 0.0
            m.sgp_ic4_no_alky_con = pyo.Constraint(m.PERIODS, rule=sgp_ic4_no_alky_rule)

    # ------------------------------------------------------------------
    # Hydrogen balance
    # ------------------------------------------------------------------

    # ------------------------------------------------------------------
    # Sulfur complex constraints (Sprint A)
    # ------------------------------------------------------------------

    def _add_sulfur_complex_constraints(self, m: pyo.ConcreteModel) -> None:
        """Amine → SRU → TGT mass balance with capacity limits.

        H2S from hydrotreaters, FCC, and coker enters the amine unit, which
        concentrates it for the SRU.  The SRU runs modified Claus (~97%
        recovery); tail gas goes to TGT which recovers ~90% of residual S.

        Sprint A.1: H2S generation is now driven by crude-assay S content
        (library-weighted average cut S wt%), not by flat volumetric
        constants.  The ``products_s_lt`` bucket absorbs the residual S
        that stays in finished products, closing the crude-feed balance.

        All flows are LT/D (long tons per day).
        """
        s_cut = self._cut_s_lt_per_bbl  # LT S / bbl of cut
        s_to_h2s = 34.0 / 32.0           # kg H2S per kg S liberated

        def h2s_sources_expr(m: Any, p: int) -> Any:
            """Total H2S production (LT/D) from sulfur-bearing processes.

            Each term is feed_volume × cut_S_per_bbl × unit_removal × 34/32.
            Coefficients are library-weighted averages; actual-slate
            variation is absorbed by the products_s_lt closure.
            """
            h2s = 0.0
            if self.has_goht:
                h2s += (m.vgo_to_goht[p] * s_cut["vgo"]
                        * _HT_S_REMOVAL["vgo"] * s_to_h2s)
            if self.has_scanfiner:
                h2s += (m.hcn_to_scanfiner[p] * s_cut["heavy_naphtha"]
                        * _HT_S_REMOVAL["heavy_naphtha"] * s_to_h2s)
            if self.has_kht:
                h2s += (m.kero_to_kht[p] * s_cut["kerosene"]
                        * _HT_S_REMOVAL["kerosene"] * s_to_h2s)
            if self.has_dht:
                dht_total = m.diesel_to_dht[p] + m.lco_to_dht[p]
                if self.has_coker:
                    dht_total += m.coker_go_to_dht[p]
                h2s += (dht_total * s_cut["diesel"]
                        * _HT_S_REMOVAL["diesel"] * s_to_h2s)
            if self.has_coker:
                # Coker naphtha HT + coker gas H2S (fraction of vac-resid S)
                h2s += (m.coker_naphtha_vol[p] * s_cut["heavy_naphtha"]
                        * _HT_S_REMOVAL["coker_naphtha"] * s_to_h2s)
                h2s += (m.coker_feed[p] * s_cut["vacuum_residue"]
                        * _COKER_S_TO_H2S * s_to_h2s)
            if self.has_hcu:
                h2s += (m.vgo_to_hcu[p] * s_cut["vgo"]
                        * _HT_S_REMOVAL["hcu"] * s_to_h2s)
            # FCC liberates ~30% of VGO sulfur as H2S
            h2s += (m.vgo_to_fcc[p] * s_cut["vgo"]
                    * _FCC_S_TO_H2S * s_to_h2s)
            return h2s

        def crude_s_feed_expr(m: Any, p: int) -> Any:
            """LT/D of elemental S entering CDU from the active crude slate."""
            return sum(
                m.crude_rate[c, p] * self._crude_s_lt_per_bbl.get(c, 0.0)
                for c in m.CRUDES
            )

        # --- Amine unit: H2S balance and capacity ---
        def amine_balance_rule(m: Any, p: int) -> Any:
            return m.amine_feed[p] == h2s_sources_expr(m, p) + m.tgt_recycle_s[p] / _S_PER_H2S
        m.amine_balance_con = pyo.Constraint(m.PERIODS, rule=amine_balance_rule)

        if self.has_amine and self.amine_capacity > 0:
            amine_cap = self.amine_capacity

            def amine_cap_rule(m: Any, p: int) -> Any:
                return m.amine_to_sru[p] <= amine_cap
            m.amine_capacity_con = pyo.Constraint(m.PERIODS, rule=amine_cap_rule)

        def amine_split_rule(m: Any, p: int) -> Any:
            return m.amine_to_sru[p] + m.amine_slip[p] == m.amine_feed[p]
        m.amine_split_con = pyo.Constraint(m.PERIODS, rule=amine_split_rule)

        # Amine removal efficiency: at most 99.5% of feed is captured.
        # (A single equality would force full recovery even above capacity,
        # so express it as an inequality that lets excess slip when the
        # contactor is saturated.)
        def amine_eff_rule(m: Any, p: int) -> Any:
            return m.amine_to_sru[p] <= m.amine_feed[p] * _AMINE_H2S_REMOVAL
        m.amine_eff_con = pyo.Constraint(m.PERIODS, rule=amine_eff_rule)

        # --- SRU: Claus conversion ---
        def sru_feed_rule(m: Any, p: int) -> Any:
            return m.sru_feed[p] == m.amine_to_sru[p]
        m.sru_feed_def = pyo.Constraint(m.PERIODS, rule=sru_feed_rule)

        def sulfur_yield_rule(m: Any, p: int) -> Any:
            return m.sulfur_produced[p] == m.sru_feed[p] * _S_PER_H2S * _SRU_RECOVERY
        m.sru_yield_def = pyo.Constraint(m.PERIODS, rule=sulfur_yield_rule)

        def sru_tail_rule(m: Any, p: int) -> Any:
            return m.sru_tail_gas_s[p] == m.sru_feed[p] * _S_PER_H2S * (1.0 - _SRU_RECOVERY)
        m.sru_tail_def = pyo.Constraint(m.PERIODS, rule=sru_tail_rule)

        if self.has_sru and self.sru_capacity > 0:
            sru_cap = self.sru_capacity

            def sru_cap_rule(m: Any, p: int) -> Any:
                return m.sulfur_produced[p] <= sru_cap
            m.sru_capacity_con = pyo.Constraint(m.PERIODS, rule=sru_cap_rule)

        # --- TGT: recover residual S from SRU tail gas ---
        def tgt_feed_rule(m: Any, p: int) -> Any:
            return m.tgt_feed[p] == m.sru_tail_gas_s[p]
        m.tgt_feed_def = pyo.Constraint(m.PERIODS, rule=tgt_feed_rule)

        if self.has_tgt:
            def tgt_recycle_rule(m: Any, p: int) -> Any:
                return m.tgt_recycle_s[p] == m.tgt_feed[p] * _TGT_RECOVERY
            m.tgt_recycle_def = pyo.Constraint(m.PERIODS, rule=tgt_recycle_rule)

            def tgt_stack_rule(m: Any, p: int) -> Any:
                return m.s_to_stack[p] == m.tgt_feed[p] * (1.0 - _TGT_RECOVERY)
            m.tgt_stack_def = pyo.Constraint(m.PERIODS, rule=tgt_stack_rule)

            if self.tgt_capacity > 0:
                tgt_cap = self.tgt_capacity

                def tgt_cap_rule(m: Any, p: int) -> Any:
                    return m.tgt_feed[p] <= tgt_cap
                m.tgt_capacity_con = pyo.Constraint(m.PERIODS, rule=tgt_cap_rule)
        else:
            # No TGT: no recycle, all SRU tail gas emits to stack
            def no_tgt_recycle_rule(m: Any, p: int) -> Any:
                return m.tgt_recycle_s[p] == 0.0
            m.no_tgt_recycle_con = pyo.Constraint(m.PERIODS, rule=no_tgt_recycle_rule)

            def no_tgt_stack_rule(m: Any, p: int) -> Any:
                return m.s_to_stack[p] == m.sru_tail_gas_s[p]
            m.no_tgt_stack_con = pyo.Constraint(m.PERIODS, rule=no_tgt_stack_rule)

        # Sulfur sales == elemental S produced (merchant sulfur market absorbs
        # whatever we make; demand constraints handled separately).
        def sulfur_sales_rule(m: Any, p: int) -> Any:
            return m.sulfur_sales[p] == m.sulfur_produced[p]
        m.sulfur_sales_con = pyo.Constraint(m.PERIODS, rule=sulfur_sales_rule)

        # Sprint A.1: crude-feed S closure.
        # Every LT of S entering with crude must leave the refinery through
        # exactly one of: SUP sales, SRU stack, amine slip to fuel gas, or
        # in finished liquid/solid products.  ``products_s_lt`` is a free
        # variable that absorbs the complement; this turns an untracked
        # leak into an auditable sink without constraining LP optimization.
        def crude_s_closure_rule(m: Any, p: int) -> Any:
            return (
                crude_s_feed_expr(m, p)
                == m.sulfur_sales[p]
                + m.s_to_stack[p]
                + m.amine_slip[p] * _S_PER_H2S
                + m.products_s_lt[p]
            )
        m.crude_s_closure_con = pyo.Constraint(m.PERIODS, rule=crude_s_closure_rule)

    def _add_hydrogen_balance(self, m: pyo.ConcreteModel) -> None:
        """H2 supply >= H2 demand.  Reformer produces H2; HTs consume it."""
        def h2_rule(m: Any, p: int) -> Any:
            supply = m.h2_purchased[p]
            if self.has_reformer:
                supply += m.reformer_hydrogen[p]
            if self.has_arom:
                supply += m.arom_hydrogen[p]

            demand = 0.0
            if self.has_goht:
                demand += m.vgo_to_goht[p] * 1000.0 / 1e6  # 1000 SCFB → MMSCFD
            if self.has_scanfiner:
                demand += m.hcn_to_scanfiner[p] * 300.0 / 1e6
            if self.has_kht:
                demand += m.kero_to_kht[p] * 600.0 / 1e6
            if self.has_dht:
                dht_feed = m.diesel_to_dht[p] + m.lco_to_dht[p]
                if self.has_coker:
                    dht_feed += m.coker_go_to_dht[p]
                demand += dht_feed * 800.0 / 1e6
            # Coker naphtha needs NHT - dirty stream, ~1500 SCFB (5x normal naphtha)
            if self.has_coker:
                demand += m.coker_naphtha_vol[p] * 1500.0 / 1e6
            # Hydrocracker - biggest consumer, 1500-2550 SCFB depending on conversion
            if self.has_hcu:
                hcu_scfb = 1500.0 + 30.0 * (m.hcu_conversion[p] - 60.0)
                demand += m.vgo_to_hcu[p] * hcu_scfb / 1e6
            # C5/C6 Isom: 150 SCFB, C4 Isom: 50 SCFB (both very low)
            if self.has_isom56:
                demand += m.ln_to_isom[p] * 150.0 / 1e6
            if self.has_isomc4:
                demand += m.nc4_to_c4isom[p] * 50.0 / 1e6

            return supply >= demand

        m.h2_balance_con = pyo.Constraint(m.PERIODS, rule=h2_rule)

    # ------------------------------------------------------------------
    # Disposition constraints
    # ------------------------------------------------------------------

    def _add_disposition_constraints(self, m: pyo.ConcreteModel) -> None:
        # CDU light naphtha — 2 or 3 destinations depending on C5/C6 isom
        has_isom56 = self.has_isom56

        def ln_disp_rule(m: Any, p: int) -> Any:
            lhs = m.ln_to_blend[p] + m.ln_to_sell[p]
            if has_isom56:
                lhs += m.ln_to_isom[p]
            return lhs == self._cdu_cut_volume(m, "light_naphtha", p)

        m.ln_disposition = pyo.Constraint(m.PERIODS, rule=ln_disp_rule)

        # CDU heavy naphtha — multiple destinations: blend, sell, mogas
        # reformer, aromatics reformer.
        has_ref = self.has_reformer
        has_arom = self.has_arom

        def hn_disp_rule(m: Any, p: int) -> Any:
            lhs = m.hn_to_blend[p] + m.hn_to_sell[p]
            if has_ref:
                lhs += m.hn_to_reformer[p]
            if has_arom:
                lhs += m.hn_to_arom[p]
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

        # CDU VGO — multiple destinations: FCC, GO HT, HCU, fuel oil.
        # When vacuum unit exists, vacuum LVGO + HVGO add to the available VGO pool.
        has_goht = self.has_goht
        has_vac = self.has_vacuum
        has_hcu = self.has_hcu

        def vgo_disp_rule(m: Any, p: int) -> Any:
            lhs = m.vgo_to_fcc[p] + m.vgo_to_fo[p]
            if has_goht:
                lhs += m.vgo_to_goht[p]
            if has_hcu:
                lhs += m.vgo_to_hcu[p]
            rhs = self._cdu_cut_volume(m, "vgo", p)
            if has_vac:
                # Vacuum unit recovers VGO from heavy bottoms
                rhs += m.vac_feed[p] * (_VAC_LVGO_FRAC + _VAC_HVGO_FRAC)
            return lhs == rhs

        m.vgo_disposition = pyo.Constraint(m.PERIODS, rule=vgo_disp_rule)

        # NC4 — fraction of CDU LPG cut.
        # Destinations: gasoline blend, LPG sale, C4 isom (feeds alky iC4).
        has_isomc4 = self.has_isomc4

        def nc4_disp_rule(m: Any, p: int) -> Any:
            nc4_avail = _NC4_FRACTION_OF_LPG * self._cdu_cut_volume(m, "lpg", p)
            lhs = m.nc4_to_blend[p] + m.nc4_to_lpg[p]
            if has_isomc4:
                lhs += m.nc4_to_c4isom[p]
            return lhs == nc4_avail

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

        # CDU vacuum residue disposition (Sprint 12)
        # Without vacuum unit: all CDU vac_resid → fuel oil (handled in fuel_oil_def).
        # With vacuum unit: vac_resid splits between vacuum unit feed and fuel oil bypass.
        if self.has_vacuum:
            def vac_resid_disp_rule(m: Any, p: int) -> Any:
                # vac_feed comes from CDU vacuum_residue (with optional fuel oil bypass)
                return m.vac_feed[p] <= self._cdu_cut_volume(m, "vacuum_residue", p)
            m.vac_resid_disposition = pyo.Constraint(m.PERIODS, rule=vac_resid_disp_rule)

    # ------------------------------------------------------------------
    # Product volume constraints
    # ------------------------------------------------------------------

    def _add_product_volume_constraints(self, m: pyo.ConcreteModel) -> None:
        # Gasoline = LN + HN + LCN + HCN + NC4 + reformate + scanfiner_output
        #          + alkylate + isomerate (Sprint 14) + raffinate + dimate (Sprint 15)
        has_ref = self.has_reformer
        has_scan = self.has_scanfiner
        has_alky = self.has_alky
        has_isom56 = self.has_isom56
        has_arom = self.has_arom
        has_dim = self.has_dimersol

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
            if has_isom56:
                total += m.isomerate_vol[p]
            if has_arom:
                total += m.arom_raffinate_vol[p]
            if has_dim:
                total += m.dimate_vol[p]
            return m.gasoline_volume[p] == total

        m.gasoline_def = pyo.Constraint(m.PERIODS, rule=gasoline_def)

        # Naphtha sales = LN_sell + HN_sell + coker_naphtha + hcu_naphtha
        # (HCU naphtha is clean but low RON, sold as surplus naphtha)
        has_coker = self.has_coker
        has_hcu_n = self.has_hcu

        def naphtha_def(m: Any, p: int) -> Any:
            total = m.ln_to_sell[p] + m.hn_to_sell[p]
            if has_coker:
                total += m.coker_naphtha_vol[p]
            if has_hcu_n:
                total += m.hcu_naphtha_vol[p]
            return m.naphtha_volume[p] == total

        m.naphtha_def = pyo.Constraint(m.PERIODS, rule=naphtha_def)

        # Jet: when KHT exists, ALL CDU jet comes from KHT (mandatory).
        # HCU jet bypasses KHT (already meets specs without HT).
        has_kht_ = self.has_kht
        has_hcu_ = self.has_hcu

        def jet_def(m: Any, p: int) -> Any:
            if has_kht_:
                total = m.kero_to_kht[p] * 0.995
            else:
                total = m.kero_to_jet[p]
            if has_hcu_:
                total += m.hcu_jet_vol[p]
            return m.jet_volume[p] == total

        m.jet_def = pyo.Constraint(m.PERIODS, rule=jet_def)

        # Diesel pool:
        # When DHT exists: ALL diesel must go through DHT (mandatory for ULSD spec).
        #   Feed to DHT = diesel_to_dht + lco_to_dht + kero_to_diesel
        #   Diesel volume = DHT output × 99% yield
        # When no DHT: direct CDU diesel + kero_to_diesel + lco_to_diesel.
        has_dht_ = self.has_dht

        has_coker_d = self.has_coker
        has_hcu_d = self.has_hcu

        def diesel_def(m: Any, p: int) -> Any:
            if has_dht_:
                dht_feed = m.diesel_to_dht[p] + m.lco_to_dht[p]
                if has_coker_d:
                    dht_feed += m.coker_go_to_dht[p]
                dht_output = dht_feed * 0.99
                # kero_to_diesel bypasses DHT (it's a lighter cut, lower sulfur)
                total = dht_output + m.kero_to_diesel[p]
            else:
                cdu_diesel = self._cdu_cut_volume(m, "diesel", p)
                total = cdu_diesel + m.kero_to_diesel[p] + m.lco_to_diesel[p]
            # HCU diesel bypasses DHT (already cetane 55+, ultra-low sulfur)
            if has_hcu_d:
                total += m.hcu_diesel_vol[p]
            return m.diesel_volume[p] == total

        m.diesel_def = pyo.Constraint(m.PERIODS, rule=diesel_def)

        # Fuel oil pool = vgo_to_fo + hcn_to_fo + lco_to_fo + (CDU vac_resid bypass)
        # + vacuum_vr_to_fo + coker_hgo + coker_go_to_fo + hcu_unconverted
        has_vac_ = self.has_vacuum
        has_coker_ = self.has_coker
        has_hcu_f = self.has_hcu

        def fuel_oil_def(m: Any, p: int) -> Any:
            cdu_vresid = self._cdu_cut_volume(m, "vacuum_residue", p)
            # CDU vac_resid that's not sent to vacuum unit goes to fuel oil
            vac_resid_to_fo = cdu_vresid - (m.vac_feed[p] if has_vac_ else 0.0)
            total = (
                m.vgo_to_fo[p]
                + m.hcn_to_fo[p]
                + m.lco_to_fo[p]
                + vac_resid_to_fo
            )
            if has_vac_:
                total += m.vacuum_vr_to_fo[p]
            if has_coker_:
                total += m.coker_hgo_vol[p] + m.coker_go_to_fo[p]
            if has_hcu_f:
                # HCU unconverted oil goes to fuel oil (no recycle loop modeled)
                total += m.hcu_unconverted_vol[p]
            return m.fuel_oil_volume[p] == total

        m.fuel_oil_def = pyo.Constraint(m.PERIODS, rule=fuel_oil_def)

        # LPG pool:
        #   Without gas plants — aggregate FCC C3/C4, CDU non-nC4 LPG, HCU LPG etc
        #   directly, and subtract alky/dimersol consumption from the pool.
        #   With UGP (FCC C3/C4 path) — replace fcc_c3/c4 + alky/dim subtraction
        #   with UGP propane + iC4-to-LPG + nC4-to-LPG (exact accounting).
        #   With SGP (CDU/coker/HCU paraffin path) — replace cdu_non_nc4 +
        #   hcu_lpg with SGP propane + iC4-to-LPG + nC4-to-LPG. When SGP is
        #   active, coker_gas_vol becomes a real LPG-producing stream (it
        #   was previously unaccounted for).
        has_hcu_l = self.has_hcu
        has_arom_l = self.has_arom
        has_dim_l = self.has_dimersol
        has_ugp_l = self.has_ugp
        has_sgp_l = self.has_sgp

        def lpg_def(m: Any, p: int) -> Any:
            cdu_non_nc4 = (1.0 - _NC4_FRACTION_OF_LPG) * self._cdu_cut_volume(m, "lpg", p)

            # nC4 routed to LPG sale (from CDU disposition path)
            total = m.nc4_to_lpg[p]

            # Add reformer + aromatics reformer LPG unchanged
            if has_ref:
                total += m.reformer_lpg[p]
            if has_arom_l:
                total += m.arom_lpg[p]

            # UGP replaces FCC C3/C4 direct path
            if has_ugp_l:
                total += (
                    m.ugp_propane_vol[p]
                    + m.ugp_ic4_to_lpg[p]
                    + m.ugp_nc4_to_lpg[p]
                )
            else:
                total += m.fcc_c3_vol[p] + m.fcc_c4_vol[p]
                if has_alky:
                    total -= m.c3c4_to_alky[p]
                if has_dim_l:
                    total -= m.prop_to_dimersol[p]

            # SGP replaces CDU non-nC4 + HCU LPG direct path
            if has_sgp_l:
                total += (
                    m.sgp_propane_vol[p]
                    + m.sgp_ic4_to_lpg[p]
                    + m.sgp_nc4_to_lpg[p]
                )
            else:
                total += cdu_non_nc4
                if has_hcu_l:
                    total += m.hcu_lpg_vol[p]

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

        has_isom56_b = self.has_isom56
        has_arom_b = self.has_arom
        has_dim_b = self.has_dimersol

        def _blend_terms(m: Any, p: int, attr: str) -> Any:
            total = (
                m.ln_to_blend[p] * _BLEND_COMPONENT_PROPS["cdu_ln"][attr]
                + m.hn_to_blend[p] * _BLEND_COMPONENT_PROPS["cdu_hn"][attr]
                + m.fcc_lcn_vol[p] * _BLEND_COMPONENT_PROPS["fcc_lcn"][attr]
                + m.hcn_to_blend[p] * _BLEND_COMPONENT_PROPS["fcc_hcn"][attr]
                + m.nc4_to_blend[p] * _BLEND_COMPONENT_PROPS["n_butane"][attr]
                + m.reformate_purchased[p] * _BLEND_COMPONENT_PROPS["reformate"][attr]
            )
            if has_isom56_b:
                total += m.isomerate_vol[p] * _BLEND_COMPONENT_PROPS["isomerate"][attr]
            if has_arom_b:
                total += m.arom_raffinate_vol[p] * _BLEND_COMPONENT_PROPS["raffinate"][attr]
            if has_dim_b:
                total += m.dimate_vol[p] * _BLEND_COMPONENT_PROPS["dimate"][attr]
            return total

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
            if has_isom56_b:
                bi_total += m.isomerate_vol[p] * bi["isomerate"]
            if has_arom_b:
                bi_total += m.arom_raffinate_vol[p] * bi["raffinate"]
            if has_dim_b:
                bi_total += m.dimate_vol[p] * bi["dimate"]
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
            if has_isom56_b:
                rvp_total += m.isomerate_vol[p] * rvp_pow["isomerate"]
            if has_arom_b:
                rvp_total += m.arom_raffinate_vol[p] * rvp_pow["raffinate"]
            if has_dim_b:
                rvp_total += m.dimate_vol[p] * rvp_pow["dimate"]
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
            if has_isom56_b:
                wt_sulfur += m.isomerate_vol[p] * spg_s("isomerate")
                wt_total += m.isomerate_vol[p] * spg("isomerate")
            if has_arom_b:
                wt_sulfur += m.arom_raffinate_vol[p] * spg_s("raffinate")
                wt_total += m.arom_raffinate_vol[p] * spg("raffinate")
            if has_dim_b:
                wt_sulfur += m.dimate_vol[p] * spg_s("dimate")
                wt_total += m.dimate_vol[p] * spg("dimate")
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

        # Inherit demand_min from config.products when PeriodData doesn't specify.
        # Only min_demand (commitments), not max (caps), to avoid breaking scenarios.
        _PRODUCT_ID_MAP: dict[str, str] = {
            "jet_fuel": "jet",
            "regular_gasoline": "gasoline",
            "ulsd": "diesel",
        }
        config_demand_min: dict[str, float] = {}
        for pid, prod in self.config.products.items():
            builder_key = _PRODUCT_ID_MAP.get(pid)
            if builder_key and prod.min_demand > 0:
                config_demand_min[builder_key] = max(
                    config_demand_min.get(builder_key, 0.0), prod.min_demand
                )

        def demand_min_rule(m: Any, p: int, prod: str) -> Any:
            period = self.plan.periods[p]
            min_d = period.demand_min.get(prod, config_demand_min.get(prod, 0.0))
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
                    dht_total = m.diesel_to_dht[p] + m.lco_to_dht[p]
                    if self.has_coker:
                        dht_total += m.coker_go_to_dht[p]
                    extra_opex += dht_total * 2.5  # $2.50/bbl diesel HT
                if self.has_vacuum:
                    extra_opex += m.vac_feed[p] * _VACUUM_OPEX
                if self.has_coker:
                    extra_opex += m.coker_feed[p] * _COKER_OPEX
                    # Coker naphtha needs NHT (~$2/bbl on top of H2 cost)
                    extra_opex += m.coker_naphtha_vol[p] * 2.0
                    # Coke revenue: bbl -> tons -> $
                    extra_credit += m.coker_coke_vol[p] * _BBL_TO_TON_COKE * _COKE_PRICE
                if self.has_hcu:
                    extra_opex += m.vgo_to_hcu[p] * _HCU_OPEX
                if self.has_isom56:
                    extra_opex += m.ln_to_isom[p] * _ISOM56_OPEX
                if self.has_isomc4:
                    extra_opex += m.nc4_to_c4isom[p] * _ISOMC4_OPEX
                if self.has_arom:
                    extra_opex += m.hn_to_arom[p] * _AROM_OPEX
                    # BTX revenue: bbl -> tons -> $
                    extra_credit += m.btx_volume[p] * _BBL_TO_TON_BTX * _BTX_PRICE_PER_TON
                    # H2 credit from aromatics reformer
                    extra_credit += m.arom_hydrogen[p] * 1.5  # $1.50/MSCF H2
                if self.has_dimersol:
                    extra_opex += m.prop_to_dimersol[p] * _DIMERSOL_OPEX
                if self.has_ugp:
                    extra_opex += m.ugp_feed[p] * _UGP_OPEX
                if self.has_sgp:
                    extra_opex += m.sgp_feed[p] * _SGP_OPEX
                if self.has_amine or self.has_sru or self.has_tgt:
                    extra_credit += m.sulfur_sales[p] * _SULFUR_PRICE_PER_LT
                    extra_opex += m.amine_feed[p] * _AMINE_OPEX_PER_LT
                    extra_opex += m.sulfur_produced[p] * _SRU_OPEX_PER_LT
                    extra_opex += m.tgt_feed[p] * _TGT_OPEX_PER_LT
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
