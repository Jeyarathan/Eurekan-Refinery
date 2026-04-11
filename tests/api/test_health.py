"""Tests for the /health endpoint — Sprint 5 Task 5.1."""

from __future__ import annotations

from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from eurekan.api.app import app

DATA_FILE = Path("data/gulf_coast/Gulf_Coast.xlsx")

pytestmark = pytest.mark.skipif(
    not DATA_FILE.exists(), reason="Gulf Coast Excel file not present"
)


@pytest.fixture(scope="module")
def client() -> TestClient:
    """TestClient drives the lifespan, so the Gulf Coast data is loaded once."""
    with TestClient(app) as c:
        yield c


class TestHealthEndpoint:
    def test_health_returns_200(self, client: TestClient):
        response = client.get("/health")
        assert response.status_code == 200

    def test_health_has_status_ok(self, client: TestClient):
        response = client.get("/health")
        body = response.json()
        assert body["status"] == "ok"

    def test_health_has_crudes(self, client: TestClient):
        response = client.get("/health")
        body = response.json()
        assert "crudes_loaded" in body
        assert body["crudes_loaded"] >= 40

    def test_health_reports_stale_flag(self, client: TestClient):
        response = client.get("/health")
        body = response.json()
        assert "is_stale" in body
        assert isinstance(body["is_stale"], bool)
