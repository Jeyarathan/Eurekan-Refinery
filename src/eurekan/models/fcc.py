"""FCC (Fluid Catalytic Cracker) model — correlations + equipment bounds + calibration.

Conversion (68-90%) is the key decision variable. Yield correlations use
published relationships with 11 calibration parameters for plant-specific tuning.

Equipment bounds (regen temp, gas compressor, air blower) are physics-based
and LIMIT max conversion on heavy feeds.
"""

from __future__ import annotations

from dataclasses import dataclass, fields

from eurekan.core.config import UnitConfig
from eurekan.core.crude import CutProperties
from eurekan.core.results import EquipmentStatus, FCCResult
from eurekan.models.base import BaseUnitModel

# ---------------------------------------------------------------------------
# Default feed properties — ARL-like VGO when properties are missing
# ---------------------------------------------------------------------------
_DEFAULT_API = 22.0
_DEFAULT_CCR = 1.0
_DEFAULT_SULFUR = 1.0
_DEFAULT_METALS = 5.0  # Ni + V, ppm

# ---------------------------------------------------------------------------
# Regen temp constraints
# ---------------------------------------------------------------------------
_REGEN_BASE = 1100.0  # °F
_REGEN_COKE_COEFF = 3800.0  # °F per unit coke yield fraction
_REGEN_HARD_LIMIT = 1400.0  # °F — absolute metallurgical limit (ProcLim)
_REGEN_SOFT_LIMIT = 1350.0  # °F — normal operating limit

# ---------------------------------------------------------------------------
# LCN/HCN split and product property defaults
# ---------------------------------------------------------------------------
_DEFAULT_LCN_FRACTION = 0.80  # LCN is ~80% of total gasoline by default
_LCN_RON_BASE = 93.0
_HCN_RON_BASE = 80.0
_LCO_CETANE_BASE = 25.0

# Light gas / C3 / C4 allocation fractions of (1 - gasoline - LCO - coke)
_FUEL_GAS_FRAC = 0.30  # fuel gas (C1-C2 + H2S)
_C3_FRAC = 0.30  # propane + propylene
_C4_FRAC = 0.30  # butanes + butylenes
_SLURRY_FRAC = 0.10  # slurry oil (unconverted heavy bottoms)


@dataclass
class FCCCalibration:
    """11 calibration parameters. All default to neutral (1.0 or 0.0)."""

    alpha_gasoline: float = 1.0
    alpha_coke: float = 1.0
    alpha_lcn_split: float = 1.0
    alpha_c3c4: float = 1.0
    alpha_lco: float = 1.0
    delta_lcn_ron: float = 0.0
    delta_hcn_ron: float = 0.0
    delta_lcn_sulfur: float = 1.0  # multiplier, not offset
    delta_hcn_sulfur: float = 1.0  # multiplier, not offset
    delta_lco_cetane: float = 0.0
    delta_regen: float = 0.0


