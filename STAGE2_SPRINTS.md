# STAGE2_SPRINTS.md — Implementation Spec for Stage 2A (API + UI)

## Prerequisites

Stage 1 is complete: 385 tests, 91% coverage. The engine works. Stage 2A wraps it in FastAPI + React. **No changes to core/, models/, optimization/, parsers/, or analysis/.** The API is a thin layer on top.

## How To Use This File

Same as Stage 1: work through tasks in order. For each task:
1. Read the spec
2. Write the code
3. Write the tests
4. Run the tests — fix failures before moving on
5. Commit after each passing milestone

---

## SPRINT 5: FastAPI BACKEND

### Task 5.1: FastAPI app setup

Install API dependencies:
```bash
uv pip install fastapi uvicorn
```

Update `pyproject.toml` to add `api` optional dependency group:
```toml
[project.optional-dependencies]
api = ["fastapi>=0.111", "uvicorn>=0.30"]
```

Create `src/eurekan/api/__init__.py`

Create `src/eurekan/api/app.py`:
```python
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from contextlib import asynccontextmanager

@asynccontextmanager
async def lifespan(app: FastAPI):
    """Load Gulf Coast data on startup."""
    from eurekan.parsers.gulf_coast import GulfCoastParser
    parser = GulfCoastParser("data/gulf_coast/Gulf_Coast.xlsx")
    app.state.config = parser.parse()
    app.state.scenarios = {}  # in-memory scenario store
    yield

app = FastAPI(
    title="Eurekan Refinery Planner",
    version="0.2.0",
    description="Refinery planning optimization API",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173"],  # Vite dev server
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

@app.get("/health")
def health():
    crude_count = len(app.state.config.crude_library)
    return {"status": "ok", "crudes_loaded": crude_count}
```

Create `src/eurekan/api/routes/__init__.py`

Test manually: `uv run uvicorn eurekan.api.app:app --reload`
Then: `curl http://localhost:8000/health` → should return crudes_loaded > 0.

Create `tests/api/__init__.py`
Create `tests/api/test_health.py`:
- Use FastAPI TestClient (from `fastapi.testclient`)
- test_health_returns_200
- test_health_has_crudes

Run: `uv run pytest tests/api/test_health.py -v`

### Task 5.2: Services layer

Create `src/eurekan/api/services.py`:

```python
class RefineryService:
    """Bridge between API routes and core engine.
    Holds config and scenario store. All business logic here, not in routes.
    """
    
    def __init__(self, config: RefineryConfig):
        self.config = config
        self.scenarios: dict[str, PlanningResult] = {}
    
    def optimize(self, periods: list[PeriodData], mode: OperatingMode,
                 fixed_variables: dict | None = None,
                 scenario_name: str = "Untitled",
                 parent_scenario_id: str | None = None) -> PlanningResult:
        """Build PlanDefinition, run optimizer, store result."""
        plan = PlanDefinition(
            periods=periods, mode=mode,
            fixed_variables=fixed_variables or {},
            scenario_name=scenario_name,
            parent_scenario_id=parent_scenario_id,
        )
        if mode == OperatingMode.OPTIMIZE:
            result = run_optimization(self.config, plan)
        elif mode == OperatingMode.SIMULATE:
            result = run_simulation(self.config, plan)
        else:
            result = run_hybrid(self.config, plan)
        
        self.scenarios[result.scenario_id] = result
        return result
    
    def quick_optimize(self, crude_prices: dict | None = None,
                       product_prices: dict | None = None,
                       scenario_name: str = "Quick Plan") -> PlanningResult:
        """Single-period optimization with optional price overrides."""
        # Build 1-period PlanDefinition using config defaults + overrides
        ...
    
    def get_scenario(self, scenario_id: str) -> PlanningResult | None:
        return self.scenarios.get(scenario_id)
    
    def list_scenarios(self) -> list[dict]:
        """Return scenario summaries (id, name, margin, parent, created_at)."""
        ...
    
    def branch_scenario(self, parent_id: str, name: str,
                        changes: dict) -> PlanningResult:
        """Branch from existing scenario with price/availability changes."""
        ...
    
    def compare_scenarios(self, base_id: str, comparison_id: str) -> ScenarioComparison:
        ...
    
    def run_oracle(self, actual_decisions: dict) -> OracleResult:
        ...
```

