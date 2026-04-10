"""Refinery configuration and completeness tracking."""

from __future__ import annotations

from typing import Optional

from pydantic import BaseModel

from eurekan.core.crude import CrudeLibrary, CutPointTemplate
from eurekan.core.enums import DataSource, UnitType
from eurekan.core.product import Product
from eurekan.core.stream import Stream
from eurekan.core.tank import Tank


class ConfigCompleteness(BaseModel):
    """Result of a completeness assessment on a RefineryConfig."""

    overall_pct: float
    missing: list[str]
    using_defaults: list[str]
    ready_to_optimize: bool
    margin_uncertainty_pct: float
    highest_value_missing: Optional[str] = None


class UnitConfig(BaseModel):
    """Configuration for a single processing unit."""

    unit_id: str
    unit_type: UnitType
    capacity: float
    min_throughput: float = 0.0
    equipment_limits: dict[str, float] = {}
    source: DataSource = DataSource.DEFAULT


class RefineryConfig(BaseModel):
    """Top-level refinery configuration aggregating all data."""

    name: str
    units: dict[str, UnitConfig] = {}
    crude_library: CrudeLibrary
    products: dict[str, Product] = {}
    streams: dict[str, Stream] = {}
    tanks: dict[str, Tank] = {}
    cut_point_template: CutPointTemplate

    model_config = {"arbitrary_types_allowed": True}

    def completeness(self) -> ConfigCompleteness:
        """Assess how complete this configuration is for optimization."""
        missing: list[str] = []
        using_defaults: list[str] = []

        # --- units ---
        has_cdu = any(u.unit_type == UnitType.CDU for u in self.units.values())
        if not has_cdu:
            missing.append("CDU unit configuration")
        for uid, uc in self.units.items():
            if uc.source == DataSource.DEFAULT:
                using_defaults.append(f"unit:{uid}")
            if uc.capacity <= 0:
                missing.append(f"unit:{uid} capacity")

        # --- crudes ---
        n_crudes = len(self.crude_library)
        if n_crudes == 0:
            missing.append("crude assays")
        for cid in self.crude_library:
            assay = self.crude_library.get(cid)
            if assay is None:
                continue
            if assay.price is None:
                missing.append(f"crude:{cid} price")
            for cut in assay.cuts:
                if cut.source == DataSource.DEFAULT:
                    using_defaults.append(f"crude:{cid}:{cut.name}")
                if cut.properties.ccr is None and cut.name in ("vgo", "heavy_vgo"):
                    missing.append(f"crude:{cid} VGO CCR")

        # --- products ---
        if not self.products:
            missing.append("product definitions")
        for pid, prod in self.products.items():
            if not prod.specs:
                missing.append(f"product:{pid} specs")

        # --- streams ---
        if not self.streams:
            missing.append("stream definitions")

        # --- overall ---
        total_items = max(
            len(self.units) + n_crudes + len(self.products) + len(self.streams) + len(self.tanks),
            1,
        )
        filled = total_items - len(missing)
        overall_pct = max(0.0, min(100.0, (filled / total_items) * 100.0))

        # Ready to optimize if we have at least a CDU, one crude, and one product
        ready = has_cdu and n_crudes > 0 and len(self.products) > 0

        # Margin uncertainty: higher completeness → lower uncertainty
        if overall_pct >= 95:
            margin_uncertainty_pct = 3.0
        elif overall_pct >= 80:
            margin_uncertainty_pct = 8.0
        elif overall_pct >= 60:
            margin_uncertainty_pct = 15.0
        else:
            margin_uncertainty_pct = 25.0

        # Highest-value missing item
        highest_value_missing: Optional[str] = None
        if missing:
            # Prioritise VGO CCR entries (highest impact on FCC/margin accuracy)
            vgo_ccr = [m for m in missing if "VGO CCR" in m]
            if vgo_ccr:
                highest_value_missing = vgo_ccr[0]
            else:
                highest_value_missing = missing[0]

        return ConfigCompleteness(
            overall_pct=round(overall_pct, 1),
            missing=missing,
            using_defaults=using_defaults,
            ready_to_optimize=ready,
            margin_uncertainty_pct=margin_uncertainty_pct,
            highest_value_missing=highest_value_missing,
        )
