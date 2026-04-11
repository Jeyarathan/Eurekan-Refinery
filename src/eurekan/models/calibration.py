"""Auto-calibrate FCC parameters from plant operating data.

Uses scipy.optimize.least_squares WITH Tikhonov regularization.
Regularization prevents overfitting when plant data is sparse.
The prior is: published correlations are probably close (alpha~1.0, delta~0.0).

Objective: minimize  sum(predicted - actual)^2  +  lambda * sum(param - default)^2
"""

from __future__ import annotations

from dataclasses import fields
from typing import Optional

import numpy as np
from pydantic import BaseModel
from scipy.optimize import least_squares

from eurekan.core.crude import CutProperties
from eurekan.models.fcc import FCCCalibration, FCCModel

# ---------------------------------------------------------------------------
# Parameter metadata — order, defaults, bounds, scaling
# ---------------------------------------------------------------------------

_PARAM_NAMES: list[str] = [f.name for f in fields(FCCCalibration)]

_PARAM_DEFAULTS: np.ndarray = np.array(
    [f.default for f in fields(FCCCalibration)], dtype=float
)

# Property residual scaling — make property errors comparable to yield errors
_PROPERTY_SCALES: dict[str, float] = {
    "ron": 100.0,
    "sulfur": 1.0,
    "cetane": 100.0,
}


# ---------------------------------------------------------------------------
# Data models
# ---------------------------------------------------------------------------


class CalibrationDataPoint(BaseModel):
    """A single plant observation for calibration."""

    feed_properties: CutProperties
    conversion: float
    actual_yields: dict[str, float]
    actual_properties: dict[str, float] = {}


class CalibrationResult(BaseModel):
    """Results from calibration."""

    calibration: FCCCalibration
    lambda_used: float
    residuals: dict[str, float]
    confidence: dict[str, float]

    model_config = {"arbitrary_types_allowed": True}


# ---------------------------------------------------------------------------
# CalibrationEngine
# ---------------------------------------------------------------------------


