# STAGE2B_SPRINTS.md — Reformer + Alkylation + Diesel HT + PostgreSQL

## Overview

Stage 2A built the product: API + UI + flowsheet + scenarios + narratives.
Stage 2B adds process units to match the Gulf Coast reference model. Same architecture — each unit follows the BaseUnitModel pattern, plugs into PyomoModelBuilder, and appears on the flowsheet automatically.

**Gulf Coast reference model has 25+ process units. Our Stage 2B scope covers the most economically impactful ones that connect to the CDU+FCC core:**

```
STAGE 2B SCOPE (matching Gulf Coast Caps sheet):

NAPHTHA PROCESSING:
  CNSP  Naphtha Splitter    80K bbl/d  — splits naphtha into LN + HN
  CNHT  Naphtha HT          60K bbl/d  — desulfurizes HN for reformer feed
  CLPR  Mogas Reformer      35K bbl/d  — HN → reformate (RON 98+) + hydrogen

DISTILLATE PROCESSING:
  CKHT  Kero HT             30K bbl/d  — treats kerosene for jet fuel quality
  CDHT  Diesel HT           30K bbl/d  — treats diesel + LCO for ULSD
  CGHT  GO Hydrotreater     60K bbl/d  — treats VGO before FCC (reduces S, metals)

CRACKING SUPPORT:
  CGTU  Scanfiner           25K bbl/d  — treats FCC naphtha sulfur, preserves octane
  CSFA  Alkylation          14K bbl/d  — C3/C4 olefins → alkylate (RON 96)

HYDROGEN:
  CH2P  H2 Plant           0.15 MMSCFD — supplies H2 when reformer isn't enough
  Hydrogen balance linking reformer → NHT + KHT + DHT + GOHT
```

**What changes with each unit:**

```
NAPHTHA SPLITTER:
  Before: CDU produces separate light_naphtha and heavy_naphtha cuts
  After:  CDU produces full-range naphtha → splitter separates at cut point
  Impact: More realistic — planner can adjust the split point

NAPHTHA HYDROTREATER:
  Before: Heavy naphtha goes directly to reformer (implicit clean feed)
  After:  HN → NHT (removes sulfur to <1 ppm) → Reformer
  Impact: Required for reformer operation (catalyst protection)

REFORMER:
  Before: Purchased reformate at $70/bbl fills the octane gap
  After:  Heavy naphtha → NHT → reformer → reformate (RON 100+)
  Impact: Purchased reformate drops to zero, margin increases ~$200-400K/day

GO HYDROTREATER:
  Before: Raw VGO goes directly to FCC
  After:  VGO → GO HT (removes sulfur + metals) → FCC
  Impact: Lower sulfur in FCC products → easier gasoline blending
          Less metals → protects FCC catalyst, allows higher conversion

SCANFINER (FCC Naphtha Treating):
  Before: FCC HCN goes to blend with high sulfur (spec-limited)
  After:  FCC HCN → Scanfiner → treated HCN (low sulfur, octane preserved)
  Impact: THIS is why the Gulf Coast model makes spec gasoline
          Without Scanfiner, HCN sulfur is the binding constraint

KERO HYDROTREATER:
  Before: Kerosene sells directly as jet fuel (assumed clean)
  After:  Kerosene → Kero HT → jet fuel meeting sulfur + smoke point specs

DIESEL HYDROTREATER:
  Before: Flat $2/bbl proxy cost on diesel
  After:  CDU diesel + FCC LCO → Diesel HT → ULSD (<15 ppm sulfur)

ALKYLATION:
  Before: FCC C3/C4 sold as LPG at $44/bbl
  After:  C3/C4 olefins + iC4 → alkylation → alkylate (RON 96, zero sulfur)

NAPHTHA HYDROTREATER:
  Before: Heavy naphtha goes directly to reformer (implicit)
  After:  Explicit sulfur removal to protect reformer catalyst

KEROSENE HYDROTREATER:
  Before: Kerosene sells directly as jet fuel (assumed clean)
  After:  Explicit sulfur removal to meet jet fuel specs
```

## Prerequisites

Stage 2A complete: 456 tests, 18 API endpoints, 18 React components.
All existing tests must continue passing after each sprint.

---

## SPRINT 9: NAPHTHA PROCESSING CHAIN (Splitter → NHT → Reformer)

The naphtha processing chain is sequential: CDU → Naphtha Splitter → NHT → Reformer. Must be built in order.

### Task 9.0: Naphtha Splitter model

Create `src/eurekan/models/naphtha_splitter.py`:

