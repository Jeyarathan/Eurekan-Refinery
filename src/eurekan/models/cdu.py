"""CDU (Crude Distillation Unit) model — exact yields from assay data.

Yields are LINEAR in crude volumes:
    cut_volume[k] = sum_c(crude_rate[c] * yield[c][k])

Cut properties are WEIGHTED AVERAGES (nonlinear — ratios):
    cut_prop[k] = sum_c(crude_rate[c] * yield[c][k] * prop[c][k]) / cut_volume[k]
"""

from __future__ import annotations

from typing import Optional

from eurekan.core.config import UnitConfig
from eurekan.core.crude import CrudeLibrary, CutProperties
from eurekan.core.results import CDUResult
from eurekan.models.base import BaseUnitModel

# Properties that support weighted-average blending
_BLENDABLE_PROPS = [
    "api", "sulfur", "spg", "ron", "mon", "rvp",
    "olefins", "aromatics", "benzene", "nitrogen",
    "ccr", "nickel", "vanadium", "cetane",
    "flash_point", "pour_point", "cloud_point",
]


class CDUModel(BaseUnitModel):
    """CDU yield model — exact from assay data."""

    def __init__(self, unit_config: UnitConfig) -> None:
        self.capacity = unit_config.capacity
        self.min_throughput = unit_config.min_throughput

    def calculate(  # type: ignore[override]
        self,
        crude_rates: dict[str, float],
        crude_library: CrudeLibrary,
    ) -> CDUResult:
        """Compute CDU cut volumes and properties from crude slate.

        Args:
            crude_rates: {crude_id: rate_bbl_per_day}
            crude_library: CrudeLibrary with assay data

        Returns:
            CDUResult with cut volumes, properties, and VGO feed quality.
        """
        total_crude = sum(crude_rates.values())

        if total_crude == 0.0:
            return CDUResult(total_crude=0.0)

        # Collect all cut names from the first crude that has cuts
        cut_names: list[str] = []
        for cid in crude_rates:
            assay = crude_library.get(cid)
            if assay is not None and assay.cuts:
                cut_names = [c.name for c in assay.cuts]
                break

        # 1. Compute cut volumes (linear)
        cut_volumes: dict[str, float] = {k: 0.0 for k in cut_names}
        # Accumulators for weighted property sums
        prop_weighted: dict[str, dict[str, float]] = {
            k: {p: 0.0 for p in _BLENDABLE_PROPS} for k in cut_names
        }

        for cid, rate in crude_rates.items():
            if rate <= 0.0:
                continue
            assay = crude_library.get(cid)
            if assay is None:
                continue
            for cut in assay.cuts:
                vol = rate * cut.vol_yield
                cut_volumes[cut.name] = cut_volumes.get(cut.name, 0.0) + vol

                # Accumulate weighted property sums
                for prop in _BLENDABLE_PROPS:
                    val = getattr(cut.properties, prop, None)
                    if val is not None:
                        acc = prop_weighted.setdefault(
                            cut.name, {p: 0.0 for p in _BLENDABLE_PROPS}
                        )
                        acc[prop] = acc.get(prop, 0.0) + vol * val

        # 2. Compute cut properties (weighted average)
        cut_properties: dict[str, CutProperties] = {}
        for k in cut_names:
            total_vol = cut_volumes.get(k, 0.0)
            if total_vol <= 0.0:
                cut_properties[k] = CutProperties()
                continue
            props: dict[str, Optional[float]] = {}
            for prop in _BLENDABLE_PROPS:
                weighted_sum = prop_weighted.get(k, {}).get(prop, 0.0)
                if weighted_sum != 0.0:
                    props[prop] = weighted_sum / total_vol
                else:
                    props[prop] = None
            cut_properties[k] = CutProperties(**props)

        # 3. VGO feed properties (the blended VGO going to FCC)
        vgo_props = cut_properties.get("vgo", CutProperties())

        return CDUResult(
            total_crude=total_crude,
            cut_volumes=cut_volumes,
            cut_properties=cut_properties,
            vgo_feed_properties=vgo_props,
        )
