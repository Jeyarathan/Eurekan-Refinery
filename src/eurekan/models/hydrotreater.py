"""Generic hydrotreater — one model class, multiple configurations.

Three standard configs:
  NAPHTHA_HT: reformer protection, 99.9% desulf, <1 ppm out
  KERO_HT:    jet fuel quality, 99% desulf
  DIESEL_HT:  ULSD spec, 99.5% desulf, +3 cetane improvement
"""

from __future__ import annotations

from dataclasses import dataclass

from eurekan.core.crude import CutProperties
from eurekan.core.results import EquipmentStatus
from eurekan.models.base import BaseUnitModel
from pydantic import BaseModel


class HydrotreaterResult(BaseModel):
    product_volume: float
    product_sulfur: float
    product_cetane: float
    h2_consumed: float  # MMSCFD
    equipment: list[EquipmentStatus] = []


@dataclass
class HydrotreaterConfig:
    unit_id: str
    capacity: float
    desulf_efficiency: float  # 0-1
    cetane_improvement: float  # delta cetane
    volume_yield: float  # 0-1
    h2_scfb: float  # SCF per barrel feed
    opex_per_bbl: float


class HydrotreaterModel(BaseUnitModel):
    def __init__(self, ht_config: HydrotreaterConfig) -> None:
        self.cfg = ht_config

    def calculate(self, feed_properties: CutProperties, feed_rate: float) -> HydrotreaterResult:  # type: ignore[override]
        cfg = self.cfg
        feed_s = feed_properties.sulfur if feed_properties.sulfur is not None else 0.5
        feed_cetane = feed_properties.cetane if feed_properties.cetane is not None else 35.0

        product_volume = feed_rate * cfg.volume_yield
        product_sulfur = feed_s * (1.0 - cfg.desulf_efficiency)
        product_cetane = feed_cetane + cfg.cetane_improvement
        h2_consumed = feed_rate * cfg.h2_scfb / 1e6  # MMSCFD

        return HydrotreaterResult(
            product_volume=product_volume,
            product_sulfur=product_sulfur,
            product_cetane=product_cetane,
            h2_consumed=h2_consumed,
        )


# Standard configurations
NAPHTHA_HT_CONFIG = HydrotreaterConfig(
    unit_id="nht_1", capacity=60000, desulf_efficiency=0.999,
    cetane_improvement=0, volume_yield=0.998, h2_scfb=400, opex_per_bbl=1.5,
)

KERO_HT_CONFIG = HydrotreaterConfig(
    unit_id="kht_1", capacity=30000, desulf_efficiency=0.990,
    cetane_improvement=0, volume_yield=0.995, h2_scfb=600, opex_per_bbl=2.0,
)

DIESEL_HT_CONFIG = HydrotreaterConfig(
    unit_id="dht_1", capacity=30000, desulf_efficiency=0.995,
    cetane_improvement=3.0, volume_yield=0.990, h2_scfb=800, opex_per_bbl=2.5,
)
