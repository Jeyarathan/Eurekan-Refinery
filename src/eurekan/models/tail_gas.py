"""Tail Gas Treatment (TGT) model.

Polishes the SRU tail gas to meet stack-emission limits.  A SCOT-type unit
hydrogenates residual SOx/SO2 back to H2S, absorbs it in a lean amine, and
recycles the concentrated H2S to the SRU front end.  Net effect: ~90% of the
sulfur slipping past the SRU is captured and eventually converted to S.

Gulf Coast: CTGT, 0.2 LT/D residual sulfur capacity.
"""

from __future__ import annotations

from dataclasses import dataclass

from pydantic import BaseModel

from eurekan.core.config import UnitConfig
from eurekan.models.base import BaseUnitModel


_DEFAULT_TGT_RECOVERY = 0.90      # fraction of tail-gas S captured and recycled
_DEFAULT_OPEX_PER_LT = 80.0       # $ per LT S treated (higher than SRU)


class TailGasResult(BaseModel):
    """Results from the Tail Gas Treatment unit."""

    s_in: float               # LT/D sulfur equivalent feed
    s_recovered: float        # LT/D additional sulfur captured (recycled to SRU)
    s_to_stack: float         # LT/D sulfur emitted to atmosphere
    utilization: float


@dataclass
class TailGasCalibration:
    alpha_recovery: float = 1.0


class TailGasModel(BaseUnitModel):
    """SCOT-type tail gas treatment."""

    def __init__(
        self,
        unit_config: UnitConfig,
        calibration: TailGasCalibration | None = None,
    ) -> None:
        self.capacity = unit_config.capacity  # LT/D residual S
        self.calibration = calibration or TailGasCalibration()

    def calculate(  # type: ignore[override]
        self,
        tail_gas_s: float = 0.0,
    ) -> TailGasResult:
        """Recover residual sulfur from SRU tail gas."""
        cal = self.calibration
        recovery = max(0.0, min(1.0, cal.alpha_recovery * _DEFAULT_TGT_RECOVERY))
        recovered = tail_gas_s * recovery
        to_stack = tail_gas_s - recovered

        util = (tail_gas_s / self.capacity) if self.capacity > 0 else 0.0

        return TailGasResult(
            s_in=tail_gas_s,
            s_recovered=recovered,
            s_to_stack=to_stack,
            utilization=min(1.0, util),
        )