Tests in `tests/api/test_services.py`:
- test_optimize_returns_result
- test_quick_optimize_works
- test_scenario_stored
- test_list_scenarios
- test_branch_scenario
- test_compare_scenarios

### Task 5.3: Optimization endpoints

Create `src/eurekan/api/routes/optimize.py`:

```python
from fastapi import APIRouter, Request

router = APIRouter(prefix="/api", tags=["optimization"])

@router.post("/optimize")
def optimize(request: Request, body: OptimizeRequest) -> PlanningResult:
    service: RefineryService = request.app.state.service
    return service.optimize(
        periods=body.periods, mode=body.mode,
        fixed_variables=body.fixed_variables,
        scenario_name=body.scenario_name,
        parent_scenario_id=body.parent_scenario_id,
    )

@router.post("/optimize/quick")
def quick_optimize(request: Request, body: QuickOptimizeRequest) -> PlanningResult:
    service: RefineryService = request.app.state.service
    return service.quick_optimize(
        crude_prices=body.crude_prices,
        product_prices=body.product_prices,
        scenario_name=body.scenario_name,
    )
```

Create `src/eurekan/api/schemas.py`:
- `OptimizeRequest`: mode (str), periods (list[PeriodData]), fixed_variables (dict), scenario_name (str), parent_scenario_id (Optional[str])
- `QuickOptimizeRequest`: crude_prices (Optional[dict[str, float]]), product_prices (Optional[dict[str, float]]), scenario_name (str, default "Quick Plan")

Register router in app.py.

Tests in `tests/api/test_optimize.py`:
- test_optimize_endpoint_200: POST /api/optimize returns PlanningResult
- test_quick_optimize_endpoint: POST /api/optimize/quick with no body returns result
- test_optimize_margin_positive: result.total_margin > 0
- test_simulate_mode: mode="simulate" works
- test_hybrid_mode: mode="hybrid" with fixed_variables works

### Task 5.4: Configuration endpoints

Create `src/eurekan/api/routes/config.py`:

```
GET /api/config
  → { name, units: [{id, type, capacity}], crude_count, product_count, completeness }

GET /api/config/crudes
  → list of { crude_id, name, api, sulfur, price, max_rate }

GET /api/config/products
  → list of { product_id, name, price, min_demand, specs: [{name, min, max}] }

GET /api/config/completeness
  → ConfigCompleteness

PUT /api/config/crude/{crude_id}/price
  Body: { price: float }
  Updates price in-memory. Sets stale flag on service.

PUT /api/config/product/{product_id}/price
  Body: { price: float }
  Updates price. Sets stale flag.
```

Add `is_stale: bool` to RefineryService — set True when any input changes after last optimize. Reset to False on each optimize call. Return in config response.

Tests in `tests/api/test_config.py`:
- test_get_config
- test_get_crudes_list
- test_get_products_list
- test_get_completeness
- test_update_crude_price
- test_update_product_price
- test_stale_flag_after_price_change

### Task 5.5: Scenario and flow endpoints

Create `src/eurekan/api/routes/scenarios.py`:

```
GET /api/scenarios
  → list of scenario summaries

GET /api/scenarios/{scenario_id}
  → full PlanningResult

POST /api/scenarios/{scenario_id}/branch
  Body: { name: str, changes: { crude_prices?: {}, product_prices?: {} } }
  → new PlanningResult (branched from parent)

GET /api/scenarios/compare?base={id}&comparison={id}
  → ScenarioComparison

GET /api/scenarios/{scenario_id}/flow
  → MaterialFlowGraph (for the flowsheet)

GET /api/scenarios/{scenario_id}/diagnostics
  → list[ConstraintDiagnostic]

GET /api/scenarios/{scenario_id}/crude-disposition/{crude_id}
  → CrudeDisposition
```

