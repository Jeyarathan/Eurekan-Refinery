"""Pydantic request/response schemas for the API layer.

These wrap the core domain types so the routes accept clean JSON payloads
without exposing internal optimizer plumbing.
"""

from __future__ import annotations

from typing import Optional

from pydantic import BaseModel, Field

from eurekan.core.enums import OperatingMode
from eurekan.core.period import PeriodData


class OptimizeRequest(BaseModel):
    """Full optimize request — accepts a list of periods and a mode."""

    periods: list[PeriodData]
    mode: OperatingMode = OperatingMode.OPTIMIZE
    fixed_variables: dict[str, float] = Field(default_factory=dict)
    scenario_name: str = "Untitled"
    parent_scenario_id: Optional[str] = None


class QuickOptimizeRequest(BaseModel):
    """Single-period optimize with optional price overrides."""

    crude_prices: Optional[dict[str, float]] = None
    product_prices: Optional[dict[str, float]] = None
    scenario_name: str = "Quick Plan"


class PriceUpdateRequest(BaseModel):
    """Body for the PUT price-edit endpoints."""

    price: float


class BranchScenarioRequest(BaseModel):
    """Body for POST /api/scenarios/{id}/branch."""

    name: str
    changes: dict = Field(default_factory=dict)


class OracleRequest(BaseModel):
    """Body for POST /api/oracle."""

    actual_decisions: dict[str, float]
