# SPRINTS.md — Implementation Spec for Claude Code

## How To Use This File

Each sprint section below is a self-contained set of tasks. Work through them in order. For each task:
1. Read the specification
2. Explore any referenced data files BEFORE writing code
3. Write the code
4. Write the tests
5. Run the tests — fix failures before moving on
6. Run `ruff check` and `ruff format` before committing

---

## PHASE 0: PROJECT SCAFFOLD

### Task 0.1: Create project files

Create `pyproject.toml`:

```toml
[project]
name = "eurekan-refinery"
version = "0.1.0"
description = "Refinery planning optimizer — NLP-based, auto-model-generation"
requires-python = ">=3.12"
dependencies = [
    "pyomo>=6.7",
    "cyipopt>=1.4",
    "highspy>=1.7",
    "pydantic>=2.7",
    "numpy>=1.26",
    "scipy>=1.13",
    "pandas>=2.2",
    "openpyxl>=3.1",
    "xlrd>=2.0",
    "orjson>=3.10",
]

[project.optional-dependencies]
dev = [
    "pytest>=8.2",
    "pytest-cov>=5.0",
    "mypy>=1.10",
    "ruff>=0.5",
]
notebooks = [
    "jupyterlab>=4.2",
    "matplotlib>=3.9",
    "plotly>=5.22",
]

[build-system]
requires = ["hatchling"]
build-backend = "hatchling.build"

[tool.hatch.build.targets.wheel]
packages = ["src/eurekan"]

[tool.pytest.ini_options]
testpaths = ["tests"]
addopts = "-v --tb=short"

[tool.mypy]
python_version = "3.12"
strict = true
plugins = ["pydantic.mypy"]

[tool.ruff]
line-length = 100
target-version = "py312"

[tool.ruff.lint]
select = ["E", "F", "I", "N", "UP", "B", "SIM", "TCH"]
```

Create the full directory structure with `__init__.py` files:
```
src/eurekan/__init__.py
src/eurekan/core/__init__.py
src/eurekan/models/__init__.py
src/eurekan/optimization/__init__.py
src/eurekan/parsers/__init__.py
src/eurekan/analysis/__init__.py
tests/__init__.py
tests/unit/__init__.py
tests/integration/__init__.py
tests/validation/__init__.py
notebooks/          (empty directory)
data/gulf_coast/    (for the Excel file)
```

Create `.gitignore`:
```
__pycache__/
*.pyc
.venv/
*.egg-info/
dist/
build/
.mypy_cache/
.pytest_cache/
.ruff_cache/
*.ipynb_checkpoints/
data/gulf_coast/*.xlsx
data/gulf_coast/*.xls
.env
```

Create `ruff.toml`:
```toml
line-length = 100
target-version = "py312"

[lint]
select = ["E", "F", "I", "N", "UP", "B", "SIM", "TCH"]

[format]
quote-style = "double"
```

### Task 0.2: Smoke test

Create `tests/test_smoke.py`:
```python
"""Verify all critical dependencies are importable."""

def test_pyomo_imports():
    import pyomo.environ as pyo
    assert hasattr(pyo, 'ConcreteModel')

def test_ipopt_available():
    import pyomo.environ as pyo
    solver = pyo.SolverFactory('ipopt')
    assert solver.available()

def test_highs_imports():
    import highspy
    assert hasattr(highspy, 'Highs')

def test_pydantic_imports():
    from pydantic import BaseModel
    class Test(BaseModel):
        x: float = 1.0
    assert Test().x == 1.0

def test_numpy_scipy():
    import numpy as np
    from scipy.optimize import least_squares
    assert np.array([1, 2, 3]).sum() == 6

def test_pandas_openpyxl():
    import pandas as pd
    import openpyxl
    assert hasattr(pd, 'read_excel')
```

Run: `uv run pytest tests/test_smoke.py -v`

All 6 tests must pass before proceeding.

---

## SPRINT 1: DATA LAYER + CDU MODEL

### Task 1.1: Enums

Create `src/eurekan/core/enums.py`:

```python
from enum import Enum

class OperatingMode(str, Enum):
    SIMULATE = "simulate"
    OPTIMIZE = "optimize"
    HYBRID = "hybrid"

class UnitType(str, Enum):
    CDU = "cdu"
    FCC = "fcc"
    REFORMER = "reformer"
    HYDROTREATER = "hydrotreater"
    HYDROCRACKER = "hydrocracker"
    COKER = "coker"
    ALKYLATION = "alkylation"
    ISOMERIZATION = "isomerization"
    BLENDER = "blender"

class TankType(str, Enum):
    CRUDE = "crude"
    PRODUCT = "product"
    INTERMEDIATE = "intermediate"

class BlendMethod(str, Enum):
    LINEAR_VOLUME = "linear_volume"
    LINEAR_WEIGHT = "linear_weight"
    POWER_LAW = "power_law"
    INDEX = "index"

class StreamDisposition(str, Enum):
    BLEND = "blend"
    SELL = "sell"
    FUEL_OIL = "fuel_oil"
    INTERNAL = "internal"
    FCC_FEED = "fcc_feed"

class DataSource(str, Enum):
    """Tracks WHERE every data value came from. Shown in UI."""
    DEFAULT = "default"          # Built-in library or published value
    TEMPLATE = "template"        # From refinery template selection
    IMPORTED = "imported"        # Parsed from uploaded file (Excel, PDF, etc.)
    USER_ENTERED = "user"        # Manually typed by user
    AI_EXTRACTED = "ai"          # Extracted by AI from a document
    CALIBRATED = "calibrated"    # Auto-calibrated from plant operating data
    CALCULATED = "calculated"    # Computed from other data
    MARKET_DATA = "market"       # From market data API (prices)
```

### Task 1.2: Core data model — crude.py

Create `src/eurekan/core/crude.py`:

**DESIGN PRINCIPLE:** No PIMS tags in the core. All names are human-readable, engineer-native. Cuts are defined by temperature ranges, not arbitrary tags. PIMS translation lives ONLY in the parser.