Create `src/eurekan/api/routes/oracle.py`:

```
POST /api/oracle
  Body: { actual_decisions: dict }
  → OracleResult
```

Register all routers in app.py.

Tests in `tests/api/test_scenarios.py`:
- test_list_scenarios_empty
- test_optimize_then_list
- test_get_scenario_by_id
- test_branch_scenario
- test_compare_scenarios
- test_get_flow_graph
- test_get_diagnostics
- test_get_crude_disposition

### Task 5.6: Sprint 5 integration test

Create `tests/api/test_sprint5_integration.py`:

Full API workflow:
1. GET /health → 200, crudes loaded
2. POST /api/optimize/quick → PlanningResult, margin > 0
3. GET /api/scenarios → 1 scenario
4. PUT /api/config/crude/ARL/price → 200
5. POST /api/scenarios/{id}/branch with new prices → new scenario
6. GET /api/scenarios/compare → ScenarioComparison with margin_delta
7. GET /api/scenarios/{id}/flow → MaterialFlowGraph with nodes + edges
8. GET /api/scenarios/{id}/diagnostics → diagnostics list
9. POST /api/oracle with suboptimal decisions → gap > 0

Run: `uv run pytest tests/api/ -v`
Then: `uv run pytest tests/ -v --cov=eurekan`

All tests pass. Commit:
```
git commit -m "Sprint 5 complete: FastAPI backend, all endpoints working"
```

---

## SPRINT 6: REACT FRONTEND — FLOWSHEET + OPTIMIZATION

### Task 6.1: React project setup

From the project root:
```bash
npm create vite@latest frontend -- --template react-ts
cd frontend
npm install
npm install -D tailwindcss @tailwindcss/vite
npm install @xyflow/react recharts zustand @tanstack/react-query lucide-react
```

Configure `vite.config.ts`:
```typescript
import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'
import tailwindcss from '@tailwindcss/vite'

export default defineConfig({
  plugins: [react(), tailwindcss()],
  server: {
    proxy: {
      '/api': 'http://localhost:8000',
      '/health': 'http://localhost:8000',
    },
  },
})
```

Create basic layout:
- `App.tsx`: Main layout with sidebar + content area
- Sidebar: navigation (Flowsheet, Scenarios, Oracle)
- Content: renders active view
- Verify: `npm run dev` shows blank app at localhost:5173

### Task 6.2: TypeScript types and API client

Create `frontend/src/types/index.ts`:
- TypeScript interfaces matching ALL Pydantic models from core/results.py:
  PlanningResult, PeriodResult, FCCResult, BlendResult, MaterialFlowGraph,
  FlowNode, FlowEdge, ConstraintDiagnostic, InfeasibilityReport,
  SolutionNarrative, ScenarioComparison, CrudeDisposition, OracleResult,
  ConfigCompleteness, EquipmentStatus, SpecResult
- Match field names and types exactly to the Pydantic models.

Create `frontend/src/api/client.ts`:
```typescript
const BASE = '/api';

export async function quickOptimize(params?: {
  crude_prices?: Record<string, number>;
  product_prices?: Record<string, number>;
  scenario_name?: string;
}): Promise<PlanningResult> {
  const res = await fetch(`${BASE}/optimize/quick`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(params ?? {}),
  });
  return res.json();
}

export async function getScenarios(): Promise<ScenarioSummary[]> { ... }
export async function getScenario(id: string): Promise<PlanningResult> { ... }
export async function getFlowGraph(id: string): Promise<MaterialFlowGraph> { ... }
export async function getDiagnostics(id: string): Promise<ConstraintDiagnostic[]> { ... }
export async function branchScenario(id: string, body: BranchRequest): Promise<PlanningResult> { ... }
export async function compareScenarios(baseId: string, compId: string): Promise<ScenarioComparison> { ... }
export async function getConfig(): Promise<ConfigSummary> { ... }
export async function getCrudes(): Promise<CrudeSummary[]> { ... }
export async function getProducts(): Promise<ProductSummary[]> { ... }
export async function updateCrudePrice(crudeId: string, price: number): Promise<void> { ... }
export async function updateProductPrice(productId: string, price: number): Promise<void> { ... }
```