class CalibrationEngine:
    """Auto-calibrate 11 FCC parameters from plant operating data."""

    PARAM_BOUNDS: dict[str, tuple[float, float]] = {
        "alpha_gasoline": (0.7, 1.3),
        "alpha_coke": (0.7, 1.3),
        "alpha_lcn_split": (0.7, 1.3),
        "alpha_c3c4": (0.7, 1.3),
        "alpha_lco": (0.7, 1.3),
        "delta_lcn_ron": (-3.0, 3.0),
        "delta_hcn_ron": (-3.0, 3.0),
        "delta_lcn_sulfur": (0.5, 2.0),
        "delta_hcn_sulfur": (0.5, 2.0),
        "delta_lco_cetane": (-5.0, 5.0),
        "delta_regen": (-30.0, 30.0),
    }

    def calibrate(
        self,
        fcc_model: FCCModel,
        observed_data: list[CalibrationDataPoint],
        lambda_reg: Optional[float] = None,
    ) -> CalibrationResult:
        """Fit calibration parameters to minimize regularized error.

        Args:
            fcc_model: The FCC model to calibrate (calibration will be swapped
                       temporarily during optimization, then restored).
            observed_data: Plant observations.
            lambda_reg: Regularization strength. None = auto-tune if >=6 points,
                        otherwise default to 1.0.
        """
        if lambda_reg is None:
            if len(observed_data) >= 6:
                lambda_reg = self.auto_tune_lambda(fcc_model, observed_data)
            else:
                lambda_reg = 1.0

        # Force high regularization with sparse data
        if len(observed_data) < 6:
            lambda_reg = max(lambda_reg, 1.0)

        fitted_params = self._optimize(fcc_model, observed_data, lambda_reg)
        fitted_cal = _params_to_calibration(fitted_params)

        # Compute per-data-point residuals with the fitted calibration
        residuals = self._compute_residuals_per_point(
            fcc_model, observed_data, fitted_cal
        )

        # Confidence: how far each parameter moved from default (0 = at default, 1 = at bound)
        confidence = self._compute_confidence(fitted_params)

        return CalibrationResult(
            calibration=fitted_cal,
            lambda_used=lambda_reg,
            residuals=residuals,
            confidence=confidence,
        )

    def auto_tune_lambda(
        self,
        fcc_model: FCCModel,
        observed_data: list[CalibrationDataPoint],
    ) -> float:
        """Leave-one-out cross-validation to find optimal lambda."""
        candidates = [0.01, 0.05, 0.1, 0.5, 1.0, 5.0, 10.0]
        best_lambda = 1.0
        best_cv_error = float("inf")

        for lam in candidates:
            cv_error = 0.0
            for i in range(len(observed_data)):
                train = observed_data[:i] + observed_data[i + 1 :]
                test_pt = observed_data[i]

                fitted_params = self._optimize(fcc_model, train, lam)
                fitted_cal = _params_to_calibration(fitted_params)

                # Predict on held-out point
                original_cal = fcc_model.calibration
                fcc_model.calibration = fitted_cal
                result = fcc_model.calculate(test_pt.feed_properties, test_pt.conversion)
                fcc_model.calibration = original_cal

                for key, actual in test_pt.actual_yields.items():
                    predicted = result.yields.get(key)
                    if predicted is not None:
                        cv_error += (predicted - actual) ** 2

            if cv_error < best_cv_error:
                best_cv_error = cv_error
                best_lambda = lam

        return best_lambda

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _optimize(
        self,
        fcc_model: FCCModel,
        data: list[CalibrationDataPoint],
        lambda_reg: float,
    ) -> np.ndarray:
        """Run least_squares optimization, return fitted parameter vector."""
        original_cal = fcc_model.calibration
        x0 = _PARAM_DEFAULTS.copy()

        # Build bounds arrays
        lower = np.array([self.PARAM_BOUNDS[n][0] for n in _PARAM_NAMES])
        upper = np.array([self.PARAM_BOUNDS[n][1] for n in _PARAM_NAMES])

        def residual_fn(params: np.ndarray) -> np.ndarray:
            fcc_model.calibration = _params_to_calibration(params)
            resids: list[float] = []

            for dp in data:
                result = fcc_model.calculate(dp.feed_properties, dp.conversion)

                # Yield residuals
                for key, actual in dp.actual_yields.items():
                    predicted = result.yields.get(key)
                    if predicted is not None:
                        resids.append(predicted - actual)

                # Property residuals (scaled)
                for key, actual in dp.actual_properties.items():
                    predicted = _get_predicted_property(result, key)
                    if predicted is not None:
                        scale = _get_scale_for_property(key)
                        resids.append((predicted - actual) / scale)

            # Tikhonov regularization: sqrt(lambda) * (param - default)
            sqrt_lam = lambda_reg**0.5
            for param_val, default_val in zip(params, _PARAM_DEFAULTS):
                resids.append(sqrt_lam * (param_val - default_val))

            return np.array(resids)

        result = least_squares(
            residual_fn,
            x0,
            bounds=(lower, upper),
            method="trf",
            max_nfev=500,
        )

        fcc_model.calibration = original_cal
        return result.x

    def _compute_residuals_per_point(
        self,
        fcc_model: FCCModel,
        data: list[CalibrationDataPoint],
        calibration: FCCCalibration,
    ) -> dict[str, float]:
        """Compute sum-of-squared yield residuals per data point."""
        original_cal = fcc_model.calibration
        fcc_model.calibration = calibration
        residuals: dict[str, float] = {}

        for i, dp in enumerate(data):
            result = fcc_model.calculate(dp.feed_properties, dp.conversion)
            sse = 0.0
            for key, actual in dp.actual_yields.items():
                predicted = result.yields.get(key)
                if predicted is not None:
                    sse += (predicted - actual) ** 2
            residuals[f"point_{i}"] = sse

        fcc_model.calibration = original_cal
        return residuals

    def _compute_confidence(self, fitted_params: np.ndarray) -> dict[str, float]:
        """Per-parameter confidence: fraction of bound range used (0=default, 1=at bound)."""
        confidence: dict[str, float] = {}
        for i, name in enumerate(_PARAM_NAMES):
            lo, hi = self.PARAM_BOUNDS[name]
            default = _PARAM_DEFAULTS[i]
            fitted = fitted_params[i]
            # Distance from default as fraction of max possible distance to bound
            max_dist = max(abs(hi - default), abs(default - lo))
            if max_dist > 0:
                confidence[name] = abs(fitted - default) / max_dist
            else:
                confidence[name] = 0.0
        return confidence


# ---------------------------------------------------------------------------
# Conversion helpers
# ---------------------------------------------------------------------------


def _params_to_calibration(params: np.ndarray) -> FCCCalibration:
    """Convert parameter vector to FCCCalibration dataclass."""
    return FCCCalibration(**{name: float(params[i]) for i, name in enumerate(_PARAM_NAMES)})


def _get_predicted_property(result: object, key: str) -> Optional[float]:
    """Extract a predicted property value from FCCResult.

    Keys follow the pattern '{product}_{property}', e.g. 'lcn_ron', 'lco_cetane'.
    """
    parts = key.rsplit("_", 1)
    if len(parts) != 2:
        return None
    product, prop = parts
    props_dict = getattr(result, "properties", {})
    if product not in props_dict:
        return None
    return getattr(props_dict[product], prop, None)


def _get_scale_for_property(key: str) -> float:
    """Return the scaling factor for a property key."""
    parts = key.rsplit("_", 1)
    if len(parts) == 2:
        return _PROPERTY_SCALES.get(parts[1], 1.0)
    return 1.0
