# STAGE3_SPRINTS.md — Full Conversion Refinery (Remaining Gulf Coast Units)

## Overview

Stage 2B built 10 process units with $1.36M/day margin. Stage 3 adds the remaining conversion and processing units to complete the Gulf Coast reference model.

**Priority focus: units that CREATE VALUE by upgrading low-value streams.**

```
STAGE 3 SCOPE (9 units):

HIGH PRIORITY (massive economic impact):
  CVT1  Vacuum Unit        50K bbl/d  — separates atmospheric resid → VGO + vacuum resid
  CDLC  Delayed Coker      50K bbl/d  — cracks vacuum resid → coker naphtha + gas oil + coke
  CHCU  Hydrocracker       20K bbl/d  — cracks gas oil → jet + diesel (high value)

HIGH PRIORITY (gasoline optimization):
  CIS6  C5/C6 Isomerization 15K bbl/d — upgrades LN octane (RON 68 → RON 82+)
  CIS4  C4 Isomerization     5K bbl/d — converts nC4 → iC4 for alkylation feed

MEDIUM PRIORITY:
  CARU  Aromatics Reformer  35K bbl/d — produces BTX (benzene, toluene, xylene)
  CDIM  Dimersol             6K bbl/d — dimerizes propylene → gasoline
  SUGP  Unsaturated Gas Plant         — separates FCC light ends
  SSGP  Saturated Gas Plant           — separates CDU/coker light ends

DEFERRED TO STAGE 4:
  Multi-CDU (CAT2, CAT3) — same model, different capacity
  Multi-vacuum (CVT2, CVT3) — same model, different capacity
  Sulfur recovery, amine, tail gas — environmental compliance
  Utility generation, plant fuel — energy balance
```

**What changes economically:**

```
VACUUM UNIT:
  Before: CDU atmospheric resid → fuel oil at $55-70/bbl
  After:  Atm resid → Vacuum Unit → VGO (to FCC/HCU) + vacuum resid
  Impact: More FCC feed → more gasoline. VGO worth $70+ cracked, resid only $55.

DELAYED COKER:
  Before: Vacuum residue → fuel oil at $55/bbl
  After:  Vac resid → Coker → coker naphtha + coker gas oil + petroleum coke
  Impact: Upgrades the heaviest, cheapest material. Coke sells as fuel.
          Coker naphtha → gasoline. Coker gas oil → HCU or FCC feed.

HYDROCRACKER:
  Before: Heavy gas oil limited to FCC (makes gasoline + LCO)
  After:  Gas oil → HCU → jet + diesel at $87-88/bbl
  Impact: High-value middle distillates. HCU diesel has excellent cetane.
          HCU jet meets all specs without hydrotreating.
          Alternative to FCC for heavy feed upgrading.

C5/C6 ISOMERIZATION:
  Before: Light naphtha (RON 68) → gasoline blend or naphtha sale ($52/bbl)
  After:  LN → Isom → isomerate (RON 82+) → much better blend component
  Impact: Reduces purchased reformate need. Improves gasoline octane.

C4 ISOMERIZATION:
  Before: n-butane → LPG sale ($44/bbl) or limited gasoline blend
  After:  nC4 → iC4 → alkylation feed → alkylate (RON 96, $90+/bbl value)
  Impact: More iC4 for alkylation without purchasing externally.
```

## Prerequisites

Stage 2B complete: 510 tests, 93% coverage, 10 process units, $1.36M/day.
All existing tests must continue passing after each sprint.

---

## SPRINT 12: VACUUM UNIT + DELAYED COKER (Heavy End Upgrade)

These two units work together: Vacuum Unit separates atmospheric residue into VGO + vacuum residue. Coker converts vacuum residue into lighter products.

### Task 12.1: Vacuum Unit model

Create `src/eurekan/models/vacuum_unit.py`:

