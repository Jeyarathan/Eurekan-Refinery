"""Smoke tests to verify all core dependencies are importable and functional."""


def test_pyomo_and_ipopt():
    import pyomo.environ as pyo

    solver = pyo.SolverFactory("ipopt")
    assert solver.available(), "ipopt solver is not available"


def test_highspy():
    import highspy  # noqa: F401


def test_pydantic():
    from pydantic import BaseModel

    class _Dummy(BaseModel):
        x: int = 1

    assert _Dummy().x == 1


def test_numpy():
    import numpy as np

    assert np.array([1, 2, 3]).sum() == 6


def test_scipy():
    from scipy.optimize import least_squares

    result = least_squares(lambda x: x - 1.0, x0=[0.0])
    assert abs(result.x[0] - 1.0) < 1e-6


def test_pandas_and_openpyxl():
    import pandas as pd

    import openpyxl  # noqa: F401

    df = pd.DataFrame({"a": [1, 2, 3]})
    assert len(df) == 3