Define these Pydantic models:

**CutProperties**: All Optional[float] fields — api, sulfur, ron, mon, rvp, spg, olefins, aromatics, benzene, nitrogen, ccr, nickel, vanadium, cetane, flash_point, pour_point, cloud_point. Include a `metals` computed property that returns `(nickel or 0) + (vanadium or 0)`.

**DistillationCut**: A temperature-defined fraction of crude oil.
- name (str): human-readable, e.g. "light_naphtha", "kerosene", "vgo"
- display_name (str): e.g. "Light Naphtha (C5-180°F)"
- tbp_start_f (Optional[float]): starting temperature in °F (None for lightest cut)
- tbp_end_f (Optional[float]): ending temperature in °F (None for heaviest cut)
- vol_yield (float): volume fraction 0-1
- properties (CutProperties)
- source (DataSource): where this data came from (DEFAULT, IMPORTED, USER_ENTERED, etc.)
- confidence (float): 0-1, how much we trust this value (1.0 = measured, 0.5 = default/estimated)

**CutPointTemplate**: Defines how to slice the TBP curve into cuts.
- name (str): e.g. "us_gulf_coast_630ep"
- display_name (str): e.g. "US Gulf Coast (630°F EP Diesel)"
- cuts (list[CutPointDef]) where CutPointDef has: name, display_name, tbp_start_f, tbp_end_f

Ship three default templates:
- "us_gulf_coast_630ep": LN C5-180, HN 180-350, Kero 350-500, Diesel 500-630, VGO 630-1050, Resid 1050+
- "european_580ep": LN C5-180, HN 180-330, Kero 330-480, Diesel 480-580, VGO 580-1020, Resid 1020+
- "max_kerosene": LN C5-160, HN 160-300, Kero 300-520, Diesel 520-650, VGO 650-1050, Resid 1050+

**CrudeAssay**: crude_id (str), name (str), origin (Optional[str]), api (float), sulfur (float), tan (Optional[float]), price (Optional[float]), max_rate (Optional[float]), min_rate (float, default 0), cuts (list[DistillationCut]). Add a `total_yield` property that sums vol_yield across cuts. Add `get_cut(name)` method. Add a model_validator that warns if total_yield is outside 0.95-1.05.

**CrudeLibrary**: A class wrapping dict[str, CrudeAssay] with `get(crude_id)`, `list_crudes()`, `__len__()`, `__iter__()` methods.

**Standard cut names used throughout Eurekan:**
```python
STANDARD_CUT_NAMES = [
    "light_gases",     # C1-C2
    "lpg",             # C3-C4
    "light_naphtha",   # C5-180°F
    "heavy_naphtha",   # 180-350°F
    "kerosene",        # 350-500°F
    "diesel",          # 500-650°F
    "light_vgo",       # 650-800°F (optional split)
    "heavy_vgo",       # 800-1050°F (optional split)
    "vgo",             # 650-1050°F (combined — Stage 1)
    "vacuum_residue",  # 1050°F+
]
```

These names are used EVERYWHERE in the system — in models, optimization, results, API, UI. Never PIMS tags.

### Task 1.3: Core data model — product.py, stream.py, tank.py

**product.py**:
- `ProductSpec`: spec_name (str), min_value (Optional[float]), max_value (Optional[float])
- `BlendingRule`: property_name (str), method (BlendMethod), exponent (Optional[float] for power law)
- `Product`: product_id (str), name (str), price (float), min_demand (float, default 0), max_demand (Optional[float]), specs (list[ProductSpec]), blending_rules (list[BlendingRule]), allowed_components (list[str]). Add `get_spec(name)` method.

**stream.py**:
- `Stream`: stream_id (str), source_unit (str), stream_type (str), possible_dispositions (list[StreamDisposition]), properties (Optional[CutProperties])

**tank.py**:
- `Tank`: tank_id (str), tank_type (TankType), capacity (float, must be > 0), minimum (float, default 0), current_level (float, default 0), connected_streams (list[str])

### Task 1.4: Core data model — config.py, period.py, results.py

**config.py**:
- `UnitConfig`: unit_id (str), unit_type (UnitType), capacity (float), min_throughput (float, default 0), equipment_limits (dict[str, float]), source (DataSource, default DEFAULT)
- `RefineryConfig`: name (str), units (dict[str, UnitConfig]), crude_library (CrudeLibrary), products (dict[str, Product]), streams (dict[str, Stream]), tanks (dict[str, Tank]), cut_point_template (CutPointTemplate). Add a `completeness()` method that returns `ConfigCompleteness` — overall_pct (float), missing (list[str]), using_defaults (list[str]), ready_to_optimize (bool), margin_uncertainty_pct (float — estimated ± percentage on margin given current data quality, e.g. ±15% at 60% completeness, ±3% at 95%), highest_value_missing (Optional[str] — the single missing data item that would most reduce uncertainty, e.g. "Add VGO CCR for Mars crude to reduce margin uncertainty from ±15% to ±8%"). The model is ready to optimize even at 50% completeness — defaults fill gaps. The uncertainty estimate turns completeness from a progress bar into a business metric.
- `ConfigCompleteness`: overall_pct (float), missing (list[str]), using_defaults (list[str]), ready_to_optimize (bool), margin_uncertainty_pct (float), highest_value_missing (Optional[str])

**period.py**:
- `PeriodData`: period_id (int), duration_hours (float), crude_prices (dict[str, float]), product_prices (dict[str, float]), crude_availability (dict[str, tuple[float, float]] — min/max), unit_status (dict[str, str]), demand_min (dict[str, float]), demand_max (dict[str, float]), initial_inventory (dict[str, float])
- `PlanDefinition`: periods (list[PeriodData]), mode (OperatingMode), fixed_variables (dict[str, float] — for hybrid mode), scenario_id (str — auto-generated UUID), scenario_name (str — user-friendly label, e.g. "Base Case", "High Gas Price"), parent_scenario_id (Optional[str] — links to the scenario this was branched from), description (Optional[str] — what changed from parent)

