"""Tests for scenario, flow, diagnostics, and oracle endpoints — Sprint 5 Task 5.5."""

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
    """Fresh client per test so the scenario store starts empty."""
    with TestClient(app) as c:
        yield c


def _quick_optimize(client: TestClient, name: str = "Base") -> dict:
    response = client.post("/api/optimize/quick", json={"scenario_name": name})
    assert response.status_code == 200
    return response.json()


# ---------------------------------------------------------------------------
# List & get scenarios
# ---------------------------------------------------------------------------


class TestListScenarios:
    def test_list_scenarios_empty(self, client):
        response = client.get("/api/scenarios")
        assert response.status_code == 200
        assert response.json() == []

    def test_optimize_then_list(self, client):
        _quick_optimize(client, "First")
        _quick_optimize(client, "Second")
        response = client.get("/api/scenarios")
        body = response.json()
        assert len(body) == 2
        names = {s["scenario_name"] for s in body}
        assert names == {"First", "Second"}


class TestGetScenario:
    def test_get_scenario_by_id(self, client):
        scenario = _quick_optimize(client, "Get test")
        sid = scenario["scenario_id"]
        response = client.get(f"/api/scenarios/{sid}")
        assert response.status_code == 200
        body = response.json()
        assert body["scenario_id"] == sid
        assert body["scenario_name"] == "Get test"

    def test_get_unknown_scenario_404(self, client):
        response = client.get("/api/scenarios/missing")
        assert response.status_code == 404


# ---------------------------------------------------------------------------
# Branch & compare
# ---------------------------------------------------------------------------


class TestBranchScenario:
    def test_branch_scenario(self, client):
        base = _quick_optimize(client, "Branch base")
        sid = base["scenario_id"]
        response = client.post(
            f"/api/scenarios/{sid}/branch",
            json={
                "name": "Branch high gas",
                "changes": {"product_prices": {"gasoline": 120.0}},
            },
        )
        assert response.status_code == 200
        body = response.json()
        assert body["parent_scenario_id"] == sid
        assert body["scenario_name"] == "Branch high gas"
        # Higher gasoline price → higher margin
        assert body["total_margin"] > base["total_margin"]

    def test_branch_unknown_parent_404(self, client):
        response = client.post(
            "/api/scenarios/nope/branch",
            json={"name": "X", "changes": {}},
        )
        assert response.status_code == 404


class TestCompareScenarios:
    def test_compare_scenarios(self, client):
        base = _quick_optimize(client, "Compare base")
        branched = client.post(
            f"/api/scenarios/{base['scenario_id']}/branch",
            json={
                "name": "Compare branch",
                "changes": {"product_prices": {"gasoline": 120.0}},
            },
        ).json()

        response = client.get(
            "/api/scenarios/compare",
            params={
                "base": base["scenario_id"],
                "comparison": branched["scenario_id"],
            },
        )
        assert response.status_code == 200
        body = response.json()
        assert body["base_scenario_id"] == base["scenario_id"]
        assert body["comparison_scenario_id"] == branched["scenario_id"]
        assert body["margin_delta"] > 0
        assert "key_insight" in body

    def test_compare_unknown_404(self, client):
        base = _quick_optimize(client)
        response = client.get(
            "/api/scenarios/compare",
            params={"base": base["scenario_id"], "comparison": "missing"},
        )
        assert response.status_code == 404


# ---------------------------------------------------------------------------
# Flow / diagnostics / disposition
# ---------------------------------------------------------------------------


class TestFlowGraph:
    def test_get_flow_graph(self, client):
        scenario = _quick_optimize(client, "Flow test")
        response = client.get(f"/api/scenarios/{scenario['scenario_id']}/flow")
        assert response.status_code == 200
        body = response.json()
        assert "nodes" in body
        assert "edges" in body
        assert len(body["nodes"]) > 0
        assert len(body["edges"]) > 0

    def test_flow_unknown_scenario_404(self, client):
        response = client.get("/api/scenarios/missing/flow")
        assert response.status_code == 404


class TestDiagnostics:
    def test_get_diagnostics(self, client):
        scenario = _quick_optimize(client, "Diag test")
        response = client.get(
            f"/api/scenarios/{scenario['scenario_id']}/diagnostics"
        )
        assert response.status_code == 200
        diagnostics = response.json()
        assert isinstance(diagnostics, list)
        assert len(diagnostics) > 0
        # At least one binding constraint
        binding = [d for d in diagnostics if d["binding"]]
        assert len(binding) > 0

    def test_diagnostics_unknown_scenario_404(self, client):
        response = client.get("/api/scenarios/missing/diagnostics")
        assert response.status_code == 404


class TestCrudeDisposition:
    def test_get_crude_disposition(self, client):
        scenario = _quick_optimize(client, "Disposition test")
        sid = scenario["scenario_id"]
        # Pick a crude that the optimizer actually used
        used = scenario["crude_valuations"]
        assert len(used) > 0
        crude_id = used[0]["crude_id"]
        response = client.get(f"/api/scenarios/{sid}/crude-disposition/{crude_id}")
        assert response.status_code == 200
        body = response.json()
        assert body["crude_id"] == crude_id
        assert body["total_volume"] > 0

    def test_crude_disposition_unknown_404(self, client):
        scenario = _quick_optimize(client)
        sid = scenario["scenario_id"]
        response = client.get(f"/api/scenarios/{sid}/crude-disposition/NOPE")
        assert response.status_code == 404


# ---------------------------------------------------------------------------
# Oracle
# ---------------------------------------------------------------------------


class TestOracleEndpoint:
    def test_oracle_returns_result(self, client):
        # Find the most expensive crude in the loaded library so we can pin it
        crudes = client.get("/api/config/crudes").json()
        most_expensive = max(crudes, key=lambda c: c["price"] or 0.0)["crude_id"]
        response = client.post(
            "/api/oracle",
            json={
                "actual_decisions": {
                    f"crude_rate[{most_expensive},0]": 60_000.0,
                    "fcc_conversion[0]": 75.0,
                }
            },
        )
        assert response.status_code == 200
        body = response.json()
        assert "actual_margin" in body
        assert "optimal_margin" in body
        assert "gap" in body
        assert "gap_sources" in body
        # Suboptimal actual → gap should be > 0
        assert body["gap"] > 0
