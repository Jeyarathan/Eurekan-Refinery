"""Sheet schema validation for Excel-based PIMS data files."""

from __future__ import annotations

from pydantic import BaseModel


class SheetSchema(BaseModel):
    """Expected structure of a Gulf Coast Excel sheet."""

    sheet_name: str
    required_row_tags: list[str]
    required_column_tags: list[str] = []


class SchemaValidationError(Exception):
    """Raised when Excel data doesn't match expected schema."""


def validate_sheet(ws, schema: SheetSchema) -> list[str]:
    """Check sheet against schema. Return list of issues (empty = OK).

    Parameters
    ----------
    ws : openpyxl Worksheet
    schema : SheetSchema defining expected row and column tags
    """
    issues: list[str] = []

    # Collect all values in column A (row tags)
    row_tags: set[str] = set()
    for row in ws.iter_rows(min_col=1, max_col=1):
        val = row[0].value
        if val is not None:
            row_tags.add(str(val).strip())

    for tag in schema.required_row_tags:
        if tag not in row_tags:
            issues.append(
                f"Expected row tag '{tag}' not found in {schema.sheet_name} sheet"
            )

    # Collect all values across all rows for column tag checks
    if schema.required_column_tags:
        col_tags: set[str] = set()
        for row in ws.iter_rows():
            for cell in row:
                if cell.value is not None:
                    col_tags.add(str(cell.value).strip())
        for tag in schema.required_column_tags:
            if tag not in col_tags:
                issues.append(
                    f"Expected column tag '{tag}' not found in {schema.sheet_name} sheet"
                )

    return issues
