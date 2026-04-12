"""Alkylation unit — converts C3/C4 olefins + iC4 → alkylate.

Alkylate is the best gasoline blend component: RON 96, zero sulfur,
low RVP (4.5 psi).  Yield is ~1.75× the olefin feed volume.
"""

from __future__ import annotations

from dataclasses import dataclass

from eurekan.core.config import UnitConfig
from eurekan.core.crude import CutProperties
from eurekan.core.results import EquipmentStatus
from eurekan.models.base import BaseUnitModel
from pydantic import BaseModel


class AlkylationResult(BaseModel):
    alkylate_volume: float
    alkylate_properties: CutProperties
    ic4_consumed: float
    equipment: list[EquipmentStatus] = []


@dataclass
class AlkylationCalibration:
    alkylate_yield_ratio: float = 1.75   # bbl alkylate / bbl olefin feed
    ic4_ratio: float = 1.1               # bbl iC4 / bbl olefins
    alkylate_ron: float = 96.0
    alkylate_rvp: float = 4.5


class AlkylationModel(BaseUnitModel):
    def __init__(self, unit_config: UnitConfig, calibration: AlkylationCalibration | None = None) -> None:
        self.capacity = unit_config.capacity
        self.calibration = calibration or AlkylationCalibration()

    def calculate(self, olefin_feed: float) -> AlkylationResult:  # type: ignore[override]
        cal = self.calibration
        alkylate_volume = olefin_feed * cal.alkylate_yield_ratio
        ic4_consumed = olefin_feed * cal.ic4_ratio

        props = CutProperties(
            ron=cal.alkylate_ron,
            sulfur=0.0,
            rvp=cal.alkylate_rvp,
            spg=0.695,
            aromatics=0.5,
            olefins=0.5,
            benzene=0.0,
        )

        return AlkylationResult(
            alkylate_volume=alkylate_volume,
            alkylate_properties=props,
            ic4_consumed=ic4_consumed,
        )