```python
class VacuumUnitModel(BaseUnitModel):
    """
    Vacuum Distillation Unit: further separates atmospheric residue
    from the CDU into vacuum gas oil (VGO) and vacuum residue.
    
    Gulf Coast: CVT1, 50K bbl/d capacity.
    
    Key physics:
    - Feed: atmospheric residue from CDU (1050°F+ material)
    - Light VGO (650-800°F): FCC feed or GO HT feed
    - Heavy VGO (800-1050°F): FCC feed, HCU feed, or fuel oil
    - Vacuum Residue (1050°F+): coker feed or fuel oil
    
    Yields are from assay data (like CDU — exact, not correlated).
    Typical split: 40-60% VGO, 40-60% vacuum residue.
    
    The vacuum unit INCREASES the amount of VGO available for 
    cracking. Without it, atmospheric resid goes to fuel oil.
    With it, the VGO fraction is recovered and cracked.
    """
    
    def calculate(self, atm_resid_rate: float, atm_resid_properties: CutProperties,
                  crude_contributions: dict[str, float]) -> VacuumUnitResult:
        """
        Split atmospheric residue into LVGO, HVGO, and vacuum residue.
        Yields from assay data interpolation.
        """
        ...
```

Add `VacuumUnitResult` to results.py:
- lvgo_volume, hvgo_volume, vac_resid_volume (bbl/d)
- lvgo_properties, hvgo_properties, vac_resid_properties (CutProperties)

Tests:
- test_mass_balance: LVGO + HVGO + vac_resid = atm_resid feed
- test_vgo_quality: VGO API higher than feed, vac_resid API lower
- test_yield_range: VGO 40-60% of feed, vac_resid 40-60%

### Task 12.2: Delayed Coker model

Create `src/eurekan/models/coker.py`:

```python
class CokerModel(BaseUnitModel):
    """
    Delayed Coker: thermally cracks vacuum residue into lighter products.
    
    Gulf Coast: CDLC, 50K bbl/d capacity.
    
    Key physics:
    - Feed: vacuum residue (heaviest, cheapest material)
    - Products:
      Coker Naphtha (C5-350°F): low octane, needs hydrotreating → gasoline
      Coker Gas Oil (350-650°F): high sulfur → HCU or FCC feed
      Coker Heavy Gas Oil (650°F+): → FCC or HCU feed
      C1-C4 gas: fuel gas + LPG
      Petroleum Coke: solid fuel, sold separately
    
    Correlations (feed-quality dependent):
    - Naphtha yield = 0.12 + 0.002 × (API - 5) — heavier feed → less naphtha
    - Gas oil yield = 0.25 + 0.003 × (API - 5)
    - Coke yield = 0.25 - 0.004 × (API - 5) + 0.015 × CCR
      Higher CCR → more coke
    - Gas yield = 0.10 + 0.001 × (API - 5)
    - Heavy gas oil = remainder from mass balance
    
    The coker is the "bottom of the barrel" upgrader.
    It converts the LEAST valuable stream into crackable material.
    """
    
    def calculate(self, feed_rate: float, feed_properties: CutProperties) -> CokerResult:
        ...
```

Add `CokerResult` to results.py:
- coker_naphtha_volume, coker_gas_oil_volume, coker_hgo_volume
- coke_volume, gas_volume, lpg_volume
- product properties for each stream
- coke_tons_per_day

Tests:
- test_base_case: typical vacuum resid → yields in expected ranges
- test_mass_balance: all products sum to feed ±3%
- test_heavy_feed: higher CCR → more coke, less liquid
- test_coke_yield: 20-35% of feed depending on quality

### Task 12.3: Integrate Vacuum Unit + Coker into PyomoModelBuilder

Update builder.py:

Vacuum Unit variables:
- atm_resid_to_vac[p]: atmospheric resid from CDU → vacuum unit
- atm_resid_to_fo[p]: bypass to fuel oil (if no vacuum unit or capacity full)
- lvgo_volume[p], hvgo_volume[p], vac_resid_volume[p]

VGO routing update:
- Total VGO now = CDU VGO (direct) + vacuum LVGO + vacuum HVGO
- All goes to GO HT → FCC (or direct to FCC, or fuel oil)
- More VGO available → FCC can run at higher rates

