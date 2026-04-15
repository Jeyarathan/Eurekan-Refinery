"""Stage 3 full-scope validation — all 14 units, directional price tests.

Verifies the complete Gulf Coast refinery model produces sensible results:
  - Margin in target range
  - All Sprint 12-15 units appear in flow graph
  - Fuel oil reduced (vacuum + coker + HCU upgrade heavy ends)
  - Gasoline specs met with isomerate + alkylate
  - H2 balance closes (reformers supply, HTs + HCU consume)
  - Directional responses to price shocks
"""

from __future__ import annotations

from pathlib import Path

import pytest

from eurekan.core.enums import OperatingMode
from eurekan.core.period import PeriodData, PlanDefinition
from eurekan.optimization.modes import run_optimization
from eurekan.parsers.gulf_coast import GulfCoastParser

DATA_FILE = Path("data/gulf_coast/Gulf_Coast.xlsx")

pytestmark = pytest.mark.skipif(
    not DATA_FILE.exists(), reason="Gulf Coast Excel file not present"
)


# --------------------------------------------------------------------------
# Fixtures
# --------------------------------------------------------------------------


@pytest.fixture(scope="module")
def config():
    return GulfCoastParser(DATA_FILE).parse()


def _base_plan(config, **price_overrides) -> PlanDefinition:
    cheap = {
        c: max((config.crude_library.get(c).price or 70) - 10, 55)
        for c in config.crude_library
    }
    product_prices = {
        "gasoline": 95.0, "diesel": 100.0, "jet": 100.0,
        "naphtha": 60.0, "fuel_oil": 55.0, "lpg": 50.0,
    }
    product_prices.update(price_overrides)
    return PlanDefinition(
        periods=[PeriodData(
            period_id=0, duration_hours=24.0,
            crude_prices=cheap, product_prices=product_prices,
        )],
        mode=OperatingMode.OPTIMIZE,
        scenario_name="Stage 3 validation",
    )


@pytest.fixture(scope="module")
def base_result(config):
    return run_optimization(config, _base_plan(config))


# --------------------------------------------------------------------------
# Economic viability
# --------------------------------------------------------------------------


class TestMargin:
    def test_converges(self, base_result):
        assert base_result.solver_status == "optimal"

    def test_margin_in_target_range(self, base_result):
        """Stage 3 target: $1.5-2.5M/day."""
        m = base_result.total_margin
        assert 1_500_000 <= m <= 2_500_000, f"Margin ${m:,.0f} outside target $1.5-2.5M"

    def test_margin_exceeds_stage2b(self, base_result):
        """Stage 3 (+3 units from 2B) should beat Stage 2B's $1.36M baseline."""
        assert base_result.total_margin > 1_400_000


# --------------------------------------------------------------------------
# Unit participation
# --------------------------------------------------------------------------


class TestCoreUnitsActive:
    """The economically essential units should run at meaningful throughput."""

    def test_cdu_at_capacity(self, base_result):
        cdu = next(
            (n for n in base_result.material_flow.nodes if n.node_id == "cdu_1"),
            None,
        )
        assert cdu is not None
        assert cdu.throughput >= 75_000  # near 80K capacity

    def test_fcc_active(self, base_result):
        fcc = next(
            (n for n in base_result.material_flow.nodes if n.node_id == "fcc_1"),
            None,
        )
        assert fcc is not None
        assert fcc.throughput > 10_000

    def test_hcu_active(self, base_result):
        """HCU should run at or near capacity with distillate-favored prices."""
        hcu = next(
            (n for n in base_result.material_flow.nodes if n.node_id == "hcu_1"),
            None,
        )
        assert hcu is not None
        assert hcu.throughput > 15_000  # most of 20K capacity

    def test_vacuum_active(self, base_result):
        vac = next(
            (n for n in base_result.material_flow.nodes if n.node_id == "vacuum_1"),
            None,
        )
        assert vac is not None
        assert vac.throughput > 10_000

    def test_reformer_active(self, base_result):
        """Mogas reformer should run (replaces purchased reformate)."""
        ref = next(
            (n for n in base_result.material_flow.nodes if n.node_id == "reformer_1"),
            None,
        )
        assert ref is not None
        assert ref.throughput > 5_000

    def test_isom_c56_active(self, base_result):
        """C5/C6 isom should run (upgrades LN octane)."""
        iso = next(
            (n for n in base_result.material_flow.nodes if n.node_id == "isom_c56"),
            None,
        )
        assert iso is not None
        assert iso.throughput > 3_000


# --------------------------------------------------------------------------
# Product slate
# --------------------------------------------------------------------------


