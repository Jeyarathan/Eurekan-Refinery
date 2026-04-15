"""C4 Isomerization model.

Converts n-butane to isobutane (feed for alkylation).

Gulf Coast: CIS4, 5K bbl/d capacity.

Key physics:
  Feed: n-butane (from CDU, FCC, or purchased)
  Product: isobutane (iC4) - alkylation feed
  Near 100% yield, equilibrium limited (~60% per pass)
  With recycle: effectively 95%+ overall conversion

This unit FEEDS the alkylation unit with iC4. Without it,
alkylation is limited by iC4 availability and must purchase
expensive iC4 externally at ~$50/bbl.
"""

from __future__ import annotations

from dataclasses import dataclass

from pydantic import BaseModel

from eurekan.core.config import UnitConfig
from eurekan.models.base import BaseUnitModel


_DEFAULT_IC4_YIELD = 0.95   # 95% with recycle
_DEFAULT_H2_SCFB = 50.0     # very low - equilibrium reaction


class C4IsomerizationResult(BaseModel):
    """Results from the C4 isomerization model."""

    ic4_volume: float           # isobutane produced (for alky feed)
    unconverted_nc4_volume: float
    hydrogen_consumption_mmscf: float


@dataclass
class C4IsomerizationCalibration:
    """Calibration overrides."""

    alpha_yield: float = 1.0


class C4IsomerizationModel(BaseUnitModel):
    """C4 isomerization - nC4 -> iC4 for alkylation feed."""

    def __init__(
        self,
        unit_config: UnitConfig,
        calibration: C4IsomerizationCalibration | None = None,
    ) -> None:
        self.capacity = unit_config.capacity
        self.calibration = calibration or C4IsomerizationCalibration()

    def calculate(  # type: ignore[override]
        self,
        feed_rate: float,
    ) -> C4IsomerizationResult:
        """Compute iC4 yield from nC4 feed."""
        cal = self.calibration

        ic4_yield = max(0.0, min(1.0, cal.alpha_yield * _DEFAULT_IC4_YIELD))
        ic4_vol = feed_rate * ic4_yield
        unconverted = feed_rate * (1.0 - ic4_yield)

        h2_mmscf = _DEFAULT_H2_SCFB * feed_rate / 1.0e6

        return C4IsomerizationResult(
            ic4_volume=ic4_vol,
            unconverted_nc4_volume=unconverted,
            hydrogen_consumption_mmscf=h2_mmscf,
        )
