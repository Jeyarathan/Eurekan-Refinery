# CLAUDE.md — Eurekan Refinery Planner

## Project Overview

Eurekan Refinery Planner is a refinery planning optimization tool that auto-generates optimization models from crude assay data, unit configurations, and product specifications. It replaces PIMS/GRTMPS with direct NLP optimization via IPOPT — no delta-base vectors, no SLP recursion, no manual model building.

**Stage 1 scope:** 1 CDU (80K bbl/d) + 1 FCC (50K bbl/d) + Gasoline Blender. 45+ crudes from the Gulf Coast PIMS model. Multi-period planning with simulation, optimization, and hybrid modes.

## Tech Stack

- **Python 3.12+** with **uv** for package management
- **Pyomo 6.x** for optimization modeling
- **IPOPT** (via cyipopt) for NLP solving
- **HiGHS** (via highspy) for LP/MILP fallback
- **Pydantic v2** for all data models (typed, validated, JSON-serializable)
- **numpy/scipy** for scientific computation
- **pandas + openpyxl + xlrd** for data import
- **pytest** for testing, **ruff** for linting, **mypy** for type checking

## Project Structure

```
src/eurekan/
├── core/           # Pydantic data models — NEVER import from other eurekan packages
│   ├── config.py   # RefineryConfig, UnitConfig
│   ├── crude.py    # CrudeAssay, CutYield, CutProperties, CrudeLibrary
│   ├── period.py   # PeriodData, PlanDefinition
│   ├── product.py  # Product, ProductSpec, BlendingRule
│   ├── stream.py   # Stream, StreamDisposition
│   ├── tank.py     # Tank, TankInventory
│   ├── results.py  # PlanningResult, SimulationResult, OracleResult, etc.
│   └── enums.py    # OperatingMode, UnitType, TankType, BlendMethod
│
├── models/         # Unit models (physics) — depends on core/ only
│   ├── base.py     # BaseUnitModel (abstract)
│   ├── cdu.py      # CDUModel — exact yields from assay interpolation
│   ├── fcc.py      # FCCModel — correlations + equipment bounds + calibration
│   └── blending.py # BlendingModel — ASTM standard methods
│
├── optimization/   # NLP builder + solver — depends on core/ and models/
│   ├── builder.py  # PyomoModelBuilder — generates NLP for N periods
│   ├── objective.py# Economic objective function
│   ├── constraints.py # All constraint builders
│   ├── solver.py   # IPOPT integration, multi-start, LP fallback
│   ├── diagnostics.py # Constraint diagnostics, infeasibility negotiator, shadow prices
│   └── modes.py    # Simulation/Optimization/Hybrid mode logic
│
├── parsers/        # Data import — depends on core/ only
│   ├── gulf_coast.py # Gulf Coast Excel parser
│   └── schema.py   # Sheet schema validation (tag-based, not position-based)
│
├── analysis/       # Post-solve analysis — depends on core/ and models/
│   ├── oracle.py   # Oracle gap analysis
│   ├── alternatives.py # Near-optimal solution enumeration
│   ├── sensitivity.py # Price/crude sensitivity
│   └── reports.py  # Output formatting
│
├── api/            # FastAPI layer (Stage 2) — depends on everything above
│   ├── app.py      # FastAPI app, CORS, lifespan
│   ├── services.py # Business logic bridge (routes → core)
│   ├── schemas.py  # Request models
│   └── routes/     # Endpoint handlers (optimize, config, scenarios, oracle, ai)
│
└── ai/             # Claude API integration (Stage 2)
    ├── narrative.py # Three-step pipeline: facts → rules → prose
    └── what_if.py  # Natural language → structured action parser
```

## Architecture Rules