**results.py** — Organized into four groups: flow graph, diagnostics, narrative, and plan results.

*1. Material Flow Graph (stream tracing — built automatically from optimization results):*
- `FlowNodeType` enum: PURCHASE, UNIT, BLEND_HEADER, SALE_POINT, TANK
- `FlowNode`: node_id (str), node_type (FlowNodeType), display_name (str), throughput (float)
- `FlowEdge`: edge_id (str), source_node (str), dest_node (str), stream_name (str), display_name (str), volume (float), properties (CutProperties), economic_value (float), crude_contributions (dict[str, float] — what fraction of each crude is in this stream)
- `MaterialFlowGraph`: nodes (list[FlowNode]), edges (list[FlowEdge]). Add methods: `trace_crude(crude_id) -> list[FlowEdge]`, `trace_product(product_id) -> list[FlowEdge]`, `streams_by_property(prop, min_val) -> list[FlowEdge]`
- `CrudeDisposition`: crude_id (str), total_volume (float), product_breakdown (dict[str, float]), value_created (float), crude_cost (float), net_margin (float)

*2. Constraint Diagnostics (from IPOPT shadow prices):*
- `EquipmentStatus`: name (str), display_name (str), current_value (float), limit (float), utilization_pct (float), is_binding (bool)
- `ConstraintDiagnostic`: constraint_name (str), display_name (str), violation (float), shadow_price (Optional[float] — raw, in native units $/ppm or $/°F), bottleneck_score (float 0-100 — normalized for UI heat map, higher = more limiting to profitability), binding (bool), source_stream (Optional[str] — which stream/unit is causing this, e.g. "Mars VGO sulfur"), relaxation_suggestion (Optional[str] — must reference the specific stream/unit causing the issue), relaxation_cost (Optional[float])
- `InfeasibilityReport`: is_feasible (bool), violated_constraints (list[ConstraintDiagnostic] — sorted cheapest fix first), suggestions (list[str]), cheapest_fix (Optional[str])

*3. AI Narrative (generated after every solve — the knowledge layer):*
- `DecisionExplanation`: decision (str), reasoning (str — economic logic chain), alternatives_considered (str), confidence (float)
- `RiskFlag`: severity (str — critical/warning/info), message (str), recommendation (str)
- `SolutionNarrative`: executive_summary (str), decision_explanations (list[DecisionExplanation]), risk_flags (list[RiskFlag]), economics_narrative (str), data_quality_warnings (list[str] — generated from DataSource/confidence: if calibration confidence is low, warn "FCC yields based on limited data — conversion results may be ±4% accurate"; if key values use defaults, warn "VGO CCR using default value — margin estimate uncertainty ±$200K/month"). Generated via: (1) deterministic domain rules extract facts from results, (2) Claude API synthesizes facts into readable prose. Narrative is Optional — None if Claude API not configured (Stage 1 CLI mode).

*4. Unit and Plan Results:*
- `FCCResult`: conversion (float), yields (dict[str, float]), properties (dict[str, CutProperties]), equipment (list[EquipmentStatus])
- `BlendResult`: product_id (str), total_volume (float), recipe (dict[str, float]), quality (dict[str, dict] — value, limit, margin, feasible per spec)
- `DispositionResult`: stream_id (str), to_blend (float), to_sell (float), to_fuel_oil (float)
- `PeriodResult`: period_id (int), crude_slate (dict[str, float]), cdu_cuts (dict[str, float]), fcc_result (Optional[FCCResult]), blend_results (list[BlendResult]), dispositions (list[DispositionResult]), product_volumes (dict[str, float]), revenue (float), crude_cost (float), operating_cost (float), margin (float)
- `PlanningResult`: scenario_id (str), scenario_name (str), parent_scenario_id (Optional[str]), created_at (datetime), periods (list[PeriodResult]), total_margin (float), solve_time_seconds (float), solver_status (str), inventory_trajectory (dict[str, list[float]]), material_flow (MaterialFlowGraph), crude_valuations (list[CrudeDisposition]), constraint_diagnostics (list[ConstraintDiagnostic]), infeasibility_report (Optional[InfeasibilityReport]), narrative (Optional[SolutionNarrative])
- `OracleResult`: actual_margin (float), optimal_margin (float), gap (float), gap_pct (float), gap_sources (dict[str, float])
- `ScenarioComparison`: base_scenario_id (str), comparison_scenario_id (str), margin_delta (float), crude_slate_changes (dict[str, float]), conversion_delta (float), product_volume_deltas (dict[str, float]), constraint_changes (list[dict] — which bottlenecks moved, appeared, or disappeared between scenarios, e.g. {"constraint": "regen_temp", "base_utilization": 98%, "comparison_utilization": 85%, "change": "relaxed"}), key_insight (str)

### Task 1.5: Tests for core data model

Create `tests/unit/test_core.py`:

Test every model can be constructed with sample data. Test JSON round-trip (model → json → model, values preserved). Test validation (negative capacity raises error). Test CrudeLibrary CRUD. Test CutProperties.metals computed property. Test Product.get_spec returns correct spec. Test DataSource enum on DistillationCut (default, imported, etc.). Test RefineryConfig.completeness() returns sensible values (partially-filled config shows <100%, lists missing items, ready_to_optimize=True if critical fields present). Test that CutPointTemplate defaults produce valid temperature ranges (no gaps, no overlaps).

### Task 1.6: Gulf Coast parser — sheet exploration + schema validation

Create `src/eurekan/parsers/gulf_coast.py` with class `GulfCoastParser`.

**CRITICAL: Before writing any parsing code, explore each sheet.** Write a method `explore_sheet(sheet_name, n_rows=15)` that prints the first N rows with row/column indices. Call this for Assays, Buy, Sell, Blnspec, Blnmix, Blnnaph, Caps, ProcLim. Study the output to understand the exact layout before writing parsers.

The Gulf Coast file uses PIMS conventions:
- Row tags in column A identify what each row contains
- Crude tags in the header row identify columns
- Values are volume fractions (0-1), not percentages