```python
class NaphthaSplitterModel(BaseUnitModel):
    """
    Naphtha Splitter: separates full-range CDU naphtha into
    light naphtha (LN) and heavy naphtha (HN) at a configurable cut point.
    
    Gulf Coast: SNSP, 80K bbl/d capacity.
    
    Key physics:
    - Feed: full-range naphtha from CDU (C5-350°F)
    - Light cut: C5 to cut_point (default 180°F) → gasoline blend or isomerization
    - Heavy cut: cut_point to 350°F → NHT → reformer feed
    - Cut point is adjustable (this is the advantage over PIMS!)
    - Split ratio determined by TBP curve interpolation at cut point
    - Properties of each cut from assay data (weighted by contributing crudes)
    """
    
    def calculate(self, naphtha_rate: float, naphtha_properties: CutProperties,
                  cut_point_f: float = 180.0) -> NaphthaSplitterResult:
        """
        Args:
            naphtha_rate: total naphtha from CDU (bbl/d)
            naphtha_properties: blended properties of full-range naphtha
            cut_point_f: split temperature (°F), default 180
        Returns:
            NaphthaSplitterResult with LN and HN volumes and properties
        """
        ...
```

**MATHEMATICAL GUARDRAIL:** Use cubic spline interpolation (scipy.interpolate.CubicSpline) for TBP curve interpolation, NOT linear lookup. IPOPT requires smooth, differentiable functions to compute gradients. Linear interpolation creates non-differentiable kinks at data points that can cause IPOPT to struggle with convergence. The spline must be fitted once from assay data and reused — do not re-fit per solve iteration.
```

Add `NaphthaSplitterResult` to results.py:
- light_naphtha_volume (float, bbl/d)
- heavy_naphtha_volume (float, bbl/d)
- light_naphtha_properties (CutProperties)
- heavy_naphtha_properties (CutProperties)
- cut_point_f (float)

Tests in `tests/unit/test_naphtha_splitter.py`:
- test_split_ratio: at 180°F, LN ≈ 35-45% of total naphtha
- test_properties_differ: LN should have higher API, lower sulfur than HN
- test_mass_balance: LN + HN = total feed
- test_cut_point_variation: higher cut point → more LN, less HN
- test_hn_suitable_for_reformer: HN properties in reformer feed range

### Task 9.1: Reformer model

Create `src/eurekan/models/reformer.py`:

```python
class ReformerCalibration(BaseModel):
    """Calibration parameters for the reformer."""
    alpha_reformate_yield: float = 1.0    # multiplier on reformate yield
    alpha_hydrogen_yield: float = 1.0     # multiplier on H2 production
    delta_ron: float = 0.0                # offset on reformate RON
    severity_factor: float = 1.0          # adjusts severity response

class ReformerModel(BaseUnitModel):
    """
    Catalytic reformer: converts heavy naphtha to high-octane reformate.
    
    Key physics:
    - Feed: heavy naphtha (180-350°F, RON ~42)
    - Product: reformate (RON 95-102 depending on severity)
    - Byproducts: hydrogen (valuable), LPG, fuel gas
    - Higher severity → higher RON but lower liquid yield
    - Typical: 85% vol yield at RON 98
    
    Correlations (simplified, calibratable):
    - Reformate yield = α × (0.95 - 0.0015 × (severity - 90))
      At severity 95: ~92.5% vol yield
      At severity 100: ~85% vol yield
      At severity 105: ~77.5% vol yield (max practical)
    - Reformate RON = severity + Δ_ron
    - Hydrogen production = 0.03 + 0.001 × (severity - 90) (wt fraction)
    - LPG + fuel gas = 1.0 - reformate_yield - hydrogen
    """
    
    def calculate(self, feed_properties: CutProperties, feed_rate: float,
                  severity: float, calibration: ReformerCalibration = None) -> ReformerResult:
        """
        Args:
            feed_properties: heavy naphtha properties
            feed_rate: bbl/d of heavy naphtha feed
            severity: target RON of reformate (90-105)
        Returns:
            ReformerResult with reformate volume, RON, hydrogen, LPG
        """
        ...
    
    def max_severity(self, feed_properties: CutProperties) -> float:
        """Max severity limited by catalyst stability and feed quality."""
        # Higher naphthene content → can push higher severity
        # Typical limit: 102-105 depending on feed
        ...
    
    def equipment_status(self, feed_rate: float, severity: float) -> list[EquipmentStatus]:
        """Heater duty, recycle compressor, reactor temperature."""
        ...