1. **Dependency direction:** `core/` ← `models/` ← `optimization/`. Never import backwards.
2. **Pydantic everywhere:** All data structures are Pydantic BaseModel. No plain dicts for structured data.
3. **Period-agnostic:** All equations are indexed by period `p`. Same code handles N=1 (monthly) and N=168 (future hourly scheduling). Never hardcode single-period assumptions.
4. **Mode via variable flags:** Each decision variable has a mode: FIXED, FREE, or BOUNDED. Simulation fixes all. Optimization frees all. Hybrid is user-specified. The equation system is identical across modes.
5. **Unit models are callable classes:** `FCCModel.calculate(feed_props, conversion)` returns `FCCResult`. Layer-independent. Planning calls it once. Future scheduling calls it per hour.
6. **Tank inventory is first-class:** Even in Stage 1 with N=1, inventory tracking is built in via `inv[tank, p] = inv[tank, p-1] + inflow - outflow`.
7. **Engineer-native naming — NO PIMS TAGS in the core.** All names are human-readable, domain-standard. Cuts are defined by temperature ranges (light_naphtha, kerosene, vgo), not PIMS tags (DBALLN1, VBALKE1). Products use plain names (regular_gasoline, ulsd), not codes (CRG, ULS). Properties use standard names (ron, rvp, sulfur), not spec codes (NDON, XRVI, XSUL). PIMS tags exist ONLY inside `parsers/gulf_coast.py` as a translation layer.
8. **Temperature-based cuts:** Distillation cuts are defined by TBP temperature ranges, not arbitrary names. The user can adjust cut points — the model regenerates automatically. This is fundamentally different from PIMS where cut points are baked into the model.
9. **Parser is a pluggable adapter:** The Gulf Coast parser translates PIMS format → Eurekan model. A future customer uploads their own Excel → a different parser translates THEIR format → same Eurekan model. The core never changes.
10. **Data provenance on every value.** Every data field tracks its source (DataSource enum: DEFAULT, TEMPLATE, IMPORTED, USER_ENTERED, AI_EXTRACTED, CALIBRATED, CALCULATED) and confidence (0-1). The UI shows where every number came from. Users trust their own data, verify defaults, and see which values matter most to improve.
11. **Smart defaults everywhere — nothing blocks the user.** Every field has a reasonable default. Missing VGO CCR? Use typical for that crude type. Missing product spec? Use regulatory standard. The system produces a result at 50% completeness. Accuracy improves as users add data. The first optimization runs in minutes, not months.
12. **Completeness tracking.** RefineryConfig exposes a `completeness()` method that returns overall percentage, list of missing items, items using defaults, and a `ready_to_optimize` boolean. The UI shows this as a progress indicator, not a blocker.
13. **Progressive disclosure — three layers of depth.** Layer 1 (everyone): flowsheet view with numbers and economics. Layer 2 (planners): configuration forms, scenario comparison, constraint editing. Layer 3 (engineers): correlations, calibration parameters, equipment models. Most users never leave Layer 1.

## UX Design Philosophy — We Are NOT PIMS

Eurekan competes with PIMS by being its opposite in user experience:

| PIMS | Eurekan |
|------|---------|
| Blank spreadsheet — user fills 218 rows | Pre-configured template — user adjusts what's different |
| Arcane tags (DBALLN1, XRVI, NDON) | Engineer language (Light Naphtha, RVP, Road Octane) |
| 6-12 months to first useful result | 15-30 minutes to first optimization |
| Model building IS programming | Model builds itself from data |
| Changes require expert rebuild | Changes regenerate automatically |
| Results are tables of numbers | Results are visual with plain-English explanations |
| No guidance when things go wrong | AI explains what went wrong and suggests fixes |
| Sub-models require simulation expertise | Sub-models from templates, upgraded via plant data |
| Cut points baked into model | Cut points adjustable, model regenerates |
| One input format (PIMS syntax) | Upload anything — AI parses it |

**The core principle: the user describes their refinery in THEIR language. The system figures out the math.**

### Sub-Model Creation (Stage 2+ AI feature, but architecture supports it now)

