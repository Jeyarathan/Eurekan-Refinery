"""Catalytic reformer model — converts heavy naphtha to high-octane reformate.

Key physics:
  Feed: heavy naphtha (180-350 deg F, RON ~42)
  Product: reformate (RON 95-102 depending on severity)
  Byproducts: hydrogen (valuable), LPG, fuel gas
  Higher severity -> higher RON but lower liquid yield
  Typical: 85% vol yield at RON 98
"""

from __future__ import annotations

from dataclasses import dataclass

from eurekan.core.config import UnitConfig
from eurekan.core.crude import CutProperties
from eurekan.core.results import EquipmentStatus, ReformerResult
from eurekan.models.base import BaseUnitModel

_DEFAULT_SEVERITY = 98.0
_MAX_HEATER_DUTY = 1.0  # normalized capacity


@dataclass
class ReformerCalibration:
    """4 calibration parameters. All default to neutral."""

    alpha_reformate_yield: float = 1.0
    alpha_hydrogen_yield: float = 1.0
    delta_ron: float = 0.0
    severity_factor: float = 1.0


class ReformerModel(BaseUnitModel):
    """Catalytic reformer with severity as continuous decision variable."""

    def __init__(
        self, unit_config: UnitConfig, calibration: ReformerCalibration | None = None
    ) -> None:
        self.capacity = unit_config.capacity
        self.equipment_limits = unit_config.equipment_limits
        self.calibration = calibration or ReformerCalibration()

    def calculate(  # type: ignore[override]
        self,
        feed_properties: CutProperties,
        feed_rate: float,
        severity: float,
    ) -> ReformerResult:
        """Calculate reformer yields and product properties.

        Args:
            feed_properties: Heavy naphtha feed properties.
            feed_rate: Feed rate in bbl/d.
            severity: Target RON of reformate (90-105).
        """
        cal = self.calibration

        # Reformate yield: decreases with severity (more cracking at higher RON)
        reformate_yield = cal.alpha_reformate_yield * (
            0.95 - 0.0125 * cal.severity_factor * (severity - 90.0)
        )
        reformate_yield = max(0.0, min(1.0, reformate_yield))

        # Hydrogen production: increases with severity (more dehydrogenation)
        hydrogen_yield = cal.alpha_hydrogen_yield * (
            0.03 + 0.001 * cal.severity_factor * (severity - 90.0)
        )
        hydrogen_yield = max(0.0, hydrogen_yield)

        # LPG + fuel gas from mass balance
        remainder = max(0.0, 1.0 - reformate_yield - hydrogen_yield)
        lpg_fraction = 0.6 * remainder
        fuel_gas_fraction = 0.4 * remainder

        # Volumes
        reformate_volume = feed_rate * reformate_yield
        hydrogen_production = feed_rate * hydrogen_yield
        lpg_production = feed_rate * lpg_fraction
        fuel_gas_production = feed_rate * fuel_gas_fraction

        # Reformate RON = severity + calibration offset
        reformate_ron = severity + cal.delta_ron

        equip = self.equipment_status(feed_rate, severity)

        return ReformerResult(
            reformate_volume=reformate_volume,
            reformate_ron=reformate_ron,
            hydrogen_production=hydrogen_production,
            lpg_production=lpg_production,
            fuel_gas_production=fuel_gas_production,
            severity=severity,
            equipment=equip,
        )

    def max_severity(self, feed_properties: CutProperties) -> float:
        """Max severity limited by catalyst stability and feed quality.

        Higher naphthene content allows higher severity. Typical 102-105.
        """
        # If feed has high aromatics (already partially reformed), limit severity
        aromatics = feed_properties.aromatics if feed_properties.aromatics is not None else 15.0
        # More naphthenes (lower existing aromatics) → can push harder
        base_max = 105.0 - 0.1 * max(aromatics - 10.0, 0.0)
        return max(100.0, min(105.0, base_max))

    def equipment_status(
        self, feed_rate: float, severity: float
    ) -> list[EquipmentStatus]:
        """Heater duty, recycle compressor, reactor temperature."""
        # Heater duty increases with severity (endothermic reactions)
        heater_duty = 0.5 + 0.005 * (severity - 90.0)
        heater_limit = self.equipment_limits.get("heater_duty_max", _MAX_HEATER_DUTY)

        # Recycle compressor: proportional to feed rate
        compressor_load = feed_rate / self.capacity if self.capacity > 0 else 0.0

        return [
            EquipmentStatus(
                name="heater_duty",
                display_name="Reformer Heater Duty",
                current_value=heater_duty,
                limit=heater_limit,
                utilization_pct=min(heater_duty / heater_limit * 100, 100) if heater_limit > 0 else 0,
                is_binding=heater_duty >= heater_limit * 0.99,
            ),
            EquipmentStatus(
                name="recycle_compressor",
                display_name="Recycle Compressor",
                current_value=compressor_load,
                limit=1.0,
                utilization_pct=min(compressor_load * 100, 100),
                is_binding=compressor_load >= 0.99,
            ),
        ]