```

Add `ReformerResult` to `core/results.py`:
- reformate_volume (float, bbl/d)
- reformate_ron (float)
- hydrogen_production (float, MMSCFD)
- lpg_production (float, bbl/d)
- fuel_gas_production (float, bbl/d)
- severity (float)
- equipment (list[EquipmentStatus])

Tests in `tests/unit/test_reformer.py`:
- test_base_case: severity 98, reformate yield ~85%, RON ~98
- test_severity_response: higher severity → lower yield, higher RON
- test_mass_balance: reformate + H2 + LPG + fuel gas ≈ feed (±3%)
- test_max_severity: returns value between 100-105
- test_hydrogen_increases: higher severity → more hydrogen
- test_calibration_neutral: default calibration doesn't change outputs

### Task 9.2: Integrate reformer into PyomoModelBuilder

Update `src/eurekan/optimization/builder.py`:

Add reformer variables (per period):
- reformer_feed[p]: bbl/d of heavy naphtha to reformer, bounded [0, capacity]
- reformer_severity[p]: continuous [90, 105]
- reformate_from_reformer[p]: bbl/d produced
- hydrogen_production[p]: MMSCFD

Add reformer constraints:
- Feed balance: reformer_feed[p] + hn_to_blend[p] + hn_to_sell[p] = hn_available[p]
  (heavy naphtha now has THREE destinations: reformer, blend, sell)
- Reformate yield: reformate_from_reformer = f(reformer_feed, severity) (nonlinear)
- Reformate RON: = severity + delta (feeds into blend octane constraint)
- Hydrogen balance: hydrogen_production = g(reformer_feed, severity)
- Equipment constraints: heater duty, reactor temp limits

Update gasoline blending:
- Reformate source changes: reformate_purchased + reformate_from_reformer
- If reformer produces enough, purchased reformate drops to zero
- The optimizer decides the split

Update objective function:
- Remove purchased reformate cost for reformer-produced volume
- Add reformer opex (~$3/bbl feed)
- Add hydrogen credit (hydrogen has value, ~$1.50/MSCF)

IMPORTANT: The builder should check if 'reformer' exists in config.units.
If no reformer → skip all reformer variables/constraints (Stage 1 behavior).
If reformer exists → add them. This keeps backward compatibility.

Tests in `tests/integration/test_reformer_integration.py`:
- test_reformer_replaces_purchased: with reformer, purchased reformate < 1000 bbl/d
- test_margin_increases: margin with reformer > margin without reformer
- test_reformer_value_matches_shadow: margin increase ≈ shadow price of reformate from Stage 1
- test_hn_routes_to_reformer: most heavy naphtha goes to reformer, not naphtha sale
- test_severity_optimized: optimizer picks severity between 95-102
- test_backward_compatible: config WITHOUT reformer still works (Stage 1 tests pass)

### Task 9.3: Update Gulf Coast parser and config

Update `src/eurekan/parsers/gulf_coast.py`:
- Parse Caps sheet for reformer capacity (SLPR tag if present)
- Add reformer UnitConfig to RefineryConfig
- If reformer capacity not found, skip (backward compatible)

Update `src/eurekan/api/services.py`:
- quick_optimize uses reformer if present in config

### Task 9.4: Update flowsheet for reformer

Update `src/eurekan/optimization/modes.py`:
- Add reformer node to MaterialFlowGraph
- Add edges: CDU → HN → Reformer, Reformer → Reformate → Blender
- Add hydrogen stream (info only, no destination yet)

Frontend should auto-render the new node (React Flow reads MaterialFlowGraph).
Verify: reformer appears on flowsheet between CDU and Blender.

Run all tests: `uv run pytest tests/ -v --cov=eurekan`
ALL existing tests must still pass. Commit.

---

## SPRINT 10: FCC SUPPORT UNITS (GO HT + Scanfiner + Alkylation)

Three units that improve FCC feed quality and product value.

### Task 10.0: GO Hydrotreater model

Create `src/eurekan/models/go_hydrotreater.py`:

```python
class GOHydrotreaterModel(BaseUnitModel):
    """
    Gas Oil Hydrotreater: treats VGO before FCC feed.
    
    Gulf Coast: SGHT, 60K bbl/d capacity.
    
    Key physics:
    - Feed: VGO from CDU (650-1050°F)
    - Removes sulfur (3% → 0.3%) and nitrogen
    - Removes some metals (Ni, V) — protects FCC catalyst
    - Mild hydrogenation improves FCC gasoline yield
    - Consumes significant hydrogen
    
    Impact on FCC:
    - Lower feed sulfur → lower sulfur in FCC naphtha → easier gasoline blending
    - Lower metals → less catalyst deactivation → longer cycle
    - Slightly higher API → marginally better conversion
    
    Correlations:
    - Sulfur removal: 90% efficiency (3% → 0.3%)
    - Nitrogen removal: 60% efficiency
    - Metals removal: 70% of Ni+V
    - API improvement: +1-2 numbers
    - H2 consumption: 800-1200 SCFB (highest of all HTs)
    - Volume yield: ~100% (slight gain from hydrogenation)
    """
    
    def calculate(self, feed_rate: float, feed_properties: CutProperties,
                  hydrogen_available: float) -> GOHTResult:
        ...
