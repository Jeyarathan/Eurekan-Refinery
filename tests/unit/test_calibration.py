"""Tests for CalibrationEngine — Task 2.5."""

from __future__ import annotations

from dataclasses import fields

import pytest

from eurekan.core.config import UnitConfig
from eurekan.core.crude import CutProperties
from eurekan.core.enums import UnitType
from eurekan.models.calibration import (
    CalibrationDataPoint,
    CalibrationEngine,
    CalibrationResult,
)
from eurekan.models.fcc import FCCCalibration, FCCModel


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def fcc_config() -> UnitConfig:
    return UnitConfig(
        unit_id="fcc_1",
        unit_type=UnitType.FCC,
        capacity=50000.0,
        equipment_limits={"fcc_regen_temp_max": 1400.0},
    )


@pytest.fixture
def fcc_model(fcc_config) -> FCCModel:
    return FCCModel(fcc_config)


@pytest.fixture
def engine() -> CalibrationEngine:
    return CalibrationEngine()


@pytest.fixture
def sccu_vgo() -> CutProperties:
    """ARL VGO at SCCU conditions."""
    return CutProperties(api=21.8, ccr=0.5, sulfur=1.1, nickel=0.5, vanadium=0.5)


def _generate_neutral_data(fcc_model: FCCModel, n: int = 5) -> list[CalibrationDataPoint]:
    """Generate synthetic data from the default (neutral) model at varied conditions."""
    feeds = [
        CutProperties(api=21.8, ccr=0.5, sulfur=1.1, nickel=0.5, vanadium=0.5),
        CutProperties(api=24.0, ccr=0.8, sulfur=0.8, nickel=0.3, vanadium=0.3),
        CutProperties(api=19.0, ccr=1.5, sulfur=2.0, nickel=2.0, vanadium=5.0),
        CutProperties(api=22.0, ccr=1.0, sulfur=1.0, nickel=1.0, vanadium=1.0),
        CutProperties(api=26.0, ccr=0.4, sulfur=0.5, nickel=0.2, vanadium=0.2),
        CutProperties(api=18.0, ccr=2.0, sulfur=2.5, nickel=3.0, vanadium=6.0),
        CutProperties(api=23.0, ccr=0.7, sulfur=0.9, nickel=0.5, vanadium=0.8),
        CutProperties(api=20.0, ccr=1.2, sulfur=1.5, nickel=1.5, vanadium=3.0),
    ]
    conversions = [75.0, 78.0, 80.0, 82.0, 85.0, 77.0, 79.0, 83.0]
    data: list[CalibrationDataPoint] = []
    for i in range(min(n, len(feeds))):
        result = fcc_model.calculate(feeds[i], conversions[i])
        data.append(
            CalibrationDataPoint(
                feed_properties=feeds[i],
                conversion=conversions[i],
                actual_yields={
                    "gasoline": result.yields["gasoline"],
                    "lco": result.yields["lco"],
                    "coke": result.yields["coke"],
                },
            )
        )
    return data


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


class TestNeutralData:
    """If plant data matches the default model, calibration returns near-neutral params."""

    def test_neutral_data_alphas_near_one(self, fcc_model, engine):
        data = _generate_neutral_data(fcc_model, n=5)
        result = engine.calibrate(fcc_model, data, lambda_reg=1.0)
        cal = result.calibration

        for f in fields(cal):
            val = getattr(cal, f.name)
            if f.name.startswith("alpha_"):
                assert abs(val - 1.0) < 0.05, (
                    f"{f.name} = {val:.4f}, expected near 1.0"
                )

    def test_neutral_data_deltas_near_default(self, fcc_model, engine):
        data = _generate_neutral_data(fcc_model, n=5)
        result = engine.calibrate(fcc_model, data, lambda_reg=1.0)
        cal = result.calibration

        # delta_lcn_sulfur and delta_hcn_sulfur default to 1.0, rest to 0.0
        defaults = {f.name: f.default for f in fields(FCCCalibration)}
        for name, default in defaults.items():
            if name.startswith("delta_"):
                val = getattr(cal, name)
                assert abs(val - default) < 0.1, (
                    f"{name} = {val:.4f}, expected near {default}"
                )

    def test_neutral_model_unchanged(self, fcc_model, engine, sccu_vgo):
        """After calibrating on neutral data, model should still give same results."""
        data = _generate_neutral_data(fcc_model, n=5)
        result = engine.calibrate(fcc_model, data, lambda_reg=1.0)

        # Apply fitted calibration
        calibrated_model = FCCModel(
            UnitConfig(
                unit_id="fcc_1", unit_type=UnitType.FCC, capacity=50000.0,
                equipment_limits={"fcc_regen_temp_max": 1400.0},
            ),
            result.calibration,
        )
        r_cal = calibrated_model.calculate(sccu_vgo, 80.0)
        r_default = fcc_model.calculate(sccu_vgo, 80.0)

        for key in ["gasoline", "lco", "coke"]:
            assert abs(r_cal.yields[key] - r_default.yields[key]) < 0.01, (
                f"Calibrated {key} = {r_cal.yields[key]:.4f}, "
                f"default = {r_default.yields[key]:.4f}"
            )


