# STAGE2B_SPRINTS.md — Reformer + Alkylation + Diesel HT + PostgreSQL

## Overview

Stage 2A built the product: API + UI + flowsheet + scenarios + narratives.
Stage 2B adds three process units and persistent storage. Same architecture — each unit follows the BaseUnitModel pattern, plugs into PyomoModelBuilder, and appears on the flowsheet automatically.

**What changes with each unit:**

```
REFORMER:
  Before: Purchased reformate at $70/bbl fills the octane gap
  After:  Heavy naphtha → reformer → reformate (RON 100+)
  Impact: Purchased reformate drops to zero, HN stops selling as naphtha
          Margin increases by ~$500-800K/month (the reformer's value)
          Shadow price on purchased reformate was already predicting this

ALKYLATION:
  Before: FCC C3/C4 sold as LPG at $44/bbl
  After:  C3/C4 → alkylation → alkylate (RON 96, zero sulfur, low RVP)
  Impact: Alkylate is the BEST gasoline blend component
          LPG revenue drops but gasoline value increases more
          Sulfur constraint relaxes (alkylate has zero sulfur)

DIESEL HYDROTREATER:
  Before: Flat $2/bbl proxy cost on diesel
  After:  Real sulfur removal model (feed sulfur → product sulfur)
          LCO (high sulfur) can be treated and blended into ULSD
  Impact: More diesel from FCC LCO, less fuel oil
          Diesel sulfur spec becomes a real constraint
```

## Prerequisites

Stage 2A complete: 456 tests, 18 API endpoints, 18 React components.
All existing tests must continue passing after each sprint.

---

## SPRINT 9: CATALYTIC REFORMER

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

## SPRINT 10: ALKYLATION UNIT

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

### Task 10.2: Integrate alkylation into PyomoModelBuilder

Update builder.py:

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

### Task 10.3: Update flowsheet for alkylation

Update modes.py:
- Add alkylation node to MaterialFlowGraph
- Edges: FCC → C3/C4 → Alkylation → Alkylate → Blender
- Show LPG split (what goes to alky vs LPG sale)

---

## SPRINT 11: DIESEL HYDROTREATER + POSTGRESQL

### Task 11.1: Diesel hydrotreater model

Create `src/eurekan/models/diesel_ht.py`:

```python
class DieselHTModel(BaseUnitModel):
    """
    Diesel hydrotreater: removes sulfur from diesel + LCO blend.
    
    Key physics:
    - Feed: CDU diesel + FCC LCO (blended)
    - Product: ULSD (ultra-low sulfur diesel, <15 ppm S)
    - Consumes hydrogen
    - Higher feed sulfur → more hydrogen consumed
    - LCO has high sulfur (~0.5-1.5%) and low cetane (~19-25)
    - Hydrotreating improves cetane slightly (+2-4 numbers)
    
    Correlations:
    - Product sulfur = feed_sulfur × (1 - desulfurization_efficiency)
    - Desulfurization efficiency = 0.995 at design severity (99.5%)
    - Hydrogen consumption = 0.002 + 0.0015 × feed_sulfur_wt% (wt fraction)
    - Cetane improvement = +3 numbers from hydrotreating
    - Volume yield ≈ 0.99 (1% volume loss to gas)
    """
    
    def calculate(self, feed_rate: float, feed_sulfur: float,
                  feed_cetane: float, hydrogen_available: float) -> DieselHTResult:
        ...
```

Add `DieselHTResult` to results.py:
- product_volume (float, bbl/d)
- product_sulfur (float, ppm)
- product_cetane (float)
- hydrogen_consumed (float, MMSCFD)

Tests in `tests/unit/test_diesel_ht.py`:
- test_sulfur_removal: 5000 ppm feed → <15 ppm product
- test_volume_yield: ~99% of feed
- test_cetane_improvement: product cetane > feed cetane
- test_hydrogen_consumption: increases with feed sulfur
- test_high_sulfur_lco: LCO at 1.5% sulfur → still meets 15 ppm after HT

