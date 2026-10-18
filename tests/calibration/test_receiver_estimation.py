"""Independent bias controls before final continuity alignment."""

from datetime import datetime, timedelta
from types import SimpleNamespace

import numpy as np
import polars as pl
import pytest

from gnss_tec.calibration import receiver_bias as rb


def _control(bias=5.0, *, separation=0.6):
    factors = np.tile([1.2, 1.2 + separation], 20)
    times = [
        datetime(2024, 1, 10) + timedelta(minutes=i)
        for i in range(20)
        for _ in range(2)
    ]
    return pl.DataFrame(
        {
            "time": times,
            "mf": factors,
            "stec": 20 * factors + bias + 1,
            "tx_bias": np.ones(40),
            "ipp_lat": np.zeros(40),
            "ipp_lon": np.zeros(40),
            "rx_lat": np.zeros(40),
        }
    ).select(pl.struct(pl.all()))[:, 0]


@pytest.mark.parametrize("method", [rb._mstd_rx_bias, rb._lsq_rx_bias])
def test_identifiable_receiver_coefficient_survives_redundant_nuisance_basis(method):
    assert method(_control()) == pytest.approx(5.0, abs=1e-5)
    for separation in (0, 1e-10):
        with pytest.warns(RuntimeWarning, match="unidentifiable"):
            assert np.isnan(method(_control(separation=separation)))


def test_mstd_bound_solution_is_not_success():
    with pytest.warns(RuntimeWarning, match="search bound"):
        assert np.isnan(rb._mstd_rx_bias(_control(600)))


@pytest.mark.parametrize(
    "method,solver",
    [(rb._mstd_rx_bias, "minimize_scalar"), (rb._lsq_rx_bias, "lsq_linear")],
)
def test_solver_failure_does_not_become_bias(monkeypatch, method, solver):
    monkeypatch.setattr(
        rb,
        solver,
        lambda *args, **kwargs: SimpleNamespace(
            success=False, x=np.array([5.0]), fun=0.0
        ),
    )
    with pytest.warns(RuntimeWarning, match="did not converge"):
        assert np.isnan(method(_control()))