class FCCModel(BaseUnitModel):
    """FCC model with conversion as continuous decision variable.

    Uses published correlations with calibration parameters.
    Equipment bounds computed from feed quality.
    """

    def __init__(
        self, unit_config: UnitConfig, calibration: FCCCalibration | None = None
    ) -> None:
        self.capacity = unit_config.capacity
        self.equipment_limits = unit_config.equipment_limits
        self.calibration = calibration or FCCCalibration()

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def yields(
        self, conversion: float, api: float, ccr: float, metals: float
    ) -> dict[str, float]:
        """Yield correlations. Returns vol fractions of feed.

        Args:
            conversion: FCC conversion, 0-100 (e.g. 80 for 80%)
            api: VGO feed API gravity
            ccr: VGO feed Conradson carbon residue, wt%
            metals: VGO feed metals (Ni+V), ppm
        """
        cal = self.calibration
        c = conversion / 100.0  # fractional conversion

        # --- Main product yields (vol fraction of feed) ---
        # Constant calibrated to match SCCU BASE (~49.4% gasoline at 80% conv, API=22, CCR=1)
        gasoline_raw = -0.0833 + 1.3364 * c - 0.7744 * c**2 + 0.0024 * (api - 22) - 0.0118 * (ccr - 1)
        gasoline = cal.alpha_gasoline * max(gasoline_raw, 0.0)

        lco_raw = 0.3247 - 0.2593 * c + 0.0031 * (api - 22)
        lco = cal.alpha_lco * max(lco_raw, 0.0)

        coke_raw = 0.0455 + 1.5 * ccr / 100.0 + 0.001 * (c * 100.0 - 75) + 0.0002 * metals
        coke = cal.alpha_coke * max(coke_raw, 0.0)

        # --- LCN / HCN split ---
        lcn_frac = _DEFAULT_LCN_FRACTION * cal.alpha_lcn_split
        lcn_frac = max(0.1, min(0.95, lcn_frac))  # clamp
        lcn = gasoline * lcn_frac
        hcn = gasoline * (1.0 - lcn_frac)

        # --- Remaining products from mass balance ---
        # Everything that isn't gasoline, LCO, or coke is split among
        # fuel gas, C3, C4, and slurry oil
        remaining = max(1.0 - gasoline - lco - coke, 0.0)

        c3 = remaining * _C3_FRAC * cal.alpha_c3c4
        c4 = remaining * _C4_FRAC * cal.alpha_c3c4
        fuel_gas = remaining * _FUEL_GAS_FRAC
        slurry = remaining * _SLURRY_FRAC

        # Adjust fuel_gas and slurry to maintain mass balance after c3c4 calibration
        c3c4_total = c3 + c4
        c3c4_default = remaining * (_C3_FRAC + _C4_FRAC)
        delta_c3c4 = c3c4_total - c3c4_default
        # Subtract excess from fuel_gas first, then slurry
        fuel_gas = max(fuel_gas - delta_c3c4 * 0.7, 0.001)
        slurry = max(slurry - delta_c3c4 * 0.3, 0.001)

        return {
            "lcn": lcn,
            "hcn": hcn,
            "gasoline": gasoline,
            "lco": lco,
            "coke": coke,
            "c3": c3,
            "c4": c4,
            "fuel_gas": fuel_gas,
            "slurry": slurry,
        }

    def product_properties(
        self, conversion: float, api: float, sulfur: float
    ) -> dict[str, CutProperties]:
        """Product quality correlations.

        Args:
            conversion: FCC conversion, 0-100
            api: VGO feed API gravity
            sulfur: VGO feed sulfur, wt%
        """
        cal = self.calibration
        c = conversion / 100.0

        # --- LCN properties ---
        lcn_ron = _LCN_RON_BASE + 2.0 * (c - 0.75) * 100.0 + cal.delta_lcn_ron
        lcn_sulfur = 0.02 * sulfur * cal.delta_lcn_sulfur  # ~2% of feed sulfur

        # --- HCN properties ---
        hcn_ron = _HCN_RON_BASE + 1.5 * (c - 0.75) * 100.0 + cal.delta_hcn_ron
        hcn_sulfur = 0.10 * sulfur * cal.delta_hcn_sulfur  # ~10% of feed sulfur

        # --- LCO properties ---
        # LCO cetane decreases with conversion (more aromatic at higher conversion)
        lco_cetane = _LCO_CETANE_BASE - 5.0 * (c - 0.75) + cal.delta_lco_cetane
        lco_sulfur = 0.50 * sulfur  # ~50% of feed sulfur ends up in LCO

        return {
            "lcn": CutProperties(ron=lcn_ron, sulfur=lcn_sulfur),
            "hcn": CutProperties(ron=hcn_ron, sulfur=hcn_sulfur),
            "lco": CutProperties(cetane=lco_cetane, sulfur=lco_sulfur),
        }

    def equipment_status(
        self, conversion: float, ccr: float, metals: float, feed_rate: float
    ) -> list[EquipmentStatus]:
        """Compute regen temp, gas compressor load, air blower load.

        Args:
            conversion: FCC conversion, 0-100
            ccr: VGO feed CCR, wt%
            metals: VGO feed metals (Ni+V), ppm
            feed_rate: FCC feed rate, bbl/d
        """
        cal = self.calibration
        c = conversion / 100.0

        # Coke yield for regen temp calculation
        coke = cal.alpha_coke * max(
            0.0455 + 1.5 * ccr / 100.0 + 0.001 * (c * 100.0 - 75) + 0.0002 * metals,
            0.0,
        )

        # Regenerator temperature
        regen_temp = _REGEN_BASE + _REGEN_COKE_COEFF * coke + cal.delta_regen
        regen_limit = self.equipment_limits.get("fcc_regen_temp_max", _REGEN_HARD_LIMIT)

        # Gas compressor — proportional to gas make (conversion drives gas production)
        gas_make_factor = c * feed_rate / self.capacity  # normalized
        gas_comp_limit = 1.0  # normalized capacity
        gas_comp_value = gas_make_factor

        # Air blower — proportional to coke burn requirement
        air_factor = coke * feed_rate / self.capacity  # normalized
        air_limit = 1.0  # normalized capacity
        air_value = air_factor / 0.08  # normalize: ~8% coke = 100% air blower

        statuses = [
            EquipmentStatus(
                name="regen_temp",
                display_name="Regenerator Temperature",
                current_value=regen_temp,
                limit=regen_limit,
                utilization_pct=min(regen_temp / regen_limit * 100.0, 100.0),
                is_binding=regen_temp >= regen_limit * 0.99,
            ),
            EquipmentStatus(
                name="gas_compressor",
                display_name="Gas Compressor",
                current_value=gas_comp_value,
                limit=gas_comp_limit,
                utilization_pct=min(gas_comp_value / gas_comp_limit * 100.0, 100.0),
                is_binding=gas_comp_value >= gas_comp_limit * 0.99,
            ),
            EquipmentStatus(
                name="air_blower",
                display_name="Air Blower",
                current_value=air_value,
                limit=air_limit,
                utilization_pct=min(air_value / air_limit * 100.0, 100.0),
                is_binding=air_value >= air_limit * 0.99,
            ),
        ]
        return statuses

    def max_conversion(self, feed_properties: CutProperties) -> float:
        """Physics-based max conversion for this feed quality.

        Finds the conversion at which the regenerator temperature hits its limit.
        Uses bisection since the relationship is monotonic in conversion.
        """
        api = feed_properties.api if feed_properties.api is not None else _DEFAULT_API
        ccr = feed_properties.ccr if feed_properties.ccr is not None else _DEFAULT_CCR
        metals = feed_properties.metals

        cal = self.calibration
        regen_limit = self.equipment_limits.get("fcc_regen_temp_max", _REGEN_HARD_LIMIT)

        # Bisection search for conversion where regen_temp == regen_limit
        lo, hi = 50.0, 95.0
        for _ in range(50):
            mid = (lo + hi) / 2.0
            c = mid / 100.0
            coke = cal.alpha_coke * max(
                0.0455 + 1.5 * ccr / 100.0 + 0.001 * (c * 100.0 - 75) + 0.0002 * metals,
                0.0,
            )
            regen_temp = _REGEN_BASE + _REGEN_COKE_COEFF * coke + cal.delta_regen
            if regen_temp < regen_limit:
                lo = mid
            else:
                hi = mid

        return round((lo + hi) / 2.0, 2)

    def calculate(  # type: ignore[override]
        self, feed_properties: CutProperties, conversion: float
    ) -> FCCResult:
        """Calculate all FCC yields, properties, and equipment status.

        Args:
            feed_properties: Blended VGO feed properties from CDU
            conversion: FCC conversion, 0-100 (e.g. 80 for 80%)

        Returns:
            FCCResult with yields, product properties, and equipment status.
        """
        api = feed_properties.api if feed_properties.api is not None else _DEFAULT_API
        ccr = feed_properties.ccr if feed_properties.ccr is not None else _DEFAULT_CCR
        sulfur = feed_properties.sulfur if feed_properties.sulfur is not None else _DEFAULT_SULFUR
        metals = feed_properties.metals

        ylds = self.yields(conversion, api, ccr, metals)
        props = self.product_properties(conversion, api, sulfur)
        equip = self.equipment_status(conversion, ccr, metals, self.capacity)

        return FCCResult(
            conversion=conversion,
            yields=ylds,
            properties=props,
            equipment=equip,
        )
