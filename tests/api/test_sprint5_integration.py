"""Sprint 5 end-to-end integration test.

Walks through every Sprint 5 endpoint in a single workflow:

  1. GET  /health
  2. POST /api/optimize/quick
  3. GET  /api/scenarios
  4. PUT  /api/config/crude/ARL/price
  5. GET  /api/config (is_stale = true)
  6. POST /api/scenarios/{id}/branch
  7. GET  /api/scenarios/compare
  8. GET  /api/scenarios/{id}/flow
  9. GET  /api/scenarios/{id}/diagnostics
  10. POST /api/oracle
"""

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
    """Fresh client per test so the in-memory state starts clean."""
    with TestClient(app) as c:
        yield c


def test_full_sprint5_workflow(client: TestClient):
    # ------------------------------------------------------------------
    # 1. GET /health → 200, crudes loaded
    # ------------------------------------------------------------------
    health = client.get("/health")
    assert health.status_code == 200
    health_body = health.json()
    assert health_body["status"] == "ok"
    assert health_body["crudes_loaded"] >= 40

    # ------------------------------------------------------------------
    # 2. POST /api/optimize/quick → PlanningResult, margin > 0
    # ------------------------------------------------------------------
    optimize_response = client.post(
        "/api/optimize/quick", json={"scenario_name": "Sprint 5 Base"}
    )
    assert optimize_response.status_code == 200
    base_scenario = optimize_response.json()
    assert base_scenario["solver_status"] == "optimal"
    assert base_scenario["total_margin"] > 0
    base_id = base_scenario["scenario_id"]
    base_margin = base_scenario["total_margin"]

    # ------------------------------------------------------------------
    # 3. GET /api/scenarios → at least 1 scenario
    # ------------------------------------------------------------------
    scenarios = client.get("/api/scenarios").json()
    assert len(scenarios) >= 1
    scenario_ids = {s["scenario_id"] for s in scenarios}
    assert base_id in scenario_ids

    # ------------------------------------------------------------------
    # 4. PUT /api/config/crude/ARL/price → 200
    # ------------------------------------------------------------------
    price_update = client.put(
        "/api/config/crude/ARL/price", json={"price": 80.0}
    )
    assert price_update.status_code == 200
    update_body = price_update.json()
    assert update_body["crude_id"] == "ARL"
    assert update_body["price"] == 80.0
    assert update_body["is_stale"] is True

    # ------------------------------------------------------------------
    # 5. GET /api/config → is_stale = true
    # ------------------------------------------------------------------
    config_after_edit = client.get("/api/config").json()
    assert config_after_edit["is_stale"] is True
    assert config_after_edit["crude_count"] >= 40

    # ------------------------------------------------------------------
    # 6. POST /api/scenarios/{id}/branch → new scenario
    # ------------------------------------------------------------------
    branch_response = client.post(
        f"/api/scenarios/{base_id}/branch",
        json={
            "name": "Sprint 5 Higher Gas",
            "changes": {"product_prices": {"gasoline": 120.0}},
        },
    )
    assert branch_response.status_code == 200
    branched = branch_response.json()
    assert branched["parent_scenario_id"] == base_id
    assert branched["scenario_id"] != base_id
    assert branched["scenario_name"] == "Sprint 5 Higher Gas"
    branch_id = branched["scenario_id"]
    # Higher gasoline price → higher margin
    assert branched["total_margin"] > base_margin

    # ------------------------------------------------------------------
    # 7. GET /api/scenarios/compare → ScenarioComparison with margin_delta
    # ------------------------------------------------------------------
    compare_response = client.get(
        "/api/scenarios/compare",
        params={"base": base_id, "comparison": branch_id},
    )
    assert compare_response.status_code == 200
    comparison = compare_response.json()
    assert comparison["base_scenario_id"] == base_id
    assert comparison["comparison_scenario_id"] == branch_id
    assert comparison["margin_delta"] > 0
    assert "key_insight" in comparison
    assert len(comparison["key_insight"]) > 0

    # ------------------------------------------------------------------
    # 8. GET /api/scenarios/{id}/flow → MaterialFlowGraph
    # ------------------------------------------------------------------
    flow_response = client.get(f"/api/scenarios/{base_id}/flow")
    assert flow_response.status_code == 200
    flow = flow_response.json()
    assert "nodes" in flow
    assert "edges" in flow
    assert len(flow["nodes"]) > 0
    assert len(flow["edges"]) > 0

    # ------------------------------------------------------------------
    # 9. GET /api/scenarios/{id}/diagnostics → non-empty list
    # ------------------------------------------------------------------
    diagnostics_response = client.get(f"/api/scenarios/{base_id}/diagnostics")
    assert diagnostics_response.status_code == 200
    diagnostics = diagnostics_response.json()
    assert isinstance(diagnostics, list)
    assert len(diagnostics) > 0
    binding = [d for d in diagnostics if d["binding"]]
    assert len(binding) > 0, "Expected at least one binding constraint"

    # ------------------------------------------------------------------
    # 10. POST /api/oracle with suboptimal decisions → gap > 0
    # ------------------------------------------------------------------
    crudes_response = client.get("/api/config/crudes").json()
    most_expensive = max(crudes_response, key=lambda c: c["price"] or 0.0)["crude_id"]
    oracle_response = client.post(
        "/api/oracle",
        json={
            "actual_decisions": {
                f"crude_rate[{most_expensive},0]": 60_000.0,
                "fcc_conversion[0]": 75.0,
            }
        },
    )
    assert oracle_response.status_code == 200
    oracle = oracle_response.json()
    assert "actual_margin" in oracle
    assert "optimal_margin" in oracle
    assert "gap" in oracle
    assert "gap_sources" in oracle
    assert oracle["gap"] > 0  # suboptimal → real gap


def test_sprint5_workflow_after_optimize_resets_stale(client: TestClient):
    """Optimizing after a price edit should reset the stale flag."""
    client.post("/api/optimize/quick", json={})
    client.put("/api/config/crude/ARL/price", json={"price": 78.5})
    assert client.get("/api/config").json()["is_stale"] is True
    client.post("/api/optimize/quick", json={})
    assert client.get("/api/config").json()["is_stale"] is False
