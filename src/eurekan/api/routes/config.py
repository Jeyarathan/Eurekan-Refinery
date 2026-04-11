"""Configuration endpoints — Sprint 5 Task 5.4."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, HTTPException, Request

from eurekan.api.schemas import PriceUpdateRequest
from eurekan.api.services import RefineryService
from eurekan.core.config import ConfigCompleteness

router = APIRouter(prefix="/api/config", tags=["config"])


def _service(request: Request) -> RefineryService:
    return request.app.state.service


@router.get("")
def get_config(request: Request) -> dict[str, Any]:
    """High-level config summary: name, units, counts, completeness, stale flag."""
    service = _service(request)
    config = service.config
    return {
        "name": config.name,
        "units": [
            {
                "id": u.unit_id,
                "type": u.unit_type.value,
                "capacity": u.capacity,
            }
            for u in config.units.values()
        ],
        "crude_count": len(config.crude_library),
        "product_count": len(config.products),
        "completeness": config.completeness().model_dump(),
        "is_stale": service.is_stale,
    }


@router.get("/crudes")
def get_crudes(request: Request) -> list[dict[str, Any]]:
    """List of crudes with id, name, API, sulfur, price, max_rate."""
    config = _service(request).config
    crudes: list[dict[str, Any]] = []
    for crude_id in config.crude_library.list_crudes():
        assay = config.crude_library.get(crude_id)
        if assay is None:
            continue
        crudes.append(
            {
                "crude_id": assay.crude_id,
                "name": assay.name,
                "api": assay.api,
                "sulfur": assay.sulfur,
                "price": assay.price,
                "max_rate": assay.max_rate,
            }
        )
    return crudes


@router.get("/products")
def get_products(request: Request) -> list[dict[str, Any]]:
    """List of products with specs."""
    config = _service(request).config
    products: list[dict[str, Any]] = []
    for product in config.products.values():
        products.append(
            {
                "product_id": product.product_id,
                "name": product.name,
                "price": product.price,
                "min_demand": product.min_demand,
                "max_demand": product.max_demand,
                "specs": [
                    {
                        "name": spec.spec_name,
                        "min": spec.min_value,
                        "max": spec.max_value,
                    }
                    for spec in product.specs
                ],
            }
        )
    return products


@router.get("/completeness", response_model=ConfigCompleteness)
def get_completeness(request: Request) -> ConfigCompleteness:
    return _service(request).config.completeness()


@router.put("/crude/{crude_id}/price")
def update_crude_price(
    request: Request, crude_id: str, body: PriceUpdateRequest
) -> dict[str, Any]:
    """Update a crude price in-memory and mark the service stale."""
    service = _service(request)
    try:
        service.update_crude_price(crude_id, body.price)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    return {"crude_id": crude_id, "price": body.price, "is_stale": service.is_stale}


@router.put("/product/{product_id}/price")
def update_product_price(
    request: Request, product_id: str, body: PriceUpdateRequest
) -> dict[str, Any]:
    """Update a product price in-memory and mark the service stale."""
    service = _service(request)
    try:
        service.update_product_price(product_id, body.price)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    return {
        "product_id": product_id,
        "price": body.price,
        "is_stale": service.is_stale,
    }