Four tiers, user graduates through them:
1. **Template** (30 seconds): "I have an FCC" → published correlations, works immediately, ±10%
2. **AI-Assisted** (15 minutes): Upload operating manual or test run data → AI extracts parameters → ±5%
3. **Plant data calibration** (ongoing): Monthly auto-calibration from historian → ±2-3%
4. **Expert override** (power users): Full control over every parameter, starting from a working model

Every tier produces a working model. Tier 1 takes seconds. Nobody starts from a blank page.

### Crude Library (built-in, searchable)

Eurekan ships with a library of 100+ common crudes with full assays, origins, and typical properties. Users SEARCH AND SELECT, not type 218 rows. Custom crudes added via upload, paste, or AI extraction from supplier documents. The library grows as users contribute (anonymized) assay data.

## Coding Conventions

- **Type everything.** No `Any` types. Use `Optional[float]` for nullable fields.
- **Docstrings on all public classes and functions.** Explain WHAT and WHY, not HOW.
- **No magic numbers.** Constants go in the model or config, not inline.
- **ruff format** before every commit. Line length 100.
- **Tests mirror source structure:** `tests/unit/test_cdu.py` tests `src/eurekan/models/cdu.py`.
- **Validation tests are first-class citizens** — not afterthoughts. They verify the MODEL is correct, not just the code.

## Development Workflow Rules

These rules govern how code is written and validated in this project. They apply to every task.

**Atomic tasks:** Each coding task should touch 1-3 files and take 5-15 minutes. Never attempt "build the whole refinery" in one pass. Complete one model, test it, commit it, then move to the next.

**Test before moving on:** No unit model is accepted without a validation test comparing it against known Gulf Coast data. If the CDU model doesn't match ARL yields within tolerance, fix it before starting the FCC model.

**Run tests after every change:** After writing or modifying any code, run `uv run pytest tests/ -v` and fix failures immediately. Do not accumulate test debt.

**Commit after every milestone:** Each passing test suite is a commit. Provides recovery points if subsequent work goes wrong.

**Think before coding:** If a task is ambiguous, STATE your assumptions explicitly before writing code. If multiple interpretations exist, present them and ask. If a simpler approach exists than what was requested, say so. If confused, STOP and ask — do not guess and run with it.

**Simplicity first:** Write the minimum code that solves the problem. No speculative features. No abstractions for single-use code. No "flexibility" or "configurability" that wasn't requested. No error handling for impossible scenarios. If 200 lines could be 50, rewrite it. Would a senior engineer say this is overcomplicated? If yes, simplify.

**Surgical changes:** Touch ONLY what the task requires. Do not "improve" adjacent code, comments, or formatting. Do not refactor things that aren't broken. Match existing style. If you notice unrelated issues, MENTION them — don't fix them. When your changes create orphaned imports or variables, clean up YOUR mess only. Every changed line must trace directly to the task. This is especially critical in Stage 2: do NOT modify core/, models/, optimization/, parsers/, or analysis/ while building api/ or frontend/ unless explicitly asked.

**Solver-specific guardrails:**
- IPOPT requires a feasible starting point — never initialize variables at zero
- All Pyomo constraints MUST be indexed by period `p` — even for N=1 cases
- All Pyomo variables must have explicit bounds — unbounded variables cause IPOPT divergence
- After building any Pyomo model, verify it has the expected number of variables and constraints before solving
- If IPOPT returns non-optimal status, log the full solver output before retrying

**Mathematical verification:** When implementing FCC correlations, blending rules, or any physics-based calculation:
- Compute expected output by hand for at least one test case
- Compare code output against hand calculation within stated tolerance
- Document the hand calculation in the test as a comment
- If suggesting a Pyomo formulation or solver setting, explain WHY that formulation was chosen

## NLP Solver Strategy

NLPs are sensitive to starting points. IPOPT with a "cold start" (all zeros) will fail. The solver must use a three-tier initialization strategy:

**Tier 1 — Heuristic warm-start (always used):**
- Crude rates: split total capacity equally across available crudes
- FCC conversion: 80% (mid-range, physically feasible on most feeds)
- Blend fractions: proportional to component availability
- Dispositions: all material to highest-value destination
- This produces a physically feasible (not optimal) starting point

