from datetime import datetime, timedelta

import numpy as np
import polars as pl
import pytest
from scipy.integrate import solve_ivp

import gnss_tec as gt
from gnss_tec.calculation.observation_geometry import _prepare_observations


@pytest.mark.parametrize("seconds", [-300, 300, 901])
def test_glonass_off_epoch_against_independent_dop853(tmp_path, seconds):
    # A synthetic broadcast state in RINEX units. DOP853 is independent of Rust RK4.
    nav = tmp_path / "glonass.nav"

    def h(text, label):
        return f"{text:<60}{label}\n"

    def fields(values):
        return "".join(f"{v:19.12E}".replace("E", "D") for v in values)

    state = np.array(
        [19_100_000.0, 12_500_000.0, 10_000_000.0, -1200.0, 2300.0, -800.0]
    )
    acc = np.array([1e-6, -2e-6, 0.0])
    content = h(
        "     3.04           NAVIGATION DATA     R", "RINEX VERSION / TYPE"
    ) + h("", "END OF HEADER")
    content += "R01 2024 01 10 00 00 00" + fields([0.0, 0.0, 0.0]) + "\n"
    for i in range(3):
        content += (
            "    "
            + fields([state[i] / 1000, state[i + 3] / 1000, acc[i] / 1000, 0.0])
            + "\n"
        )
    nav.write_text(content)
    obs = tmp_path / "glonass.obs"
    epoch = datetime(2024, 1, 10) + timedelta(seconds=seconds)
    obs.write_text(
        h("     3.04           OBSERVATION DATA    R", "RINEX VERSION / TYPE")
        + h("TEST", "MARKER NAME")
        + h("R    1 C1C", "SYS / # / OBS TYPES")
        + h("  2024     1    10     0     0    0.0000000     UTC", "TIME OF FIRST OBS")
        + h("", "END OF HEADER")
        + f"> {epoch:%Y %m %d %H %M} {epoch.second:10.7f}  0  1\nR01  21000000.000  \n"
    )

    def derivative(_, s):
        mu, j2, radius, omega = 3.9860044e14, 1.0826257e-3, 6378136.0, 7.292115e-5
        r = np.linalg.norm(s[:3])
        z2 = (s[2] / r) ** 2
        gravity = -mu * s[:3] / r**3
        gravity += (
            1.5
            * j2
            * mu
            * radius**2
            / r**5
            * s[:3]
            * np.array([5 * z2 - 1, 5 * z2 - 1, 5 * z2 - 3])
        )
        gravity += (
            np.array(
                [
                    omega**2 * s[0] + 2 * omega * s[4],
                    omega**2 * s[1] - 2 * omega * s[3],
                    0,
                ]
            )
            + acc
        )
        return np.r_[s[3:], gravity]

    header, frame = gt.read_rinex_obs(obs, constellations="R")
    data = _prepare_observations(frame, header, pl.col("time"), nav).collect(
        engine="in-memory"
    )
    if seconds > 900:
        assert data["_geometry_available"].item() is False
        assert data["_sat_x"].item() is None
        assert data["elevation"].item() is None
        return
    reference = solve_ivp(
        derivative, (0, seconds), state, method="DOP853", rtol=1e-12, atol=1e-7
    ).y[:3, -1]
    actual = data.select("_sat_x", "_sat_y", "_sat_z").row(0)
    np.testing.assert_allclose(actual, reference, rtol=0, atol=0.02)
    assert np.linalg.norm(np.asarray(actual) - state[:3]) > 100_000
    assert data["_geometry_available"].item() is True