**Parser robustness rules:**
1. Parse by ROW TAGS (column A), never by row numbers. Search for tags like DBALLN1, VBALKE1.
2. Parse by COLUMN HEADERS, not column indices. Find the header row with crude tags, then map tags to columns.
3. Add a schema validation step: before extracting values, verify that all expected row tags exist. If a tag is missing, raise a clear `SchemaValidationError("Expected row tag 'DBALLN1' not found in Assays sheet")`.
4. Tolerate extra rows/columns — ignore rows the parser doesn't recognize.
5. Validate value ranges after extraction: yields should be 0-1, API should be 5-80, sulfur should be 0-10%.

Create `src/eurekan/parsers/schema.py`:
```python
class SheetSchema(BaseModel):
    """Expected structure of a Gulf Coast Excel sheet."""
    sheet_name: str
    required_row_tags: list[str]
    required_column_tags: list[str]  # empty if N/A
    
class SchemaValidationError(Exception):
    """Raised when Excel data doesn't match expected schema."""
    pass

def validate_sheet(ws, schema: SheetSchema) -> list[str]:
    """Check sheet against schema. Return list of issues (empty = OK)."""
    ...
```

Define schemas for all 8 sheets we parse (Assays, Buy, Sell, Blnspec, Blnmix, Blnnaph, Caps, ProcLim).

### Task 1.7: Gulf Coast parser — Assays sheet

Parse the Assays sheet (218 rows × 50 cols). This is the CD1 (sweet crude, 630EP diesel) mode.

**The parser is a TRANSLATION LAYER. PIMS tags go in. Eurekan models come out. No PIMS tag survives past the parser.**

Steps:
1. Find the header row with crude tags (ARL, AMM, BRT, BSL, etc.)
2. Find yield rows by PIMS row tags (search column A): VBALNC3, VBALIC4, VBALNC4, DBALLN1, DBALMN1, VBALKE1, etc.
3. **TRANSLATE** PIMS tags to Eurekan cut names using a mapping dict:
   ```python
   PIMS_YIELD_MAP = {
       'VBALNC3': ('lpg', 'propane'),
       'VBALIC4': ('lpg', 'isobutane'),
       'VBALNC4': ('lpg', 'n_butane'),
       'DBALLN1': ('light_naphtha', None),
       'DBALMN1': ('heavy_naphtha', None),
       'VBALKE1': ('kerosene', None),
       # ... etc
   }
   ```
4. Aggregate sub-components into cuts (C3+iC4+nC4 → lpg)
5. Extract cut properties from deeper rows (API, sulfur, RON where available)
6. Build DistillationCut objects with temperature ranges from the US Gulf Coast template
7. Build CrudeAssay for each crude column using CLEAN Eurekan names
8. Return CrudeLibrary

**The PIMS_YIELD_MAP dict is the ONLY place PIMS tags exist.** If someone brings a different Excel format, they write a different mapping. The CrudeAssay output is identical either way.

**Validate:** ARL light_naphtha yield ≈ 0.0952. ARL API ≈ 32.84.

### Task 1.8: Gulf Coast parser — Buy and Sell sheets

Parse Buy sheet:
- Crude tags, names, prices (COST column), min/max availability, API, sulfur
- Update CrudeAssay objects with price, max_rate, api, sulfur from Buy sheet
- Crude IDs stay as-is (ARL, MRS, WTI) — these are industry-standard crude identifiers, NOT PIMS artifacts

Parse Sell sheet:
- Product tags, names, prices, min/max demand
- **TRANSLATE** PIMS product tags to Eurekan names:
  ```python
  PIMS_PRODUCT_MAP = {
      'CRG': 'regular_gasoline',
      'CPG': 'premium_gasoline',
      'ULS': 'ulsd',
      'JET': 'jet_fuel',
      'N2O': 'no2_oil',
      'LSF': 'low_sulfur_fuel_oil',
      'HSF': 'high_sulfur_fuel_oil',
      'LPG': 'lpg',
      'CKE': 'coke',
  }
  ```
- Return dict of Product objects with Eurekan names (not PIMS tags)

### Task 1.9: Gulf Coast parser — Blnspec, Blnmix, Blnnaph

Parse Blnspec:
- Find regular_gasoline (PIMS tag: CRG) column
- Extract spec rows by PIMS tags and **TRANSLATE** to Eurekan property names:
  ```python
  PIMS_SPEC_MAP = {
      'NDON': ('road_octane', 'min'),
      'XRVI': ('rvp_index', 'max'),
      'XSUL': ('sulfur', 'max'),
      'XBNZ': ('benzene', 'max'),
      'XARO': ('aromatics', 'max'),
      'XOLF': ('olefins', 'max'),
  }
  ```
- Build ProductSpec list using Eurekan property names (not PIMS tags)

Parse Blnmix:
- Component rows × product columns
- Value of 1.0 means component is allowed in product
- **TRANSLATE** component tags to Eurekan stream names:
  ```python
  PIMS_COMPONENT_MAP = {
      'LCN': 'fcc_light_naphtha',
      'HCN': 'fcc_heavy_naphtha',
      'LN1': 'cdu_light_naphtha',
      'NC4': 'n_butane',
      'RFT': 'reformate',
  }
  ```
- Build Product.allowed_components with Eurekan names

Parse Blnnaph:
- Component properties for blending
- RON, MON, RVP, sulfur, SPG, olefins, aromatics, benzene per component
- Extract n_butane (PIMS: NC4) properties: RON=93.8, RVP index
- Build CutProperties for each blend component using Eurekan property names

### Task 1.10: Gulf Coast parser — Caps and ProcLim

Parse Caps:
- Find CDU and FCC capacity rows
- Extract capacity values (bbl/d)
- Build UnitConfig objects

Parse ProcLim:
- Find FCC operating limits (conversion range, RTT range)
- Build equipment_limits dict for FCC UnitConfig

### Task 1.11: Gulf Coast parser — assemble RefineryConfig

