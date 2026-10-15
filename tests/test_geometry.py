"""WGS84 reference values, independent ENU controls and Polars integration."""

from pathlib import Path

import numpy as np
import polars as pl
import pytest
from polars.testing import assert_frame_equal

import gnss_tec as gt
from gnss_tec._arrow import record_batch
from gnss_tec._core import _azimuth_elevation, _ecef_to_geodetic
from gnss_tec.calculation.observation_geometry import (
    _calculate_azimuth_elevation,
    _prepare_observations,
)

FIXTURES = Path(__file__).parent / "fixtures/geometry"
COORDINATES = ["_sat_x", "_sat_y", "_sat_z", "rx_lat", "rx_lon", "_rx_alt"]


def reference_values(name):
    columns = (
        ["x", "y", "z", "latitude", "longitude", "altitude"]
        if name == "geodetic"
        else COORDINATES + ["azimuth", "elevation"]
    )
    return pl.read_csv(
        FIXTURES / f"{name}.csv",
        schema_overrides={name: pl.Float64 for name in columns},
    )


def test_geodetic_matches_frozen_reference():
    reference = reference_values("geodetic")
    actual = np.array(
        [_ecef_to_geodetic(*row) for row in reference.select("x", "y", "z").iter_rows()]
    )
    np.testing.assert_allclose(
        actual[:, :2], reference.select("latitude", "longitude"), rtol=0, atol=1e-11
    )
    np.testing.assert_allclose(actual[:, 2], reference["altitude"], rtol=0, atol=5e-8)


def test_angles_match_frozen_reference_and_batch_partitions():
    reference = reference_values("aer")
    frame = reference.select(COORDINATES)
    expected = reference.select("azimuth", "elevation")
    actual = _calculate_azimuth_elevation(frame.to_struct()).struct.unnest()
    np.testing.assert_allclose(actual, expected, rtol=0, atol=1e-11)
    # Sliced/chunked Arrow inputs and Polars callback partitions keep row order.
    chunked = pl.concat(
        [frame.slice(i, 3) for i in range(0, frame.height, 3)], rechunk=False
    )
    assert chunked.n_chunks() > 1
    assert_frame_equal(
        _calculate_azimuth_elevation(chunked.to_struct()).struct.unnest(),
        actual,
        check_exact=True,
    )
    partitioned = pl.concat(
        [
            _calculate_azimuth_elevation(frame.slice(i, 3).to_struct()).struct.unnest()
            for i in range(0, frame.height, 3)
        ]
    )
    assert_frame_equal(partitioned, actual, check_exact=True)


@pytest.mark.parametrize("moving", [False, True])
def test_parallel_angles_and_observer_cache_match_analytic_enu(moving):
    # At lat/lon zero, ECEF deltas (1000,1000,1000) are ENU (1000,1000,1000).
    # More than 128 distinct observers also exercises the bounded cache fallback.
    altitude = np.arange(20000, dtype=float) if moving else np.zeros(20000)
    frame = pl.DataFrame(
        {
            "_sat_x": 6378137 + altitude + 1000,
            "_sat_y": np.full(20000, 1000.0),
            "_sat_z": np.full(20000, 1000.0),
            "rx_lat": np.zeros(20000),
            "rx_lon": np.zeros(20000),
            "_rx_alt": altitude,
        }
    )
    actual = _calculate_azimuth_elevation(frame.to_struct()).struct.unnest()
    np.testing.assert_allclose(actual["azimuth"], 45.0, rtol=0, atol=1e-12)
    np.testing.assert_allclose(
        actual["elevation"], np.degrees(np.arctan2(1, np.sqrt(2))), rtol=0, atol=1e-12
    )


def test_missing_geometry_and_empty_batches():
    frame = reference_values("aer").select(COORDINATES).head(1)
    missing = pl.concat(
        [
            frame.with_columns(pl.lit(None, dtype=pl.Float64).alias(name))
            for name in COORDINATES
        ]
    )
    result = _calculate_azimuth_elevation(missing.to_struct()).struct.unnest()
    assert result.select(pl.all().is_nan().all()).row(0) == (True, True)
    empty = _calculate_azimuth_elevation(frame.head(0).to_struct()).struct.unnest()
    assert empty.schema == {"azimuth": pl.Float64, "elevation": pl.Float64}
    assert empty.is_empty()


def test_native_geometry_requires_float64_coordinates():
    frame = reference_values("aer").select(COORDINATES)
    for invalid in [
        frame.drop("_sat_x"),
        frame.with_columns(pl.col("_sat_x").cast(pl.Float32)),
    ]:
        with pytest.raises(ValueError, match="geometry column: _sat_x"):
            _azimuth_elevation(record_batch(invalid))


@pytest.mark.parametrize("engine", ["in-memory", "streaming"])
def test_real_receiver_header_and_gps_beidou_geometry(
    short_rinex_v3, rinex_nav_v3, engine
):
    header, observations = gt.read_rinex_obs(short_rinex_v3, constellations="CG")
    np.testing.assert_allclose(
        header.rx_geodetic,
        [-6.490367937958374, 106.84916836419953, 173.0000212144293],
        rtol=0,
        atol=1e-8,
    )
    expected = pl.read_csv(FIXTURES / "cibg.csv")
    prepared = (
        _prepare_observations(observations, header, pl.col("time"), rinex_nav_v3)
        .select(expected.columns)
        .collect(engine=engine)
    )
    actual = expected.select("_utc_ns", "prn").join(
        prepared.with_columns(pl.col("prn").cast(pl.String)),
        on=["_utc_ns", "prn"],
        how="left",
        validate="1:1",
        maintain_order="left",
    )
    assert_frame_equal(actual, expected, check_exact=False, rel_tol=0, abs_tol=1e-11)
