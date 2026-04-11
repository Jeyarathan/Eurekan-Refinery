"""Optimization endpoints — Sprint 5 Task 5.3."""

from __future__ import annotations

from fastapi import APIRouter, Request

from eurekan.api.schemas import OptimizeRequest, QuickOptimizeRequest
from eurekan.api.services import RefineryService
from eurekan.core.results import PlanningResult

router = APIRouter(prefix="/api", tags=["optimization"])


def _service(request: Request) -> RefineryService:
    return request.app.state.service


@router.post("/optimize", response_model=PlanningResult)
def optimize(request: Request, body: OptimizeRequest) -> PlanningResult:
    """Run a full optimization with explicit periods and mode."""
    return _service(request).optimize(
        periods=body.periods,
        mode=body.mode,
        fixed_variables=body.fixed_variables,
        scenario_name=body.scenario_name,
        parent_scenario_id=body.parent_scenario_id,
    )


@router.post("/optimize/quick", response_model=PlanningResult)
def quick_optimize(
    request: Request, body: QuickOptimizeRequest | None = None
) -> PlanningResult:
    """Single-period optimization with optional price overrides."""
    payload = body or QuickOptimizeRequest()
    return _service(request).quick_optimize(
        crude_prices=payload.crude_prices,
        product_prices=payload.product_prices,
        scenario_name=payload.scenario_name,
    )
