"""Dimersol model.

Dimerizes propylene into C6 gasoline-range olefins (dimate).
Alternative use for propylene vs alkylation:
  - Alkylation: propylene + iC4 -> alkylate (RON 94, sulfur-free)
  - Dimersol:   propylene      -> dimate (RON 95-97, higher olefins)

Dimersol doesn't need iC4 (unlike alkylation), but product has higher
olefin content which counts against gasoline olefin spec.

Gulf Coast: CDIM, 6K bbl/d capacity.

Small unit, niche value. Optimizer decides propylene routing based on
relative alkylate vs dimate economics.
"""

from __future__ import annotations

from dataclasses import dataclass

from pydantic import BaseModel

from eurekan.core.config import UnitConfig
from eurekan.core.crude import CutProperties
from eurekan.models.base import BaseUnitModel


_DEFAULT_DIMATE_YIELD = 0.90     # 90 vol% (propylene -> dimate, some loss)
_DEFAULT_DIMATE_RON = 96.0


class DimersolResult(BaseModel):
    """Results from the dimersol model."""

    dimate_volume: float
    dimate_ron: float
    dimate_properties: CutProperties = CutProperties()


@dataclass
class DimersolCalibration:
    """Calibration overrides."""

    alpha_yield: float = 1.0
    delta_ron: float = 0.0


class DimersolModel(BaseUnitModel):
    """Dimersol - propylene -> dimate (gasoline blend component)."""

    def __init__(
        self,
        unit_config: UnitConfig,
        calibration: DimersolCalibration | None = None,
    ) -> None:
        self.capacity = unit_config.capacity
        self.calibration = calibration or DimersolCalibration()

    def calculate(  # type: ignore[override]
        self,
        feed_rate: float,
    ) -> DimersolResult:
        """Compute dimate yield from propylene feed."""
        cal = self.calibration

        dimate_yield = max(0.0, min(1.0, cal.alpha_yield * _DEFAULT_DIMATE_YIELD))
        dimate_vol = feed_rate * dimate_yield
        dimate_ron = _DEFAULT_DIMATE_RON + cal.delta_ron

        # Dimate properties: high RON, high olefins, low sulfur
        dimate_props = CutProperties(
            api=58.0,
            sulfur=0.0001,
            ron=dimate_ron,
            rvp=3.0,
            spg=0.72,
            aromatics=1.0,
            benzene=0.0,
            olefins=80.0,  # HIGH olefins (C6 alkenes)
        )

        return DimersolResult(
            dimate_volume=dimate_vol,
            dimate_ron=dimate_ron,
            dimate_properties=dimate_props,
        )
