"""Aromatics Reformer model.

High-severity catalytic reforming optimized for BTX (benzene, toluene,
xylene) production rather than gasoline octane. BTX is sold as a
petrochemical feedstock at $800-1200/ton.

Gulf Coast: CARU, 35K bbl/d capacity.

Key physics:
  Feed: heavy naphtha (same as mogas reformer CLPR)
  Mode: higher severity than mogas (RON 105+ equivalent)
  Products:
    BTX extract:  40-50 vol% of feed — sold as petchem
    Raffinate:    35-45 vol% — low octane remainder, to gasoline blend
                   or further processing
    Hydrogen:     4-5 wt% — higher than mogas reformer
    LPG/fuel gas: byproducts

Different from mogas reformer (ReformerModel):
  - optimizes aromatics yield, not RON
  - BTX extract is a separate product stream
  - higher hydrogen make
  - raffinate has low RON (not directly useful as gasoline)
"""

from __future__ import annotations

from dataclasses import dataclass

from pydantic import BaseModel

from eurekan.core.config import UnitConfig
from eurekan.core.crude import CutProperties
from eurekan.core.results import EquipmentStatus
from eurekan.models.base import BaseUnitModel


_DEFAULT_BTX_YIELD = 0.45       # 45 vol% BTX at typical severity
_DEFAULT_RAFFINATE_YIELD = 0.40
_DEFAULT_H2_WT_PCT = 0.045
_DEFAULT_BTX_SPG = 0.870         # mixed BTX specific gravity (~aromatics average)


class AromaticsReformerResult(BaseModel):
    """Results from the aromatics reformer model."""

    btx_volume: float              # BTX extract (petchem product), bbl/d
    btx_tons_per_day: float        # BTX in metric tons/day
    raffinate_volume: float        # low-RON raffinate, bbl/d
    hydrogen_production_mmscf: float
    lpg_production: float
    fuel_gas_production: float
    raffinate_properties: CutProperties = CutProperties()
    equipment: list[EquipmentStatus] = []


@dataclass
class AromaticsReformerCalibration:
    """Calibration overrides (default neutral)."""

    alpha_btx: float = 1.0
    alpha_h2: float = 1.0


class AromaticsReformerModel(BaseUnitModel):
    """Aromatics reformer - HN -> BTX + raffinate + H2."""

    def __init__(
        self,
        unit_config: UnitConfig,
        calibration: AromaticsReformerCalibration | None = None,
    ) -> None:
        self.capacity = unit_config.capacity
        self.equipment_limits = unit_config.equipment_limits
        self.calibration = calibration or AromaticsReformerCalibration()

    def calculate(  # type: ignore[override]
        self,
        feed_rate: float,
        feed_properties: CutProperties,
    ) -> AromaticsReformerResult:
        """Compute BTX + raffinate + H2 yields."""
        cal = self.calibration

        btx_yield = max(0.0, min(1.0, cal.alpha_btx * _DEFAULT_BTX_YIELD))
        raffinate_yield = _DEFAULT_RAFFINATE_YIELD
        h2_wt = cal.alpha_h2 * _DEFAULT_H2_WT_PCT

        btx_vol = feed_rate * btx_yield
        raffinate_vol = feed_rate * raffinate_yield

        # BTX ton/day: vol bbl * spg * 0.159 m3/bbl * 1000 kg/m3 / 1000 kg/ton
        # = vol * spg * 0.159
        btx_tons = btx_vol * _DEFAULT_BTX_SPG * 0.159

        # Remainder -> LPG + fuel gas (mass balance)
        remainder = max(0.0, 1.0 - btx_yield - raffinate_yield - h2_wt)
        lpg_vol = feed_rate * 0.6 * remainder
        fuel_gas_vol = feed_rate * 0.4 * remainder

        # Hydrogen production: wt% of feed converted to MMSCFD
        # Rough: 1 bbl naphtha ~ 42 gal ~ 280 lb. wt% * feed_lb / (scf/lb)
        # Simplified linear: h2_wt * feed_rate * 400 SCF/bbl typical factor / 1e6
        h2_mmscf = h2_wt * feed_rate * 500.0 / 1e6  # rough SCF/bbl approximation

        # Raffinate: low-RON aromatics-depleted stream (~60 RON)
        raffinate_props = CutProperties(
            api=60.0, sulfur=0.0005, ron=60.0, rvp=3.0, spg=0.72,
            aromatics=5.0, benzene=0.0, olefins=0.5,
        )

        equip = self.equipment_status(feed_rate)

        return AromaticsReformerResult(
            btx_volume=btx_vol,
            btx_tons_per_day=btx_tons,
            raffinate_volume=raffinate_vol,
            hydrogen_production_mmscf=h2_mmscf,
            lpg_production=lpg_vol,
            fuel_gas_production=fuel_gas_vol,
            raffinate_properties=raffinate_props,
            equipment=equip,
        )

    def equipment_status(self, feed_rate: float) -> list[EquipmentStatus]:
        cap_load = feed_rate / self.capacity if self.capacity > 0 else 0.0
        return [
            EquipmentStatus(
                name="reactor_throughput",
                display_name="Aromatics Reformer Throughput",
                current_value=cap_load,
                limit=1.0,
                utilization_pct=min(cap_load * 100.0, 100.0),
                is_binding=cap_load >= 0.99,
            ),
        ]