Coker variables:
- vac_resid_to_coker[p]: vacuum residue → coker
- vac_resid_to_fo[p]: bypass to fuel oil
- coker_naphtha[p], coker_go[p], coker_hgo[p], coke[p], coker_gas[p]

Coker product routing:
- Coker naphtha → naphtha HT → reformer (or gasoline blend)
  **WARNING: Coker naphtha is "dirty" — highly olefinic with elevated nitrogen and sulfur compared to straight-run naphtha. The NHT model must handle this: increase H2 consumption by ~50% when coker naphtha is in the feed blend. If the NHT H2 model uses a flat SCFB rate, update it to be feed-quality dependent. Without this, the optimizer will underestimate H2 cost of processing coker naphtha.**
- Coker gas oil → diesel HT (or FCC feed)
- Coker HGO → FCC feed (or GO HT → FCC)
- Coke → sold at coke price (~$30/ton)
- Gas → fuel gas system

Objective updates:
- Add coke revenue
- Add vacuum unit opex (~$1/bbl)
- Add coker opex (~$4/bbl — high energy)

Check config.units for vacuum_1, coker_1 — skip if absent.

Tests:
- test_vacuum_increases_vgo: FCC feed increases with vacuum unit
- test_coker_reduces_fuel_oil: fuel oil drops, gasoline + diesel increase
- test_margin_increases: margin with vac+coker > without
- test_backward_compatible: Stage 2B config still works

### Task 12.4: Update parser + flowsheet

- Parse Caps: CVT1 → vacuum_1 (50K), CDLC → coker_1 (50K)
- Flowsheet: Add "HEAVY END" swim lane below Distillate
  Vacuum Unit → Coker in this lane
  Edges: CDU resid → Vacuum → VGO to FCC lane, Vac resid → Coker
  Coker products fan up to naphtha lane (coker naphtha) and FCC lane (coker GO)

Run: `uv run pytest tests/ -v`

---

## SPRINT 13: HYDROCRACKER (Middle Distillate Machine)

### Task 13.1: Hydrocracker model

Create `src/eurekan/models/hydrocracker.py`:

```python
class HydrocrackerModel(BaseUnitModel):
    """
    Hydrocracker: catalytic cracking under high hydrogen pressure.
    Produces high-quality middle distillates (jet + diesel).
    
    Gulf Coast: CHCU, 20K bbl/d capacity.
    
    Key physics:
    - Feed: VGO, coker gas oil, or heavy gas oil
    - Products:
      HCU Naphtha: RON ~70, needs reforming
      HCU Jet/Kero: excellent quality, meets all jet specs without HT
      HCU Diesel: cetane 55+ (much better than FCC LCO cetane 20)
      Unconverted oil: recycle or fuel oil
      LPG: significant C3/C4 production
    
    Two operating modes:
    - MAX DISTILLATE: optimized for jet + diesel (typical)
    - MAX NAPHTHA: higher severity, more naphtha (gasoline mode)
    
    Correlations (conversion dependent):
    - Conversion = 60-95% (once-through) or 95-99% (with recycle)
    - At 80% conversion (typical):
      Naphtha: 15-20%, Jet/Kero: 25-35%, Diesel: 25-35%
      LPG: 5-10%, Unconverted: 5-20%
    
    The HCU is an ALTERNATIVE to FCC for VGO processing:
    - FCC: maximizes gasoline (but poor diesel quality)
    - HCU: maximizes jet+diesel (excellent quality)
    - The optimizer chooses the split based on product prices
    
    Consumes SIGNIFICANT hydrogen (1500-2500 SCFB) — 
    the biggest H2 consumer in the refinery.
    """
    
    def calculate(self, feed_rate: float, feed_properties: CutProperties,
                  conversion: float = 80.0) -> HydrocrackerResult:
        ...
```

Add `HydrocrackerResult` to results.py.

Tests:
- test_base_case: 80% conversion, yields in expected ranges
- test_mass_balance: all products sum to feed
- test_high_conversion: more products, less unconverted
- test_diesel_quality: HCU diesel cetane > 50 (much better than LCO)
- test_hydrogen_consumption: 1500-2500 SCFB (highest of all units)
- test_jet_quality: HCU jet meets specs without further treatment