Create `frontend/src/stores/refineryStore.ts` (Zustand):
```typescript
interface RefineryState {
  activeScenarioId: string | null;
  activeResult: PlanningResult | null;
  isStale: boolean;             // inputs changed since last optimize
  isOptimizing: boolean;        // solver running
  lastOptimizedAt: Date | null;
  lastInputChangedAt: Date | null;
  
  setActiveResult: (result: PlanningResult) => void;
  markStale: () => void;
  startOptimizing: () => void;
  finishOptimizing: (result: PlanningResult) => void;
}
```

### Task 6.3: Refinery flowsheet

Create `frontend/src/components/flowsheet/RefineryFlowsheet.tsx`:
- Uses @xyflow/react (React Flow v12)
- Reads MaterialFlowGraph from active PlanningResult
- Converts FlowNodes → React Flow nodes, FlowEdges → React Flow edges
- Layout: left-to-right (crude purchases → CDU → FCC → products)
- Auto-layout using dagre or manual positioning based on node_type

Create `frontend/src/components/flowsheet/UnitNode.tsx`:
- Custom React Flow node for CDU, FCC, Blender
- Shows: unit name, throughput, utilization bar (EquipmentBar)
- FCC node: also shows conversion % and regen temp bar
- If binding constraint (from diagnostics): node border pulses amber
- Hover on binding node: tooltip with shadow price in business terms
  "FCC Regen: 94% utilized. +$45K/month if limit +10°F"
- Click: opens detail side panel

Create `frontend/src/components/flowsheet/StreamEdge.tsx`:
- Custom React Flow edge with volume label
- Width proportional to volume (min 2px, max 12px)
- Color gradient by economic value (darker = higher value)
- If data source is DEFAULT/low confidence: dashed line + "⚠" badge
- Click: opens stream detail panel showing properties + crude_contributions

Create `frontend/src/components/flowsheet/PurchaseNode.tsx`:
- Crude name, volume (bbl/d), cost ($/d)
- Color by data source confidence

Create `frontend/src/components/flowsheet/ProductNode.tsx`:
- Product name, volume, revenue
- Spec badges (SpecBadge component): green/yellow/red per spec
- Click: opens blend recipe panel

### Task 6.4: Optimization panel

Create `frontend/src/components/optimization/OptimizePanel.tsx`:
- Positioned as a fixed panel (top or sidebar)
- Mode selector: Optimize / Simulate / Hybrid (radio buttons)
- "Optimize" button: large, prominent, with loading spinner
- After solve: margin ($4.18M/month), solve time, status badge
- STALE STATE: If `isStale` in store, show amber banner:
  "Inputs changed — results may be outdated. Click Optimize to refresh."
  Gray out flowsheet numbers when stale.
- Quick price editor: inline editable crude + product prices
  Editing a price → calls updateCrudePrice/updateProductPrice API
  → marks state as stale

Create `frontend/src/components/optimization/ResultsSummary.tsx`:
- Revenue breakdown by product (horizontal stacked bar or waterfall)
- Cost breakdown: crude purchase, CDU opex, FCC opex, HT, reformate
- Net margin (large number, prominent)
- Comparison to parent scenario if available (delta shown)

### Task 6.5: Common components

Create `frontend/src/components/common/EquipmentBar.tsx`:
- Horizontal bar, 0-100%
- Color: green (<80%), yellow (80-95%), red (>95%)
- Label: "Regen Temp: 1,320°F / 1,400°F (94%)"
- Optional tooltip with shadow price

Create `frontend/src/components/common/SpecBadge.tsx`:
- Compact badge showing spec compliance
- Green: "RON 87.3 ✓" (margin shown on hover)
- Yellow: "S 28ppm ⚠" (tight margin)
- Red: "RVP 9.2 ✗" (violated)

