"""Gasoline blending model — ASTM standard methods.

Implements the four blending methods used by the optimizer:
  - INDEX (RON, MON):  blending index method, NONLINEAR
  - POWER_LAW (RVP):   power-law with exponent 1.25
  - LINEAR_WEIGHT:     weight-fraction blending (sulfur)
  - LINEAR_VOLUME:     volume-fraction blending (benzene, aromatics, olefins)

The RON blending index is mandatory — linear-by-volume blending of RON
gives systematically wrong answers (off by 1-3 octane numbers, which
matters when the spec margin is fractional).
"""

from __future__ import annotations

import math

from eurekan.core.crude import CutProperties
from eurekan.core.enums import BlendMethod
from eurekan.core.product import Product
from eurekan.core.results import SpecResult

# ---------------------------------------------------------------------------
# Blending Index coefficients (Ethyl Corporation method, ASTM standard)
# ---------------------------------------------------------------------------
_BI_A = 0.0037397  # quadratic coefficient
_BI_B = 0.83076  # linear coefficient
_BI_C = -36.1572  # constant

# Power-law exponent for RVP blending (Chevron, ASTM)
_RVP_EXPONENT = 1.25

# Default specific gravity used when a component lacks SPG data
_DEFAULT_SPG = 0.75


def _ron_to_bi(ron: float) -> float:
    """Convert RON to its blending index."""
    return _BI_C + _BI_B * ron + _BI_A * ron * ron


def _bi_to_ron(bi: float) -> float:
    """Invert the BI quadratic to recover RON.

    Solves _BI_A*RON^2 + _BI_B*RON + (_BI_C - bi) = 0
    using the positive root of the quadratic formula.
    """
    a = _BI_A
    b = _BI_B
    c = _BI_C - bi
    discriminant = b * b - 4.0 * a * c
    if discriminant < 0:
        # Should not happen for any physical BI; clamp to zero
        discriminant = 0.0
    return (-b + math.sqrt(discriminant)) / (2.0 * a)


class BlendingModel:
    """Gasoline blending calculations using ASTM standard methods."""

    def calculate_blend_property(
        self,
        component_volumes: dict[str, float],
        component_properties: dict[str, CutProperties],
        property_name: str,
        method: BlendMethod,
    ) -> float:
        """Calculate a blended property value across components.

        Args:
            component_volumes: {component_id: volume}
            component_properties: {component_id: CutProperties}
            property_name: name of the property on CutProperties (e.g. 'ron', 'rvp')
            method: blending method to apply

        Returns:
            Blended property value. Returns 0.0 if no components have the property.
        """
        total_vol = sum(v for v in component_volumes.values() if v > 0)
        if total_vol <= 0:
            return 0.0

        if method == BlendMethod.INDEX:
            return self._blend_index(
                component_volumes, component_properties, property_name, total_vol
            )
        if method == BlendMethod.POWER_LAW:
            return self._blend_power_law(
                component_volumes, component_properties, property_name, total_vol
            )
        if method == BlendMethod.LINEAR_WEIGHT:
            return self._blend_linear_weight(
                component_volumes, component_properties, property_name
            )
        if method == BlendMethod.LINEAR_VOLUME:
            return self._blend_linear_volume(
                component_volumes, component_properties, property_name, total_vol
            )

        raise ValueError(f"Unknown blend method: {method}")

    def check_specs(
        self,
        blend_properties: dict[str, float],
        product: Product,
    ) -> list[SpecResult]:
        """Check every product spec against the blended properties.

        Returns one SpecResult per spec defined on the product. Specs whose
        property is missing from blend_properties are reported as feasible
        with value=0 (so the optimizer can still inspect the structure).
        """
        results: list[SpecResult] = []
        for spec in product.specs:
            value = blend_properties.get(spec.spec_name, 0.0)

            if spec.max_value is not None:
                limit = spec.max_value
                margin = limit - value
                feasible = value <= limit + 1e-9
            elif spec.min_value is not None:
                limit = spec.min_value
                margin = value - limit
                feasible = value >= limit - 1e-9
            else:
                limit = 0.0
                margin = 0.0
                feasible = True

            results.append(
                SpecResult(
                    spec_name=spec.spec_name,
                    value=value,
                    limit=limit,
                    margin=margin,
                    feasible=feasible,
                )
            )
        return results

    # ------------------------------------------------------------------
    # Internal blending methods
    # ------------------------------------------------------------------

    def _blend_index(
        self,
        volumes: dict[str, float],
        properties: dict[str, CutProperties],
        prop: str,
        total_vol: float,
    ) -> float:
        """Blending Index method for octane (RON / MON)."""
        bi_sum = 0.0
        used_vol = 0.0
        for comp_id, vol in volumes.items():
            if vol <= 0:
                continue
            cprops = properties.get(comp_id)
            if cprops is None:
                continue
            ron = getattr(cprops, prop, None)
            if ron is None:
                continue
            bi_sum += vol * _ron_to_bi(ron)
            used_vol += vol

        if used_vol <= 0:
            return 0.0
        blend_bi = bi_sum / used_vol
        return _bi_to_ron(blend_bi)

    def _blend_power_law(
        self,
        volumes: dict[str, float],
        properties: dict[str, CutProperties],
        prop: str,
        total_vol: float,
    ) -> float:
        """Power-law blending (RVP^1.25)."""
        weighted_sum = 0.0
        used_vol = 0.0
        for comp_id, vol in volumes.items():
            if vol <= 0:
                continue
            cprops = properties.get(comp_id)
            if cprops is None:
                continue
            val = getattr(cprops, prop, None)
            if val is None or val <= 0:
                continue
            weighted_sum += vol * (val**_RVP_EXPONENT)
            used_vol += vol

        if used_vol <= 0:
            return 0.0
        return (weighted_sum / used_vol) ** (1.0 / _RVP_EXPONENT)

    def _blend_linear_weight(
        self,
        volumes: dict[str, float],
        properties: dict[str, CutProperties],
        prop: str,
    ) -> float:
        """Weight-fraction blending. Used for sulfur."""
        weighted_sum = 0.0
        total_wt = 0.0
        for comp_id, vol in volumes.items():
            if vol <= 0:
                continue
            cprops = properties.get(comp_id)
            if cprops is None:
                continue
            val = getattr(cprops, prop, None)
            if val is None:
                continue
            spg = cprops.spg if cprops.spg is not None else _DEFAULT_SPG
            wt = vol * spg
            weighted_sum += wt * val
            total_wt += wt

        if total_wt <= 0:
            return 0.0
        return weighted_sum / total_wt

    def _blend_linear_volume(
        self,
        volumes: dict[str, float],
        properties: dict[str, CutProperties],
        prop: str,
        total_vol: float,
    ) -> float:
        """Volume-fraction blending. Used for benzene, aromatics, olefins."""
        weighted_sum = 0.0
        used_vol = 0.0
        for comp_id, vol in volumes.items():
            if vol <= 0:
                continue
            cprops = properties.get(comp_id)
            if cprops is None:
                continue
            val = getattr(cprops, prop, None)
            if val is None:
                continue
            weighted_sum += vol * val
            used_vol += vol

        if used_vol <= 0:
            return 0.0
        return weighted_sum / used_vol
