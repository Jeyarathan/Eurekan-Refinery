"""Amine Unit model.

Scrubs H2S from sour refinery gas streams using a regenerable amine solvent
(typically MDEA).  The lean amine absorbs H2S in the contactor; the rich amine
is regenerated in a stripper, releasing a concentrated H2S stream that feeds
the Sulfur Recovery Unit (SRU).

Gulf Coast: CAMN, 3 LT/D H2S capacity (long tons per day).

Inputs:
  hts_h2s:   H2S-equivalent volume removed by all hydrotreaters (LT/D)
  fcc_h2s:   H2S-equivalent volume released by the FCC (LT/D)
  coker_h2s: H2S-equivalent volume released by the coker (LT/D)

Output:
  concentrated H2S stream to SRU (LT/D), near-lossless recovery (~99.5%).
"""

from __future__ import annotations

from dataclasses import dataclass

from pydantic import BaseModel

from eurekan.core.config import UnitConfig
from eurekan.models.base import BaseUnitModel


_DEFAULT_H2S_REMOVAL_EFF = 0.995  # fraction of inlet H2S captured
_DEFAULT_OPEX_PER_LT = 25.0       # $ per LT H2S processed (steam + circulation)


class AmineResult(BaseModel):
    """Results from the amine unit."""

    h2s_in: float          # LT/D total inlet H2S
    h2s_to_sru: float      # LT/D concentrated H2S sent to SRU
    h2s_slip: float        # LT/D residual H2S escaping to fuel gas
    utilization: float     # 0-1 fraction of nameplate capacity


@dataclass
class AmineCalibration:
    """Calibration overrides."""

    alpha_removal: float = 1.0  # scales removal efficiency


class AmineModel(BaseUnitModel):
    """Amine contactor + stripper — concentrates H2S for SRU feed."""

    def __init__(
        self,
        unit_config: UnitConfig,
        calibration: AmineCalibration | None = None,
    ) -> None:
        self.capacity = unit_config.capacity  # LT/D
        self.calibration = calibration or AmineCalibration()

    def calculate(  # type: ignore[override]
        self,
        hts_h2s: float = 0.0,
        fcc_h2s: float = 0.0,
        coker_h2s: float = 0.0,
    ) -> AmineResult:
        """Concentrate H2S from sour gas streams."""
        cal = self.calibration
        total_in = hts_h2s + fcc_h2s + coker_h2s

        eff = max(0.0, min(1.0, cal.alpha_removal * _DEFAULT_H2S_REMOVAL_EFF))
        to_sru = total_in * eff
        slip = total_in - to_sru

        util = (to_sru / self.capacity) if self.capacity > 0 else 0.0

        return AmineResult(
            h2s_in=total_in,
            h2s_to_sru=to_sru,
            h2s_slip=slip,
            utilization=min(1.0, util),
        )