### Task 13.2: Integrate HCU into PyomoModelBuilder

Update builder.py:

HCU variables:
- vgo_to_hcu[p]: VGO routed to hydrocracker (vs FCC)
- hcu_conversion[p]: continuous [60, 95]
- hcu_naphtha[p], hcu_jet[p], hcu_diesel[p], hcu_lpg[p], hcu_unconverted[p]

VGO routing becomes 4-way:
- vgo_to_goht (→ FCC), vgo_to_fcc_direct, vgo_to_hcu, vgo_to_fo

The optimizer now chooses: how much VGO to FCC vs HCU?
- FCC: more gasoline (high gas price → more to FCC)
- HCU: more jet + diesel (high distillate price → more to HCU)
- This is a KEY economic decision the planner wants optimized

HCU products:
- HCU jet → jet fuel sale (NO kero HT needed — already clean)
- HCU diesel → diesel sale (cetane 55 — excellent)
- HCU naphtha → naphtha HT → reformer
- HCU LPG → gas plant or LPG sale
- Unconverted → recycle to HCU or fuel oil

Hydrogen: HCU is the BIGGEST consumer
- h2_to_hcu[p] added to H2 balance constraint
- May force more H2 purchase or higher reformer severity

Check config.units for hcu_1 — skip if absent.

Tests:
- test_fcc_vs_hcu_split: optimizer splits VGO between FCC and HCU
- test_distillate_price_drives_hcu: high diesel price → more to HCU
- test_gasoline_price_drives_fcc: high gasoline price → more to FCC
- test_h2_balance_tighter: HCU increases H2 demand significantly
- test_hcu_diesel_cetane: HCU diesel blends easily into ULSD

### Task 13.3: Update parser + flowsheet

- Parse Caps: CHCU → hcu_1 (20K)
- Flowsheet: HCU in FCC Complex lane (alternative to FCC)
  or new "HYDROCRACKING" lane between FCC and Distillate
- Edges: VGO → HCU → Jet, Diesel, Naphtha

---

## SPRINT 14: LIGHT ENDS PROCESSING (Isomerization + Gas Plants)

### Task 14.1: C5/C6 Isomerization model

Create `src/eurekan/models/isomerization.py`:

```python
class C56IsomerizationModel(BaseUnitModel):
    """
    C5/C6 Isomerization: converts straight-chain C5/C6 paraffins 
    to branched isomers for higher octane.
    
    Gulf Coast: CIS6, 15K bbl/d capacity.
    
    Key physics:
    - Feed: light naphtha (C5-C6 fraction, RON ~68)
    - Product: isomerate (RON 82-87 depending on process)
    - Significant octane improvement with near-100% yield
    - Small H2 consumption
    - Alternative to selling LN as low-value naphtha
    
    The C5/C6 isom is a "cheap octane" source — less expensive 
    than reforming and preserves more liquid volume.
    """
    
    def calculate(self, feed_rate: float, feed_properties: CutProperties) -> IsomResult:
        # Isomerate RON: 82-87 (depends on recycle configuration)
        # Volume yield: 97-99%
        # H2 consumption: 100-200 SCFB (very low)
        ...
```

### Task 14.2: C4 Isomerization model

Create `src/eurekan/models/c4_isom.py`:

```python
class C4IsomerizationModel(BaseUnitModel):
    """
    C4 Isomerization: converts n-butane to isobutane.
    
    Gulf Coast: CIS4, 5K bbl/d capacity.
    
    Key physics:
    - Feed: n-butane (from CDU, FCC, or purchased)
    - Product: isobutane (feed for alkylation unit)
    - Near 100% yield, equilibrium limited (~60% conversion per pass)
    - With recycle: effectively 95%+ conversion
    
    This unit FEEDS the alkylation unit with iC4.
    Without it, alkylation is limited by iC4 availability
    and must purchase expensive iC4 externally.
    """
    
    def calculate(self, feed_rate: float) -> C4IsomResult:
        # iC4 yield: ~95% of feed (with recycle)
        # Unconverted nC4: ~5% (recycled)
        ...
```