Create `frontend/src/components/common/LoadingSpinner.tsx`:
- Used in OptimizePanel during solve
- Animated, Eurekan-branded

Verify: Start both backend and frontend:
```bash
# Terminal 1:
uv run uvicorn eurekan.api.app:app --reload --workers 2
# Terminal 2:
cd frontend && npm run dev
```
Open localhost:5173 → should see the refinery flowsheet with data from the API.

---

## SPRINT 7: INTERACTIVE FEATURES

### Task 7.1: Scenario tree

Create `frontend/src/stores/scenarioStore.ts` (Zustand):
```typescript
interface ScenarioState {
  scenarios: ScenarioSummary[];
  activeId: string | null;
  loadScenarios: () => Promise<void>;
  setActive: (id: string) => void;
  branch: (parentId: string, name: string, changes: object) => Promise<PlanningResult>;
}
```

Create `frontend/src/components/scenarios/ScenarioTree.tsx`:
- Tree visualization of scenarios (parent-child hierarchy)
- Each node: name, margin, timestamp, status badge
- Click node → loads that scenario into the flowsheet
- Right-click or button → "Branch from this" dialog
- Active scenario highlighted with border

Create `frontend/src/components/scenarios/CreateScenarioDialog.tsx`:
- Modal dialog for branching
- Fields: name, description
- Price overrides: inline editor for crude and product prices
- "Create & Optimize" button

### Task 7.2: Scenario comparison

Create `frontend/src/components/scenarios/ScenarioComparison.tsx`:
- Select two scenarios to compare (dropdown or click-to-compare)
- Calls GET /api/scenarios/compare
- Shows: margin delta (large, green/red), crude slate changes (bar chart),
  FCC conversion delta, product volume deltas
- Constraint changes table: which bottlenecks moved/appeared/disappeared
- Key insight text from AI (or deterministic summary)
- DIFF MODE toggle: switches the flowsheet to show Δ volumes on edges
  (green = more flow vs parent, red = less flow)
  Nodes show throughput change (±bbl/d)

### Task 7.3: Conversion explorer

Create `frontend/src/components/optimization/ConversionSlider.tsx`:
- Range slider from 68% to 90% (or max_conversion from model)
- On page load: pre-compute margin at 9 points (72-88% in 2% steps)
  by calling API in hybrid mode with fixed conversion
- Display: Recharts line chart of margin vs conversion
- Marks on chart: current optimal, equipment limit, overcracking peak
- As user drags slider: interpolate margin from pre-computed points
- On slider release: call API for exact value at that conversion
- Tooltip: "At 85%: gasoline +1,200 bbl/d, regen at 99%"
- Highlight region beyond equipment limit in red

### Task 7.4: Bottleneck visualization

Create `frontend/src/components/diagnostics/BottleneckHeatMap.tsx`:
- Grid of constraints colored by bottleneck_score (0-100)
- Red = high score (most limiting), green = low (headroom)
- Click cell → shows full ConstraintDiagnostic details

Create `frontend/src/components/diagnostics/ConstraintPanel.tsx`:
- List view sorted by bottleneck_score descending
- Each row: display_name, utilization bar, shadow price, source_stream
- Binding constraints highlighted with amber background
- Relaxation suggestion shown inline
- "What if I relax this?" button → branches scenario with relaxed constraint

Create `frontend/src/components/diagnostics/InfeasibilityDialog.tsx`:
- Modal triggered when optimization returns infeasible
- Header: "No feasible plan exists"
- Violated constraints listed with relaxation costs
- Cheapest fix prominently displayed with "Apply Fix" button
- "Show alternatives" expands to show all options
- "Apply Fix" → applies the relaxation, re-optimizes, closes dialog

### Task 7.5: Stream tracing

Create `frontend/src/components/streams/StreamTracer.tsx`:
- Click any crude purchase node → highlight all edges containing that crude
  (uses crude_contributions on FlowEdge)