class TestSCCUCalibration:
    """Use SCCU BASE values as 'plant data'; after calibration model matches ±2%."""

    def test_sccu_gasoline_match(self, fcc_model, engine, sccu_vgo):
        """Calibrate to SCCU gasoline=49.4%, model should match within ±2%."""
        sccu_data = [
            CalibrationDataPoint(
                feed_properties=sccu_vgo,
                conversion=80.0,
                actual_yields={"gasoline": 0.494, "lco": 0.162, "coke": 0.034},
            ),
            CalibrationDataPoint(
                feed_properties=CutProperties(
                    api=24.0, ccr=0.8, sulfur=0.8, nickel=0.3, vanadium=0.3
                ),
                conversion=82.0,
                actual_yields={"gasoline": 0.50, "lco": 0.15, "coke": 0.04},
            ),
            CalibrationDataPoint(
                feed_properties=CutProperties(
                    api=20.0, ccr=1.2, sulfur=1.5, nickel=1.5, vanadium=3.0
                ),
                conversion=78.0,
                actual_yields={"gasoline": 0.47, "lco": 0.17, "coke": 0.06},
            ),
        ]
        result = engine.calibrate(fcc_model, sccu_data, lambda_reg=0.1)

        # Apply fitted calibration and predict at SCCU conditions
        calibrated = FCCModel(
            UnitConfig(
                unit_id="fcc_1", unit_type=UnitType.FCC, capacity=50000.0,
                equipment_limits={"fcc_regen_temp_max": 1400.0},
            ),
            result.calibration,
        )
        r = calibrated.calculate(sccu_vgo, 80.0)

        assert abs(r.yields["gasoline"] - 0.494) < 0.02, (
            f"Gasoline {r.yields['gasoline']:.4f} not within ±2% of SCCU 0.494"
        )
        assert abs(r.yields["lco"] - 0.162) < 0.02, (
            f"LCO {r.yields['lco']:.4f} not within ±2% of SCCU 0.162"
        )

    def test_sccu_yields_physical(self, fcc_model, engine, sccu_vgo):
        """Calibrated yields should still be physical (positive, sum ~1)."""
        sccu_data = [
            CalibrationDataPoint(
                feed_properties=sccu_vgo,
                conversion=80.0,
                actual_yields={"gasoline": 0.494, "lco": 0.162, "coke": 0.034},
            ),
        ]
        result = engine.calibrate(fcc_model, sccu_data, lambda_reg=0.5)

        calibrated = FCCModel(
            UnitConfig(
                unit_id="fcc_1", unit_type=UnitType.FCC, capacity=50000.0,
                equipment_limits={"fcc_regen_temp_max": 1400.0},
            ),
            result.calibration,
        )
        r = calibrated.calculate(sccu_vgo, 80.0)

        for key, val in r.yields.items():
            assert val >= 0, f"Yield {key} is negative: {val}"

        total = sum(v for k, v in r.yields.items() if k != "gasoline")
        assert 0.90 <= total <= 1.10, f"Yields sum to {total:.4f}"


class TestSparseDataConservative:
    """With <6 data points, parameters stay close to defaults (high lambda)."""

    def test_sparse_3_points_near_defaults(self, fcc_model, engine):
        """Only 3 data points — high lambda should keep parameters near defaults."""
        sparse_data = [
            CalibrationDataPoint(
                feed_properties=CutProperties(
                    api=21.8, ccr=0.5, sulfur=1.1, nickel=0.5, vanadium=0.5
                ),
                conversion=80.0,
                actual_yields={"gasoline": 0.52, "lco": 0.14, "coke": 0.04},
            ),
            CalibrationDataPoint(
                feed_properties=CutProperties(
                    api=24.0, ccr=0.8, sulfur=0.8, nickel=0.3, vanadium=0.3
                ),
                conversion=82.0,
                actual_yields={"gasoline": 0.53, "lco": 0.13, "coke": 0.035},
            ),
            CalibrationDataPoint(
                feed_properties=CutProperties(
                    api=19.0, ccr=1.5, sulfur=2.0, nickel=2.0, vanadium=5.0
                ),
                conversion=76.0,
                actual_yields={"gasoline": 0.48, "lco": 0.16, "coke": 0.07},
            ),
        ]
        result = engine.calibrate(fcc_model, sparse_data)

        # Lambda should be >= 1.0 (forced high for sparse data)
        assert result.lambda_used >= 1.0, (
            f"Lambda {result.lambda_used} should be >= 1.0 for sparse data"
        )

        # Parameters should stay near defaults
        cal = result.calibration
        defaults = {f.name: f.default for f in fields(FCCCalibration)}
        for name, default in defaults.items():
            val = getattr(cal, name)
            if name.startswith("alpha_"):
                assert abs(val - default) < 0.15, (
                    f"Sparse: {name} = {val:.4f}, too far from default {default}"
                )
            elif name.startswith("delta_"):
                bound_lo, bound_hi = CalibrationEngine.PARAM_BOUNDS[name]
                max_range = bound_hi - bound_lo
                assert abs(val - default) < max_range * 0.3, (
                    f"Sparse: {name} = {val:.4f}, too far from default {default}"
                )