### Task 14.3: Gas Plant models (simplified)

Create `src/eurekan/models/gas_plant.py`:

```python
class UnsaturatedGasPlant(BaseUnitModel):
    """
    UGP: separates FCC light ends (C1-C4) into individual streams.
    
    Products: fuel gas (C1-C2), propane, propylene, iC4, nC4, butylenes
    The olefin/paraffin split is critical for alkylation feed.
    """
    ...

class SaturatedGasPlant(BaseUnitModel):
    """
    SGP: separates CDU/coker/HCU light ends (no olefins).
    Products: fuel gas, propane, iC4, nC4
    """
    ...
```

### Task 14.4: Integrate all into PyomoModelBuilder

- C5/C6 Isom: LN → isom → isomerate → gasoline blend (RON 83 vs 68)
  LN disposition: to_isom + to_blend + to_sell
  Isomerate goes to gasoline blend as high-value component
  
- C4 Isom: nC4 → C4 isom → iC4 → alkylation
  Reduces or eliminates iC4 purchases
  Links: CDU nC4 + FCC nC4 → C4 isom → alky feed
  
- Gas Plants: simplified separation model
  FCC gas → UGP → propylene + butylene (to alky) + propane + butane (to LPG/isom)
  CDU gas → SGP → propane + butane (to LPG/isom)
  
Check config.units for each — skip if absent.

Tests:
- test_isomerate_in_gasoline: isomerate appears in blend at RON 83
- test_c4_isom_feeds_alky: iC4 from C4 isom reduces purchased iC4
- test_ln_routing: LN goes to isom instead of low-value sale
- test_margin_increases: more gasoline octane, less purchased iC4

### Task 14.5: Update parser + flowsheet

- Parse Caps: CIS6 → isom_c56 (15K), CIS4 → isom_c4 (5K)
- Flowsheet: Add "LIGHT ENDS" swim lane at top
  C5/C6 Isom in Naphtha Processing lane (after splitter, parallel to NHT)
  C4 Isom between Light Ends and FCC lane
  Gas plants in Light Ends lane

---

## SPRINT 15: AROMATICS + DIMERSOL + FULL VALIDATION

### Task 15.1: Aromatics Reformer model

Create `src/eurekan/models/aromatics_reformer.py`:

```python
class AromaticsReformerModel(BaseUnitModel):
    """
    Aromatics Reformer: high-severity reforming for BTX production.
    
    Gulf Coast: CARU, 35K bbl/d capacity.
    
    Different from mogas reformer (CLPR):
    - Mogas reformer: optimizes for RON (gasoline octane)
    - Aromatics reformer: optimizes for benzene, toluene, xylene yield
    - Higher severity → more aromatics but less liquid yield
    
    Products: BTX extract (sold as petrochemical feedstock)
    Raffinate: low-octane remainder → gasoline blend or recycle
    Hydrogen: significant production (like mogas reformer)
    
    BTX is high-value petrochemical product ($800-1200/ton)
    This unit exists when petrochemical integration is profitable.
    """
    ...
```

### Task 15.2: Dimersol model

Create `src/eurekan/models/dimersol.py`:

```python
class DimersolModel(BaseUnitModel):
    """
    Dimersol: dimerizes propylene into C6 gasoline-range olefins.
    
    Gulf Coast: CDIM, 6K bbl/d capacity.
    
    Alternative use for propylene (vs alkylation):
    - Alkylation: propylene + iC4 → alkylate (RON 94)
    - Dimersol: propylene → dimate (RON 95-97)
    - Dimersol doesn't need iC4, but product has higher olefin content
    
    Small unit, niche value. Optimizer decides propylene routing.
    """
    ...
```

### Task 15.3: Integrate + full validation

- Add aromatics reformer and dimersol to builder
- HN routing: mogas reformer OR aromatics reformer (optimizer chooses)
- Propylene routing: alkylation OR dimersol (optimizer chooses)

