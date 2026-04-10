"""Planning period and scenario definitions."""

from __future__ import annotations

import uuid
from typing import Optional

from pydantic import BaseModel, Field

from eurekan.core.enums import OperatingMode


class PeriodData(BaseModel):
    """Data for a single planning period."""

    period_id: int
    duration_hours: float
    crude_prices: dict[str, float] = {}
    product_prices: dict[str, float] = {}
    crude_availability: dict[str, tuple[float, float]] = {}
    unit_status: dict[str, str] = {}
    demand_min: dict[str, float] = {}
    demand_max: dict[str, float] = {}
    initial_inventory: dict[str, float] = {}


class PlanDefinition(BaseModel):
    """A complete plan definition with periods, mode, and scenario metadata."""

    periods: list[PeriodData]
    mode: OperatingMode
    fixed_variables: dict[str, float] = {}
    scenario_id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    scenario_name: str
    parent_scenario_id: Optional[str] = None
    description: Optional[str] = None