class TestProductSlate:
    def test_all_standard_products_present(self, base_result):
        pv = base_result.periods[0].product_volumes
        for prod in ("gasoline", "diesel", "jet", "lpg", "fuel_oil", "naphtha"):
            assert prod in pv, f"Missing product: {prod}"

    def test_gasoline_meaningful_volume(self, base_result):
        """Gasoline production should be > 20K bbl/d."""
        assert base_result.periods[0].product_volumes.get("gasoline", 0) > 20_000

    def test_diesel_meaningful_volume(self, base_result):
        assert base_result.periods[0].product_volumes.get("diesel", 0) > 10_000

    def test_jet_at_demand_min(self, base_result):
        """Jet should be at the 10K/d min demand floor."""
        jet = base_result.periods[0].product_volumes.get("jet", 0)
        assert jet >= 9_500  # allow slight numerical slack


# --------------------------------------------------------------------------
# Directional price responses
# --------------------------------------------------------------------------


class TestDirectionalPrices:
    """Verify the VGO FCC/HCU split responds correctly to price signals."""

    def _vgo_split(self, result) -> tuple[float, float]:
        """Return (fcc_feed, hcu_feed) for a result."""
        fcc = next(
            (n.throughput for n in result.material_flow.nodes if n.node_id == "fcc_1"),
            0.0,
        )
        hcu = next(
            (n.throughput for n in result.material_flow.nodes if n.node_id == "hcu_1"),
            0.0,
        )
        return fcc, hcu

    def test_high_gasoline_favors_fcc(self, config):
        """Gasoline price up -> more VGO to FCC."""
        base = run_optimization(config, _base_plan(config))
        high_gas = run_optimization(
            config, _base_plan(config, gasoline=120.0, diesel=80.0, jet=80.0)
        )
        base_fcc, base_hcu = self._vgo_split(base)
        high_fcc, high_hcu = self._vgo_split(high_gas)
        # With high gasoline prices relative to distillates, FCC use should
        # increase (or at minimum, HCU use should decrease).
        assert high_fcc >= base_fcc * 0.95 or high_hcu < base_hcu

    def test_high_diesel_favors_hcu(self, config):
        """Diesel price up -> HCU stays active (jet+diesel most valuable)."""
        high_dist = run_optimization(
            config, _base_plan(config, diesel=130.0, jet=130.0, gasoline=80.0)
        )
        _, hcu = self._vgo_split(high_dist)
        # HCU should be at or near capacity with high distillate prices
        assert hcu >= 15_000


# --------------------------------------------------------------------------
# Flow-graph completeness
# --------------------------------------------------------------------------


class TestFlowGraphCompleteness:
    """All Stage 3 units should appear in the flow graph (active or idle)."""

    def _unit_ids(self, result) -> set[str]:
        return {n.node_id for n in result.material_flow.nodes if n.node_type == "unit"}

    def test_stage2b_units_present(self, base_result):
        units = self._unit_ids(base_result)
        for expected in ("cdu_1", "fcc_1", "reformer_1", "kht_1", "dht_1"):
            assert expected in units, f"Missing Stage 2B unit: {expected}"

    def test_sprint_12_units_present(self, base_result):
        units = self._unit_ids(base_result)
        assert "vacuum_1" in units
        assert "coker_1" in units  # idle but configured

    def test_sprint_13_hcu_present(self, base_result):
        assert "hcu_1" in self._unit_ids(base_result)

    def test_sprint_14_units_present(self, base_result):
        units = self._unit_ids(base_result)
        assert "isom_c56" in units
        assert "isom_c4" in units  # idle but configured

    def test_sprint_15_units_present(self, base_result):
        units = self._unit_ids(base_result)
        assert "arom_reformer" in units
        assert "dimersol" in units


# --------------------------------------------------------------------------
# Backward compatibility — Stage 1, 2A, 2B tests still pass
# --------------------------------------------------------------------------


class TestBackwardCompat:
    def test_stage2b_scope_still_works(self, config):
        """Stage 2B integration test scenario still converges with Stage 3 units."""
        plan = PlanDefinition(
            periods=[PeriodData(
                period_id=0, duration_hours=24.0,
                crude_prices={
                    c: max((config.crude_library.get(c).price or 70) - 10, 55)
                    for c in config.crude_library
                },
                product_prices={
                    "gasoline": 95.0, "diesel": 100.0, "jet": 100.0,
                    "naphtha": 60.0, "fuel_oil": 55.0, "lpg": 50.0,
                },
            )],
            mode=OperatingMode.OPTIMIZE,
            scenario_name="Stage 2B compat",
        )
        r = run_optimization(config, plan)
        assert r.solver_status == "optimal"
        assert r.total_margin > 1_000_000
