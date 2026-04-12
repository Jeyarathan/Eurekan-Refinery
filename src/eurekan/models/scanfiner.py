"""Scanfiner — selective HCN desulfurization with minimal octane loss.

Treats FCC heavy cat naphtha to remove sulfur while preserving olefins
and octane. Only ~1.5 RON loss vs untreated HCN.
"""

from __future__ import annotations

from dataclasses import dataclass

from eurekan.core.config import UnitConfig
from eurekan.core.crude import CutProperties
from eurekan.core.results import EquipmentStatus
from eurekan.models.base import BaseUnitModel
from pydantic import BaseModel


class ScanfinerResult(BaseModel):
    product_volume: float
    product_sulfur: float
    product_ron: float
    h2_consumed: float
    equipment: list[EquipmentStatus] = []


@dataclass
class ScanfinerCalibration:
    sulfur_removal: float = 0.85
    ron_loss: float = 1.5
    volume_yield: float = 0.98
    h2_scfb: float = 300.0


class ScanfinerModel(BaseUnitModel):
    def __init__(self, unit_config: UnitConfig, calibration: ScanfinerCalibration | None = None) -> None:
        self.capacity = unit_config.capacity
        self.calibration = calibration or ScanfinerCalibration()

    def calculate(self, feed_properties: CutProperties, feed_rate: float) -> ScanfinerResult:  # type: ignore[override]
        cal = self.calibration
        feed_s = feed_properties.sulfur or 0.30
        feed_ron = feed_properties.ron or 86.0

        product_volume = feed_rate * cal.volume_yield
        product_sulfur = feed_s * (1.0 - cal.sulfur_removal)
        product_ron = feed_ron - cal.ron_loss
        h2_consumed = feed_rate * cal.h2_scfb / 1e6

        return ScanfinerResult(
            product_volume=product_volume,
            product_sulfur=product_sulfur,
            product_ron=product_ron,
            h2_consumed=h2_consumed,
        )
