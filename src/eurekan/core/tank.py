"""Tank model — storage with capacity constraints."""

from __future__ import annotations

from pydantic import BaseModel, field_validator

from eurekan.core.enums import TankType


class Tank(BaseModel):
    """A storage tank with capacity limits and stream connections."""

    tank_id: str
    tank_type: TankType
    capacity: float
    minimum: float = 0.0
    current_level: float = 0.0
    connected_streams: list[str] = []

    @field_validator("capacity")
    @classmethod
    def _capacity_must_be_positive(cls, v: float) -> float:
        if v <= 0:
            raise ValueError("capacity must be > 0")
        return v