**LP WARM-START UPDATE (critical for convergence):**
The Stage 3 model now has several discrete-like choices that create local minima for IPOPT:
- VGO → FCC vs HCU (Sprint 13)
- HN → Mogas reformer vs Aromatics reformer (Sprint 15)
- Propylene → Alkylation vs Dimersol (Sprint 15)
- Coker GO → FCC vs HCU vs Diesel HT (Sprint 12)

Update the Tier 2 LP warm-start (from Sprint 3's solver.py) to include sensible initial values for ALL new variables. Specifically:
- Initialize VGO split: 70% to FCC, 30% to HCU (typical)
- Initialize HN: 100% to mogas reformer (default)
- Initialize propylene: 100% to alkylation (default)
- Initialize coker GO: 50% to FCC, 50% to diesel HT
- Run IPOPT from 3-5 different starting points and take the best solution to guard against local optima. Log if solutions differ by >1% margin.

### Task 15.4: Full Stage 3 validation suite

Create `tests/validation/test_stage3_validation.py`:

Complete refinery validation:
1. All units active where economic (check each unit throughput)
2. Margin should be $1.5-2.5M/day with full conversion
3. Fuel oil should DROP significantly (coker + HCU upgrade heavy ends)
4. Gasoline octane should be easier (isomerate + more alkylate)
5. H2 balance: reformers supply, HTs + HCU consume
6. Product slate: gasoline, jet, diesel, LPG, coke, BTX, fuel oil
7. All blend specs met
8. Directional tests:
   - Gasoline price up → more to FCC, less to HCU
   - Diesel price up → more to HCU, less to FCC
   - Heavy crude added → coker utilization increases
   - Light crude added → more naphtha → more reformate
9. All Stage 1, 2A, 2B tests still pass

Run: `uv run pytest tests/ -v --cov=eurekan`
Commit: `"Stage 3 complete: full Gulf Coast refinery, all validation passing"`

---

## Expected Results After Stage 3

```
MARGIN PROGRESSION:

  Stage 1 (CDU + FCC):                    $853K/day
  Stage 2B (+ reformer, HTs, alky):      $1,356K/day
  Stage 3 estimates:
    + Vacuum Unit (more VGO for FCC):     +$100-200K/day
    + Coker (resid → products):           +$200-400K/day
    + Hydrocracker (gas oil → jet+diesel): +$150-300K/day
    + C5/C6 Isom (better gasoline octane): +$50-100K/day
    + C4 Isom (more iC4 for alky):         +$30-60K/day
    + Aromatics + Dimersol:                +$30-80K/day
    
  Full Stage 3:                          ~$1.8-2.5M/day

FLOWSHEET:
  Crudes → CDU → Vacuum → VGO → GO HT → FCC → Scanfiner → Gasoline Blend
                       → VGO → HCU → Jet + Diesel
                → Naphtha → Splitter → LN → C5/C6 Isom → Blend
                                     → HN → NHT → Reformer → Blend
                → Kero → Kero HT → Jet
                → Diesel → Diesel HT → ULSD
                → VGO (direct to FCC)
         Vac Resid → Coker → Coker Naphtha → NHT
                           → Coker GO → HCU or FCC
                           → Coke (sold)
         FCC → C3/C4 → UGP → Propylene → Alky or Dimersol
                            → Butylene → Alky
                            → nC4 → C4 Isom → iC4 → Alky
         Reformers → H2 → NHT + KHT + DHT + GOHT + HCU
                        → H2 Plant makeup if needed

PRODUCT SLATE:
  Gasoline (regular + premium)
  Jet fuel (from CDU kero + HCU)
  ULSD (from CDU diesel + FCC LCO + HCU)
  LPG
  Naphtha (surplus)
  Fuel Oil (reduced — coker handles most heavy material)
  Petroleum Coke (from coker)
  BTX (from aromatics reformer, if economic)
```

## Key Design Principle

Same as Stage 2B: every unit is OPTIONAL. The Gulf Coast model has all of them, but a simpler refinery (say CDU + FCC + Reformer) works with the same codebase. The config drives the model complexity.