Create `GulfCoastParser.parse() -> RefineryConfig` that:
1. Calls all individual sheet parsers
2. Cross-references data (Buy prices into CrudeAssay, Blnspec into Product, etc.)
3. Creates UnitConfig for CDU1 and FCC1
4. Creates Stream objects for all CDU cuts and FCC products
5. Creates Product objects with specs, blending rules, and allowed components
6. Returns complete RefineryConfig

### Task 1.12: Parser tests

Create `tests/unit/test_parser.py`:
- `test_parser_loads`: GulfCoastParser doesn't error on Gulf_Coast.xlsx
- `test_schema_validation`: All 8 sheet schemas validate successfully (required tags found)
- `test_schema_validation_bad_file`: Missing tag raises SchemaValidationError with clear message
- `test_crude_count`: at least 40 crudes parsed
- `test_arl_yields`: ARL light_naphtha yield ≈ 0.095 (±0.005) — NOTE: use Eurekan name, not DBALLN1
- `test_arl_api`: ARL bulk API ≈ 32.84 (±1.0)
- `test_yields_sum`: every crude's yields sum to 0.95-1.05
- `test_cut_names_are_eurekan`: all cut names must be in STANDARD_CUT_NAMES — no PIMS tags in output
- `test_product_names_are_eurekan`: all product IDs are Eurekan names (regular_gasoline, not CRG)
- `test_buy_prices`: ARL price ≈ $74.80 (±$2)
- `test_sell_prices`: regular_gasoline price ≈ $82.81 (±$2)
- `test_gasoline_specs`: regular_gasoline road_octane min = 87.0
- `test_blend_components`: fcc_light_naphtha and fcc_heavy_naphtha are allowed in regular_gasoline
- `test_n_butane_properties`: n_butane RON ≈ 93.8
- `test_unit_capacities`: CDU = 80000, FCC = 50000
- `test_value_ranges`: all yields 0-1, all APIs 5-80, all sulfurs 0-10%
- `test_no_pims_tags_in_output`: scan all string fields in RefineryConfig — none should match known PIMS tag patterns (all caps, 3-8 chars like DBALLN1, VBALKE1, XRVI, NDON)

### Task 1.13: CDU Model

Create `src/eurekan/models/base.py`:
```python
from abc import ABC, abstractmethod

class BaseUnitModel(ABC):
    """Abstract base for all unit models."""
    
    @abstractmethod
    def calculate(self, **kwargs):
        """Run the unit model calculation."""
        ...
```

Create `src/eurekan/models/cdu.py`:

```python
class CDUModel(BaseUnitModel):
    """
    CDU yield model. Exact from assay data.
    
    Yields are LINEAR in crude volumes:
      cut_volume[k] = Σ_c crude_rate[c] × yield[c][k]
    
    Cut properties are WEIGHTED AVERAGES (nonlinear — ratios):
      cut_prop[k] = Σ_c (crude_rate[c] × yield[c][k] × prop[c][k]) / cut_volume[k]
    """
    
    def __init__(self, unit_config: UnitConfig):
        self.capacity = unit_config.capacity
        self.min_throughput = unit_config.min_throughput
    
    def calculate(
        self, 
        crude_rates: dict[str, float], 
        crude_library: CrudeLibrary
    ) -> CDUResult:
        """
        Args:
            crude_rates: {crude_id: rate_bbl_per_day}
            crude_library: CrudeLibrary with assay data
            
        Returns:
            CDUResult with cut volumes, properties, and VGO feed quality
        """
        # 1. Compute cut volumes (linear)
        # 2. Compute cut properties (weighted average — handle division by zero)
        # 3. Compute blended VGO properties for FCC feed
        # 4. Return CDUResult
```

Create `CDUResult` in results.py if not already there:
- total_crude (float)
- cut_volumes (dict[str, float])
- cut_properties (dict[str, CutProperties])
- vgo_feed_properties (CutProperties) — the blended VGO going to FCC

### Task 1.14: CDU Model tests

Create `tests/unit/test_cdu.py`:
- `test_single_crude`: 80K bbl/d ARL, verify LN volume ≈ 80000 × 0.095
- `test_mixed_crudes`: 45K ARL + 25K MRS + 10K WTI, compute expected values manually, verify within 0.1%
- `test_yields_sum_to_total`: sum of all cut volumes ≈ total crude (±2%)
- `test_vgo_properties_blended`: VGO API should be between lightest and heaviest crude VGO API
- `test_zero_crude`: empty dict → all zeros
- `test_single_crude_properties`: properties should match assay exactly (no blending)
- `test_capacity_info`: CDUModel stores capacity correctly

### Task 1.15: Sprint 1 integration test

Create `tests/integration/test_sprint1.py`:

```python
def test_full_pipeline():
    """Parse Gulf Coast → RefineryConfig → CDU model → results."""
    parser = GulfCoastParser("data/gulf_coast/Gulf_Coast.xlsx")
    config = parser.parse()
    
    # Verify config is complete
    assert len(config.crude_library) >= 40
    assert 'CDU1' in config.units
    assert 'FCC1' in config.units
    assert config.units['CDU1'].capacity == 80000
    
    # Run CDU model
    cdu = CDUModel(config.units['CDU1'])
    result = cdu.calculate(
        {'ARL': 45000, 'MRS': 25000, 'WTI': 10000},
        config.crude_library
    )
    
    # Verify results are physical
    assert result.total_crude == 80000
    assert all(v >= 0 for v in result.cut_volumes.values())
    assert 0.95 < sum(result.cut_volumes.values()) / 80000 < 1.05
    
    # VGO properties make sense
    vgo = result.vgo_feed_properties
    assert vgo.api is not None
    assert 15 < vgo.api < 30
    assert vgo.sulfur is not None
    assert 0.5 < vgo.sulfur < 5.0
```

Run full suite: `uv run pytest tests/ -v --cov=eurekan --cov-report=term-missing`

---

## SPRINT 2: FCC MODEL + EQUIPMENT BOUNDS

### Task 2.1: FCC yield correlations

Create `src/eurekan/models/fcc.py`:

