"""Hydrocracker model.

Catalytic cracking under high hydrogen pressure produces high-quality
middle distillates (jet + diesel). Alternative to FCC for VGO upgrading:
FCC maximizes gasoline (poor diesel quality), HCU maximizes jet+diesel
with excellent product quality (jet meets specs without HT, diesel
cetane 55+).

Gulf Coast: CHCU, 20K bbl/d capacity.

Yield model (continuous in conversion, 60-95%):
  unconverted = (100 - conversion) / 100
  Within the converted fraction, selectivity shifts toward naphtha + LPG
  at higher conversion (secondary cracking). At lower conversion,
  middle-distillate (jet + diesel) selectivity is highest.

  naphtha_share  = 0.25 + 0.002 * (conv - 80)    [light products go up]
  jet_share      = 0.32 - 0.001 * (conv - 80)
  diesel_share   = 0.35 - 0.0005 * (conv - 80)
  lpg_share      = 0.08 - 0.0005 * (conv - 80)

  yield_X = share_X * (conv / 100)

Hydrogen consumption: 1500 + 30 * (conv - 60) SCFB (1500-2550 range).
Highest H2 consumer in the refinery.
"""

from __future__ import annotations

from dataclasses import dataclass

from pydantic import BaseModel

from eurekan.core.config import UnitConfig
from eurekan.core.crude import CutProperties
from eurekan.core.results import EquipmentStatus
from eurekan.models.base import BaseUnitModel


_DEFAULT_CONVERSION = 80.0
_MIN_CONVERSION = 60.0
_MAX_CONVERSION = 95.0


class HydrocrackerResult(BaseModel):
    """Results from the hydrocracker model."""

    conversion: float
    naphtha_volume: float
    jet_volume: float
    diesel_volume: float
    lpg_volume: float
    unconverted_volume: float
    hydrogen_consumption_mmscf: float
    naphtha_properties: CutProperties = CutProperties()
    jet_properties: CutProperties = CutProperties()
    diesel_properties: CutProperties = CutProperties()
    equipment: list[EquipmentStatus] = []


@dataclass
class HydrocrackerCalibration:
    """Optional yield calibration overrides (default neutral)."""

    alpha_naphtha: float = 1.0
    alpha_jet: float = 1.0
    alpha_diesel: float = 1.0
    alpha_lpg: float = 1.0


def _shares(conv: float) -> tuple[float, float, float, float]:
    """Selectivity shares of converted material (sum to 1.0)."""
    delta = conv - 80.0
    naphtha = 0.25 + 0.002 * delta
    jet = 0.32 - 0.001 * delta
    diesel = 0.35 - 0.0005 * delta
    lpg = 0.08 - 0.0005 * delta
    return naphtha, jet, diesel, lpg


def _h2_scfb(conv: float) -> float:
    """SCFB hydrogen demand (1500 at 60% conv -> 2550 at 95%)."""
    return 1500.0 + 30.0 * (conv - 60.0)


class HydrocrackerModel(BaseUnitModel):
    """Hydrocracker - VGO/coker GO -> high-quality jet + diesel + naphtha."""

    def __init__(
        self,
        unit_config: UnitConfig,
        calibration: HydrocrackerCalibration | None = None,
    ) -> None:
        self.capacity = unit_config.capacity
        self.equipment_limits = unit_config.equipment_limits
        self.calibration = calibration or HydrocrackerCalibration()

    def calculate(  # type: ignore[override]
        self,
        feed_rate: float,
        feed_properties: CutProperties,
        conversion: float = _DEFAULT_CONVERSION,
    ) -> HydrocrackerResult:
        """Compute hydrocracker yields at a given conversion level."""
        cal = self.calibration
        conv = max(_MIN_CONVERSION, min(_MAX_CONVERSION, conversion))

        n_share, j_share, d_share, l_share = _shares(conv)
        conv_frac = conv / 100.0

        naphtha_yield = max(0.0, cal.alpha_naphtha * n_share * conv_frac)
        jet_yield = max(0.0, cal.alpha_jet * j_share * conv_frac)
        diesel_yield = max(0.0, cal.alpha_diesel * d_share * conv_frac)
        lpg_yield = max(0.0, cal.alpha_lpg * l_share * conv_frac)
        unconv_yield = max(0.0, 1.0 - conv_frac)

        naphtha_vol = feed_rate * naphtha_yield
        jet_vol = feed_rate * jet_yield
        diesel_vol = feed_rate * diesel_yield
        lpg_vol = feed_rate * lpg_yield
        unconv_vol = feed_rate * unconv_yield

        # Hydrogen demand in MMSCFD = SCFB * bbl/d / 1e6
        h2_mmscf = _h2_scfb(conv) * feed_rate / 1.0e6

        # Product properties - HCU products are exceptionally clean
        # HCU naphtha: needs reforming for octane but very low S/N
        naphtha_props = CutProperties(
            api=60.0, sulfur=0.0005, nitrogen=1.0, ron=70.0,
            aromatics=8.0, olefins=0.5, benzene=0.3,
        )
        # HCU jet: meets all specs without further hydrotreating
        jet_props = CutProperties(
            api=42.0, sulfur=0.0005, nitrogen=1.0,
            aromatics=12.0, flash_point=120.0,
        )
        # HCU diesel: cetane 55+ (vs FCC LCO at ~20)
        diesel_props = CutProperties(
            api=38.0, sulfur=0.0005, cetane=55.0, nitrogen=1.0,
            aromatics=15.0, cloud_point=-10.0,
        )

        equip = self.equipment_status(feed_rate, conv)

        return HydrocrackerResult(
            conversion=conv,
            naphtha_volume=naphtha_vol,
            jet_volume=jet_vol,
            diesel_volume=diesel_vol,
            lpg_volume=lpg_vol,
            unconverted_volume=unconv_vol,
            hydrogen_consumption_mmscf=h2_mmscf,
            naphtha_properties=naphtha_props,
            jet_properties=jet_props,
            diesel_properties=diesel_props,
            equipment=equip,
        )

    def equipment_status(
        self, feed_rate: float, conversion: float
    ) -> list[EquipmentStatus]:
        """Reactor capacity and recycle compressor."""
        cap_load = feed_rate / self.capacity if self.capacity > 0 else 0.0
        # Recycle compressor scales with feed and severity
        compressor_load = cap_load * (1.0 + 0.005 * (conversion - 80.0))
        return [
            EquipmentStatus(
                name="reactor_capacity",
                display_name="HCU Reactor Throughput",
                current_value=cap_load,
                limit=1.0,
                utilization_pct=min(cap_load * 100.0, 100.0),
                is_binding=cap_load >= 0.99,
            ),
            EquipmentStatus(
                name="recycle_compressor",
                display_name="HCU Recycle Compressor",
                current_value=compressor_load,
                limit=1.0,
                utilization_pct=min(compressor_load * 100.0, 100.0),
                is_binding=compressor_load >= 0.99,
            ),
        ]
