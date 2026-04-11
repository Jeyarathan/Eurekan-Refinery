/**
 * TypeScript types matching the Eurekan Pydantic models from
 * `src/eurekan/core/results.py`, `core/config.py`, etc.
 *
 * Field names are snake_case to match the API response shape verbatim.
 */

// ---------------------------------------------------------------------------
// Crude / cut properties
// ---------------------------------------------------------------------------

export interface CutProperties {
  api?: number | null
  sulfur?: number | null
  ron?: number | null
  mon?: number | null
  rvp?: number | null
  spg?: number | null
  olefins?: number | null
  aromatics?: number | null
  benzene?: number | null
  nitrogen?: number | null
  ccr?: number | null
  nickel?: number | null
  vanadium?: number | null
  cetane?: number | null
  flash_point?: number | null
  pour_point?: number | null
  cloud_point?: number | null
  metals?: number
}

// ---------------------------------------------------------------------------
// Material flow graph
// ---------------------------------------------------------------------------

export type FlowNodeType =
  | 'purchase'
  | 'unit'
  | 'blend_header'
  | 'sale_point'
  | 'tank'

export interface FlowNode {
  node_id: string
  node_type: FlowNodeType
  display_name: string
  throughput: number
}

export interface FlowEdge {
  edge_id: string
  source_node: string
  dest_node: string
  stream_name: string
  display_name: string
  volume: number
  properties: CutProperties
  economic_value: number
  crude_contributions: Record<string, number>
}

export interface MaterialFlowGraph {
  nodes: FlowNode[]
  edges: FlowEdge[]
}

// ---------------------------------------------------------------------------
// Diagnostics
// ---------------------------------------------------------------------------

export interface EquipmentStatus {
  name: string
  display_name: string
  current_value: number
  limit: number
  utilization_pct: number
  is_binding: boolean
}

export interface ConstraintDiagnostic {
  constraint_name: string
  display_name: string
  violation: number
  shadow_price: number | null
  bottleneck_score: number
  binding: boolean
  source_stream: string | null
  relaxation_suggestion: string | null
  relaxation_cost: number | null
}

export interface InfeasibilityReport {
  is_feasible: boolean
  violated_constraints: ConstraintDiagnostic[]
  suggestions: string[]
  cheapest_fix: string | null
}

// ---------------------------------------------------------------------------
// Narrative
// ---------------------------------------------------------------------------

export interface DecisionExplanation {
  decision: string
  reasoning: string
  alternatives_considered: string
  confidence: number
}

export interface RiskFlag {
  severity: string
  message: string
  recommendation: string
}

export interface SolutionNarrative {
  executive_summary: string
  decision_explanations: DecisionExplanation[]
  risk_flags: RiskFlag[]
  economics_narrative: string
  data_quality_warnings: string[]
}

// ---------------------------------------------------------------------------
// Unit and plan results
// ---------------------------------------------------------------------------

export interface FCCResult {
  conversion: number
  yields: Record<string, number>
  properties: Record<string, CutProperties>
  equipment: EquipmentStatus[]
}

export interface SpecResult {
  spec_name: string
  value: number
  limit: number
  margin: number
  feasible: boolean
}

export interface BlendResult {
  product_id: string
  total_volume: number
  recipe: Record<string, number>
  quality: Record<string, Record<string, unknown>>
}

export interface DispositionResult {
  stream_id: string
  to_blend: number
  to_sell: number
  to_fuel_oil: number
}

export interface PeriodResult {
  period_id: number
  crude_slate: Record<string, number>
  cdu_cuts: Record<string, number>
  fcc_result: FCCResult | null
  blend_results: BlendResult[]
  dispositions: DispositionResult[]
  product_volumes: Record<string, number>
  revenue: number
  crude_cost: number
  operating_cost: number
  margin: number
}

export interface CrudeDisposition {
  crude_id: string
  total_volume: number
  product_breakdown: Record<string, number>
  value_created: number
  crude_cost: number
  net_margin: number
}

export interface PlanningResult {
  scenario_id: string
  scenario_name: string
  parent_scenario_id: string | null
  created_at: string
  periods: PeriodResult[]
  total_margin: number
  solve_time_seconds: number
  solver_status: string
  inventory_trajectory: Record<string, number[]>
  material_flow: MaterialFlowGraph
  crude_valuations: CrudeDisposition[]
  constraint_diagnostics: ConstraintDiagnostic[]
  infeasibility_report: InfeasibilityReport | null
  narrative: SolutionNarrative | null
}

// ---------------------------------------------------------------------------
// Oracle and scenario comparison
// ---------------------------------------------------------------------------

export interface OracleResult {
  actual_margin: number
  optimal_margin: number
  gap: number
  gap_pct: number
  gap_sources: Record<string, number>
}

export interface ScenarioComparison {
  base_scenario_id: string
  comparison_scenario_id: string
  margin_delta: number
  crude_slate_changes: Record<string, number>
  conversion_delta: number
  product_volume_deltas: Record<string, number>
  constraint_changes: Array<Record<string, unknown>>
  key_insight: string
}

// ---------------------------------------------------------------------------
// Config and lightweight summaries (returned by the API config endpoints)
// ---------------------------------------------------------------------------

export interface ConfigCompleteness {
  overall_pct: number
  missing: string[]
  using_defaults: string[]
  ready_to_optimize: boolean
  margin_uncertainty_pct: number
  highest_value_missing: string | null
}

export interface UnitSummary {
  id: string
  type: string
  capacity: number
}

export interface ConfigSummary {
  name: string
  units: UnitSummary[]
  crude_count: number
  product_count: number
  completeness: ConfigCompleteness
  is_stale: boolean
}

export interface CrudeSummary {
  crude_id: string
  name: string
  api: number
  sulfur: number
  price: number | null
  max_rate: number | null
}

export interface ProductSpecSummary {
  name: string
  min: number | null
  max: number | null
}

export interface ProductSummary {
  product_id: string
  name: string
  price: number
  min_demand: number
  max_demand: number | null
  specs: ProductSpecSummary[]
}

export interface ScenarioSummary {
  scenario_id: string
  scenario_name: string
  parent_scenario_id: string | null
  total_margin: number
  created_at: string
  solver_status: string
  n_periods: number
}

// ---------------------------------------------------------------------------
// Request bodies
// ---------------------------------------------------------------------------

export interface QuickOptimizeRequest {
  crude_prices?: Record<string, number>
  product_prices?: Record<string, number>
  scenario_name?: string
}

export interface BranchScenarioRequest {
  name: string
  changes: {
    crude_prices?: Record<string, number>
    product_prices?: Record<string, number>
  }
}

export interface OracleRequest {
  actual_decisions: Record<string, number>
}
