"""Independent observation geometry preserves raw rows and native batch contracts."""

from dataclasses import replace
from datetime import datetime, timedelta

import polars as pl
import pyarrow as pa
import pytest
from polars.testing import assert_frame_equal

import gnss_tec as gt
from gnss_tec._arrow import record_batch
from gnss_tec._core import _satellite_positions
from gnss_tec.calculation import observation_geometry as geometry


@pytest.fixture(scope="module")
def navigation(rinex_nav_v3):
    return gt.read_rinex_nav(rinex_nav_v3)


@pytest.mark.parametrize("engine", ["in-memory", "streaming"])
def test_public_geometry_matches_private_preserves_input(
    small_observations, navigation, rinex_nav_v3, engine
):
    header, data = small_observations
    data = data.head(512).reverse().with_columns(pl.lit(float("nan")).alias("external"))
    original = data.clone()
    result = gt.compute_az_el(data, header, navigation).collect(engine=engine)
    assert_frame_equal(result.select(data.columns), original, check_exact=True)
    expected = (
        geometry._prepare_observations(
            data.lazy(), header, pl.col("time"), rinex_nav_v3
        )
        .select("time", "prn", "azimuth", "elevation")
        .collect(engine=engine)
    )
    assert_frame_equal(
        result.select(expected.columns).sort("time", "prn"),
        expected.sort("time", "prn"),
        check_exact=True,
    )
    assert result.columns == data.columns + ["azimuth", "elevation"]


def test_long_geometry_propagates_unique_keys(
    small_observations, navigation, monkeypatch
):
    header, data = small_observations
    wide = data.head(64)
    long = pl.concat(
        [
            wide.with_columns(pl.lit(code).alias("code"))
            for code in ("L1C", "C1C", "S1C")
        ]
    )
    seen = []
    original = geometry._satellite_positions

    def capture(nav, query):
        seen.append(query.num_rows)
        return original(nav, query)

    monkeypatch.setattr(geometry, "_satellite_positions", capture)
    result = gt.compute_az_el(long, header, navigation).collect()
    assert seen == [wide.select("time", "prn").unique().height]
    assert result.height == long.height
    assert_frame_equal(result.select(long.columns), long, check_exact=True)


def test_overwrite_missing_geometry_and_empty(small_observations, navigation):
    header, frame = small_observations
    frame = frame.head(10).with_columns(pl.lit(123.0).alias("azimuth"))
    with pytest.raises(ValueError, match="overwrite=True"):
        gt.compute_az_el(frame, header, navigation)
    result = gt.compute_az_el(frame, header, navigation, overwrite=True).collect()
    assert result["azimuth"].ne(123.0).any()
    missing = frame.drop("azimuth").with_columns(pl.lit("G99").alias("prn"))
    result = gt.compute_az_el(missing, header, navigation).collect()
    assert result["azimuth"].null_count() == missing.height
    assert result["elevation"].null_count() == missing.height
    assert (
        gt.compute_az_el(frame.drop("azimuth").clear(), header, navigation)
        .collect()
        .is_empty()
    )


def test_gps_time_and_receiver_history(small_observations, navigation, rinex_nav_v3):
    header, frame = small_observations
    frame = frame.head(80).reverse()
    utc = gt.compute_az_el(frame, header, navigation).collect()
    gps = frame.with_columns(
        (pl.col("time").dt.replace_time_zone(None) + pl.duration(seconds=18)).alias(
            "time"
        )
    )
    actual = gt.compute_az_el(
        gps, replace(header, leap_seconds=18), navigation
    ).collect()
    assert_frame_equal(
        actual.select("azimuth", "elevation"),
        utc.select("azimuth", "elevation"),
        check_exact=True,
    )
    assert actual.schema["time"] == gps.schema["time"]
    first = frame["time"].dt.epoch("ns").min()
    last = frame["time"].dt.epoch("ns").max()
    history = (
        (first, header.rx_ecef, "first"),
        (last, (6378137.0, 0.0, 0.0), "second"),
    )
    changed = replace(header, receiver_history=history)
    expected = (
        geometry._prepare_observations(
            frame.lazy(), changed, pl.col("time"), rinex_nav_v3
        )
        .select("time", "prn", "azimuth", "elevation")
        .collect()
    )
    result = gt.compute_az_el(frame, changed, navigation).collect()
    assert_frame_equal(result.select(frame.columns), frame, check_exact=True)
    assert_frame_equal(
        result.select(expected.columns).sort("time", "prn"),
        expected.sort("time", "prn"),
        check_exact=True,
    )


@pytest.mark.parametrize(
    "kind", ["null", "integer", "zone", "range", "prn", "stations"]
)
def test_geometry_invalid_inputs(small_observations, navigation, kind):
    header, frame = small_observations
    frame = frame.head(2)
    if kind == "null":
        frame = frame.with_columns(
            pl.lit(None, dtype=frame.schema["time"]).alias("time")
        )
    elif kind == "integer":
        frame = frame.with_columns(pl.lit(1).alias("time"))
    elif kind == "zone":
        frame = frame.with_columns(pl.col("time").dt.convert_time_zone("Asia/Shanghai"))
    elif kind == "range":
        frame = frame.with_columns(pl.lit(datetime(3000, 1, 1)).alias("time"))
    elif kind == "prn":
        frame = frame.with_columns(pl.lit("bad").alias("prn"))
    else:
        frame = frame.with_columns(pl.Series("station", ["A", "B"]))
    with pytest.raises((TypeError, ValueError)):
        gt.compute_az_el(frame, header, navigation)