```

Add `GOHTResult` to results.py:
- product_volume, product_sulfur, product_nitrogen, product_metals
- hydrogen_consumed, api_improvement

Tests in `tests/unit/test_go_ht.py`:
- test_sulfur_removal: 3% feed → ~0.3% product
- test_metals_removal: 70% Ni+V removed
- test_nitrogen_removal: 60% removed
- test_hydrogen_consumption: 800-1200 SCFB range
- test_impact_on_fcc: treated VGO produces lower sulfur FCC products

### Task 10.0b: Scanfiner (FCC Naphtha Treating) model

Create `src/eurekan/models/scanfiner.py`:

```python
class ScanfinerModel(BaseUnitModel):
    """
    Scanfiner / FCC Naphtha Treating Unit: selectively removes
    sulfur from FCC naphtha while preserving octane.
    
    Gulf Coast: SGTU, 25K bbl/d capacity.
    
    Key physics:
    - Feed: FCC heavy cat naphtha (HCN) — high sulfur, high RON
    - Challenge: conventional HT destroys olefins → kills octane
    - Scanfiner selectively removes sulfur (80-90%) with minimal
      octane loss (only 1-2 RON points)
    - THIS is how the Gulf Coast model makes spec gasoline
    
    Without Scanfiner:
      HCN sulfur ~500-3000 ppm → gasoline sulfur constraint binding
      Must reduce HCN in blend → less gasoline, lower octane
    
    With Scanfiner:
      HCN sulfur ~500 ppm → treated HCN ~50-100 ppm
      More HCN in gasoline blend → more volume, octane preserved
    
    Correlations:
    - Sulfur removal: 85% efficiency
    - RON loss: -1.5 numbers (minimal — preserves olefinic octane)
    - Volume yield: 98% (2% to light ends)
    - H2 consumption: 200-400 SCFB (much less than conventional HT)
    """
    
    def calculate(self, feed_rate: float, feed_sulfur: float,
                  feed_ron: float) -> ScanfinerResult:
        ...
```

Add `ScanfinerResult` to results.py:
- product_volume, product_sulfur, product_ron, hydrogen_consumed, octane_loss

Tests in `tests/unit/test_scanfiner.py`:
- test_sulfur_removal: 500 ppm → ~75 ppm (85% removal)
- test_octane_preservation: RON drops only 1-2 numbers
- test_volume_yield: ~98%
- test_hydrogen_low: 200-400 SCFB (much less than regular HT)
- test_impact_on_gasoline: treated HCN can now blend into gasoline at spec

### Task 10.1: Alkylation model

Create `src/eurekan/models/alkylation.py`:

```python
class AlkylationModel(BaseUnitModel):
    """
    Alkylation: converts C3/C4 olefins + isobutane → alkylate.
    
    Key physics:
    - Feed: C3= (propylene) + C4= (butylene) from FCC
    - Reactant: isobutane (from FCC + purchased)
    - Product: alkylate (RON 96, zero sulfur, RVP ~4.5)
    - The BEST gasoline blend component — high octane, no sulfur
    
    Correlations:
    - Alkylate yield ≈ 1.7-1.8 × olefin feed (iC4 consumed)
    - Alkylate RON ≈ 94 (C3= feed) to 97 (C4= feed), blended
    - Alkylate RVP ≈ 4.5 psi
    - Alkylate sulfur = 0 ppm
    - iC4 requirement ≈ 1.1 × olefin feed (volume basis)
    - n-butane byproduct: small amount from isomerization side reaction
    """
    
    def calculate(self, c3_olefin_rate: float, c4_olefin_rate: float,
                  ic4_available: float) -> AlkylationResult:
        """
        Args:
            c3_olefin_rate: propylene from FCC (bbl/d)
            c4_olefin_rate: butylene from FCC (bbl/d)
            ic4_available: isobutane available (bbl/d)
        Returns:
            AlkylationResult with alkylate volume, properties
        """
        ...