**Tier 2 — LP relaxation warm-start (if Tier 1 fails):**
- Discretize FCC conversion into 5 modes (72%, 76%, 80%, 84%, 88%)
- Each mode has pre-computed yields (from FCCModel at that conversion)
- Solve the resulting LP with HiGHS (milliseconds)
- Use LP solution as IPOPT starting point
- The LP solution is feasible and near-optimal — IPOPT converges quickly from here
- **CRITICAL: The LP must include the same material balances, capacity constraints, and stream dispositions as the NLP.** Only the FCC yields are discretized — everything else is identical. This ensures the warm-start is physically consistent and IPOPT doesn't encounter constraint violations on the first iteration.

**Tier 3 — Multi-start (if Tier 2 fails):**
- Generate 5 random starting points (random crude split, random conversion 72-88%)
- Solve IPOPT from each starting point
- Return the best feasible solution
- If all 5 fail, report infeasibility with diagnostics

Implementation: `EurekanSolver` tries Tier 1 → Tier 2 → Tier 3 automatically. The user never sees the initialization strategy — they just get a solution or a clear infeasibility message.

## Solver Observability — The Constraint Negotiator

NLP solvers are black boxes. PIMS users dread "Infeasible" because it gives no explanation. Eurekan's solver ALWAYS provides diagnostics, whether the solution is feasible or not.

**After EVERY solve (feasible or not):**
- Extract Lagrange multipliers (shadow prices) from IPOPT for all constraints
- Identify binding constraints (shadow price ≠ 0) — these are the bottlenecks
- Rank by economic impact ($/month per unit of relaxation)
- Generate plain-English explanations

**Example (feasible solution):**
```
Your plan is feasible. The tightest constraints are:
1. FCC Regen Temperature: 98% utilized (1,320°F of 1,350°F limit)
   → Each °F of additional headroom is worth $45K/month
   → This is your bottleneck. Driven by Mars crude CCR.
2. Gasoline Sulfur: 93% utilized (28ppm of 30ppm limit)
   → Close to spec. HCN sulfur is the driver.
```

**When INFEASIBLE — the Constraint Negotiator:**
- Add slack variables to all constraints (elastic programming)
- Re-solve minimizing total slack to find the minimum relaxation
- For each violated constraint: compute relaxation needed, estimate cost, suggest fix
- Present as a business conversation, not a math problem

**Example (infeasible):**
```
No feasible plan exists with current constraints. Here's why:

Violated: Gasoline sulfur at 50ppm (spec is 30ppm)
  Your crude slate produces too much sulfur for 30ppm gasoline.
  
  Options (cheapest first):
  1. Relax sulfur to 35ppm → plan becomes feasible, +$40K/month
  2. Reduce Mars from 25K to 17K bbl/d → feasible at 30ppm
  3. Add Scanfiner (FCC naphtha desulfurizer) → long-term fix
  
  Apply option 1? [Yes] [No, show me option 2]
```

This is implemented via `ConstraintDiagnostician` in `optimization/diagnostics.py`. It runs after every solve and populates `PlanningResult.constraint_diagnostics` and `PlanningResult.infeasibility_report`.

## Scenario Management

Planning is iterative. Users explore "what if" by branching scenarios. Eurekan supports this natively.

**Every PlanningResult has:**
- `scenario_id`: unique identifier (UUID)
- `scenario_name`: user-friendly label ("Base Case", "High Gas Price")
- `parent_scenario_id`: which scenario this was branched from (None for root)
- `created_at`: timestamp

**Scenarios form a tree:**
```
Base Case (March 2029)
├── High Gas Price (+$5/bbl gasoline)
│   └── High Gas + FCC Outage (week 3)
├── Cheap Mars Crude (-$3/bbl)
└── Basrah Light Cargo (replace 15K ARL)
```

