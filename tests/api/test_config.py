"""Tests for the config endpoints — Sprint 5 Task 5.4."""

from __future__ import annotations

from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from eurekan.api.app import app

DATA_FILE = Path("data/gulf_coast/Gulf_Coast.xlsx")

pytestmark = pytest.mark.skipif(
    not DATA_FILE.exists(), reason="Gulf Coast Excel file not present"
)


@pytest.fixture
def client() -> TestClient:
    """Fresh client per test so the stale flag starts predictable."""
    with TestClient(app) as c:
        yield c


class TestGetConfig:
    def test_get_config(self, client):
        response = client.get("/api/config")
        assert response.status_code == 200
        body = response.json()
        assert "name" in body
        assert "units" in body
        assert isinstance(body["units"], list)
        assert body["crude_count"] >= 40
        assert body["product_count"] > 0
        assert "completeness" in body
        assert "is_stale" in body

    def test_units_have_expected_fields(self, client):
        body = client.get("/api/config").json()
        for unit in body["units"]:
            assert "id" in unit
            assert "type" in unit
            assert "capacity" in unit


class TestGetCrudes:
    def test_get_crudes_list(self, client):
        response = client.get("/api/config/crudes")
        assert response.status_code == 200
        crudes = response.json()
        assert isinstance(crudes, list)
        assert len(crudes) >= 40
        first = crudes[0]
        for field in ("crude_id", "name", "api", "sulfur", "price", "max_rate"):
            assert field in first


class TestGetProducts:
    def test_get_products_list(self, client):
        response = client.get("/api/config/products")
        assert response.status_code == 200
        products = response.json()
        assert isinstance(products, list)
        assert len(products) > 0
        first = products[0]
        for field in ("product_id", "name", "price", "specs"):
            assert field in first


class TestGetCompleteness:
    def test_get_completeness(self, client):
        response = client.get("/api/config/completeness")
        assert response.status_code == 200
        body = response.json()
        for field in ("overall_pct", "missing", "ready_to_optimize", "margin_uncertainty_pct"):
            assert field in body


class TestUpdateCrudePrice:
    def test_update_crude_price(self, client):
        response = client.put(
            "/api/config/crude/ARL/price", json={"price": 65.0}
        )
        assert response.status_code == 200
        body = response.json()
        assert body["crude_id"] == "ARL"
        assert body["price"] == 65.0
        assert body["is_stale"] is True

    def test_update_unknown_crude_404(self, client):
        response = client.put(
            "/api/config/crude/NOPE/price", json={"price": 65.0}
        )
        assert response.status_code == 404


class TestUpdateProductPrice:
    def test_update_product_price(self, client):
        # Use a product known to exist in the Gulf Coast parser output
        response = client.put(
            "/api/config/product/regular_gasoline/price", json={"price": 100.0}
        )
        assert response.status_code == 200
        body = response.json()
        assert body["product_id"] == "regular_gasoline"
        assert body["price"] == 100.0
        assert body["is_stale"] is True

    def test_update_unknown_product_404(self, client):
        response = client.put(
            "/api/config/product/missing/price", json={"price": 100.0}
        )
        assert response.status_code == 404


class TestStaleFlagFlow:
    def test_stale_flag_after_price_change(self, client):
        # Reset by running a quick optimize
        client.post("/api/optimize/quick", json={})
        config_before = client.get("/api/config").json()
        assert config_before["is_stale"] is False

        client.put("/api/config/crude/ARL/price", json={"price": 65.0})
        config_after = client.get("/api/config").json()
        assert config_after["is_stale"] is True

    def test_optimize_resets_stale(self, client):
        client.put("/api/config/crude/ARL/price", json={"price": 65.0})
        client.post("/api/optimize/quick", json={})
        body = client.get("/api/config").json()
        assert body["is_stale"] is False
