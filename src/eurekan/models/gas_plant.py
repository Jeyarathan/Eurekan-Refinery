"""Gas Plant separation models (simplified).

Unsaturated Gas Plant (UGP):
  Separates FCC light ends (C1-C4) into individual components.
  Critical: accurately splits olefins (propylene, butylenes) from
  paraffins (propane, butanes). The olefin/paraffin split drives
  alkylation feed quality.

  Split fractions (per user spec, Sprint 16):
    C3 stream (45% of feed): 65% propylene + 35% propane
    C4 stream (45% of feed): 50% butylenes + 30% iC4 + 20% nC4
    Fuel gas (10% of feed): C1+C2 → plant fuel

Saturated Gas Plant (SGP):
  Separates CDU + coker + HCU light ends (no olefins).
  Products: fuel gas (C1-C2), propane, iC4, nC4.

Both modeled as split-fraction separations (not rigorous).
"""

from __future__ import annotations

from dataclasses import dataclass

from pydantic import BaseModel

from eurekan.core.config import UnitConfig
from eurekan.models.base import BaseUnitModel


# ---------------------------------------------------------------------------
# Unsaturated Gas Plant (UGP) — splits FCC C3/C4 pool
# ---------------------------------------------------------------------------
# Overall feed composition: 45% C3 pool + 45% C4 pool + 10% fuel gas (C1+C2)
_UGP_C3_POOL_FRAC = 0.45
_UGP_C4_POOL_FRAC = 0.45
_UGP_FUEL_GAS_FRAC = 0.10

# Within the C3 sub-pool
_UGP_C3_PROPYLENE_FRAC = 0.65   # olefin → alkylation / dimersol feed
_UGP_C3_PROPANE_FRAC = 0.35     # paraffin → LPG

# Within the C4 sub-pool
_UGP_C4_BUTYLENE_FRAC = 0.50    # olefin → alkylation feed
_UGP_C4_ISOBUTANE_FRAC = 0.30   # paraffin → alkylation (iC4) feed
_UGP_C4_NORMAL_BUTANE_FRAC = 0.20  # paraffin → C4 isom feed or LPG

# Pre-computed UGP fractions on total feed
UGP_PROPYLENE_FRAC = _UGP_C3_POOL_FRAC * _UGP_C3_PROPYLENE_FRAC      # 0.2925
UGP_PROPANE_FRAC = _UGP_C3_POOL_FRAC * _UGP_C3_PROPANE_FRAC          # 0.1575
UGP_BUTYLENE_FRAC = _UGP_C4_POOL_FRAC * _UGP_C4_BUTYLENE_FRAC        # 0.2250
UGP_ISOBUTANE_FRAC = _UGP_C4_POOL_FRAC * _UGP_C4_ISOBUTANE_FRAC      # 0.1350
UGP_NORMAL_BUTANE_FRAC = _UGP_C4_POOL_FRAC * _UGP_C4_NORMAL_BUTANE_FRAC  # 0.0900
UGP_FUEL_GAS_FRAC = _UGP_FUEL_GAS_FRAC                                # 0.1000
# Sum: 0.2925 + 0.1575 + 0.2250 + 0.1350 + 0.0900 + 0.1000 = 1.0

# ---------------------------------------------------------------------------
# Saturated Gas Plant (SGP) — splits CDU/coker/HCU paraffin streams
# ---------------------------------------------------------------------------
SGP_PROPANE_FRAC = 0.40
SGP_ISOBUTANE_FRAC = 0.25
SGP_NORMAL_BUTANE_FRAC = 0.25
SGP_FUEL_GAS_FRAC = 0.10
# Sum: 1.00


class UGPResult(BaseModel):
    """Results from the Unsaturated Gas Plant."""

    propylene_volume: float
    propane_volume: float
    butylene_volume: float
    isobutane_volume: float
    normal_butane_volume: float
    fuel_gas_volume: float


class SGPResult(BaseModel):
    """Results from the Saturated Gas Plant."""

    propane_volume: float
    isobutane_volume: float
    normal_butane_volume: float
    fuel_gas_volume: float


@dataclass
class GasPlantCalibration:
    """Optional calibration overrides."""

    alpha: float = 1.0


class UnsaturatedGasPlant(BaseUnitModel):
    """FCC light ends separation - olefins + paraffins."""

    def __init__(
        self,
        unit_config: UnitConfig,
        calibration: GasPlantCalibration | None = None,
    ) -> None:
        self.capacity = unit_config.capacity
        self.calibration = calibration or GasPlantCalibration()

    def calculate(  # type: ignore[override]
        self,
        feed_rate: float,
    ) -> UGPResult:
        """Split FCC C3/C4 pool + fuel gas into individual components."""
        return UGPResult(
            propylene_volume=feed_rate * UGP_PROPYLENE_FRAC,
            propane_volume=feed_rate * UGP_PROPANE_FRAC,
            butylene_volume=feed_rate * UGP_BUTYLENE_FRAC,
            isobutane_volume=feed_rate * UGP_ISOBUTANE_FRAC,
            normal_butane_volume=feed_rate * UGP_NORMAL_BUTANE_FRAC,
            fuel_gas_volume=feed_rate * UGP_FUEL_GAS_FRAC,
        )


class SaturatedGasPlant(BaseUnitModel):
    """CDU/coker/HCU light ends separation - no olefins."""

    def __init__(
        self,
        unit_config: UnitConfig,
        calibration: GasPlantCalibration | None = None,
    ) -> None:
        self.capacity = unit_config.capacity
        self.calibration = calibration or GasPlantCalibration()

    def calculate(  # type: ignore[override]
        self,
        feed_rate: float,
    ) -> SGPResult:
        """Split CDU/coker/HCU light ends into paraffin species."""
        return SGPResult(
            propane_volume=feed_rate * SGP_PROPANE_FRAC,
            isobutane_volume=feed_rate * SGP_ISOBUTANE_FRAC,
            normal_butane_volume=feed_rate * SGP_NORMAL_BUTANE_FRAC,
            fuel_gas_volume=feed_rate * SGP_FUEL_GAS_FRAC,
        )
