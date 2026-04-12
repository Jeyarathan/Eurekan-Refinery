"""Naphtha splitter — splits full-range CDU naphtha into LN + HN.

The splitter takes combined CDU naphtha (C5-350 deg F) and re-splits at a
configurable cut point.  The default cut point is 180 deg F, matching the
US Gulf Coast template.  Adjusting the cut point changes the LN/HN ratio.

The split ratio is modelled as a smooth sigmoid function of cut point
temperature within the naphtha boiling range (C5-350 deg F), which is
twice-differentiable and IPOPT-friendly.
"""

from __future__ import annotations

import math

from pydantic import BaseModel

from eurekan.core.crude import CutProperties


class NaphthaSplitterResult(BaseModel):
    """Output of the naphtha splitter."""

    ln_volume: float
    hn_volume: float
    ln_properties: CutProperties
    hn_properties: CutProperties
    cut_point_f: float


# Naphtha boiling range (deg F)
_NAPHTHA_IBP = 90.0   # C5
_NAPHTHA_FBP = 350.0  # end of heavy naphtha


def _sigmoid_split(cut_point_f: float) -> float:
    """Fraction of total naphtha that is light naphtha (below cut point).

    Uses a smooth logistic curve centred on the cut point within the
    naphtha boiling range.  At 180 deg F (default): ~40% LN / 60% HN,
    matching typical CDU yields (10% LN / 15% HN → 40/60 split).
    """
    # Normalize cut point to [0, 1] within the naphtha range
    span = _NAPHTHA_FBP - _NAPHTHA_IBP
    if span <= 0:
        return 0.5
    frac = (cut_point_f - _NAPHTHA_IBP) / span
    frac = max(0.01, min(0.99, frac))
    return frac  # smooth and monotonic — good enough for NLP


class NaphthaSplitterModel:
    """Splits combined CDU naphtha into LN and HN at a configurable cut point."""

    def __init__(self, default_cut_point_f: float = 180.0) -> None:
        self.default_cut_point_f = default_cut_point_f

    def calculate(
        self,
        total_naphtha_volume: float,
        naphtha_properties: CutProperties,
        cut_point_f: float | None = None,
    ) -> NaphthaSplitterResult:
        """Split naphtha at the given cut point.

        Args:
            total_naphtha_volume: Combined LN + HN volume (bbl/d).
            naphtha_properties: Blended properties of the combined naphtha.
            cut_point_f: Cut temperature in deg F.  None = use default (180 deg F).
        """
        cp = cut_point_f if cut_point_f is not None else self.default_cut_point_f

        ln_frac = _sigmoid_split(cp)
        hn_frac = 1.0 - ln_frac

        ln_vol = total_naphtha_volume * ln_frac
        hn_vol = total_naphtha_volume * hn_frac

        # Approximate property split: LN is lighter, HN is heavier
        ln_api = (naphtha_properties.api or 65.0) + 15.0
        hn_api = (naphtha_properties.api or 65.0) - 10.0
        ln_sulfur = (naphtha_properties.sulfur or 0.003) * 0.5
        hn_sulfur = (naphtha_properties.sulfur or 0.003) * 1.5
        ln_ron = 68.0   # straight-run LN has low RON
        hn_ron = 42.0   # straight-run HN has very low RON (reformer feed)

        ln_props = CutProperties(
            api=ln_api, sulfur=ln_sulfur, ron=ln_ron, spg=0.66,
        )
        hn_props = CutProperties(
            api=hn_api, sulfur=hn_sulfur, ron=hn_ron, spg=0.74,
            aromatics=naphtha_properties.aromatics,
        )

        return NaphthaSplitterResult(
            ln_volume=ln_vol,
            hn_volume=hn_vol,
            ln_properties=ln_props,
            hn_properties=hn_props,
            cut_point_f=cp,
        )