- Click any product node → highlight all contributing edges
- Non-highlighted edges dim to 20% opacity
- Highlighted edges show crude_contributions as percentage labels
- Click background to clear highlighting

Create `frontend/src/components/streams/CrudeDispositionTable.tsx`:
- Table showing where each crude ends up
- Columns: crude, total volume, product breakdown (% and bbl/d), value created, net margin
- Sortable by any column
- Click crude row → activates stream tracer for that crude

---

## SPRINT 8: AI NARRATIVE INTEGRATION

### Task 8.1: Claude API setup

Install: `uv pip install anthropic`

Create `src/eurekan/ai/__init__.py`
Create `src/eurekan/ai/narrative.py`:

```python
import anthropic

NARRATIVE_SYSTEM_PROMPT = """
You are a refinery planning advisor for the Eurekan system. 
Given structured optimization results (JSON), generate a concise 
executive summary and decision explanations for a refinery planner.

Rules:
- Use $/month for economics
- Reference specific crudes by name
- Explain WHY the optimizer chose each decision
- Mention what was NOT chosen and why
- Flag risks with specific numbers
- Keep each explanation under 100 words
- Respond ONLY with valid JSON matching the SolutionNarrative schema
"""

def extract_facts(result: PlanningResult) -> dict:
    """Deterministic: structured data from flow graph + diagnostics."""
    ...

def apply_domain_rules(facts: dict) -> list[dict]:
    """Deterministic: if regen > 95% → flag, if sulfur margin < 5ppm → trace."""
    ...

def generate_narrative(
    result: PlanningResult, 
    config: RefineryConfig,
    api_key: str | None = None
) -> SolutionNarrative | None:
    """
    Three-step pipeline:
    1. extract_facts (deterministic)
    2. apply_domain_rules (deterministic)
    3. Claude API synthesis (AI) — returns None if no API key
    """
    facts = extract_facts(result)
    insights = apply_domain_rules(facts)
    
    if not api_key:
        # Return a basic deterministic narrative (no Claude)
        return _build_deterministic_narrative(facts, insights)
    
    client = anthropic.Anthropic(api_key=api_key)
    response = client.messages.create(
        model="claude-sonnet-4-20250514",
        system=NARRATIVE_SYSTEM_PROMPT,
        messages=[{"role": "user", "content": json.dumps({
            "facts": facts,
            "domain_insights": insights,
            "output_schema": "SolutionNarrative",
        })}],
        max_tokens=2000,
    )
    return SolutionNarrative.model_validate_json(response.content[0].text)
```

### Task 8.2: What-If parser

Create `src/eurekan/ai/what_if.py`:

```python
class WhatIfAction(BaseModel):
    """Parsed action from natural language question."""
    action_type: str  # price_change, crude_swap, unit_outage, constraint_relax
    description: str  # human-readable description
    changes: dict     # structured changes to apply
    confirmation_prompt: str  # "I will decrease gasoline price by $5. Correct?"

def parse_what_if(
    question: str, 
    config: RefineryConfig,
    api_key: str
) -> WhatIfAction:
    """
    Use Claude to parse natural language into structured action.
    Returns a WhatIfAction for USER CONFIRMATION — never auto-executes.
    """
    ...

def execute_what_if(
    action: WhatIfAction,
    service: RefineryService,
    base_scenario_id: str,
) -> tuple[PlanningResult, ScenarioComparison]:
    """Execute confirmed action: branch scenario, optimize, compare."""
    ...
```

### Task 8.3: AI API endpoints

Create `src/eurekan/api/routes/ai.py`:

```
POST /api/ai/narrative
  Body: { scenario_id: str }
  → SolutionNarrative (or deterministic fallback if no API key)

POST /api/ai/ask
  Body: { question: str, scenario_id: str }
  Step 1 response: { proposed_action: WhatIfAction, 
                     confirmation_prompt: str }

POST /api/ai/ask/confirm
  Body: { action: WhatIfAction, scenario_id: str }
  → { answer: str, new_scenario_id: str, comparison: ScenarioComparison }
```

