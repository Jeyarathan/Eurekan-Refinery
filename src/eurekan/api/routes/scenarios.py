"""Scenario / flow / diagnostics endpoints — Sprint 5 Task 5.5."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, HTTPException, Request

from eurekan.api.schemas import BranchScenarioRequest
from eurekan.api.services import RefineryService
from eurekan.core.results import (
    ConstraintDiagnostic,
    CrudeDisposition,
    MaterialFlowGraph,
    PlanningResult,
    ScenarioComparison,
)
from eurekan.optimization.builder import PyomoModelBuilder
from eurekan.optimization.diagnostics import ConstraintDiagnostician
from eurekan.optimization.solver import EurekanSolver

router = APIRouter(prefix="/api/scenarios", tags=["scenarios"])


def _service(request: Request) -> RefineryService:
    return request.app.state.service


def _require_scenario(service: RefineryService, scenario_id: str) -> PlanningResult:
    scenario = service.get_scenario(scenario_id)
    if scenario is None:
        raise HTTPException(status_code=404, detail=f"Scenario not found: {scenario_id}")
    return scenario


@router.get("")
def list_scenarios(request: Request) -> list[dict[str, Any]]:
    """List scenario summaries (newest first)."""
    return _service(request).list_scenarios()


@router.get("/compare", response_model=ScenarioComparison)
def compare_scenarios(
    request: Request, base: str, comparison: str
) -> ScenarioComparison:
    """Diff two stored scenarios. Both query params are scenario IDs."""
    service = _service(request)
    try:
        return service.compare_scenarios(base, comparison)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.get("/{scenario_id}", response_model=PlanningResult)
def get_scenario(request: Request, scenario_id: str) -> PlanningResult:
    return _require_scenario(_service(request), scenario_id)


@router.post("/{scenario_id}/branch", response_model=PlanningResult)
def branch_scenario(
    request: Request, scenario_id: str, body: BranchScenarioRequest
) -> PlanningResult:
    service = _service(request)
    try:
        return service.branch_scenario(
            parent_id=scenario_id,
            name=body.name,
            changes=body.changes,
        )
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.get("/{scenario_id}/flow", response_model=MaterialFlowGraph)
def get_flow(request: Request, scenario_id: str) -> MaterialFlowGraph:
    scenario = _require_scenario(_service(request), scenario_id)
    return scenario.material_flow


@router.get("/{scenario_id}/diagnostics", response_model=list[ConstraintDiagnostic])
def get_diagnostics(
    request: Request, scenario_id: str
) -> list[ConstraintDiagnostic]:
    """Run the constraint diagnostician on a stored scenario.

    The diagnostician needs a Pyomo model with duals attached, so we
    rebuild and re-solve. The scenario must already exist in the store.
    """
    service = _service(request)
    scenario = _require_scenario(service, scenario_id)

    # Re-build a model that matches the stored scenario's plan structure.
    # The simplest approach: use the stored scenario's period count + the
    # current config. The diagnostician only needs binding-constraint info.
    from eurekan.core.enums import OperatingMode
    from eurekan.core.period import PeriodData, PlanDefinition

    periods = [
        PeriodData(
            period_id=p.period_id,
            duration_hours=24.0,
            product_prices={
                "gasoline": 95.0, "diesel": 100.0, "jet": 100.0,
                "naphtha": 60.0, "fuel_oil": 70.0, "lpg": 50.0,
            },
        )
        for p in scenario.periods
    ]
    plan = PlanDefinition(
        periods=periods,
        mode=OperatingMode.OPTIMIZE,
        scenario_name=f"{scenario.scenario_name} (diag)",
    )
    model = PyomoModelBuilder(service.config, plan).build()
    solver = EurekanSolver()
    solver.solve_with_fallback(model, service.config, plan)

    return ConstraintDiagnostician().diagnose_feasible(model)


@router.get(
    "/{scenario_id}/crude-disposition/{crude_id}",
    response_model=CrudeDisposition,
)
def get_crude_disposition(
    request: Request, scenario_id: str, crude_id: str
) -> CrudeDisposition:
    """Return the CrudeDisposition for a given crude in a stored scenario."""
    service = _service(request)
    scenario = _require_scenario(service, scenario_id)
    for cv in scenario.crude_valuations:
        if cv.crude_id == crude_id:
            return cv
    raise HTTPException(
        status_code=404,
        detail=f"Crude '{crude_id}' not found in scenario {scenario_id}",
    )
