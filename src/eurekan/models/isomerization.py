"""C5/C6 Isomerization model.

Converts straight-chain C5/C6 paraffins to branched isomers for
higher octane. A "cheap octane" source - less expensive than
reforming and preserves more liquid volume.

Gulf Coast: CIS6, 15K bbl/d capacity.

Key physics:
  Feed: light naphtha (C5-C6, RON ~68)
  Product: isomerate (RON 82-87 depending on recycle configuration)
  Volume yield: 97-99% (near unity)
  H2 consumption: 100-200 SCFB (very low)
"""

from __future__ import annotations

from dataclasses import dataclass

from pydantic import BaseModel

from eurekan.core.config import UnitConfig
from eurekan.core.crude import CutProperties
from eurekan.models.base import BaseUnitModel


_DEFAULT_VOLUME_YIELD = 0.98
_DEFAULT_ISOMERATE_RON = 83.0
_DEFAULT_H2_SCFB = 150.0


class IsomerizationResult(BaseModel):
    """Results from the C5/C6 isomerization model."""

    isomerate_volume: float
    isomerate_ron: float
    hydrogen_consumption_mmscf: float
    isomerate_properties: CutProperties = CutProperties()


@dataclass
class IsomerizationCalibration:
    """Calibration overrides."""

    alpha_yield: float = 1.0
    delta_ron: float = 0.0


class C56IsomerizationModel(BaseUnitModel):
    """C5/C6 isomerization - upgrades LN octane from 68 to 83."""

    def __init__(
        self,
        unit_config: UnitConfig,
        calibration: IsomerizationCalibration | None = None,
    ) -> None:
        self.capacity = unit_config.capacity
        self.calibration = calibration or IsomerizationCalibration()

    def calculate(  # type: ignore[override]
        self,
        feed_rate: float,
        feed_properties: CutProperties,
    ) -> IsomerizationResult:
        """Compute isomerate yield and properties."""
        cal = self.calibration

        vol_yield = max(0.0, min(1.0, cal.alpha_yield * _DEFAULT_VOLUME_YIELD))
        isomerate_vol = feed_rate * vol_yield
        isomerate_ron = _DEFAULT_ISOMERATE_RON + cal.delta_ron

        h2_mmscf = _DEFAULT_H2_SCFB * feed_rate / 1.0e6

        # Isomerate: high-octane, low-sulfur, low-aromatics, low-olefins
        isomerate_props = CutProperties(
            api=82.0,
            sulfur=0.0001,
            ron=isomerate_ron,
            rvp=14.0,       # higher volatility than feed
            spg=0.65,
            aromatics=0.5,
            benzene=0.0,    # near-zero benzene (regulatory advantage)
            olefins=0.5,
        )

        return IsomerizationResult(
            isomerate_volume=isomerate_vol,
            isomerate_ron=isomerate_ron,
            hydrogen_consumption_mmscf=h2_mmscf,
            isomerate_properties=isomerate_props,
        )
