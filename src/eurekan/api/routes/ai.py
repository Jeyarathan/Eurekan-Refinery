"""AI narrative and alternatives endpoints — Sprint 8."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, HTTPException, Request

from eurekan.ai.narrative import generate_narrative
from eurekan.analysis.alternatives import enumerate_near_optimal
from eurekan.api.services import RefineryService
from eurekan.core.enums import OperatingMode
from eurekan.core.period import PeriodData, PlanDefinition
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

    # Build the plan definition that matches the service's default pricing
    crude_prices = {
        cid: max((service.config.crude_library.get(cid).price or 70.0) - 10.0, 55.0)
        for cid in service.config.crude_library
    }
    plan = PlanDefinition(
        periods=[PeriodData(
            period_id=0, duration_hours=24.0,
            crude_prices=crude_prices,
            product_prices={"gasoline": 95, "diesel": 100, "jet": 100,
                            "naphtha": 60, "fuel_oil": 55, "lpg": 50},
        )],
        mode=OperatingMode.OPTIMIZE,
        scenario_name="Alternatives base",
    )
    alts = enumerate_near_optimal(
        service.config, plan, scenario, tolerance, max_alternatives=10,
    )
    return [
        {
            "name": a.name,
            "description": a.description,
            "axis": a.axis,
            "margin": a.result.total_margin,
            "margin_pct": (
                a.result.total_margin / scenario.total_margin * 100
                if scenario.total_margin > 0
                else 0
            ),
            "scenario_id": a.result.scenario_id,
            "comparison": a.comparison.model_dump() if a.comparison else None,
        }
        for a in alts
    ]
