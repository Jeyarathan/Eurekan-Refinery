"""Delayed Coker model.

Thermally cracks vacuum residue into lighter products.

Key physics:
  Feed: vacuum residue (heaviest, cheapest material)
  Products:
    Coker Naphtha (C5-350F):    low octane, "dirty" - high olefins/N/S, needs HT
    Coker Gas Oil (350-650F):   high sulfur - HCU or FCC feed via HT
    Coker Heavy Gas Oil (650F+): FCC or HCU feed
    C1-C4 gas:                   fuel gas + LPG
    Petroleum Coke:              solid fuel, sold separately

Yield correlations (feed-quality dependent, all volume fractions):
  naphtha = 0.12 + 0.002 * (api - 5)
  gas_oil = 0.25 + 0.003 * (api - 5)
  coke    = 0.25 - 0.004 * (api - 5) + 0.015 * ccr
  gas     = 0.10 + 0.001 * (api - 5)
  hgo     = remainder (mass balance)

Coke yield typically 20-35% of feed; sold at ~$30/ton.
"""

from __future__ import annotations

from dataclasses import dataclass

from pydantic import BaseModel

from eurekan.core.config import UnitConfig
from eurekan.core.crude import CutProperties
from eurekan.models.base import BaseUnitModel


# Density: 1 bbl petroleum coke ~ 0.157 metric tons (specific gravity ~1.00,
# but typical bulk density gives this conversion).
_BBL_TO_TON_COKE = 0.157


class CokerResult(BaseModel):
    """Results from the delayed coker model."""

    coker_naphtha_volume: float
    coker_gas_oil_volume: float
    coker_hgo_volume: float
    gas_volume: float
    coke_volume: float
    coke_tons_per_day: float
    coker_naphtha_properties: CutProperties = CutProperties()
    coker_gas_oil_properties: CutProperties = CutProperties()
    coker_hgo_properties: CutProperties = CutProperties()


@dataclass
class CokerCalibration:
    """Calibration overrides for coker yields."""

    alpha_naphtha: float = 1.0
    alpha_gas_oil: float = 1.0
    alpha_coke: float = 1.0
    alpha_gas: float = 1.0


class CokerModel(BaseUnitModel):
    """Delayed coker - upgrades vacuum residue to lighter cracked products."""

    def __init__(
        self,
        unit_config: UnitConfig,
        calibration: CokerCalibration | None = None,
    ) -> None:
        self.capacity = unit_config.capacity
        self.calibration = calibration or CokerCalibration()

    def calculate(  # type: ignore[override]
        self,
        feed_rate: float,
        feed_properties: CutProperties,
    ) -> CokerResult:
        """Compute coker product yields from feed quality."""
        cal = self.calibration

        api = feed_properties.api if feed_properties.api is not None else 8.0
        ccr = feed_properties.ccr if feed_properties.ccr is not None else 15.0
        sulfur = feed_properties.sulfur if feed_properties.sulfur is not None else 4.0

        api_term = api - 5.0

        naphtha_frac = max(0.0, cal.alpha_naphtha * (0.12 + 0.002 * api_term))
        gas_oil_frac = max(0.0, cal.alpha_gas_oil * (0.25 + 0.003 * api_term))
        coke_frac = max(0.0, cal.alpha_coke * (0.25 - 0.004 * api_term + 0.015 * ccr))
        gas_frac = max(0.0, cal.alpha_gas * (0.10 + 0.001 * api_term))

        # HGO from mass balance
        hgo_frac = max(0.0, 1.0 - naphtha_frac - gas_oil_frac - coke_frac - gas_frac)

        naphtha_vol = feed_rate * naphtha_frac
        gas_oil_vol = feed_rate * gas_oil_frac
        coke_vol = feed_rate * coke_frac
        gas_vol = feed_rate * gas_frac
        hgo_vol = feed_rate * hgo_frac

        coke_tons = coke_vol * _BBL_TO_TON_COKE

        # Product property estimates (typical coker streams)
        # Coker naphtha: dirty, olefinic
        coker_naphtha_props = CutProperties(
            api=55.0,
            sulfur=max(0.05, sulfur * 0.05),
            nitrogen=200.0,
            olefins=35.0,
            ron=70.0,
        )
        # Coker gas oil: high sulfur, needs HT
        coker_go_props = CutProperties(
            api=28.0,
            sulfur=max(0.5, sulfur * 0.5),
            nitrogen=1500.0,
        )
        # Coker HGO: heavier, dirtier
        coker_hgo_props = CutProperties(
            api=18.0,
            sulfur=max(1.0, sulfur * 0.7),
            nitrogen=2500.0,
            ccr=2.0,
        )

        return CokerResult(
            coker_naphtha_volume=naphtha_vol,
            coker_gas_oil_volume=gas_oil_vol,
            coker_hgo_volume=hgo_vol,
            gas_volume=gas_vol,
            coke_volume=coke_vol,
            coke_tons_per_day=coke_tons,
            coker_naphtha_properties=coker_naphtha_props,
            coker_gas_oil_properties=coker_go_props,
            coker_hgo_properties=coker_hgo_props,
        )