**ScenarioComparison** shows the diff between any two scenarios: margin delta, crude slate changes, conversion delta, product volume changes, and an AI-generated plain-English summary of what changed and why.

This replaces the `plan_v1_final_v2_REALLYFINAL.xls` workflow that every PIMS user suffers through. Scenarios are immutable snapshots — the user can always go back to any branch.

## Calibration Strategy

The calibration engine fits 11 FCC parameters from plant operating data. With sparse data (6-12 monthly points), plain least-squares will overfit.

**Use Tikhonov regularization (ridge regression):**
```
minimize: Σ(predicted - actual)² + λ × Σ(param - default)²
```
Where `default` = the published correlation values (α=1.0, Δ=0.0). This penalizes large deviations from published correlations — the prior belief is "the published correlation is probably close, adjust only as much as the data demands."

λ (regularization strength) controls the tradeoff:
- High λ: trust published correlations, small adjustments only
- Low λ: trust plant data, larger adjustments allowed
- Auto-tune λ via leave-one-out cross-validation on the plant data

Additional safeguards:
- Bound all α parameters to [0.7, 1.3] (±30% of published)
- Bound all Δ parameters to physically reasonable ranges
- If fewer than 6 data points, use high λ (conservative calibration)
- Report confidence intervals on each parameter

## Excel Parser Robustness

The Gulf Coast Excel file uses PIMS conventions. Parsers must be robust to minor layout changes.

**Design rules:**
1. **Parse by ROW TAGS, not row numbers.** PIMS row tags (DBALLN1, VBALKE1, etc.) are in column A. Search for these tags to find data rows. Never hardcode "row 47 = gasoline yield."
2. **Parse by COLUMN HEADERS, not column indices.** Crude tags (ARL, AMM, BRT) are in a header row. Find the header row first, then map crude tags to column indices.
3. **Schema validation before parsing.** Before extracting values, verify that all expected row tags and column headers exist. If a tag is missing, raise a clear error: "Expected row tag 'DBALLN1' not found in Assays sheet" — not a cryptic KeyError.
4. **Implement schema validation using Pydantic.** Define expected sheet schemas (required tags, expected value ranges) and validate the raw Excel data against them before building domain objects.
5. **Tolerate extra rows/columns.** The parser should ignore rows it doesn't recognize — the Gulf Coast file has many rows we don't need in Stage 1.

## Key Domain Concepts

### CDU (Crude Distillation Unit)
Splits crude oil into cuts by boiling point. Yields are EXACT from assay data — no correlation needed. This is linear: `cut_volume = Σ(crude_rate × yield_fraction)`. Cut properties are weighted averages (nonlinear — ratios of linear terms).

Cuts are defined by TBP temperature ranges, not arbitrary tags:
- light_naphtha (C5-180°F), heavy_naphtha (180-350°F), kerosene (350-500°F), diesel (500-650°F), vgo (650-1050°F), vacuum_residue (1050°F+)
- Cut points are configurable per refinery — model regenerates automatically when cut points change.
- The Gulf Coast model uses the "US Gulf Coast (630°F EP)" template.

### FCC (Fluid Catalytic Cracker)
Cracks heavy VGO into lighter products. **Conversion** (68-90%) is the key decision variable. Yield correlations:
- Gasoline = α_gas × (-0.1553 + 1.3364c - 0.7744c² + 0.0024(API-22) - 0.0118(CCR-1))
- LCO = α_lco × (0.3247 - 0.2593c + 0.0031(API-22))
- Coke = α_coke × (0.0455 + 1.5×CCR/100 + 0.001(C-75) + 0.0002×metals)
Where c = conversion/100, API/CCR/metals are blended VGO feed properties.

Equipment bounds are physics-based:
- Regen temp = 1100 + 3800 × coke_yield + Δ_regen ≤ 1,350°F
- This LIMITS max conversion on heavy feeds — not an arbitrary bound.