```

Add `AlkylationResult` to `core/results.py`:
- alkylate_volume (float, bbl/d)
- alkylate_properties (CutProperties — RON 96, sulfur 0, RVP 4.5)
- ic4_consumed (float, bbl/d)
- n_butane_byproduct (float, bbl/d)

Tests in `tests/unit/test_alkylation.py`:
- test_base_case: typical olefin feed → alkylate yield ~1.75×
- test_alkylate_properties: RON 94-97, sulfur = 0, RVP ~4.5
- test_ic4_requirement: iC4 consumed ≈ 1.1 × olefins
- test_mass_balance: alkylate + n-butane ≈ olefins + iC4 consumed (±5%)
- test_zero_feed: no olefins → no alkylate

### Task 10.2: Integrate GO HT, Scanfiner, and Alkylation into PyomoModelBuilder

Update builder.py to add all three Sprint 10 units (each optional based on config.units):

**GO Hydrotreater (before FCC):**
- go_ht_feed[p]: VGO routed to GO HT
- go_ht_product[p]: treated VGO → FCC feed
- VGO disposition: vgo_to_go_ht[p] + vgo_to_fcc_direct[p] + vgo_to_fo[p] = vgo_available
- FCC feed becomes: go_ht_product + vgo_direct (blended properties)
- FCC feed sulfur DECREASES when GO HT is active → better products
- Hydrogen consumed by GO HT
- If no GO HT in config → VGO goes directly to FCC (current behavior)

**Scanfiner (after FCC, before gasoline blend):**
- scanfiner_feed[p]: FCC HCN routed to Scanfiner
- scanfiner_product[p]: treated HCN with lower sulfur, slight octane loss
- HCN disposition: hcn_to_scanfiner[p] + hcn_to_blend_direct[p] + hcn_to_fo[p]
- Treated HCN goes to gasoline blend with sulfur ~75 ppm instead of 500+ ppm
- RON drops by 1.5 (still high — ~92.5)
- THIS RELAXES the gasoline sulfur constraint dramatically
- If no Scanfiner → HCN goes to blend with high sulfur (Stage 1 behavior, sulfur-limited)

**Alkylation (from FCC C3/C4):**

Add alkylation variables:
- c3_to_alky[p], c4_to_alky[p]: olefin feed from FCC
- c3_to_lpg[p], c4_to_lpg[p]: FCC C3/C4 sold as LPG
- alkylate_volume[p]: bbl/d produced
- ic4_purchased[p]: isobutane purchased externally if needed

Add constraints:
- C3 disposition: c3_to_alky + c3_to_lpg = fcc_c3_production
- C4 disposition: c4_to_alky + c4_to_lpg = fcc_c4_production
- Alkylate yield: alkylate_volume = 1.75 × (c3_to_alky + c4_to_alky)
- iC4 balance: ic4_consumed = 1.1 × (c3_to_alky + c4_to_alky)
  ic4_consumed ≤ fcc_ic4 + ic4_purchased

Update gasoline blending:
- Add alkylate as a blend component (RON 96, sulfur 0, RVP 4.5)
- This is the BEST component — optimizer will use all of it

Update objective:
- LPG revenue now only for C3/C4 NOT sent to alky
- Alkylate value captured through gasoline blend revenue
- Alky opex (~$4/bbl alkylate)
- ic4 purchase cost (~$50/bbl if needed)

Check config.units for 'alkylation' — skip if not present.

**IMPORTANT: iC4 availability is the real bottleneck for alkylation.** Verify that the Gulf Coast parser extracts iC4 production from FCC yields AND iC4 purchase price/availability from the Buy sheet. If iC4 is not available in the Buy sheet, add a default purchase price (~$50/bbl) and unlimited availability. The optimizer must be able to purchase iC4 externally if FCC production is insufficient.

Tests in `tests/integration/test_alkylation_integration.py`:
- test_alkylate_in_gasoline: alkylate appears in gasoline blend recipe
- test_lpg_decreases: LPG volume lower with alky than without
- test_gasoline_sulfur_easier: gasoline sulfur margin improves (zero-sulfur component)
- test_margin_increases: margin with alky > without alky
- test_backward_compatible: config without alky still works

### Task 10.3: Update flowsheet for Sprint 10 units

Update modes.py:
- Add GO HT node: CDU → VGO → GO HT → treated VGO → FCC
- Add Scanfiner node: FCC → HCN → Scanfiner → treated HCN → Blender
- Add Alkylation node: FCC → C3/C4 → Alkylation → Alkylate → Blender
- Show LPG split (what goes to alky vs LPG sale)

Tests:
- test_go_ht_reduces_fcc_sulfur: FCC products have lower sulfur with GO HT
- test_scanfiner_enables_more_hcn_in_blend: more HCN in gasoline when Scanfiner active
- test_gasoline_sulfur_relaxed: gasoline sulfur margin improves with Scanfiner + GO HT
- test_alkylate_in_gasoline: alkylate appears in blend recipe
- test_margin_increase: margin with all three > without
- test_backward_compatible: config without these units still works

---

## SPRINT 11: HYDROTREATERS + POSTGRESQL

Three hydrotreaters — each is a simple sulfur-removal model with the same pattern but different feed/product specs.

### Task 11.1: Hydrotreater model (generic)

Create `src/eurekan/models/hydrotreater.py`:

```python
class HydrotreaterConfig(BaseModel):
    """Configuration for any hydrotreater — same physics, different specs."""
    unit_id: str                        # "naphtha_ht", "kero_ht", "diesel_ht"
    display_name: str                   # "Naphtha Hydrotreater"
    capacity_bpd: float                 # max feed rate
    desulfurization_efficiency: float   # 0.995 = removes 99.5% of sulfur
    cetane_improvement: float           # 0 for naphtha/kero, +3 for diesel
    volume_yield: float                 # 0.99 typical (1% to gas)
    hydrogen_consumption_base: float    # wt fraction per wt% feed sulfur
    opex_per_bbl: float                 # $/bbl feed

