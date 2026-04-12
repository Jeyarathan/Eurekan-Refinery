"""GO Hydrotreater — treats VGO before FCC to remove sulfur/nitrogen/metals.

Improves FCC feed quality: lower sulfur → less SOx, lower metals → longer
catalyst life, higher API → better gasoline yield.
"""

from __future__ import annotations

from dataclasses import dataclass

from eurekan.core.config import UnitConfig
from eurekan.core.crude import CutProperties
from eurekan.core.results import EquipmentStatus
from eurekan.models.base import BaseUnitModel
from pydantic import BaseModel


class GOHTResult(BaseModel):
    product_volume: float
    product_sulfur: float
    product_nitrogen: float
    product_metals: float
    h2_consumed: float
    equipment: list[EquipmentStatus] = []


@dataclass
class GOHTCalibration:
    sulfur_removal: float = 0.90
    nitrogen_removal: float = 0.60
    metals_removal: float = 0.70
    h2_scfb: float = 1000.0


class GOHydrotreaterModel(BaseUnitModel):
    def __init__(self, unit_config: UnitConfig, calibration: GOHTCalibration | None = None) -> None:
        self.capacity = unit_config.capacity
        self.calibration = calibration or GOHTCalibration()

    def calculate(self, feed_properties: CutProperties, feed_rate: float) -> GOHTResult:  # type: ignore[override]
        cal = self.calibration
        feed_s = feed_properties.sulfur or 1.5
        feed_n = feed_properties.nitrogen or 0.1
        feed_metals = feed_properties.metals

        product_volume = feed_rate * 0.995  # ~0.5% volume loss
        product_sulfur = feed_s * (1.0 - cal.sulfur_removal)
        product_nitrogen = feed_n * (1.0 - cal.nitrogen_removal)
        product_metals = feed_metals * (1.0 - cal.metals_removal)
        h2_consumed = feed_rate * cal.h2_scfb / 1e6  # MMSCFD

        return GOHTResult(
            product_volume=product_volume,
            product_sulfur=product_sulfur,
            product_nitrogen=product_nitrogen,
            product_metals=product_metals,
            h2_consumed=h2_consumed,
        )