**IMPORTANT: Cetane reality check.** LCO cetane is ~20. Even with +3 improvement from hydrotreating, product cetane is ~23 — far below the ULSD spec of 40+. The diesel pool needs enough straight-run CDU diesel (cetane ~45-55) to dilute the LCO. The ConstraintDiagnostician should flag "LCO cetane limits diesel inclusion rate" when the diesel cetane spec is binding. The AI narrative (domain rules) should include: if diesel_cetane_margin < 3 → flag "LCO inclusion in diesel is limited by cetane. Consider reducing FCC LCO routing to diesel."

### Task 11.2: Integrate diesel HT into PyomoModelBuilder

Update builder.py:

Replace the flat $2/bbl diesel HT cost with real model:
- diesel_ht_feed[p]: CDU diesel + LCO routed to HT
- diesel_ht_sulfur[p]: blended feed sulfur (nonlinear)
- diesel_product_sulfur[p]: after treatment
- hydrogen_to_ht[p]: consumed

Add diesel sulfur spec constraint: product_sulfur ≤ 15 ppm
This replaces the proxy — now the model knows WHY diesel costs
what it costs and what limits LCO inclusion.

Hydrogen balance (simplified for Stage 2B):
- Hydrogen supply: reformer production + purchased
- Hydrogen demand: diesel HT consumption
- If reformer provides enough H2 → no purchase needed
- If not → hydrogen purchase cost (~$1.50/MSCF)

Check config.units for 'diesel_hydrotreater' — skip if not present.

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

Full refinery with all units:
1. Parse Gulf Coast with reformer + alky + diesel HT configs
2. Optimize → verify all units active on flowsheet
3. Verify reformer produces reformate (purchased reformate ≈ 0)
4. Verify alkylate in gasoline blend
5. Verify diesel meets 15 ppm sulfur spec via HT
6. Verify hydrogen balance (reformer → HT)
7. Compare margin: full refinery vs Stage 1 (CDU+FCC only)
   Margin should increase significantly
8. All Stage 1 tests still pass (backward compatibility)
9. All Stage 2A tests still pass

Run: `uv run pytest tests/ -v --cov=eurekan`
Report total tests and coverage.

Commit: `git commit -m "Stage 2B complete: reformer + alkylation + diesel HT + PostgreSQL"`

---

## Expected Results After Stage 2B

```
MARGIN PROGRESSION:

  Stage 1 (CDU + FCC):                    ~$853K/day
  + Reformer (no more purchased reformate): +$200-400K/day
  + Alkylation (C3/C4 → alkylate):          +$100-200K/day  
  + Diesel HT (LCO → ULSD instead of FO):  +$50-100K/day
  
  Full Stage 2B:                          ~$1.1-1.5M/day
  
  The margin increase VALIDATES the shadow prices from Stage 1:
  - Shadow price on purchased reformate predicted the reformer value
  - Price gap between LPG and alkylate predicted the alky value
  - Price gap between fuel oil and diesel predicted the HT value

FLOWSHEET EVOLUTION:

  Stage 1:
  Crudes → CDU → FCC → Blender → Products
                                 ↗ Reformate (purchased)

  Stage 2B:
  Crudes → CDU → Reformer → Reformate → Blender → Products
               → FCC → C3/C4 → Alkylation → Alkylate → Blender
                     → LCO → Diesel HT → ULSD
                     → LCN/HCN → Blender
               → Hydrogen (Reformer → Diesel HT)
```

## Key Design Principle

Each unit is OPTIONAL. The PyomoModelBuilder checks `config.units`:
- No reformer → purchased reformate fills octane gap (Stage 1 behavior)
- No alkylation → C3/C4 all sold as LPG
- No diesel HT → flat opex proxy on diesel

The same codebase handles a simple CDU+FCC refinery and a complex
CDU+FCC+Reformer+Alky+HT refinery. The config drives the model.
This is what makes it a PLATFORM, not a one-off tool.