class HydrotreaterModel(BaseUnitModel):
    """
    Generic hydrotreater: removes sulfur, consumes hydrogen.
    Same model used for naphtha HT, kero HT, and diesel HT.
    
    Three instances in a typical refinery:
    
    1. Naphtha HT (NHT):
       Feed: heavy naphtha from CDU (before reformer)
       Purpose: sulfur < 1 ppm (reformer catalyst protection)
       Critical: reformer CANNOT run without pretreated feed
    
    2. Kerosene HT:
       Feed: kerosene from CDU
       Purpose: meet jet fuel sulfur spec (<3000 ppm) + smoke point
       Without this: kerosene may not meet jet fuel quality
    
    3. Diesel HT:
       Feed: CDU diesel + FCC LCO
       Purpose: ULSD spec (<15 ppm sulfur)
       LCO has high sulfur (~0.5-1.5%) and low cetane (~20)
       Cetane improvement: +3 numbers from hydrotreating
    """
    
    def calculate(self, feed_rate: float, feed_sulfur: float,
                  feed_cetane: float, config: HydrotreaterConfig) -> HydrotreaterResult:
        """
        product_sulfur = feed_sulfur × (1 - desulf_efficiency)
        product_cetane = feed_cetane + cetane_improvement
        hydrogen_consumed = h2_base × feed_sulfur_wt% × feed_rate
        product_volume = feed_rate × volume_yield
        """
        ...
```

Add `HydrotreaterResult` to results.py:
- unit_id (str)
- product_volume (float, bbl/d)
- product_sulfur (float, ppm)
- product_cetane (float — relevant for diesel only)
- hydrogen_consumed (float, MMSCFD)

Default configs for the three HT units:
```python
NAPHTHA_HT_CONFIG = HydrotreaterConfig(
    unit_id="naphtha_ht", display_name="Naphtha Hydrotreater",
    capacity_bpd=30000, desulfurization_efficiency=0.999,
    cetane_improvement=0, volume_yield=0.995,
    hydrogen_consumption_base=0.001, opex_per_bbl=1.50,
)

KERO_HT_CONFIG = HydrotreaterConfig(
    unit_id="kero_ht", display_name="Kerosene Hydrotreater",
    capacity_bpd=20000, desulfurization_efficiency=0.990,
    cetane_improvement=0, volume_yield=0.995,
    hydrogen_consumption_base=0.0012, opex_per_bbl=1.50,
)

