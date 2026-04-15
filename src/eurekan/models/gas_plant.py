"""Gas Plant separation models (simplified).

Unsaturated Gas Plant (UGP):
  Separates FCC light ends (C1-C4) into individual components.
  Critical: accurately splits olefins (propylene, butylenes) from
  paraffins (propane, butanes). The olefin/paraffin split drives
  alkylation feed quality.

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


# UGP split fractions (approximate FCC light ends composition after
# separation). These reflect a typical olefin/paraffin split where FCC
# makes substantial propylene and butylenes.
_UGP_PROPYLENE_FRAC = 0.35    # olefin, -> alkylation feed
_UGP_PROPANE_FRAC = 0.20      # paraffin, -> LPG
_UGP_BUTYLENE_FRAC = 0.20     # olefin, -> alkylation feed
_UGP_ISOBUTANE_FRAC = 0.10    # paraffin, -> alky (iC4)
_UGP_NORMAL_BUTANE_FRAC = 0.10  # paraffin, -> LPG or blend
_UGP_FUEL_GAS_FRAC = 0.05     # C1-C2, -> fuel gas

# SGP split fractions (saturated streams - no olefins)
_SGP_PROPANE_FRAC = 0.40
_SGP_ISOBUTANE_FRAC = 0.25
_SGP_NORMAL_BUTANE_FRAC = 0.25
_SGP_FUEL_GAS_FRAC = 0.10


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
        """Split FCC light ends by component."""
        return UGPResult(
            propylene_volume=feed_rate * _UGP_PROPYLENE_FRAC,
            propane_volume=feed_rate * _UGP_PROPANE_FRAC,
            butylene_volume=feed_rate * _UGP_BUTYLENE_FRAC,
            isobutane_volume=feed_rate * _UGP_ISOBUTANE_FRAC,
            normal_butane_volume=feed_rate * _UGP_NORMAL_BUTANE_FRAC,
            fuel_gas_volume=feed_rate * _UGP_FUEL_GAS_FRAC,
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
            propane_volume=feed_rate * _SGP_PROPANE_FRAC,
            isobutane_volume=feed_rate * _SGP_ISOBUTANE_FRAC,
            normal_butane_volume=feed_rate * _SGP_NORMAL_BUTANE_FRAC,
            fuel_gas_volume=feed_rate * _SGP_FUEL_GAS_FRAC,
        )
