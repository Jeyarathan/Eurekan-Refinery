"""Core crude oil data models — temperature-based cuts, no PIMS tags."""

from __future__ import annotations

import logging
import warnings
from typing import Iterator, Optional

from pydantic import BaseModel, computed_field, model_validator

from eurekan.core.enums import DataSource

logger = logging.getLogger(__name__)


STANDARD_CUT_NAMES = [
    "light_gases",
    "lpg",
    "light_naphtha",
    "heavy_naphtha",
    "kerosene",
    "diesel",
    "light_vgo",
    "heavy_vgo",
    "vgo",
    "vacuum_residue",
]
"""Standard cut names used throughout Eurekan — in models, optimization, results, API, UI."""


class CutProperties(BaseModel):
    """Physical and chemical properties of a distillation cut."""

    api: Optional[float] = None
    sulfur: Optional[float] = None
    ron: Optional[float] = None
    mon: Optional[float] = None
    rvp: Optional[float] = None
    spg: Optional[float] = None
    olefins: Optional[float] = None
    aromatics: Optional[float] = None
    benzene: Optional[float] = None
    nitrogen: Optional[float] = None
    ccr: Optional[float] = None
    nickel: Optional[float] = None
    vanadium: Optional[float] = None
    cetane: Optional[float] = None
    flash_point: Optional[float] = None
    pour_point: Optional[float] = None
    cloud_point: Optional[float] = None

    @computed_field  # type: ignore[prop-decorator]
    @property
    def metals(self) -> float:
        """Total metals content (Ni + V) in ppm."""
        return (self.nickel or 0.0) + (self.vanadium or 0.0)


class CutPointDef(BaseModel):
    """Definition of a single cut point in a template."""

    name: str
    display_name: str
    tbp_start_f: Optional[float] = None
    tbp_end_f: Optional[float] = None


class DistillationCut(BaseModel):
    """A temperature-defined fraction of crude oil."""

    name: str
    display_name: str
    tbp_start_f: Optional[float] = None
    tbp_end_f: Optional[float] = None
    vol_yield: float
    properties: CutProperties = CutProperties()
    source: DataSource = DataSource.DEFAULT
    confidence: float = 1.0


class CutPointTemplate(BaseModel):
    """Defines how to slice the TBP curve into cuts."""

    name: str
    display_name: str
    cuts: list[CutPointDef]


# ---------------------------------------------------------------------------
# Default templates
# ---------------------------------------------------------------------------

US_GULF_COAST_630EP = CutPointTemplate(
    name="us_gulf_coast_630ep",
    display_name="US Gulf Coast (630\u00b0F EP Diesel)",
    cuts=[
        CutPointDef(name="light_naphtha", display_name="Light Naphtha (C5-180\u00b0F)", tbp_start_f=None, tbp_end_f=180.0),
        CutPointDef(name="heavy_naphtha", display_name="Heavy Naphtha (180-350\u00b0F)", tbp_start_f=180.0, tbp_end_f=350.0),
        CutPointDef(name="kerosene", display_name="Kerosene (350-500\u00b0F)", tbp_start_f=350.0, tbp_end_f=500.0),
        CutPointDef(name="diesel", display_name="Diesel (500-630\u00b0F)", tbp_start_f=500.0, tbp_end_f=630.0),
        CutPointDef(name="vgo", display_name="VGO (630-1050\u00b0F)", tbp_start_f=630.0, tbp_end_f=1050.0),
        CutPointDef(name="vacuum_residue", display_name="Vacuum Residue (1050\u00b0F+)", tbp_start_f=1050.0, tbp_end_f=None),
    ],
)