```python
@dataclass
class FCCCalibration:
    """11 calibration parameters. All default to neutral (1.0 or 0.0)."""
    alpha_gasoline: float = 1.0
    alpha_coke: float = 1.0
    alpha_lcn_split: float = 1.0
    alpha_c3c4: float = 1.0
    alpha_lco: float = 1.0
    delta_lcn_ron: float = 0.0
    delta_hcn_ron: float = 0.0
    delta_lcn_sulfur: float = 1.0   # multiplier, not offset
    delta_hcn_sulfur: float = 1.0   # multiplier, not offset
    delta_lco_cetane: float = 0.0
    delta_regen: float = 0.0


class FCCModel(BaseUnitModel):
    """
    FCC model with conversion as continuous decision variable.
    Uses published correlations with calibration parameters.
    Equipment bounds computed from feed quality.
    """
    
    def __init__(self, unit_config: UnitConfig, calibration: FCCCalibration | None = None):
        self.capacity = unit_config.capacity
        self.equipment_limits = unit_config.equipment_limits
        self.calibration = calibration or FCCCalibration()
    
    def calculate(self, feed_properties: CutProperties, conversion: float) -> FCCResult:
        """Calculate all FCC yields, properties, and equipment status."""
        ...
    
    def yields(self, conversion: float, api: float, ccr: float, metals: float) -> dict[str, float]:
        """Yield correlations. Returns vol fractions of feed."""
        ...
    
    def product_properties(self, conversion: float, api: float, sulfur: float) -> dict[str, CutProperties]:
        """Product quality correlations."""
        ...
    
    def equipment_status(self, conversion: float, ccr: float, metals: float, feed_rate: float) -> list[EquipmentStatus]:
        """Compute regen temp, gas compressor load, air blower load."""
        ...
    
    def max_conversion(self, feed_properties: CutProperties) -> float:
        """Physics-based max conversion for this feed quality."""
        ...
```

Implement all yield correlations from CLAUDE.md. Implement all product property correlations. Implement equipment constraints (regen temp, gas compressor, air blower).

### Task 2.2: FCC validation against SCCU

Create `tests/validation/test_fcc_accuracy.py`:
- At 80% conversion on ARL VGO (API≈21.8, CCR≈0.5): gasoline should be 45-54% (SCCU says 49.4%)
- LCO should be 14-18% (SCCU says 16.2%)
- Yields must sum to ~100% (±2%)
- If yields are off by more than ±10%, adjust correlation coefficients and document why

### Task 2.3: Conversion sweep test

Create `tests/validation/test_conversion_response.py`:
- Sweep conversion 72% to 88% in 2% steps on ARL VGO
- Assert: gasoline yield INCREASES then PEAKS (overcracking)
- Assert: LCO yield monotonically DECREASES
- Assert: coke yield monotonically INCREASES
- Assert: regen temp INCREASES with conversion
- Assert: max_conversion() returns a value where regen hits limit

### Task 2.4: Crude sensitivity test

Create `tests/validation/test_crude_sensitivity.py`:
- Light crude VGO (highest API in library): max conversion should be highest
- Heavy crude VGO (lowest API, highest CCR): max conversion should be lowest
- Verify Mars-like crude (CCR ~2.8) is limited to ~80-82% by regen

### Task 2.5: Calibration engine

Create `src/eurekan/models/calibration.py`:

```python
class CalibrationEngine:
    """
    Auto-calibrate 11 FCC parameters from plant operating data.
    Uses scipy.optimize.least_squares WITH Tikhonov regularization.
    
    Regularization prevents overfitting when plant data is sparse.
    The prior is: published correlations are probably close (α≈1.0, Δ≈0.0).
    
    Objective: minimize Σ(predicted - actual)² + λ × Σ(param - default)²
    
    λ (regularization strength) is auto-tuned via leave-one-out 
    cross-validation when ≥6 data points are available.
    With <6 points, use conservative λ=1.0 (strong regularization).
    """
    
    # Parameter bounds (physically reasonable ranges)
    PARAM_BOUNDS = {
        'alpha_gasoline': (0.7, 1.3),
        'alpha_coke': (0.7, 1.3),
        'alpha_lcn_split': (0.7, 1.3),
        'alpha_c3c4': (0.7, 1.3),
        'alpha_lco': (0.7, 1.3),
        'delta_lcn_ron': (-3.0, 3.0),
        'delta_hcn_ron': (-3.0, 3.0),
        'delta_lcn_sulfur': (0.5, 2.0),
        'delta_hcn_sulfur': (0.5, 2.0),
        'delta_lco_cetane': (-5.0, 5.0),
        'delta_regen': (-30.0, 30.0),
    }
    
    def calibrate(
        self, 
        fcc_model: FCCModel,
        observed_data: list[CalibrationDataPoint],
        lambda_reg: float | None = None,  # None = auto-tune
    ) -> CalibrationResult:
        """
        Fit calibration parameters to minimize regularized error.
        
        Returns CalibrationResult with:
          - fitted FCCCalibration
          - per-parameter confidence (how much data moved it from default)
          - residual errors per data point
          - lambda used
        """
        ...
    
    def auto_tune_lambda(
        self, fcc_model, observed_data
    ) -> float:
        """Leave-one-out cross-validation to find optimal λ."""
        ...
```

Where `CalibrationDataPoint` contains: feed_properties, conversion, actual_yields (dict), actual_properties (dict).

Where `CalibrationResult` contains: calibration (FCCCalibration), lambda_used (float), residuals (dict), confidence (dict — per parameter, how far from default).

Test: Use SCCU BASE values as "plant data". After calibration, model should match within ±2%. Test that with only 3 data points and high λ, parameters stay close to defaults. Test that parameter bounds are respected.

---

## SPRINT 3: NLP OPTIMIZER + BLENDING

### Task 3.1: Blending model

Create `src/eurekan/models/blending.py`:

Implement ASTM standard blending methods:
- RON: Blending Index method (NONLINEAR — mandatory):
  - BI(RON) = -36.1572 + 0.83076×RON + 0.0037397×RON²
  - Blend BI = Σ(vol_i × BI_i) / Σ(vol_i)
  - Blend RON = solve inverse of BI quadratic
  - DO NOT use linear-by-volume — it gives systematically wrong answers
