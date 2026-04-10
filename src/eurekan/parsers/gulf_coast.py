"""Gulf Coast Excel parser — PIMS format to Eurekan models.

This module is a TRANSLATION LAYER. PIMS tags go in, Eurekan models come out.
No PIMS tag survives past the parser.
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Optional

import openpyxl

from eurekan.core.crude import (
    CrudeAssay,
    CrudeLibrary,
    CutProperties,
    DistillationCut,
    US_GULF_COAST_630EP,
)
from eurekan.core.enums import DataSource
from eurekan.core.product import Product, ProductSpec
from eurekan.parsers.schema import SchemaValidationError, SheetSchema, validate_sheet

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# PIMS → Eurekan translation maps (the ONLY place PIMS tags exist)
# ---------------------------------------------------------------------------

# Yield rows: tag → (eurekan_cut_name, sub_component_name_or_None)
PIMS_YIELD_MAP: dict[str, tuple[str, Optional[str]]] = {
    "VBALNC3": ("lpg", "propane"),
    "VBALIC4": ("lpg", "isobutane"),
    "VBALNC4": ("lpg", "n_butane"),
    "DBALLN1": ("light_naphtha", None),
    "DBALMN1": ("heavy_naphtha", None),
    "VBALKE1": ("kerosene", None),
    "VBALDS1": ("diesel", None),
    "VBALLV1": ("vgo", "lvgo"),
    "VBALHV1": ("vgo", "hvgo"),
    "VBALVR1": ("vacuum_residue", None),
}

# Property rows for each cut — tag → (eurekan_cut_name, property_name)
PIMS_PROPERTY_MAP: dict[str, tuple[str, str]] = {
    # Specific gravity
    "ISPGLN1": ("light_naphtha", "spg"),
    "ISPGMN1": ("heavy_naphtha", "spg"),
    "ISPGKE1": ("kerosene", "spg"),
    "ISPGDS1": ("diesel", "spg"),
    "ISPGLV1": ("vgo", "spg_lvgo"),
    "ISPGHV1": ("vgo", "spg_hvgo"),
    "ISPGVR1": ("vacuum_residue", "spg"),
    # API gravity
    "IAPIKE1": ("kerosene", "api"),
    "IAPIDS1": ("diesel", "api"),
    "IAPILV1": ("vgo", "api_lvgo"),
    "IAPIHV1": ("vgo", "api_hvgo"),
    "IAPIVR1": ("vacuum_residue", "api"),
    # Sulfur
    "ISULLN1": ("light_naphtha", "sulfur"),
    "ISULMN1": ("heavy_naphtha", "sulfur"),
    "ISULKE1": ("kerosene", "sulfur"),
    "ISULDS1": ("diesel", "sulfur"),
    "ISULLV1": ("vgo", "sulfur_lvgo"),
    "ISULHV1": ("vgo", "sulfur_hvgo"),
    "ISULVR1": ("vacuum_residue", "sulfur"),
    # RON (light naphtha only)
    "IRONLN1": ("light_naphtha", "ron"),
    # CCR (VGO sub-cuts and vacuum residue)
    "ICCNLV1": ("vgo", "ccr_lvgo"),
    "ICCNHV1": ("vgo", "ccr_hvgo"),
    "ICCNVR1": ("vacuum_residue", "ccr"),
    # Nickel
    "INIKLV1": ("vgo", "nickel_lvgo"),
    "INIKHV1": ("vgo", "nickel_hvgo"),
    "INIKVR1": ("vacuum_residue", "nickel"),
    # Vanadium
    "IVANLV1": ("vgo", "vanadium_lvgo"),
    "IVANHV1": ("vgo", "vanadium_hvgo"),
    "IVANVR1": ("vacuum_residue", "vanadium"),
    # Nitrogen (as naphthenic acids — N2A rows)
    "IN2ALN1": ("light_naphtha", "nitrogen"),
    "IN2AMN1": ("heavy_naphtha", "nitrogen"),
}

# Product tag → Eurekan name
PIMS_PRODUCT_MAP: dict[str, str] = {
    "CRG": "regular_gasoline",
    "CPR": "premium_gasoline",
    "RRG": "rfg_regular",
    "RPR": "rfg_premium",
    "ULS": "ulsd",
    "JET": "jet_fuel",
    "N2O": "no2_oil",
    "LSF": "low_sulfur_fuel_oil",
    "HSF": "high_sulfur_fuel_oil",
    "LPG": "lpg",
    "BUT": "mixed_butanes",
    "CKE": "coke",
    "LSR": "light_straight_run",
    "BEN": "benzene",
    "TOL": "toluene",
    "XYL": "xylenes",
    "LUB": "lube_base_stocks",
    "ATB": "a960",
    "SUP": "sulfur",
}

# Schemas for validation
ASSAYS_SCHEMA = SheetSchema(
    sheet_name="Assays",
    required_row_tags=[
        "VBALNC3", "VBALIC4", "VBALNC4",
        "DBALLN1", "DBALMN1",
        "VBALKE1", "VBALDS1",
        "VBALLV1", "VBALHV1", "VBALVR1",
    ],
    required_column_tags=["ARL"],
)

BUY_SCHEMA = SheetSchema(
    sheet_name="Buy",
    required_row_tags=["ARL"],
)

SELL_SCHEMA = SheetSchema(
    sheet_name="Sell",
    required_row_tags=["CRG", "JET", "ULS"],
)

# Temperature ranges from the US Gulf Coast 630EP template, keyed by cut name
_CUT_TEMPS: dict[str, tuple[Optional[float], Optional[float], str]] = {}
for _cpd in US_GULF_COAST_630EP.cuts:
    _CUT_TEMPS[_cpd.name] = (_cpd.tbp_start_f, _cpd.tbp_end_f, _cpd.display_name)
# LPG has no TBP range in the template — add manually
_CUT_TEMPS["lpg"] = (None, None, "LPG (C3-C4)")


class GulfCoastParser:
    """Parser for the Gulf Coast PIMS-format Excel workbook."""

    def __init__(self, filepath: str | Path) -> None:
        self._filepath = Path(filepath)
        self._wb = openpyxl.load_workbook(self._filepath, data_only=True)

    @property
    def sheet_names(self) -> list[str]:
        return self._wb.sheetnames

    def explore_sheet(self, sheet_name: str, n_rows: int = 15) -> None:
        """Print the first *n_rows* of a sheet with row/column indices."""
        ws = self._wb[sheet_name]
        print(f"\n{'=' * 80}")
        print(f"Sheet: {sheet_name}  (rows={ws.max_row}, cols={ws.max_column})")
        print(f"{'=' * 80}")

        for row_idx, row in enumerate(
            ws.iter_rows(max_row=n_rows, values_only=False), start=1
        ):
            values = []
            for cell in row:
                v = cell.value
                if v is None:
                    values.append("")
                elif isinstance(v, float):
                    values.append(f"{v:.4f}")
                else:
                    values.append(str(v))
            truncated = [s[:12].ljust(12) for s in values]
            print(f"  Row {row_idx:3d}: {' | '.join(truncated)}")

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _build_row_tag_index(self, ws) -> dict[str, int]:
        """Map column-A tags → row numbers (1-based)."""
        index: dict[str, int] = {}
        for row in ws.iter_rows(min_col=1, max_col=1):
            cell = row[0]
            if cell.value is not None:
                tag = str(cell.value).strip()
                if not tag.startswith("*"):
                    index[tag] = cell.row
        return index

    def _build_col_header_index(self, ws, header_row: int) -> dict[str, int]:
        """Map header tags → column numbers (1-based) from a given row."""
        index: dict[str, int] = {}
        for cell in ws[header_row]:
            if cell.value is not None:
                tag = str(cell.value).strip()
                if tag and tag != "TEXT":
                    index[tag] = cell.column
        return index

    def _find_header_row(self, ws, known_tag: str = "ARL") -> int:
        """Find the row containing crude/column tags (e.g. 'ARL')."""
        for row in ws.iter_rows():
            for cell in row:
                if cell.value is not None and str(cell.value).strip() == known_tag:
                    return cell.row
        raise SchemaValidationError(
            f"Could not find header row with tag '{known_tag}' in sheet"
        )

    def _cell_value(self, ws, row: int, col: int) -> Optional[float]:
        """Read a numeric cell value, returning None if empty or non-numeric."""
        val = ws.cell(row=row, column=col).value
        if val is None:
            return None
        try:
            return float(val)
        except (ValueError, TypeError):
            return None

    # ------------------------------------------------------------------
    # Task 1.7: Parse Assays sheet
    # ------------------------------------------------------------------

    def parse_assays(self) -> CrudeLibrary:
        """Parse the Assays sheet → CrudeLibrary with Eurekan-native names."""
        ws = self._wb["Assays"]

        # Validate schema
        issues = validate_sheet(ws, ASSAYS_SCHEMA)
        if issues:
            raise SchemaValidationError(
                f"Assays sheet validation failed: {'; '.join(issues)}"
            )

        # Build indices
        header_row_num = self._find_header_row(ws, "ARL")
        col_index = self._build_col_header_index(ws, header_row_num)
        row_index = self._build_row_tag_index(ws)

        # Identify crude columns (skip TEXT column, skip empty)
        crude_tags = [
            tag for tag in col_index
            if tag not in ("TEXT", "***") and col_index[tag] > 2
        ]

        library = CrudeLibrary()

        for crude_tag in crude_tags:
            col = col_index[crude_tag]

            # --- Read whole-crude properties ---
            # API is in the row containing ZLIMAP1 (CDU-1 API) or from row 5 (*API Gravity)
            crude_api = self._cell_value(ws, row_index.get("ZLIMAP1", 0), col)
            if crude_api is None:
                # Fallback: read from row 5 (header section)
                crude_api = self._cell_value(ws, 5, col)
            crude_sulfur = self._cell_value(ws, row_index.get("ZLIMSU1", 0), col)
            if crude_sulfur is None:
                crude_sulfur = self._cell_value(ws, 9, col)
            crude_tan = self._cell_value(ws, row_index.get("ZLIMTA1", 0), col)

            if crude_api is None:
                crude_api = 30.0  # safe default
            if crude_sulfur is None:
                crude_sulfur = 1.0

            # --- Read yields ---
            # Accumulate sub-components into cuts
            cut_yields: dict[str, float] = {}
            for pims_tag, (cut_name, _sub) in PIMS_YIELD_MAP.items():
                if pims_tag not in row_index:
                    continue
                val = self._cell_value(ws, row_index[pims_tag], col)
                if val is not None:
                    cut_yields[cut_name] = cut_yields.get(cut_name, 0.0) + val

            # --- Read cut properties ---
            cut_props_raw: dict[str, dict[str, float]] = {}
            for pims_tag, (cut_name, prop_name) in PIMS_PROPERTY_MAP.items():
                if pims_tag not in row_index:
                    continue
                val = self._cell_value(ws, row_index[pims_tag], col)
                if val is not None:
                    cut_props_raw.setdefault(cut_name, {})[prop_name] = val

            # --- Build DistillationCut objects ---
            cuts: list[DistillationCut] = []
            for cut_name in [
                "lpg", "light_naphtha", "heavy_naphtha",
                "kerosene", "diesel", "vgo", "vacuum_residue",
            ]:
                vol_yield = cut_yields.get(cut_name, 0.0)
                if vol_yield == 0.0 and cut_name == "lpg":
                    continue  # Skip LPG if no yields found

                tbp_start, tbp_end, display = _CUT_TEMPS.get(
                    cut_name, (None, None, cut_name)
                )

                # Assemble CutProperties
                raw = cut_props_raw.get(cut_name, {})
                props = self._build_cut_properties(cut_name, raw)

                cuts.append(
                    DistillationCut(
                        name=cut_name,
                        display_name=display,
                        tbp_start_f=tbp_start,
                        tbp_end_f=tbp_end,
                        vol_yield=vol_yield,
                        properties=props,
                        source=DataSource.IMPORTED,
                        confidence=0.95,
                    )
                )

            # Read crude full name from row 2
            name_val = ws.cell(row=2, column=col).value
            crude_name = str(name_val).strip() if name_val else crude_tag

            assay = CrudeAssay(
                crude_id=crude_tag,
                name=crude_name,
                origin=None,
                api=crude_api,
                sulfur=crude_sulfur,
                tan=crude_tan,
                cuts=cuts,
            )
            library.add(assay)

        return library

    def _build_cut_properties(
        self, cut_name: str, raw: dict[str, float]
    ) -> CutProperties:
        """Build CutProperties from raw property dict, handling VGO aggregation."""
        if cut_name == "vgo":
            # Weighted average of LVGO and HVGO properties
            # Use simple average as approximation (true weighting needs volumes)
            api = self._avg(raw.get("api_lvgo"), raw.get("api_hvgo"))
            sulfur = self._avg(raw.get("sulfur_lvgo"), raw.get("sulfur_hvgo"))
            spg = self._avg(raw.get("spg_lvgo"), raw.get("spg_hvgo"))
            ccr = self._avg(raw.get("ccr_lvgo"), raw.get("ccr_hvgo"))
            nickel = self._avg(raw.get("nickel_lvgo"), raw.get("nickel_hvgo"))
            vanadium = self._avg(raw.get("vanadium_lvgo"), raw.get("vanadium_hvgo"))
            return CutProperties(
                api=api, sulfur=sulfur, spg=spg,
                ccr=ccr, nickel=nickel, vanadium=vanadium,
            )
        else:
            return CutProperties(
                api=raw.get("api"),
                sulfur=raw.get("sulfur"),
                spg=raw.get("spg"),
                ron=raw.get("ron"),
                nitrogen=raw.get("nitrogen"),
                ccr=raw.get("ccr"),
                nickel=raw.get("nickel"),
                vanadium=raw.get("vanadium"),
            )

    @staticmethod
    def _avg(a: Optional[float], b: Optional[float]) -> Optional[float]:
        """Average two optional values."""
        if a is not None and b is not None:
            return (a + b) / 2.0
        return a if a is not None else b

    # ------------------------------------------------------------------
    # Task 1.8: Parse Buy sheet
    # ------------------------------------------------------------------

    def parse_buy(self, library: CrudeLibrary) -> CrudeLibrary:
        """Parse Buy sheet and update CrudeAssay objects with price/availability."""
        ws = self._wb["Buy"]

        issues = validate_sheet(ws, BUY_SCHEMA)
        if issues:
            raise SchemaValidationError(
                f"Buy sheet validation failed: {'; '.join(issues)}"
            )

        # Find header row by searching for 'COST' or 'TEXT'
        header_row_num = 3  # Known from exploration
        col_index = self._build_col_header_index(ws, header_row_num)

        cost_col = col_index.get("COST")
        min_col = col_index.get("MIN")
        max_col = col_index.get("MAX")
        api_col = col_index.get("API")
        sul_col = col_index.get("!SUL")

        row_index = self._build_row_tag_index(ws)

        for crude_tag, row_num in row_index.items():
            assay = library.get(crude_tag)
            if assay is None:
                continue

            price = self._cell_value(ws, row_num, cost_col) if cost_col else None
            min_rate = self._cell_value(ws, row_num, min_col) if min_col else None
            max_rate = self._cell_value(ws, row_num, max_col) if max_col else None

            if price is not None:
                assay.price = price
            if max_rate is not None:
                # Convert from '000 BPD → BPD
                assay.max_rate = max_rate * 1000.0
            if min_rate is not None:
                assay.min_rate = min_rate * 1000.0

        return library

    # ------------------------------------------------------------------
    # Task 1.8: Parse Sell sheet
    # ------------------------------------------------------------------

    def parse_sell(self) -> dict[str, Product]:
        """Parse Sell sheet → dict of Products keyed by Eurekan names."""
        ws = self._wb["Sell"]

        issues = validate_sheet(ws, SELL_SCHEMA)
        if issues:
            raise SchemaValidationError(
                f"Sell sheet validation failed: {'; '.join(issues)}"
            )

        header_row_num = 3
        col_index = self._build_col_header_index(ws, header_row_num)

        price_col = col_index.get("PRICE")
        min_col = col_index.get("MIN")
        max_col = col_index.get("MAX")

        row_index = self._build_row_tag_index(ws)
        products: dict[str, Product] = {}

        for pims_tag, row_num in row_index.items():
            eurekan_name = PIMS_PRODUCT_MAP.get(pims_tag)
            if eurekan_name is None:
                continue  # Skip products we don't map

            price = self._cell_value(ws, row_num, price_col) if price_col else None
            min_demand = self._cell_value(ws, row_num, min_col) if min_col else None
            max_demand = self._cell_value(ws, row_num, max_col) if max_col else None

            # Read display name from column B
            name_val = ws.cell(row=row_num, column=2).value
            display_name = str(name_val).strip() if name_val else eurekan_name

            products[eurekan_name] = Product(
                product_id=eurekan_name,
                name=display_name,
                price=price if price is not None else 0.0,
                min_demand=(min_demand * 1000.0) if min_demand is not None else 0.0,
                max_demand=(max_demand * 1000.0) if max_demand is not None else None,
            )

        return products