11 calibration parameters: α_gasoline, α_coke, α_lcn_split, α_c3c4, α_lco, Δ_lcn_ron, Δ_hcn_ron, Δ_lcn_sulfur, Δ_hcn_sulfur, Δ_lco_cetane, Δ_regen.

### Blending
ASTM standard methods:
- RON: Blending Index method (NONLINEAR, mandatory even in Stage 1):
  - BI(RON) = -36.1572 + 0.83076×RON + 0.0037397×RON²
  - Blend BI = Σ(vol_i × BI_i) / Σ(vol_i)
  - Blend RON = inverse of BI function
  - DO NOT use linear-by-volume for RON — it gives wrong answers that matter for planning
- RVP: power law RVP^1.25 — nonlinear
- Sulfur: linear by weight — nearly linear
- Benzene, aromatics, olefins: linear by volume

### Economic Objective
```
MAXIMIZE: Σ_p margin[p] × duration[p] / 24

Revenue: gasoline×$82.81 + naphtha×$52.22 + jet×$87.59 + diesel×$86.53
         + no2oil×$85.59 + fuel_oil×$69.63 + lpg×$44.24
Costs:   crude purchase + CDU opex ($1/bbl) + FCC opex ($1.50/bbl)
         + diesel HT ($2/bbl) + purchased reformate ($70/bbl)
```

### Stream Disposition
Every stream has alternatives. The optimizer chooses:
- vgo → FCC feed or sell as fuel oil
- light_naphtha / heavy_naphtha → gasoline blend or sell as naphtha
- fcc_heavy_naphtha → gasoline or fuel oil (sulfur-limited)
- kerosene → jet fuel or diesel pool
- fcc_lco → diesel or fuel oil (cetane-limited)
- purchased_reformate fills the octane gap (no reformer in Stage 1)

All stream names are Eurekan-native. No PIMS tags.

## Solution Interpretation — The Knowledge Layer

PIMS outputs tables of 500+ rows of variable names and numbers. Planners spend 2-4 hours interpreting one solution. Eurekan embeds three layers of knowledge INTO every result — not as an afterthought, but as core data structures.

### Layer 1: Material Flow Graph (deterministic, computed)

Every optimization result includes a `MaterialFlowGraph` — a directed graph where nodes are units/tanks/products and edges are streams. Every barrel is traceable from crude purchase to product sale.

Key capabilities:
- `trace_crude("arab_light")` → shows every product Arab Light ends up in, with volumes and economics
- `trace_product("regular_gasoline")` → shows every crude and stream that contributes, with proportions
- Every edge carries `crude_contributions` — what fraction of each crude is in that stream (computed by graph traversal, not assumed)
- `CrudeDisposition` per crude: total volume, product breakdown, value created, net margin

This replaces the manual stream-tracing that PIMS planners do with pencil and paper. The graph IS the solution.

### Layer 2: Constraint Diagnostics (deterministic, from IPOPT)

Every solve extracts Lagrange multipliers (shadow prices) from IPOPT and translates them to engineer language. See "Solver Observability — The Constraint Negotiator" section above for full details.

### Layer 3: AI Narrative (generated, via Claude API)

Every optimization result includes a `SolutionNarrative` with:
- **executive_summary**: One paragraph explaining the plan (shown at top of every result)
- **decision_explanations**: For each key decision (crude selection, conversion, blend recipe) — WHY the optimizer chose it, WHAT alternatives were considered, and HOW SENSITIVE the decision is
- **risk_flags**: What could go wrong (tight specs, near-binding equipment, price sensitivity)
- **economics_narrative**: Plain-English breakdown of where the money comes from

**How the narrative is generated (three-step pipeline):**
1. **Extract structured facts** from MaterialFlowGraph + ConstraintDiagnostics (deterministic — no AI needed)
2. **Apply domain reasoning rules** (deterministic): if regen > 95% → flag bottleneck, if sulfur margin < 5ppm → trace sulfur source through graph, if conversion below peak → explain why
3. **Synthesize into prose via Claude API** (structured JSON mode): facts + domain analysis → readable narrative. The AI turns patterns into advice that reads like an experienced planner wrote it.