Environment: `ANTHROPIC_API_KEY` env var. If not set, narrative endpoint returns deterministic version. What-if endpoint returns 503.

### Task 8.4: Narrative UI components

Create `frontend/src/components/narrative/NarrativePanel.tsx`:
- Positioned as a collapsible right panel
- Executive summary at top (always visible when expanded)
- Decision explanations: expandable accordion
  Each: decision text, reasoning, alternatives, confidence bar
- Risk flags: severity-colored cards (red/yellow/blue)
- Data quality warnings: amber cards from DataSource tracking
- Economics narrative: plain text paragraph
- "Generate Narrative" button if not yet generated
- Loading state during Claude API call

Create `frontend/src/components/narrative/AskEurekan.tsx`:
- Fixed input bar at bottom of screen
- Chat-like: user types → loading → confirmation card
- Confirmation card: "I'll decrease gasoline from $82.81 to $77.81. Correct?"
  [Confirm] [Edit] [Cancel]
- After confirm: loading → result card with answer + comparison link
- History of previous questions visible above input
- Ambiguous queries: "Which heavy crude? Mars, Arab Heavy, or Basrah?"
  → selection buttons

### Task 8.5: Near-optimal solution enumeration

Create `src/eurekan/analysis/alternatives.py`:

```python
def enumerate_near_optimal(
    config: RefineryConfig,
    plan: PlanDefinition,
    optimal_result: PlanningResult,
    tolerance: float = 0.02,  # within 2% of optimal margin
) -> list[PlanningResult]:
    """
    Find 2-3 alternative plans within tolerance of optimal.
    
    1. Add constraint: margin >= optimal × (1 - tolerance)
    2. Secondary objective: minimize crude count → Plan B (simpler logistics)
    3. Secondary objective: maximize min constraint margin → Plan C (most robust)
    4. Return [optimal, Plan B, Plan C] with comparisons
    """
    ...
```

API endpoint:
```
POST /api/optimize/alternatives
  Body: { scenario_id: str, tolerance: float = 0.02 }
  → list[PlanningResult] (2-3 alternatives)
```

UI component:
Create `frontend/src/components/optimization/AlternativePlans.tsx`:
- Card showing "3 plans achieve similar margin"
- Each card: plan name, margin, key tradeoff description
- Click to load into flowsheet
- Compare button between any two

### Task 8.6: Full Stage 2A integration test

Create `tests/api/test_stage2_integration.py`:

End-to-end:
1. GET /health → 200
2. POST /api/optimize/quick → PlanningResult with margin > 0
3. GET /api/scenarios/{id}/flow → MaterialFlowGraph
4. GET /api/scenarios/{id}/diagnostics → diagnostics
5. PUT /api/config/crude/ARL/price with new price
6. POST /api/scenarios/{id}/branch → new scenario
7. GET /api/scenarios/compare → ScenarioComparison
8. POST /api/ai/narrative → SolutionNarrative (deterministic mode)
9. POST /api/oracle → OracleResult with gap > 0

Run: `uv run pytest tests/ -v --cov=eurekan`

Commit: `git commit -m "Stage 2A complete: API + UI + AI narrative layer"`

---

## Running Stage 2A

```bash
# Backend (Terminal 1):
cd eurekan-refinery
uv run uvicorn eurekan.api.app:app --reload --workers 2

# Frontend (Terminal 2):
cd eurekan-refinery/frontend
npm run dev

# Open browser: http://localhost:5173
```

## Dependencies Added in Stage 2A

```
Backend:
  fastapi>=0.111
  uvicorn>=0.30
  anthropic>=0.30  (optional — AI features degrade gracefully without it)

Frontend:
  react, react-dom (via Vite template)
  typescript
  tailwindcss, @tailwindcss/vite
  @xyflow/react (React Flow v12)
  recharts
  zustand
  @tanstack/react-query
  lucide-react
```