class TestBoundsRespected:
    """No parameter should exceed PARAM_BOUNDS even with extreme data."""

    def test_extreme_data_within_bounds(self, fcc_model, engine):
        """Extreme 'plant data' should not push parameters outside bounds."""
        extreme_data = [
            CalibrationDataPoint(
                feed_properties=CutProperties(
                    api=21.8, ccr=0.5, sulfur=1.1, nickel=0.5, vanadium=0.5
                ),
                conversion=80.0,
                actual_yields={"gasoline": 0.70, "lco": 0.05, "coke": 0.01},
            ),
            CalibrationDataPoint(
                feed_properties=CutProperties(
                    api=21.8, ccr=0.5, sulfur=1.1, nickel=0.5, vanadium=0.5
                ),
                conversion=80.0,
                actual_yields={"gasoline": 0.65, "lco": 0.06, "coke": 0.015},
            ),
            CalibrationDataPoint(
                feed_properties=CutProperties(
                    api=21.8, ccr=0.5, sulfur=1.1, nickel=0.5, vanadium=0.5
                ),
                conversion=80.0,
                actual_yields={"gasoline": 0.68, "lco": 0.04, "coke": 0.012},
            ),
        ]
        result = engine.calibrate(fcc_model, extreme_data, lambda_reg=0.01)
        cal = result.calibration

        for name, (lo, hi) in CalibrationEngine.PARAM_BOUNDS.items():
            val = getattr(cal, name)
            assert lo <= val <= hi, (
                f"{name} = {val:.4f} outside bounds [{lo}, {hi}]"
            )

    def test_all_default_params_within_bounds(self):
        """Default parameter values should be within bounds."""
        cal = FCCCalibration()
        for name, (lo, hi) in CalibrationEngine.PARAM_BOUNDS.items():
            val = getattr(cal, name)
            assert lo <= val <= hi, (
                f"Default {name} = {val} outside bounds [{lo}, {hi}]"
            )


class TestConfidenceReported:
    """CalibrationResult should have per-parameter confidence."""

    def test_confidence_keys(self, fcc_model, engine):
        data = _generate_neutral_data(fcc_model, n=5)
        result = engine.calibrate(fcc_model, data, lambda_reg=1.0)
        for f in fields(FCCCalibration):
            assert f.name in result.confidence, (
                f"Missing confidence for {f.name}"
            )

    def test_confidence_range(self, fcc_model, engine):
        """Confidence should be 0-1 (fraction of bound used)."""
        data = _generate_neutral_data(fcc_model, n=5)
        result = engine.calibrate(fcc_model, data, lambda_reg=1.0)
        for name, conf in result.confidence.items():
            assert 0.0 <= conf <= 1.0, (
                f"Confidence for {name} = {conf:.4f}, expected 0-1"
            )

    def test_neutral_confidence_low(self, fcc_model, engine):
        """Calibrating on neutral data should give low confidence (near defaults)."""
        data = _generate_neutral_data(fcc_model, n=5)
        result = engine.calibrate(fcc_model, data, lambda_reg=1.0)
        for name, conf in result.confidence.items():
            assert conf < 0.3, (
                f"Neutral calibration: confidence for {name} = {conf:.4f}, "
                "expected < 0.3"
            )

    def test_residuals_reported(self, fcc_model, engine):
        data = _generate_neutral_data(fcc_model, n=5)
        result = engine.calibrate(fcc_model, data, lambda_reg=1.0)
        assert len(result.residuals) == 5, (
            f"Expected 5 residual entries, got {len(result.residuals)}"
        )
        for key, val in result.residuals.items():
            assert val >= 0, f"Residual {key} is negative"

    def test_result_has_lambda(self, fcc_model, engine):
        data = _generate_neutral_data(fcc_model, n=3)
        result = engine.calibrate(fcc_model, data)
        assert result.lambda_used >= 1.0
