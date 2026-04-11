"""Oracle gap analysis endpoint — Sprint 5 Task 5.5."""

from __future__ import annotations

from fastapi import APIRouter, Request

from eurekan.api.schemas import OracleRequest
from eurekan.api.services import RefineryService
from eurekan.core.results import OracleResult

router = APIRouter(prefix="/api", tags=["oracle"])


def _service(request: Request) -> RefineryService:
    return request.app.state.service


@router.post("/oracle", response_model=OracleResult)
def run_oracle(request: Request, body: OracleRequest) -> OracleResult:
    """Compare actual decisions to the optimum, decompose the gap."""
    return _service(request).run_oracle(body.actual_decisions)