The narrative is Optional in Stage 1 (None when Claude API is not configured). Domain rules and facts still populate the results — only the prose synthesis requires the API. Stage 1 CLI output shows the structured facts directly.

### All Three Layers Are Part of PlanningResult

```python
PlanningResult:
    # ... standard fields (periods, margin, solver_status) ...
    material_flow: MaterialFlowGraph        # Layer 1: stream tracing
    crude_valuations: list[CrudeDisposition] # Layer 1: per-crude economics
    constraint_diagnostics: list[ConstraintDiagnostic]  # Layer 2: shadow prices + bottleneck_score (0-100)
    infeasibility_report: Optional[InfeasibilityReport] # Layer 2: if infeasible
    narrative: Optional[SolutionNarrative]  # Layer 3: AI interpretation + data_quality_warnings
```

Every solve produces Layers 1 and 2 automatically. Layer 3 is generated when the Claude API is available. The user never needs to "request" interpretation — it's always there.

### Data Quality Drives Interpretation

The narrative pipeline is aware of data provenance and calibration confidence:
- If key values use defaults (DataSource.DEFAULT), the narrative warns: "VGO CCR using default value — margin estimate uncertainty ±$200K/month. Upload lab data to improve."
- If calibration confidence is low, the narrative warns: "FCC yields based on limited data — conversion results may be ±4% accurate."
- `ConfigCompleteness.margin_uncertainty_pct` turns the progress bar into a business metric: "You are at 60% data completeness. Margin estimate: $1.2M/day ± $200K. Add VGO CCR data for Mars crude to reduce uncertainty to ± $50K."
- `ConfigCompleteness.highest_value_missing` tells the user exactly which data point to add next for the biggest accuracy improvement.

### Constraint Diagnostics Include Source Tracing

Every `ConstraintDiagnostic` traces the issue back to a specific stream or unit:
- `source_stream`: which stream/unit is causing the constraint to bind (e.g., "Mars VGO sulfur")
- `bottleneck_score` (0-100): normalized score for UI heat map — higher means more limiting to profitability. Computed by normalizing shadow prices across all constraints.
- `relaxation_suggestion` always references the specific source: "Mars VGO sulfur is 15% higher than your limit for the current FCC feed" — not just "sulfur constraint is binding."

### Scenario Comparison Includes Constraint Changes

`ScenarioComparison` shows which bottlenecks moved between scenarios — not just margin and volume deltas. This answers "why did the margin change?" at the constraint level: "Regen temperature relaxed from 98% to 85% utilization because Mars crude was reduced, allowing 2.3% more conversion."

## Gulf Coast Data Reference

The reference data is in `data/gulf_coast/Gulf_Coast.xlsx` (75 sheets). Key sheets:

| Sheet | Content | Use |
|-------|---------|-----|
| Assays | 218×50, sweet crude yields + properties, 45+ crudes | CDU yield model |
| Buy | 59×15, crude prices, API, sulfur, availability | Crude selection |
| Sell | 41×14, product prices, demand min/max | Product economics |
| Blnspec | 47×17, gasoline specifications | Blend constraints |
| Blnmix | 50×25, component-to-product map | Blend structure |
| Blnnaph | 51×30, naphtha component properties | Blend properties |
| Caps | 69×11, unit capacities | Unit constraints |
| ProcLim | 46×10, FCC operating limits | FCC bounds |
| SCCU | 303×26, FCC delta-base model | Validation target |

**Validation targets from SCCU BASE column:** At 80% conversion on Arab Light VGO: LCN≈39.3%, HCN≈10.1%, total gasoline≈49.4%, LCO≈16.2%, Coke≈3.4% FOE.

## Testing Strategy

Three test categories:

1. **Unit tests** (`tests/unit/`): Pure functions, no solver. Data model construction, yield calculations, property blending.
2. **Integration tests** (`tests/integration/`): Solver convergence, mode switching, multi-period linking.
3. **Validation tests** (`tests/validation/`): Compare against Gulf Coast PIMS data. Six categories:
   - Base case economics (sensible crude selection)
   - FCC yield accuracy (vs SCCU BASE)
   - Conversion response (overcracking peak, regen limit)
   - Crude sensitivity (light vs heavy, different limits)
   - Blending feasibility (sulfur-limited cases)
   - Price sensitivity (gas up → conv up, diesel up → conv down)

## Success Criteria

- Same crude ranking as PIMS logic ≥90% of cases
- Correct directional conversion response 100% of cases
- All blend specs met in 100% of optimized solutions
- Margin within ±10% of PIMS-equivalent
- Solve time <1 second (1 period), <5 seconds (12 periods)
- Test coverage ≥80%

---

## Stage 2A: API + UI Architecture

Stage 2A wraps the Stage 1 engine in a FastAPI backend + React frontend. **No changes to core/, models/, optimization/, parsers/, or analysis/.** The API is a thin layer on top.

### API Architecture Rules

1. **API imports FROM core, never the reverse.** Dependency: `api/` → `core/`, `models/`, `optimization/`, `analysis/`. Core modules must NEVER import from `api/`.
2. **Pydantic models ARE API schemas.** PlanningResult, RefineryConfig, ScenarioComparison — these serialize directly to JSON via FastAPI. No separate request/response models for responses. Thin request models only where needed (OptimizeRequest, QuickOptimizeRequest).
3. **Thin routes, fat services.** `routes/` calls `services.py` which calls core functions. Zero business logic in route handlers. If you can't do it from a Jupyter notebook, you can't do it from the API.
4. **In-memory scenario store** (dict[str, PlanningResult]) for Stage 2A. No database. Server restart loses scenarios. PostgreSQL in Stage 2B.
5. **Stale state tracking.** `RefineryService.is_stale` flag: set True when any input changes after last optimize, reset to False on each optimize call. Returned in API responses so the UI can show "results outdated" warning.
6. **Run uvicorn with --workers 2** to prevent solver blocking on GET endpoints. Real job queue deferred to Stage 2B.

### Frontend Architecture Rules

1. **Flowsheet is the home screen.** Not a dashboard, not a table. An interactive process flow diagram built with React Flow. Every number is clickable.
2. **No page navigation for common tasks.** Optimize, compare scenarios, check specs — all on the same page via panels and drawers. Side panel for details, never a full page change.
3. **Color = information, applied consistently:**
   - Green: within spec, plenty of headroom (<80% utilization)
   - Yellow: within spec, tight margin (80-95% utilization)
   - Red: violated or at limit (>95% utilization)
4. **Stale state visualization.** When `isStale=true`, show amber banner "Inputs changed — click Optimize to refresh." Gray out flowsheet numbers.
5. **Shadow price tooltips on flowsheet nodes.** If a unit's constraint is binding, the node pulses amber. Hover shows business impact: "+$45K/month if regen limit +10°F."
6. **Confidence overlay.** Edges/nodes with DataSource.DEFAULT or low confidence render with dashed lines and "Low Confidence" badge.
7. **Stream diff mode.** When comparing scenarios, edges show Δ volume (green=more, red=less) instead of absolute values.

### AI Integration Rules

1. **Three-step narrative pipeline:** Extract deterministic facts → Apply domain reasoning rules → Synthesize with Claude API. Claude ONLY gets pre-validated facts, never raw data.
2. **Graceful degradation.** If ANTHROPIC_API_KEY not set, narrative falls back to deterministic version. What-if endpoint returns 503. Core optimization always works without AI.
3. **Confirmation before execution.** "Ask Eurekan" ALWAYS returns a proposed action for user confirmation before running the solver. Never auto-execute ambiguous queries.
4. **Near-optimal enumeration.** After finding optimum, check for alternatives within 2% tolerance using secondary objectives (minimize crude count, maximize robustness). Present 2-3 plans for planner to choose based on operational preferences.
