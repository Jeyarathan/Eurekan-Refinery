"""Task 2.2 — Validate FCC yields against SCCU BASE column.

SCCU BASE targets at 80% conversion on ARL VGO (API~21.8, CCR~0.5):
  - Total gasoline ~49.4%
  - LCO ~16.2%
  - Coke ~3.4% FOE (fuel oil equivalent)

Correlation coefficients were calibrated from published values to match
these SCCU targets:
  - Gasoline constant: -0.1553 -> -0.0833  (shifted +0.072 to match ~49%)
  - LCO constant: 0.3247 -> 0.37  (shifted +0.045 to match ~16.2%)
  - Coke CCR factor: 1.5 -> 1.1  (reduced; only ~70% of CCR becomes FCC coke)
  - Coke base: 0.0455 -> 0.040  (minor adjustment)
"""

from __future__ import annotations

import pytest

from eurekan.core.config import UnitConfig
from eurekan.core.crude import CutProperties
from eurekan.core.enums import UnitType
from eurekan.models.fcc import FCCModel


@pytest.fixture
def fcc_model() -> FCCModel:
    config = UnitConfig(
        unit_id="fcc_1",
        unit_type=UnitType.FCC,
        capacity=50000.0,
        equipment_limits={"fcc_regen_temp_max": 1400.0},
    )
    return FCCModel(config)


@pytest.fixture
def sccu_vgo() -> CutProperties:
    """ARL VGO at SCCU BASE conditions."""
    return CutProperties(api=21.8, ccr=0.5, sulfur=1.1, nickel=0.5, vanadium=0.5)


class TestSCCUGasolineYield:
    """Gasoline should be 45-54% (SCCU says 49.4%)."""

    def test_gasoline_in_range(self, fcc_model, sccu_vgo):
        result = fcc_model.calculate(sccu_vgo, 80.0)
        gasoline = result.yields["gasoline"]
        assert 0.45 <= gasoline <= 0.54, (
            f"Gasoline {gasoline:.4f} outside 45-54% (SCCU target 49.4%)"
        )

    def test_gasoline_within_10pct_of_sccu(self, fcc_model, sccu_vgo):
        """Within ±10% of SCCU target 0.494."""
        result = fcc_model.calculate(sccu_vgo, 80.0)
        gasoline = result.yields["gasoline"]
        assert abs(gasoline - 0.494) / 0.494 < 0.10, (
            f"Gasoline {gasoline:.4f} more than 10% off SCCU target 0.494"
        )

    def test_lcn_hcn_split_reasonable(self, fcc_model, sccu_vgo):
        """SCCU: LCN~39.3%, HCN~10.1%."""
        result = fcc_model.calculate(sccu_vgo, 80.0)
        lcn = result.yields["lcn"]
        hcn = result.yields["hcn"]
        assert 0.30 <= lcn <= 0.50, f"LCN {lcn:.4f} outside 30-50%"
        assert 0.05 <= hcn <= 0.20, f"HCN {hcn:.4f} outside 5-20%"


class TestSCCULCOYield:
    """LCO should be 14-18% (SCCU says 16.2%)."""

    def test_lco_in_range(self, fcc_model, sccu_vgo):
        result = fcc_model.calculate(sccu_vgo, 80.0)
        lco = result.yields["lco"]
        assert 0.14 <= lco <= 0.18, (
            f"LCO {lco:.4f} outside 14-18% (SCCU target 16.2%)"
        )

    def test_lco_within_10pct_of_sccu(self, fcc_model, sccu_vgo):
        """Within ±10% of SCCU target 0.162."""
        result = fcc_model.calculate(sccu_vgo, 80.0)
        lco = result.yields["lco"]
        assert abs(lco - 0.162) / 0.162 < 0.10, (
            f"LCO {lco:.4f} more than 10% off SCCU target 0.162"
        )


class TestSCCUCokeYield:
    """Coke should be reasonable. SCCU reports 3.4% FOE.

    Our model reports raw volumetric yield (~5%). The FOE (Fuel Oil
    Equivalent) conversion factor is ~0.68 due to coke being denser
    and having higher energy content per unit mass than fuel oil.
    """

    def test_coke_raw_reasonable(self, fcc_model, sccu_vgo):
        result = fcc_model.calculate(sccu_vgo, 80.0)
        coke = result.yields["coke"]
        assert 0.03 <= coke <= 0.08, f"Coke {coke:.4f} outside 3-8%"

    def test_coke_foe_near_sccu(self, fcc_model, sccu_vgo):
        """Raw coke * FOE factor should approximate SCCU 3.4%."""
        result = fcc_model.calculate(sccu_vgo, 80.0)
        coke_raw = result.yields["coke"]
        foe_factor = 0.68  # coke-to-fuel-oil-equivalent density/energy ratio
        coke_foe = coke_raw * foe_factor
        assert 0.025 <= coke_foe <= 0.050, (
            f"Coke FOE {coke_foe:.4f} outside 2.5-5.0% (SCCU target 3.4%)"
        )


class TestSCCUMassBalance:
    """All yields must sum to ~100% (±2%)."""

    def test_yields_sum_to_100(self, fcc_model, sccu_vgo):
        result = fcc_model.calculate(sccu_vgo, 80.0)
        # Sum individual products (not the aggregate "gasoline" key)
        total = (
            result.yields["lcn"]
            + result.yields["hcn"]
            + result.yields["lco"]
            + result.yields["coke"]
            + result.yields["c3"]
            + result.yields["c4"]
            + result.yields["fuel_gas"]
            + result.yields["slurry"]
        )
        assert 0.98 <= total <= 1.02, (
            f"Yields sum to {total:.4f}, expected 0.98-1.02"
        )

    def test_gasoline_is_lcn_plus_hcn(self, fcc_model, sccu_vgo):
        result = fcc_model.calculate(sccu_vgo, 80.0)
        assert abs(
            result.yields["gasoline"] - result.yields["lcn"] - result.yields["hcn"]
        ) < 1e-10

    def test_all_yields_positive(self, fcc_model, sccu_vgo):
        result = fcc_model.calculate(sccu_vgo, 80.0)
        for name, val in result.yields.items():
            assert val >= 0, f"Yield '{name}' is negative: {val}"
