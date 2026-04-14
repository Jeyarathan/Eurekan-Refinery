"""Vacuum Distillation Unit model.

Separates atmospheric residue (or CDU vacuum residue cut) into
LVGO + HVGO + vacuum residue under reduced pressure.

Key physics:
  Feed: heavy bottoms from CDU (1050 deg F+ in atmospheric terms)
  Light VGO  (650-800 deg F):  FCC feed or GO HT feed
  Heavy VGO  (800-1050 deg F): FCC feed, HCU feed, or fuel oil
  Vacuum Residue (1050 deg F+): coker feed or fuel oil

Without a vacuum unit, this material goes to fuel oil at low value.
With it, the VGO fraction is recovered for cracking.
"""

from __future__ import annotations

from dataclasses import dataclass

from pydantic import BaseModel

from eurekan.core.config import UnitConfig
from eurekan.core.crude import CutProperties
from eurekan.models.base import BaseUnitModel


# Default split fractions (typical heavy crude vacuum tower)
_DEFAULT_LVGO_FRAC = 0.25
_DEFAULT_HVGO_FRAC = 0.25
_DEFAULT_VR_FRAC = 0.50

# Default product property defaults (used when feed has no property data)
_LVGO_API_DEFAULT = 25.0
_HVGO_API_DEFAULT = 20.0
_VR_API_DEFAULT = 8.0
_LVGO_SULFUR_DEFAULT = 1.0
_HVGO_SULFUR_DEFAULT = 2.0
_VR_SULFUR_DEFAULT = 4.0


class VacuumUnitResult(BaseModel):
    """Results from the vacuum unit model."""

    lvgo_volume: float
    hvgo_volume: float
    vac_resid_volume: float
    lvgo_properties: CutProperties = CutProperties()
    hvgo_properties: CutProperties = CutProperties()
    vac_resid_properties: CutProperties = CutProperties()


@dataclass
class VacuumUnitCalibration:
    """Optional yield calibration overrides."""

    lvgo_fraction: float = _DEFAULT_LVGO_FRAC
    hvgo_fraction: float = _DEFAULT_HVGO_FRAC


class VacuumUnitModel(BaseUnitModel):
    """Vacuum unit splitting heavy bottoms into LVGO + HVGO + vac residue."""

    def __init__(
        self,
        unit_config: UnitConfig,
        calibration: VacuumUnitCalibration | None = None,
    ) -> None:
        self.capacity = unit_config.capacity
        self.calibration = calibration or VacuumUnitCalibration()

    def calculate(  # type: ignore[override]
        self,
        feed_rate: float,
        feed_properties: CutProperties,
    ) -> VacuumUnitResult:
        """Split feed into LVGO + HVGO + vacuum residue."""
        lvgo_frac = self.calibration.lvgo_fraction
        hvgo_frac = self.calibration.hvgo_fraction
        vr_frac = max(0.0, 1.0 - lvgo_frac - hvgo_frac)

        lvgo_vol = feed_rate * lvgo_frac
        hvgo_vol = feed_rate * hvgo_frac
        vr_vol = feed_rate * vr_frac

        # Property partitioning: lighter cuts get higher API, lower sulfur
        feed_api = feed_properties.api if feed_properties.api is not None else _VR_API_DEFAULT
        feed_s = feed_properties.sulfur if feed_properties.sulfur is not None else _VR_SULFUR_DEFAULT
        feed_ccr = feed_properties.ccr if feed_properties.ccr is not None else 15.0

        # LVGO cleaner and lighter than feed; VR heavier and dirtier
        lvgo_api = max(feed_api + 12.0, _LVGO_API_DEFAULT)
        hvgo_api = max(feed_api + 6.0, _HVGO_API_DEFAULT)
        vr_api = min(feed_api - 2.0, _VR_API_DEFAULT)

        # Sulfur: VR concentrates the sulfur (mass balance: ~70% of S to VR)
        # Approximate: lvgo gets 0.4× feed_s, hvgo 0.8×, vr 1.4×
        lvgo_s = max(0.0, feed_s * 0.4)
        hvgo_s = max(0.0, feed_s * 0.8)
        vr_s = feed_s * 1.4 if vr_frac > 0 else feed_s

        # CCR concentrates almost entirely into vacuum residue
        vr_ccr = feed_ccr / vr_frac if vr_frac > 0 else feed_ccr

        return VacuumUnitResult(
            lvgo_volume=lvgo_vol,
            hvgo_volume=hvgo_vol,
            vac_resid_volume=vr_vol,
            lvgo_properties=CutProperties(api=lvgo_api, sulfur=lvgo_s),
            hvgo_properties=CutProperties(api=hvgo_api, sulfur=hvgo_s),
            vac_resid_properties=CutProperties(
                api=vr_api,
                sulfur=vr_s,
                ccr=vr_ccr,
                nickel=feed_properties.nickel,
                vanadium=feed_properties.vanadium,
            ),
        )
