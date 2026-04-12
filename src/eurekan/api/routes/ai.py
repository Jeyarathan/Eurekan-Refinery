"""AI narrative and alternatives endpoints — Sprint 8."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, HTTPException, Request

from eurekan.ai.narrative import generate_narrative
from eurekan.analysis.alternatives import enumerate_near_optimal
from eurekan.api.services import RefineryService
from eurekan.core.period import PlanDefinition, PeriodData
from eurekan.core.enums import OperatingMode
from eurekan.core.results import SolutionNarrative

router = APIRouter(prefix="/api/ai", tags=["ai"])


def _service(request: Request) -> RefineryService:
    return request.app.state.service


@router.post("/narrative", response_model=SolutionNarrative)
def narrative(request: Request, body: dict[str, Any]) -> SolutionNarrative:
    """Generate a deterministic narrative for a stored scenario."""
    scenario_id = body.get("scenario_id")
    if not scenario_id:
        raise HTTPException(status_code=400, detail="scenario_id required")
    service = _service(request)
    scenario = service.get_scenario(scenario_id)
    if scenario is None:
        raise HTTPException(status_code=404, detail=f"Scenario not found: {scenario_id}")
    return generate_narrative(scenario, service.config)


@router.post("/alternatives")
def alternatives(request: Request, body: dict[str, Any]) -> list[dict[str, Any]]:
    """Enumerate near-optimal plans for a stored scenario."""
    scenario_id = body.get("scenario_id")
    tolerance = body.get("tolerance", 0.02)
    if not scenario_id:
        raise HTTPException(status_code=400, detail="scenario_id required")
    service = _service(request)
    scenario = service.get_scenario(scenario_id)
    if scenario is None:
        raise HTTPException(status_code=404, detail=f"Scenario not found: {scenario_id}")

    plan = PlanDefinition(
        periods=[PeriodData(
            period_id=0, duration_hours=24.0,
            product_prices={"gasoline": 95, "diesel": 100, "jet": 100,
                            "naphtha": 60, "fuel_oil": 55, "lpg": 50},
        )],
        mode=OperatingMode.OPTIMIZE,
        scenario_name="Alternatives base",
    )
    plans = enumerate_near_optimal(service.config, plan, scenario, tolerance)
    return [
        {
            "name": p["name"],
            "margin": p["result"].total_margin,
            "scenario_id": p["result"].scenario_id,
            "comparison": p["comparison"].model_dump() if p["comparison"] else None,
        }
        for p in plans
    ]
