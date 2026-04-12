"""Stage 2A end-to-end integration test — Sprint 8 Task 8.5.

Full workflow: optimize → narrative → alternatives → compare.
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
    with TestClient(app) as c:
        yield c


def test_stage2a_full_workflow(client: TestClient):
    # 1. Quick optimize → base scenario
    r1 = client.post("/api/optimize/quick", json={"scenario_name": "Stage2 Base"})
    assert r1.status_code == 200
    base = r1.json()
    assert base["solver_status"] == "optimal"
    assert base["total_margin"] > 0
    base_id = base["scenario_id"]

    # 2. Generate narrative for the base scenario
    r2 = client.post("/api/ai/narrative", json={"scenario_id": base_id})
    assert r2.status_code == 200
    narr = r2.json()
    assert "executive_summary" in narr
    assert len(narr["executive_summary"]) > 20
    assert "decision_explanations" in narr
    assert len(narr["decision_explanations"]) > 0
    assert "risk_flags" in narr

    # 3. Enumerate near-optimal alternatives
    r3 = client.post(
        "/api/ai/alternatives",
        json={"scenario_id": base_id, "tolerance": 0.05},
    )
    assert r3.status_code == 200
    alts = r3.json()
    assert isinstance(alts, list)
    assert len(alts) >= 1  # at least one near-optimal alternative
    assert alts[0]["margin"] > 0
    assert "name" in alts[0]
    assert "description" in alts[0]

    # 4. Branch scenario with higher gasoline price
    r4 = client.post(
        f"/api/scenarios/{base_id}/branch",
        json={
            "name": "Stage2 Gas+15",
            "changes": {"product_prices": {"gasoline": 110.0}},
        },
    )
    assert r4.status_code == 200
    branch = r4.json()
    branch_id = branch["scenario_id"]
    assert branch["total_margin"] > base["total_margin"]

    # 5. Compare base vs branch
    r5 = client.get(
        "/api/scenarios/compare",
        params={"base": base_id, "comparison": branch_id},
    )
    assert r5.status_code == 200
    comp = r5.json()
    assert comp["margin_delta"] > 0
    assert "key_insight" in comp

    # 6. Generate narrative for the branch
    r6 = client.post("/api/ai/narrative", json={"scenario_id": branch_id})
    assert r6.status_code == 200
    narr2 = r6.json()
    assert len(narr2["executive_summary"]) > 20

    # 7. Oracle analysis with suboptimal decisions
    crudes = client.get("/api/config/crudes").json()
    expensive = max(crudes, key=lambda c: c["price"] or 0)["crude_id"]
    r7 = client.post(
        "/api/oracle",
        json={
            "actual_decisions": {
                f"crude_rate[{expensive},0]": 60000.0,
                "fcc_conversion[0]": 75.0,
            }
        },
    )
    assert r7.status_code == 200
    oracle = r7.json()
    assert oracle["gap"] > 0

    # 8. Verify scenario count
    r8 = client.get("/api/scenarios")
    assert r8.status_code == 200
    scenarios = r8.json()
    assert len(scenarios) >= 2  # base + branch (alternatives may add more)
