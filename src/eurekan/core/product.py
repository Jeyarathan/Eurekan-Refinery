"""Product specifications and blending rules."""

from __future__ import annotations

from typing import Optional

from pydantic import BaseModel

from eurekan.core.enums import BlendMethod


class ProductSpec(BaseModel):
    """A single quality specification for a product."""

    spec_name: str
    min_value: Optional[float] = None
    max_value: Optional[float] = None


class BlendingRule(BaseModel):
    """How a property blends across components."""

    property_name: str
    method: BlendMethod
    exponent: Optional[float] = None


class Product(BaseModel):
    """A saleable product with specs, blending rules, and allowed components."""

    product_id: str
    name: str
    price: float
    min_demand: float = 0.0
    max_demand: Optional[float] = None
    specs: list[ProductSpec] = []
    blending_rules: list[BlendingRule] = []
    allowed_components: list[str] = []

    def get_spec(self, name: str) -> Optional[ProductSpec]:
        """Return the spec with the given name, or None."""
        for s in self.specs:
            if s.spec_name == name:
                return s
        return None