def test_native_query_validation(navigation):
    for query in (
        pa.record_batch(
            {"_utc_ns": [None], "prn": pa.array(["G01"], type=pa.large_string())}
        ),
        pa.record_batch(
            {
                "_utc_ns": pa.array([0], type=pa.int64()),
                "prn": pa.array([None], type=pa.large_string()),
            }
        ),
        pa.record_batch({"prn": ["G01"]}),
    ):
        with pytest.raises(ValueError):
            _satellite_positions(navigation._handle, query)


def test_native_query_buffers_are_shared(small_observations, navigation):
    _, frame = small_observations
    query = record_batch(
        frame.head(12).select(
            pl.col("time").dt.epoch("ns").alias("_utc_ns"),
            pl.col("prn").cast(pl.String),
        )
    )
    result = _satellite_positions(navigation._handle, query)
    for name in ("_utc_ns", "prn"):
        before = [b.address if b is not None else None for b in query[name].buffers()]
        after = [b.address if b is not None else None for b in result[name].buffers()]
        assert before == after


def test_receiver_coordinates_are_preserved_and_affect_angles(
    small_observations, navigation
):
    header, frame = small_observations
    frame = frame.head(20).with_columns(
        pl.lit(header.rx_geodetic[0], dtype=pl.Float32).alias("rx_lat"),
        pl.lit(header.rx_geodetic[1], dtype=pl.Float32).alias("rx_lon"),
    )
    first = gt.compute_az_el(frame, header, navigation).collect()
    assert_frame_equal(first.select(frame.columns), frame, check_exact=True)
    moved = frame.with_columns(pl.lit(45.0, dtype=pl.Float32).alias("rx_lat"))
    second = gt.compute_az_el(moved, header, navigation).collect()
    assert first["elevation"].ne(second["elevation"]).any()


def test_existing_private_columns_cannot_override_new_geometry(
    small_observations, navigation
):
    header, frame = small_observations
    frame = frame.head(20)
    expected = gt.compute_az_el(frame, header, navigation).collect()
    augmented = frame.with_columns(
        pl.lit(-999.0).alias("_sat_x"),
        pl.lit(999.0).alias("_header_lat"),
        pl.lit(42).alias("_utc_ns"),
    )
    result = gt.compute_az_el(augmented, header, navigation).collect()
    assert_frame_equal(result.select(augmented.columns), augmented, check_exact=True)
    assert_frame_equal(
        result.select("azimuth", "elevation"),
        expected.select("azimuth", "elevation"),
        check_exact=True,
    )


def test_single_receiver_history_keeps_pre_header_geometry_missing(
    small_observations, navigation
):
    header, frame = small_observations
    frame = frame.head(100).reverse()
    start = frame["time"].dt.epoch("ns").max()
    assert start is not None
    header = replace(header, receiver_history=((start, header.rx_ecef, "receiver"),))
    result = gt.compute_az_el(frame, header, navigation).collect()
    before = result.filter(pl.col("time").dt.epoch("ns") < start)
    assert before.height > 0
    assert before["elevation"].null_count() == before.height
    assert_frame_equal(result.select(frame.columns), frame, check_exact=True)


def test_expired_navigation_cannot_produce_angles_or_accepted_tec(
    small_observations, navigation
):
    header, data = small_observations
    data = (
        data.filter(pl.col("prn").cat.starts_with("G"))
        .head(100)
        .drop("azimuth", "elevation", strict=False)
    )
    future = data.with_columns((pl.col("time") + timedelta(days=366)).alias("time"))
    angles = gt.compute_az_el(future, header, navigation).collect()
    assert angles.height == data.height
    assert angles["azimuth"].null_count() == data.height
    assert angles["elevation"].null_count() == data.height
    config = gt.TECConfig(rx_bias=None, retain_diagnostics="all")
    result = gt.compute_tec(
        angles, replace(header, receiver_history=()), config=config
    ).collect()
    assert result.height == data.height
    assert not result["qc_valid"].any()
    assert result["stec"].null_count() == data.height
    assert result["vtec"].null_count() == data.height


def test_precomputed_angles_and_parquet_match_rinex_tec(
    short_rinex_v3, rinex_nav_v3, navigation, tmp_path
):
    header, raw = gt.read_rinex_obs(short_rinex_v3, include_lli=True)
    angles = gt.compute_az_el(raw, header, navigation).collect()
    # Complete diagnostics also checks rejected geometry/QC rows and LLI handling.
    config = gt.TECConfig(retain_diagnostics="all")
    expected = gt.compute_tec_from_rinex(
        short_rinex_v3, rinex_nav_v3, config=config
    ).collect()
    actual = gt.compute_tec(angles, header, config=config).collect()
    assert_frame_equal(actual, expected, check_exact=True)
    target = tmp_path / "angles.parquet"
    angles.write_parquet(target, metadata=header.to_metadata())
    assert_frame_equal(
        gt.compute_tec_from_parquet(target, config=config).collect(),
        expected,
        check_exact=True,
    )
