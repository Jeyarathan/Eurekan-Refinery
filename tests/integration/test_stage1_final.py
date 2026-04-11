"""Stage 1 final integration test — Sprint 4 Task 4.5.

End-to-end:
  Parse Gulf Coast Excel
    → build a 4-period weekly plan
    → optimize via EurekanSolver
    → verify inventory tracking, diagnostics, reports
    → JSON round-trip
"""

from __future__ import annotations

import json
from pathlib import Path

import pyomo.environ as pyo
import pytest

from eurekan.analysis.reports import format_console, format_json, format_summary
from eurekan.core.enums import OperatingMode, TankType
from eurekan.core.period import PeriodData, PlanDefinition
from eurekan.core.results import PlanningResult
from eurekan.core.tank import Tank
from eurekan.optimization.builder import PyomoModelBuilder
from eurekan.optimization.diagnostics import ConstraintDiagnostician
from eurekan.optimization.modes import run_optimization
from eurekan.optimization.solver import EurekanSolver
from eurekan.parsers.gulf_coast import GulfCoastParser

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
def gulf_coast_config():
    config = GulfCoastParser(DATA_FILE).parse()
    # Inject a gasoline tank so inventory tracking is exercised
    config.tanks["gasoline_tank"] = Tank(
        tank_id="gasoline_tank",
        tank_type=TankType.PRODUCT,
        capacity=2_000_000.0,
        minimum=0.0,
        current_level=0.0,
    )
    return config


@pytest.fixture(scope="module")
def four_week_plan() -> PlanDefinition:
    """4 weekly periods with a mid-plan gasoline price spike."""
    return PlanDefinition(
        periods=[
            PeriodData(
                period_id=0,
                duration_hours=168.0,
                product_prices={**_PROFITABLE_PRICES, "gasoline": 95.0},
            ),
            PeriodData(
                period_id=1,
                duration_hours=168.0,
                product_prices={**_PROFITABLE_PRICES, "gasoline": 95.0},
            ),
            PeriodData(
                period_id=2,
                duration_hours=168.0,
                product_prices={**_PROFITABLE_PRICES, "gasoline": 115.0},
            ),
            PeriodData(
                period_id=3,
                duration_hours=168.0,
                product_prices={**_PROFITABLE_PRICES, "gasoline": 95.0},
            ),
        ],
        mode=OperatingMode.OPTIMIZE,
        scenario_name="Stage 1 Final",
    )


@pytest.fixture(scope="module")
def planning_result(gulf_coast_config, four_week_plan) -> PlanningResult:
    return run_optimization(gulf_coast_config, four_week_plan)


# ---------------------------------------------------------------------------
# End-to-end pipeline
# ---------------------------------------------------------------------------


class TestStage1Pipeline:
    def test_parser_loads(self, gulf_coast_config):
        assert gulf_coast_config is not None
        assert len(gulf_coast_config.crude_library) >= 40
        assert "cdu_1" in gulf_coast_config.units
        assert "fcc_1" in gulf_coast_config.units

    def test_optimization_converges(self, planning_result):
        assert planning_result.solver_status == "optimal"
        assert len(planning_result.periods) == 4

    def test_total_margin_positive(self, planning_result):
        assert planning_result.total_margin > 0

    def test_all_periods_have_results(self, planning_result):
        for p in planning_result.periods:
            assert p.fcc_result is not None
            assert sum(p.crude_slate.values()) > 0
            assert p.product_volumes["gasoline"] > 0


# ---------------------------------------------------------------------------
# Inventory tracking
# ---------------------------------------------------------------------------


class TestInventoryTracking:
    def test_inventory_trajectory_present(self, planning_result):
        assert "gasoline" in planning_result.inventory_trajectory
        traj = planning_result.inventory_trajectory["gasoline"]
        assert len(traj) == 4

    def test_inventory_within_capacity(self, planning_result):
        traj = planning_result.inventory_trajectory["gasoline"]
        capacity = 2_000_000.0
        for p, level in enumerate(traj):
            assert -1e-6 <= level <= capacity + 1e-3, (
                f"Period {p}: inventory {level} out of bounds"
            )


# ---------------------------------------------------------------------------
# Diagnostics
# ---------------------------------------------------------------------------


class TestDiagnostics:
    def test_diagnostics_populated(self, gulf_coast_config, four_week_plan):
        """Run the diagnostician on a freshly solved model."""
        model = PyomoModelBuilder(gulf_coast_config, four_week_plan).build()
        solver = EurekanSolver()
        solve_result = solver.solve_with_fallback(
            model, gulf_coast_config, four_week_plan
        )
        assert solve_result.feasible

        diagnostician = ConstraintDiagnostician()
        diagnostics = diagnostician.diagnose_feasible(model)
        assert len(diagnostics) > 0

        binding = [d for d in diagnostics if d.binding]
        assert len(binding) > 0, "Expected at least one binding constraint"


# ---------------------------------------------------------------------------
# Reports
# ---------------------------------------------------------------------------


class TestReports:
    def test_console_report(self, planning_result):
        output = format_console(planning_result)
        assert isinstance(output, str)
        assert "EUREKAN PLANNING RESULT" in output
        assert "Stage 1 Final" in output
        assert "PERIOD 0" in output
        assert "PERIOD 3" in output
        assert "Margin" in output

    def test_summary_report(self, planning_result):
        summary = format_summary(planning_result)
        assert isinstance(summary, str)
        assert len(summary) > 50
        assert "Stage 1 Final" in summary
        assert "margin" in summary.lower()

    def test_json_report(self, planning_result):
        json_str = format_json(planning_result)
        # Must be valid JSON
        parsed = json.loads(json_str)
        assert isinstance(parsed, dict)
        assert parsed["scenario_name"] == "Stage 1 Final"
        assert parsed["solver_status"] == "optimal"
        assert "periods" in parsed
        assert len(parsed["periods"]) == 4


# ---------------------------------------------------------------------------
# JSON round-trip
# ---------------------------------------------------------------------------


class TestJSONRoundTrip:
    def test_round_trip_preserves_margin(self, planning_result):
        json_str = format_json(planning_result)
        round_tripped = PlanningResult.model_validate_json(json_str)
        assert abs(round_tripped.total_margin - planning_result.total_margin) < 1e-6

    def test_round_trip_preserves_periods(self, planning_result):
        json_str = format_json(planning_result)
        round_tripped = PlanningResult.model_validate_json(json_str)
        assert len(round_tripped.periods) == len(planning_result.periods)
        for orig, restored in zip(planning_result.periods, round_tripped.periods):
            assert orig.period_id == restored.period_id
            assert abs(orig.margin - restored.margin) < 1e-6
            assert abs(
                orig.product_volumes["gasoline"]
                - restored.product_volumes["gasoline"]
            ) < 1e-6

    def test_round_trip_preserves_inventory(self, planning_result):
        json_str = format_json(planning_result)
        round_tripped = PlanningResult.model_validate_json(json_str)
        for tank, orig_traj in planning_result.inventory_trajectory.items():
            assert tank in round_tripped.inventory_trajectory
            restored_traj = round_tripped.inventory_trajectory[tank]
            assert len(orig_traj) == len(restored_traj)
            for o, r in zip(orig_traj, restored_traj):
                assert abs(o - r) < 1e-6