- RVP: power law (RVP^1.25 blending)
- Sulfur: linear by weight
- Benzene, aromatics, olefins: linear by volume

```python
class BlendingModel:
    def calculate_blend_property(
        self, 
        component_volumes: dict[str, float],
        component_properties: dict[str, CutProperties],
        property_name: str,
        method: BlendMethod
    ) -> float:
        """Calculate blended property value."""
        ...
    
    def check_specs(
        self,
        blend_properties: dict[str, float],
        product: Product
    ) -> list[SpecResult]:
        """Check all specs, return value/limit/margin/feasible for each."""
        ...
```

### Task 3.2: Pyomo model builder

Create `src/eurekan/optimization/builder.py`:

This is the core. `PyomoModelBuilder` takes a `RefineryConfig` and `PlanDefinition` and generates a complete Pyomo ConcreteModel.

For each period p:
1. Add crude rate variables x[c,p] bounded by [0, max_rate]
2. Add FCC conversion variable conv[p] bounded by [68, 90]
3. Add VGO-to-FCC variable vgo_fcc[p]
4. Add blend component variables b[j,p]
5. Add disposition variables (ln_sell, hn_sell, hcn_fo, vgo_fo, kero_jet, kero_dies, lco_dies, lco_fo)
6. Add purchased reformate variable b_rft[p]
7. Add CDU capacity constraint
8. Add FCC capacity constraint
9. Add FCC yield equations (nonlinear)
10. Add FCC equipment constraints (nonlinear)
11. Add mass balance constraints (disposition)
12. Add blending constraints (RON, RVP, sulfur — nonlinear)
13. Add demand constraints
14. Add inventory linking if N > 1
15. Set objective function (maximize margin)

Variable modes: In SIMULATE mode, fix all decision variables to values from `PlanDefinition.fixed_variables`. In OPTIMIZE mode, all free. In HYBRID mode, fix those specified.

### Task 3.3: Solver integration

Create `src/eurekan/optimization/solver.py`:

```python
class EurekanSolver:
    """
    Three-tier solver with automatic initialization.
    
    Tier 1: Heuristic warm-start (always tried first)
      - Equal crude split, 80% conversion, proportional blend
      - Fast, usually works for well-conditioned problems
      
    Tier 2: LP relaxation warm-start (if Tier 1 fails)
      - Discretize FCC into 5 conversion modes
      - Solve LP with HiGHS (milliseconds)
      - Use LP solution as IPOPT starting point
      
    Tier 3: Multi-start (if Tier 2 fails)
      - 5 random starting points
      - Return best feasible solution
    """
    
    def generate_heuristic_start(self, config: RefineryConfig, plan: PlanDefinition) -> dict:
        """Tier 1: Physically feasible starting point."""
        # Equal crude split across available crudes up to CDU capacity
        # Conversion = 80% (safe mid-range)
        # Blend fractions proportional to component availability
        # All dispositions to highest-value destination
        ...
    
    def generate_lp_start(self, config: RefineryConfig, plan: PlanDefinition) -> dict:
        """Tier 2: Solve discretized LP, use as NLP starting point."""
        # Discretize FCC: 5 modes at 72%, 76%, 80%, 84%, 88%
        # Pre-compute yields for each mode using FCCModel
        # Build LP in Pyomo with mode selection variables
        # Solve with HiGHS
        # Extract continuous variable values as starting point
        ...
    
    def solve(self, model: pyo.ConcreteModel, multi_start: int = 1) -> SolveResult:
        """Solve with IPOPT using Tier 1 start. Optional multi-start."""
        ...
    
    def solve_with_fallback(self, model: pyo.ConcreteModel) -> SolveResult:
        """Full Tier 1 → 2 → 3 cascade. Always returns a solution or clear error."""
        ...
```

Test: Verify that Tier 1 warm-start produces a feasible (not optimal) solution. Verify that IPOPT converges from the warm-start in fewer iterations than a cold start. Verify Tier 2 LP fallback produces valid starting point. Verify multi-start returns best solution across all starts.

### Task 3.4: Simulation mode

Create `src/eurekan/optimization/modes.py`:

```python
def run_simulation(config: RefineryConfig, plan: PlanDefinition) -> SimulationResult:
    """Fix all variables, evaluate equations, report violations."""
    ...

def run_optimization(config: RefineryConfig, plan: PlanDefinition) -> PlanningResult:
    """Free all variables, solve NLP, return optimal plan."""
    ...

def run_hybrid(config: RefineryConfig, plan: PlanDefinition) -> PlanningResult:
    """Fix specified variables, optimize the rest."""
    ...
```

### Task 3.5: Integration tests for Sprint 3

- `test_simulation_mode`: Fix known inputs, verify calculated outputs match manual computation
- `test_optimization_converges`: Run optimizer with all 45 crudes, verify IPOPT converges
- `test_optimization_sensible`: Optimal crude selection makes economic sense, conversion in 78-86%, gasoline on spec
- `test_hybrid_mode`: Fix crudes, optimize conversion + blend, verify different result from full optimization
- `test_specs_met`: All blend specs met in every optimized solution
- `test_scenario_ids`: Every PlanningResult has unique scenario_id. Hybrid branched from optimization has parent_scenario_id set.

### Task 3.6: Constraint diagnostics and infeasibility negotiator

Create `src/eurekan/optimization/diagnostics.py`:

This is a KILLER FEATURE that differentiates Eurekan from every LP/NLP tool on the market. When the solver struggles or fails, the system EXPLAINS why in engineer language and SUGGESTS fixes with economic impact.