DIESEL_HT_CONFIG = HydrotreaterConfig(
    unit_id="diesel_ht", display_name="Diesel Hydrotreater",
    capacity_bpd=40000, desulfurization_efficiency=0.995,
    cetane_improvement=3, volume_yield=0.990,
    hydrogen_consumption_base=0.0015, opex_per_bbl=2.00,
)
```

Tests in `tests/unit/test_hydrotreater.py`:
- test_naphtha_ht: 500 ppm feed → <1 ppm product (reformer-safe)
- test_kero_ht: 2000 ppm feed → <20 ppm product (jet spec)
- test_diesel_ht: 5000 ppm feed → <15 ppm product (ULSD)
- test_diesel_cetane: product cetane = feed cetane + 3
- test_lco_high_sulfur: LCO at 1.5% → meets 15 ppm after HT
- test_hydrogen_consumption: increases with feed sulfur
- test_volume_yield: ~99% of feed

**IMPORTANT: Cetane reality check.** LCO cetane is ~20. Even with +3 improvement from hydrotreating, product cetane is ~23 — far below the ULSD spec of 40+. The diesel pool needs enough straight-run CDU diesel (cetane ~45-55) to dilute the LCO. The ConstraintDiagnostician should flag "LCO cetane limits diesel inclusion rate" when the diesel cetane spec is binding. The AI narrative (domain rules) should include: if diesel_cetane_margin < 3 → flag "LCO inclusion in diesel is limited by cetane. Consider reducing FCC LCO routing to diesel."

### Task 11.2: Integrate hydrotreaters into PyomoModelBuilder

Update builder.py to add ALL THREE hydrotreaters (each optional based on config.units):

**Naphtha HT (required if reformer exists):**
- nht_feed[p] = heavy_naphtha routed to NHT
- nht_product[p] = treated naphtha → reformer feed
- Flow: CDU → HN → NHT → Reformer (series, not parallel)
- Constraint: reformer_feed must come FROM NHT, not raw HN
- If no NHT in config but reformer exists → assume HN is clean enough
  (simplified for refineries without explicit NHT)

**Kerosene HT:**
- kero_ht_feed[p] = kerosene routed to kero HT
- kero_ht_product[p] = treated kerosene → jet fuel sale
- Kero disposition: kero_to_ht[p] + kero_to_diesel[p] = kero_available
- Jet fuel sulfur spec: product_sulfur ≤ jet_sulfur_max
- If no kero HT → kerosene sells directly (current Stage 1 behavior)
  with assumed sulfur compliance

**Diesel HT (replaces flat $2/bbl proxy):**
- diesel_ht_feed[p]: CDU diesel + LCO routed to HT
- diesel_ht_sulfur[p]: blended feed sulfur (nonlinear)
- diesel_product_sulfur[p]: after treatment
- hydrogen_to_ht[p]: consumed
- Diesel sulfur spec: product_sulfur ≤ 15 ppm
- Diesel cetane spec: blended cetane ≥ 40
  (CDU diesel cetane ~50, HT-LCO cetane ~23 — dilution constraint)

**Hydrogen balance — THIS IS AN EXPLICIT CONSTRAINT, NOT JUST ACCOUNTING:**

The "Octane-Hydrogen Seesaw": the reformer produces both octane (reformate) AND hydrogen. The optimizer must balance:
- Higher reformer severity → more octane, more H2, but less liquid yield
- Lower reformer severity → less octane, less H2, but more liquid yield
- If H2 demand exceeds reformer supply → must purchase H2 OR reduce HT throughput

Variables:
- h2_reformer_production[p]: MMSCFD from reformer (function of severity)
- h2_purchased[p]: MMSCFD from H2 plant, bounded [0, 0.15] (Gulf Coast CH2P capacity)
- h2_to_nht[p], h2_to_kht[p], h2_to_dht[p], h2_to_goht[p]: consumed by each HT

HARD CONSTRAINT (must always hold):
```
h2_reformer_production[p] + h2_purchased[p] >= h2_to_nht[p] + h2_to_kht[p] + h2_to_dht[p] + h2_to_goht[p]
```

If this constraint binds → the optimizer MUST either:
1. Increase reformer severity (more H2, less liquid yield)
2. Purchase H2 at $1.50/MSCF (cost hits the objective)
3. Reduce HT throughput (less treated product → less revenue)

The ConstraintDiagnostician should flag: "Hydrogen balance is binding. Reformer is the bottleneck — consider increasing severity from 98 to 100 RON to produce more H2, or purchase H2 at $X/month."

**CRITICAL: Do NOT let the optimizer "starve" hydrotreaters of hydrogen to maximize liquid yield. The H2 balance constraint prevents this — if H2 demand exceeds supply, the model must pay for it (purchase) or sacrifice something (HT throughput or reformer yield).**

Each HT checks config.units — skip if not present. Backward compatible.

### Task 11.3: PostgreSQL for scenario persistence

Add dependencies:
```toml
[project.optional-dependencies]
db = ["sqlalchemy>=2.0", "asyncpg>=0.29", "alembic>=1.13"]
```

Create `src/eurekan/db/`:
- `models.py`: SQLAlchemy models for Scenario, OptimizationRun
- `session.py`: async database session factory
- `migrations/`: Alembic migration scripts

Schema:
```sql
CREATE TABLE scenarios (
    id UUID PRIMARY KEY,
    name TEXT NOT NULL,
    parent_id UUID REFERENCES scenarios(id),
    created_at TIMESTAMP DEFAULT NOW(),
    margin FLOAT,
    solver_status TEXT,
    result_json JSONB  -- full PlanningResult serialized
);
```

**IMPORTANT: Use `result.model_dump_json()` explicitly** when storing PlanningResult to JSONB. Complex nested structures (MaterialFlowGraph, SolutionNarrative) with circular references or Pydantic computed fields can fail with generic JSON serialization. Always use Pydantic's own serializer. When reading back, use `PlanningResult.model_validate_json(row.result_json)` to reconstruct. Add a round-trip test: store → read → compare all fields.

CREATE INDEX idx_scenarios_parent ON scenarios(parent_id);
CREATE INDEX idx_scenarios_created ON scenarios(created_at DESC);
```