EUROPEAN_580EP = CutPointTemplate(
    name="european_580ep",
    display_name="European (580\u00b0F EP Diesel)",
    cuts=[
        CutPointDef(name="light_naphtha", display_name="Light Naphtha (C5-180\u00b0F)", tbp_start_f=None, tbp_end_f=180.0),
        CutPointDef(name="heavy_naphtha", display_name="Heavy Naphtha (180-330\u00b0F)", tbp_start_f=180.0, tbp_end_f=330.0),
        CutPointDef(name="kerosene", display_name="Kerosene (330-480\u00b0F)", tbp_start_f=330.0, tbp_end_f=480.0),
        CutPointDef(name="diesel", display_name="Diesel (480-580\u00b0F)", tbp_start_f=480.0, tbp_end_f=580.0),
        CutPointDef(name="vgo", display_name="VGO (580-1020\u00b0F)", tbp_start_f=580.0, tbp_end_f=1020.0),
        CutPointDef(name="vacuum_residue", display_name="Vacuum Residue (1020\u00b0F+)", tbp_start_f=1020.0, tbp_end_f=None),
    ],
)

MAX_KEROSENE = CutPointTemplate(
    name="max_kerosene",
    display_name="Max Kerosene",
    cuts=[
        CutPointDef(name="light_naphtha", display_name="Light Naphtha (C5-160\u00b0F)", tbp_start_f=None, tbp_end_f=160.0),
        CutPointDef(name="heavy_naphtha", display_name="Heavy Naphtha (160-300\u00b0F)", tbp_start_f=160.0, tbp_end_f=300.0),
        CutPointDef(name="kerosene", display_name="Kerosene (300-520\u00b0F)", tbp_start_f=300.0, tbp_end_f=520.0),
        CutPointDef(name="diesel", display_name="Diesel (520-650\u00b0F)", tbp_start_f=520.0, tbp_end_f=650.0),
        CutPointDef(name="vgo", display_name="VGO (650-1050\u00b0F)", tbp_start_f=650.0, tbp_end_f=1050.0),
        CutPointDef(name="vacuum_residue", display_name="Vacuum Residue (1050\u00b0F+)", tbp_start_f=1050.0, tbp_end_f=None),
    ],
)

DEFAULT_TEMPLATES = [US_GULF_COAST_630EP, EUROPEAN_580EP, MAX_KEROSENE]


class CrudeAssay(BaseModel):
    """Complete assay for a single crude oil."""

    crude_id: str
    name: str
    origin: Optional[str] = None
    api: float
    sulfur: float
    tan: Optional[float] = None
    price: Optional[float] = None
    max_rate: Optional[float] = None
    min_rate: float = 0.0
    cuts: list[DistillationCut]

    @computed_field  # type: ignore[prop-decorator]
    @property
    def total_yield(self) -> float:
        """Sum of volume yields across all cuts."""
        return sum(c.vol_yield for c in self.cuts)

    def get_cut(self, name: str) -> Optional[DistillationCut]:
        """Return the cut with the given name, or None."""
        for c in self.cuts:
            if c.name == name:
                return c
        return None

    @model_validator(mode="after")
    def _check_total_yield(self) -> "CrudeAssay":
        ty = self.total_yield
        if ty < 0.95 or ty > 1.05:
            warnings.warn(
                f"Crude '{self.crude_id}' total yield {ty:.4f} is outside 0.95-1.05",
                stacklevel=2,
            )
        return self


class CrudeLibrary:
    """Wrapper around a dict of CrudeAssay objects with helper methods."""

    def __init__(self, crudes: dict[str, CrudeAssay] | None = None) -> None:
        self._crudes: dict[str, CrudeAssay] = crudes or {}

    def add(self, assay: CrudeAssay) -> None:
        self._crudes[assay.crude_id] = assay

    def get(self, crude_id: str) -> Optional[CrudeAssay]:
        return self._crudes.get(crude_id)

    def list_crudes(self) -> list[str]:
        return list(self._crudes.keys())

    def __len__(self) -> int:
        return len(self._crudes)

    def __iter__(self) -> Iterator[str]:
        return iter(self._crudes)
