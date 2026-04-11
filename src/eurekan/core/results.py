"""Optimization results — flow graph, diagnostics, narrative, plan results."""

from __future__ import annotations

from datetime import datetime
from enum import Enum
from typing import Any, Optional

from pydantic import BaseModel

from eurekan.core.crude import CutProperties


# ---------------------------------------------------------------------------
# 1. Material Flow Graph
# ---------------------------------------------------------------------------


class FlowNodeType(str, Enum):
    PURCHASE = "purchase"
    UNIT = "unit"
    BLEND_HEADER = "blend_header"
    SALE_POINT = "sale_point"
    TANK = "tank"


class FlowNode(BaseModel):
    """A node in the material flow graph."""

    node_id: str
    node_type: FlowNodeType
    display_name: str
    throughput: float


class FlowEdge(BaseModel):
    """A directed edge (stream) in the material flow graph."""

    edge_id: str
    source_node: str
    dest_node: str
    stream_name: str
    display_name: str
    volume: float
    properties: CutProperties = CutProperties()
    economic_value: float = 0.0
    crude_contributions: dict[str, float] = {}


class MaterialFlowGraph(BaseModel):
    """Directed graph of material flows through the refinery."""

    nodes: list[FlowNode] = []
    edges: list[FlowEdge] = []

    def trace_crude(self, crude_id: str) -> list[FlowEdge]:
        """Return all edges that contain the given crude."""
        return [e for e in self.edges if crude_id in e.crude_contributions]

    def trace_product(self, product_id: str) -> list[FlowEdge]:
        """Return all edges whose dest_node matches the product."""
        return [e for e in self.edges if e.dest_node == product_id]

    def streams_by_property(self, prop: str, min_val: float) -> list[FlowEdge]:
        """Return edges where the given property exceeds min_val."""
        result: list[FlowEdge] = []
        for e in self.edges:
            val = getattr(e.properties, prop, None)
            if val is not None and val >= min_val:
                result.append(e)
        return result


class CrudeDisposition(BaseModel):
    """Per-crude economics — where each crude ends up and its value."""

    crude_id: str
    total_volume: float
    product_breakdown: dict[str, float] = {}
    value_created: float
    crude_cost: float
    net_margin: float


# ---------------------------------------------------------------------------
# 2. Constraint Diagnostics
# ---------------------------------------------------------------------------


class EquipmentStatus(BaseModel):
    """Status of a single equipment constraint."""

    name: str
    display_name: str
    current_value: float
    limit: float
    utilization_pct: float
    is_binding: bool


class ConstraintDiagnostic(BaseModel):
    """Diagnostic for a single constraint after solving."""

    constraint_name: str
    display_name: str
    violation: float
    shadow_price: Optional[float] = None
    bottleneck_score: float = 0.0
    binding: bool = False
    source_stream: Optional[str] = None
    relaxation_suggestion: Optional[str] = None
    relaxation_cost: Optional[float] = None


class InfeasibilityReport(BaseModel):
    """Report when the problem is infeasible."""

    is_feasible: bool
    violated_constraints: list[ConstraintDiagnostic] = []
    suggestions: list[str] = []
    cheapest_fix: Optional[str] = None


# ---------------------------------------------------------------------------
# 3. AI Narrative
# ---------------------------------------------------------------------------


class DecisionExplanation(BaseModel):
    """Explanation for a single optimizer decision."""

    decision: str
    reasoning: str
    alternatives_considered: str
    confidence: float


class RiskFlag(BaseModel):
    """A risk flag from the solution analysis."""

    severity: str
    message: str
    recommendation: str


class SolutionNarrative(BaseModel):
    """AI-generated narrative interpreting the optimization results."""

    executive_summary: str
    decision_explanations: list[DecisionExplanation] = []
    risk_flags: list[RiskFlag] = []
    economics_narrative: str = ""
    data_quality_warnings: list[str] = []


# ---------------------------------------------------------------------------
# 4. Unit and Plan Results
# ---------------------------------------------------------------------------


class CDUResult(BaseModel):
    """Results from the CDU unit model."""

    total_crude: float
    cut_volumes: dict[str, float] = {}
    cut_properties: dict[str, CutProperties] = {}
    vgo_feed_properties: CutProperties = CutProperties()


class FCCResult(BaseModel):
    """Results from the FCC unit model."""

    conversion: float
    yields: dict[str, float] = {}
    properties: dict[str, CutProperties] = {}
    equipment: list[EquipmentStatus] = []


class SpecResult(BaseModel):
    """Result of checking a single product spec against a blend property."""

    spec_name: str
    value: float
    limit: float
    margin: float
    feasible: bool


class BlendResult(BaseModel):
    """Results for a single blended product."""

    product_id: str
    total_volume: float
    recipe: dict[str, float] = {}
    quality: dict[str, dict[str, Any]] = {}


class DispositionResult(BaseModel):
    """How a stream was disposed."""

    stream_id: str
    to_blend: float = 0.0
    to_sell: float = 0.0
    to_fuel_oil: float = 0.0


class PeriodResult(BaseModel):
    """Optimization results for a single period."""

    period_id: int
    crude_slate: dict[str, float] = {}
    cdu_cuts: dict[str, float] = {}
    fcc_result: Optional[FCCResult] = None
    blend_results: list[BlendResult] = []
    dispositions: list[DispositionResult] = []
    product_volumes: dict[str, float] = {}
    revenue: float = 0.0
    crude_cost: float = 0.0
    operating_cost: float = 0.0
    margin: float = 0.0


class PlanningResult(BaseModel):
    """Complete results from a planning optimization run."""

    scenario_id: str
    scenario_name: str
    parent_scenario_id: Optional[str] = None
    created_at: datetime
    periods: list[PeriodResult] = []
    total_margin: float = 0.0
    solve_time_seconds: float = 0.0
    solver_status: str = ""
    inventory_trajectory: dict[str, list[float]] = {}
    material_flow: MaterialFlowGraph = MaterialFlowGraph()
    crude_valuations: list[CrudeDisposition] = []
    constraint_diagnostics: list[ConstraintDiagnostic] = []
    infeasibility_report: Optional[InfeasibilityReport] = None
    narrative: Optional[SolutionNarrative] = None


class OracleResult(BaseModel):
    """Oracle gap analysis — comparing actual vs optimal."""

    actual_margin: float
    optimal_margin: float
    gap: float
    gap_pct: float
    gap_sources: dict[str, float] = {}


class ScenarioComparison(BaseModel):
    """Comparison between two scenarios."""

    base_scenario_id: str
    comparison_scenario_id: str
    margin_delta: float
    crude_slate_changes: dict[str, float] = {}
    conversion_delta: float = 0.0
    product_volume_deltas: dict[str, float] = {}
    constraint_changes: list[dict[str, Any]] = []
    key_insight: str = ""