Update `services.py`:
- If DATABASE_URL env var is set → use PostgreSQL
- If not set → fall back to in-memory dict (backward compatible)
- Scenarios persist across server restarts when using PostgreSQL

### Task 11.4: Full Stage 2B integration test

Create `tests/integration/test_stage2b.py`:

Full refinery with all Stage 2B units:
1. Parse Gulf Coast with splitter + NHT + reformer + GO HT + Scanfiner + kero HT + diesel HT + alky configs
2. Optimize → verify all units active on flowsheet
3. Verify naphtha splitter separates LN and HN
4. Verify NHT feeds the reformer (sulfur <1 ppm to reformer)
5. Verify reformer produces reformate (purchased reformate ≈ 0)
6. Verify GO HT treats VGO → lower sulfur in FCC products
7. Verify Scanfiner treats HCN → more HCN in gasoline blend
8. Verify kero HT treats kerosene for jet fuel quality
9. Verify alkylate in gasoline blend
10. Verify diesel meets 15 ppm sulfur spec via diesel HT
11. Verify hydrogen balance (reformer → NHT + KHT + DHT + GOHT + H2 plant makeup)
12. Compare margin: full refinery vs Stage 1 (CDU+FCC only)
    Margin should increase significantly
13. Verify gasoline sulfur margin IMPROVES (Scanfiner + GO HT effect)
14. All Stage 1 tests still pass (backward compatibility)
15. All Stage 2A tests still pass

Run: `uv run pytest tests/ -v --cov=eurekan`
Report total tests and coverage.

Commit: `git commit -m "Stage 2B complete: reformer + alkylation + diesel HT + PostgreSQL"`

---

## Expected Results After Stage 2B

```
MARGIN PROGRESSION:

  Stage 1 (CDU + FCC only):                          ~$853K/day
  + Naphtha Splitter (realistic naphtha routing):       minimal
  + Naphtha HT + Reformer (replace purchased reformate): +$200-400K/day
  + GO Hydrotreater (cleaner FCC feed → better products): +$50-100K/day
  + Scanfiner (HCN sulfur removal → more gasoline):      +$100-200K/day
  + Alkylation (C3/C4 → alkylate):                       +$100-200K/day
  + Diesel HT (LCO → ULSD instead of FO):                +$50-100K/day
  + Kero HT (jet fuel quality):                           +$20-50K/day
  
  Full Stage 2B:                                     ~$1.3-1.8M/day
  
  The Scanfiner is the SURPRISE value driver — it's what makes 
  the Gulf Coast model able to put HCN in gasoline at spec.
  Without it, HCN sulfur is the binding constraint.

FLOWSHEET EVOLUTION:

  Stage 1:
  Crudes → CDU → FCC → Blender → Products
                                 ↗ Reformate (purchased)

  Stage 2B (matching Gulf Coast):
  Crudes → CDU → Naphtha → Splitter → LN → Gasoline Blend / C5-C6 Isom
                                     → HN → Naphtha HT → Reformer → Reformate → Blend
               → Kero → Kero HT → Jet Fuel
               → Diesel → Diesel HT → ULSD
               → VGO → GO HT → FCC → LCN → Gasoline Blend
                                    → HCN → Scanfiner → Gasoline Blend
                                    → LCO → Diesel HT → ULSD
                                    → C3/C4 → Alkylation → Alkylate → Blend
                                    → Slurry → Fuel Oil
               → Resid → Fuel Oil (Coker in Stage 3)
               → Hydrogen: Reformer → NHT + KHT + DHT + GOHT + H2 Plant makeup
```

## Key Design Principle

Each unit is OPTIONAL. The PyomoModelBuilder checks `config.units`:
- No naphtha splitter → CDU makes separate LN and HN directly
- No NHT → HN goes directly to reformer (assumed clean)
- No reformer → purchased reformate fills octane gap (Stage 1 behavior)
- No GO HT → raw VGO goes to FCC (higher sulfur products)
- No Scanfiner → FCC HCN goes to blend with high sulfur (sulfur-limited)
- No alkylation → C3/C4 all sold as LPG
- No kero HT → kerosene sells directly (assumed clean)
- No diesel HT → flat opex proxy on diesel

The same codebase handles a simple CDU+FCC refinery and a complex
25-unit refinery. The config drives the model.
This is what makes it a PLATFORM, not a one-off tool.
