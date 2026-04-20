"""Sulfur Recovery Unit (Modified Claus) model.

Converts H2S to elemental sulfur via the Claus reaction:
    2 H2S + SO2 -> 3 S + 2 H2O
with upstream thermal and catalytic stages.  Typical 2-stage Modified Claus
achieves ~97% sulfur recovery; the remaining 3% of inlet sulfur exits in the
tail gas and goes to the Tail Gas Treatment unit.

Gulf Coast: CSRU, 3 LT/D elemental sulfur capacity.

Mass stoichiometry: 1 LT H2S -> 32/34 = 0.941 LT S.
"""

from __future__ import annotations

from dataclasses import dataclass

from pydantic import BaseModel

from eurekan.core.config import UnitConfig
from eurekan.models.base import BaseUnitModel


_DEFAULT_CLAUS_RECOVERY = 0.97       # fraction of inlet S recovered as liquid S
_S_PER_H2S = 32.0 / 34.0             # mass ratio S/H2S (atomic)
_DEFAULT_OPEX_PER_LT = 50.0          # $ per LT sulfur produced


class SRUResult(BaseModel):
    """Results from the SRU."""

    h2s_in: float             # LT/D H2S inlet
    sulfur_produced: float    # LT/D elemental S recovered
    tail_gas_s: float         # LT/D sulfur equivalent escaping to TGT
    utilization: float


@dataclass
class SRUCalibration:
    alpha_recovery: float = 1.0


class SRUModel(BaseUnitModel):
    """Modified Claus sulfur recovery."""

    def __init__(
        self,
        unit_config: UnitConfig,
        calibration: SRUCalibration | None = None,
    ) -> None:
        self.capacity = unit_config.capacity  # LT/D sulfur output
        self.calibration = calibration or SRUCalibration()

    def calculate(  # type: ignore[override]
        self,
        h2s_feed: float = 0.0,
    ) -> SRUResult:
        """Convert H2S → elemental sulfur."""
        cal = self.calibration

        s_equivalent_in = h2s_feed * _S_PER_H2S
        recovery = max(0.0, min(1.0, cal.alpha_recovery * _DEFAULT_CLAUS_RECOVERY))
        sulfur_out = s_equivalent_in * recovery
        tail_gas_s = s_equivalent_in - sulfur_out

        util = (sulfur_out / self.capacity) if self.capacity > 0 else 0.0

        return SRUResult(
            h2s_in=h2s_feed,
            sulfur_produced=sulfur_out,
            tail_gas_s=tail_gas_s,
            utilization=min(1.0, util),
        )