```python
class ConstraintDiagnostician:
    """
    Extracts and interprets IPOPT solver output to provide
    engineer-friendly diagnostics.
    
    After EVERY solve (feasible or not):
    - Extract Lagrange multipliers (shadow prices) for all constraints
    - Identify binding constraints (shadow price ≠ 0)
    - Rank constraints by economic impact
    - Generate plain-English explanations
    
    When INFEASIBLE:
    - Identify violated constraints
    - For each violated constraint, compute the minimum relaxation 
      needed for feasibility
    - Estimate the economic impact of each relaxation
    - Rank by "cheapest fix first"
    - Generate suggestions in engineer language
    """
    
    def diagnose_feasible(self, model: pyo.ConcreteModel) -> list[ConstraintDiagnostic]:
        """Extract shadow prices from a feasible solution.
        
        Returns diagnostics sorted by |shadow_price| descending.
        The constraint with the highest shadow price is the one 
        that most limits profitability — the "bottleneck."
        
        Example output:
          ConstraintDiagnostic(
              constraint_name="regen_temp_limit",
              display_name="FCC Regenerator Temperature",
              violation=0.0,
              shadow_price=45000,  # $/month per °F of relaxation
              binding=True,
              relaxation_suggestion="Increasing regen temp limit by 10°F 
                  would allow 1.2% more conversion, adding ~$45K/month",
              relaxation_cost=45000
          )
        """
        ...
    
    def diagnose_infeasible(self, model: pyo.ConcreteModel) -> InfeasibilityReport:
        """When solver returns infeasible, explain WHY and suggest fixes.
        
        Approach:
        1. Add slack variables to all constraints
        2. Re-solve minimizing total slack (elastic programming)
        3. Non-zero slacks = violated constraints
        4. For each violation, compute minimum relaxation
        5. Estimate economic cost of relaxation
        6. Generate engineer-language suggestions
        
        Example output:
          InfeasibilityReport(
              is_feasible=False,
              violated_constraints=[
                  ConstraintDiagnostic(
                      constraint_name="gasoline_sulfur_spec",
                      display_name="Gasoline Sulfur ≤ 30ppm",
                      violation=0.002,  # spec is 0.003, blend gives 0.005
                      relaxation_suggestion="Gasoline sulfur at 50ppm with current 
                          crude slate. Options: (1) Relax to 35ppm → feasible, 
                          (2) Reduce Mars crude by 8K bbl/d, 
                          (3) Add Scanfiner to treat FCC naphtha",
                      relaxation_cost=40000  # $/month margin impact
                  ),
              ],
              suggestions=[
                  "Your crude slate produces too much sulfur for 30ppm gasoline.",
                  "Cheapest fix: relax sulfur spec from 30ppm to 35ppm (saves $40K/month).",
                  "Best long-term fix: reduce Mars from 25K to 17K bbl/d.",
              ],
              cheapest_fix="Relax gasoline sulfur spec to 35ppm"
          )
        """
        ...
    
    def format_shadow_price(self, constraint_name: str, shadow_price: float) -> str:
        """Convert a Lagrange multiplier into engineer language.
        
        "FCC Regen Temperature: shadow price $45K/month per °F.
         This means each additional °F of regen headroom is worth 
         $45K/month in margin. Your regen is the bottleneck."
        """
        ...
```

Tests:
- `test_binding_constraints_identified`: Run optimization, verify regen temp shows as binding when heavy crude is used
- `test_shadow_prices_positive`: All binding constraint shadow prices are non-zero
- `test_infeasibility_detected`: Create an impossible scenario (sulfur spec 1ppm with high-sulfur crude), verify InfeasibilityReport is generated
- `test_cheapest_fix_identified`: In the infeasible case, verify the cheapest_fix suggestion is sensible
- `test_diagnostics_on_feasible`: Even feasible solutions have diagnostics showing which constraints are close to binding

### Task 3.7: Oracle analysis

Create `src/eurekan/analysis/oracle.py`:

```python
def oracle_analysis(
    config: RefineryConfig,
    actual_decisions: dict,  # what the refinery actually did
    plan_definition: PlanDefinition  # same constraints
) -> OracleResult:
    """
    Run simulation with actual decisions → actual margin.
    Run optimization with same constraints → optimal margin.
    Gap = money left on table.
    Decompose gap into sources.
    """
```

---

## SPRINT 4: MULTI-PERIOD + CALIBRATION + VALIDATION

### Task 4.1: Multi-period extension

Extend `PyomoModelBuilder` to handle N periods:
- Inventory linking: inv[tank,p] = inv[tank,p-1] + inflow[p] - outflow[p]
- Period-specific prices, availability, unit status
- Tank min/max constraints per period

### Task 4.2: Multi-period tests

- `test_inventory_linking`: 4 periods, gasoline price high in period 3 → optimizer builds inventory in period 1-2
- `test_unit_outage`: FCC offline in period 2 → zero FCC products, gasoline tank drawn down
- `test_cargo_arrival`: Mars only available starting period 2 → zero Mars in period 1
- `test_annual_plan`: 12 monthly periods solve in <5 seconds

### Task 4.3: Full validation suite

Run all 6 validation test categories from the PRD:
1. Base case economics
2. FCC yield accuracy
3. Conversion response
4. Crude sensitivity
5. Blending feasibility
6. Price sensitivity

Document results in a validation notebook.

### Task 4.4: Results output

Create `src/eurekan/analysis/reports.py`:
- Console output: crude slate, FCC operation, blend recipe, economics
- JSON output: full PlanningResult serialized
- Both single-period and multi-period formats

### Task 4.5: Sprint 4 integration test

End-to-end: Parse Gulf Coast → 4-period weekly plan → optimize → verify inventory → export results.

---

## RUNNING TESTS

```bash
# All tests
uv run pytest tests/ -v

# With coverage
uv run pytest tests/ -v --cov=eurekan --cov-report=term-missing

# Just unit tests
uv run pytest tests/unit/ -v

# Just validation tests
uv run pytest tests/validation/ -v

# Single file
uv run pytest tests/unit/test_cdu.py -v
```

## LINTING

```bash
# Check
uv run ruff check src/ tests/

# Auto-fix
uv run ruff check --fix src/ tests/

# Format
uv run ruff format src/ tests/

# Type check
uv run mypy src/eurekan/
```
