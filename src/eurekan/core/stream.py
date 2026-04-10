"""Stream model — a material flow between units."""

from __future__ import annotations

from typing import Optional

from pydantic import BaseModel

from eurekan.core.crude import CutProperties
from eurekan.core.enums import StreamDisposition


class Stream(BaseModel):
    """A material stream connecting units in the refinery."""

    stream_id: str
    source_unit: str
    stream_type: str
    possible_dispositions: list[StreamDisposition] = []
    properties: Optional[CutProperties] = None
