"""Tests for the optimization endpoints — Sprint 5 Task 5.3."""

from __future__ import annotations

from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from eurekan.api.app import app

DATA_FILE = Path("data/gulf_coast/Gulf_Coast.xlsx")

pytestmark = pytest.mark.skipif(
    not DATA_FILE.exists(), reason="Gulf Coast Excel file not present"
)


_PROFITABLE_PRICES: dict[str, float] = {
    "gasoline": 95.0,
    "diesel": 100.0,
    "jet": 100.0,
    "naphtha": 60.0,
    "fuel_oil": 70.0,
    "lpg": 50.0,
}


@pytest.fixture(scope="module")
def client() -> TestClient:
    with TestClient(app) as c:
        yield c


def _full_optimize_body(scenario_name: str = "Full") -> dict:
    return {
        "mode": "optimize",
        "periods": [
            {
                "period_id": 0,
                "duration_hours": 24.0,
                "product_prices": _PROFITABLE_PRICES,
            }
        ],
        "fixed_variables": {},
        "scenario_name": scenario_name,
    }


class TestOptimizeEndpoint:
    def test_optimize_endpoint_200(self, client):
        response = client.post("/api/optimize", json=_full_optimize_body("Endpoint test"))
        assert response.status_code == 200

    def test_optimize_returns_planning_result(self, client):
        response = client.post("/api/optimize", json=_full_optimize_body())
        body = response.json()
        assert "scenario_id" in body
        assert "total_margin" in body
        assert body["solver_status"] == "optimal"
        assert len(body["periods"]) == 1

    def test_optimize_margin_positive(self, client):
        response = client.post("/api/optimize", json=_full_optimize_body())
        assert response.json()["total_margin"] > 0


class TestQuickOptimizeEndpoint:
    def test_quick_optimize_no_body(self, client):
        """POST with no body should still work — uses default profitable prices."""
        response = client.post("/api/optimize/quick", json={})
        assert response.status_code == 200
        body = response.json()
        assert body["solver_status"] == "optimal"
        assert body["total_margin"] > 0

    def test_quick_optimize_with_overrides(self, client):
        response = client.post(
            "/api/optimize/quick",
            json={
                "product_prices": {"gasoline": 110.0},
                "scenario_name": "Gas spike",
            },
        )
        assert response.status_code == 200
        body = response.json()
        assert body["scenario_name"] == "Gas spike"
        assert body["total_margin"] > 0


class TestSimulateMode:
    def test_simulate_mode(self, client):
        body = {
            "mode": "simulate",
            "periods": [
                {
                    "period_id": 0,
                    "duration_hours": 24.0,
                    "product_prices": _PROFITABLE_PRICES,
                }
            ],
            "fixed_variables": {"fcc_conversion[0]": 80.0},
            "scenario_name": "Simulate test",
        }
        response = client.post("/api/optimize", json=body)
        assert response.status_code == 200
        result = response.json()
        # The fixed conversion should flow through the simulation
        assert abs(result["periods"][0]["fcc_result"]["conversion"] - 80.0) < 1e-6


class TestHybridMode:
    def test_hybrid_mode(self, client):
        body = {
            "mode": "hybrid",
            "periods": [
                {
                    "period_id": 0,
                    "duration_hours": 24.0,
                    "product_prices": _PROFITABLE_PRICES,
                }
            ],
            "fixed_variables": {"fcc_conversion[0]": 78.0},
            "scenario_name": "Hybrid test",
        }
        response = client.post("/api/optimize", json=body)
        assert response.status_code == 200
        result = response.json()
        assert result["solver_status"] == "optimal"
        assert abs(result["periods"][0]["fcc_result"]["conversion"] - 78.0) < 1e-3
