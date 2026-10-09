"""Scientific and ordering contracts shared by Polars 1.x and 2.x."""

import math
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Literal

import numpy as np
import polars as pl
import pytest
from polars.testing import assert_frame_equal

import gnss_tec as gt
import gnss_tec.tec.tec_calculation as tc
from gnss_tec.rinex import RinexObsHeader
from gnss_tec.tec.bias import _lsq_rx_bias, _mstd_rx_bias
from gnss_tec.tec.constants import Re, c


@pytest.fixture(params=["in-memory", "streaming"])
def engine(request):
    with pl.Config(engine_affinity=request.param):
        yield request.param


@pytest.fixture
def observations() -> tuple[RinexObsHeader, pl.DataFrame]:
    header = RinexObsHeader(
        version="3.04",
        constellation="G",
        marker_name="TEST",
        marker_type=None,
        rx_ecef=(6378137.0, 0.0, 0.0),
        rx_geodetic=(0.0, 0.0, 0.0),
        sampling_interval=30,
        leap_seconds=18,
    )
    f1, f2 = 1575.42e6, 1227.60e6
    coeff = f1**2 * f2**2 / (f1**2 - f2**2) / 40.3e16
    # Two arcs per PRN, crossing a day boundary; slips after the 10-point window.
    seconds = [i * 30 for i in range(24)] + [1500 + i * 30 for i in range(24)]
    start = datetime(2024, 1, 10, 23, 50, tzinfo=UTC)
    phase = np.tile(np.r_[np.full(12, 5.0), np.full(12, 13.0)], 2)
    df = pl.DataFrame(
        {
            "time": [start + timedelta(seconds=s) for s in seconds] * 2,
            "station": ["TEST"] * 96,
            "prn": ["G02"] * 48 + ["G01"] * 48,
            "azimuth": [90.0] * 96,
            "elevation": np.tile(np.linspace(30, 80, 48), 2),
            "C1C": [0.0] * 96,
            "C2W": np.tile(np.linspace(30, 50, 48), 2) / coeff,
            "L1C": np.tile(phase, 2) * f1 / (c * coeff),
            "L2W": [0.0] * 96,
        }
    ).with_columns(pl.col("elevation", "azimuth").cast(pl.Float32))
    return header, df


def _calculate(df: pl.DataFrame | pl.LazyFrame, header: RinexObsHeader) -> pl.DataFrame:
    return gt.calc_tec_from_df(
        df, header, config=gt.TECConfig(rx_bias=None, retain_intermediate="all")
    ).collect()


def test_scientific_reference(observations, engine):
    header, raw = observations
    result = _calculate(raw, header)
    assert result.select("time", "station", "prn").equals(
        result.select("time", "station", "prn").sort("time", "station", "prn")
    )
    f1, f2 = 1575.42e6, 1227.60e6
    coeff = f1**2 * f2**2 / (f1**2 - f2**2) / 40.3e16
    np.testing.assert_array_equal(
        result["C1_freq"].to_numpy(), np.full(result.height, f1)
    )
    np.testing.assert_array_equal(
        result["C2_freq"].to_numpy(), np.full(result.height, f2)
    )
    elevation = np.deg2rad(result["elevation"].to_numpy().astype(np.float64))
    expected_mf = 1 / np.sqrt(1 - (Re / (Re + 400_000) * np.cos(elevation)) ** 2)
    np.testing.assert_allclose(result["mf"].to_numpy(), expected_mf, rtol=0, atol=1e-12)
    np.testing.assert_allclose(result["stec_p"].to_numpy(), 5.0, rtol=0, atol=1e-12)
    assert result["arc_id"].unique().sort().to_list() == [0, 1]
    for group in result.partition_by("station", "prn", "arc_id"):
        keys = group.select("time", "station", pl.col("prn").cast(pl.String))
        source = keys.join(raw, on=["time", "station", "prn"], maintain_order="left")
        expected_g = (source["C2W"].to_numpy() - source["C1C"].to_numpy()) * coeff
        np.testing.assert_allclose(
            group["stec_g"].to_numpy(), expected_g, rtol=0, atol=1e-12
        )
        # Independent NumPy Float64 trigonometry and accurately rounded sums.
        weights = (
            np.sin(np.deg2rad(source["elevation"].to_numpy().astype(np.float64))) ** 2
        )
        offset = math.fsum(
            (g - 5.0) * w for g, w in zip(expected_g, weights, strict=True)
        ) / math.fsum(weights)
        np.testing.assert_allclose(
            group["offset"].to_numpy(), offset, rtol=0, atol=1e-12
        )
        np.testing.assert_allclose(
            group["stec"].to_numpy(), 5.0 + offset, rtol=0, atol=1e-12
        )
        np.testing.assert_allclose(
            group["vtec"].to_numpy(),
            group["stec"].to_numpy() / group["mf"].to_numpy(),
            rtol=0,
            atol=1e-12,
        )


@pytest.mark.parametrize("source", ["dataframe", "lazyframe", "parquet"])
def test_shuffled_input_and_inferred_cadence(observations, engine, source, tmp_path):
    header, raw = observations
    expected = _calculate(raw, header)
    shuffled = raw.sample(fraction=1, shuffle=True, seed=17)
    inferred_header = replace(header, sampling_interval=None)
    if source == "parquet":
        path = tmp_path / "shuffled.parquet"
        shuffled.write_parquet(path, metadata=inferred_header.to_metadata())
        actual = gt.calc_tec_from_parquet(
            path, config=gt.TECConfig(rx_bias=None, retain_intermediate="all")
        ).collect()
    else:
        actual = _calculate(
            shuffled.lazy() if source == "lazyframe" else shuffled, inferred_header
        )
    assert_frame_equal(actual, expected, check_exact=False, rel_tol=0, abs_tol=1e-10)


def test_chunked_whole_arc_udf(observations, engine):
    header, raw = observations
    chunked = pl.concat(
        [raw.slice(i, 7) for i in range(0, raw.height, 7)], rechunk=False
    )
    assert chunked["time"].n_chunks() > 1
    assert_frame_equal(
        _calculate(chunked, header),
        _calculate(raw.rechunk(), header),
        check_exact=False,
        rel_tol=0,
        abs_tol=1e-10,
    )


def test_float32_geometry_matches_float64_input(observations, engine):
    header, raw = observations
    raw = raw.with_columns(
        pl.lit(12.345678, dtype=pl.Float32).alias("rx_lat"),
        pl.lit(45.678901, dtype=pl.Float32).alias("rx_lon"),
    )
    geometry = ["azimuth", "elevation", "rx_lat", "rx_lon"]
    expected = _calculate(raw.with_columns(pl.col(geometry).cast(pl.Float64)), header)
    actual = _calculate(raw.lazy(), header)
    assert all(actual.schema[name] == pl.Float64 for name in geometry)
    assert_frame_equal(actual, expected, check_exact=False, rel_tol=0, abs_tol=1e-12)


def test_duplicate_times_are_rejected(observations, engine):
    header, raw = observations
    with pytest.raises(ValueError, match="unique within each station/PRN"):
        _calculate(
            pl.concat([raw, raw.head(1)]), replace(header, sampling_interval=None)
        )


@pytest.mark.parametrize("rows", [0, 1])
def test_no_inferable_interval_is_actionable(observations, rows):
    header, raw = observations
    with pytest.raises(ValueError, match="Cannot infer sampling interval"):
        _calculate(raw.head(rows), replace(header, sampling_interval=None))


def test_empty_and_zero_weight_arcs(observations, engine):
    header, raw = observations
    assert _calculate(raw.head(0), header).is_empty()
    zero = raw.with_columns(pl.lit(0.0, dtype=pl.Float32).alias("elevation"))
    result = gt.calc_tec_from_df(
        zero, header, config=gt.TECConfig(min_elevation=0, retain_intermediate="all")
    ).collect()
    assert result["offset"].null_count() == result.height
    assert result["stec"].null_count() == result.height


def test_fractional_and_mixed_cadences(observations, engine):
    header, raw = observations
    raw = raw.filter(pl.col("prn") == "G01").head(24)
    base = raw["time"].item(0)
    fast = raw.with_columns(
        pl.Series("time", [base + timedelta(seconds=i * 0.5) for i in range(24)])
    )
    slow = raw.with_columns(
        pl.lit("G02").alias("prn"),
        pl.Series("time", [base + timedelta(seconds=i) for i in range(24)]),
    )
    mixed = pl.concat([slow, fast]).sample(fraction=1, shuffle=True, seed=4)
    result = _calculate(mixed, replace(header, sampling_interval=None))
    # Fast cadence selects the 20-sample correction window for all groups.
    assert result.filter(pl.col("prn") == "G01")["stec_p"].item(12) == pytest.approx(13)
    assert result.height == mixed.height


def test_mixed_high_and_low_rate_inference_is_actionable(observations, engine):
    header, raw = observations
    raw = raw.with_columns(
        pl.when(pl.col("prn") == "G01")
        .then(pl.col("time") - (pl.col("time") - pl.col("time").min()) / 2)
        .otherwise(pl.col("time"))
        .alias("time")
    )
    # 15 s and 30 s share the same arc/slip and bias-sampling settings.
    assert _calculate(raw, replace(header, sampling_interval=None)).height == raw.height
    raw = raw.with_columns(
        pl.when(pl.col("prn") == "G01")
        .then(pl.col("time") - (pl.col("time") - pl.col("time").min()) * (14 / 15))
        .otherwise(pl.col("time"))
        .alias("time")
    )
    with pytest.raises(ValueError, match="process sampling groups separately"):
        _calculate(raw, replace(header, sampling_interval=None))


def test_missing_second_band_is_preserved_until_observation_filter(
    observations, engine
):
    header, raw = observations
    missing = (
        raw.drop("C2W", "L2W").lazy().with_columns(pl.col("prn").cast(pl.Categorical))
    )
    selected = tc._coalesce_observations(missing, None, gt.TECConfig(), "3").collect()
    assert selected.height == raw.height
    assert selected["C2_code"].null_count() == raw.height
    assert _calculate(raw.drop("C2W", "L2W"), header).is_empty()


def test_weighted_code_priority_and_deterministic_ties(observations, engine):
    _, raw = observations
    raw = raw.with_columns(
        pl.col("C1C").alias("C1W"),
        pl.col("C2W").alias("C2C"),
        pl.col("C2W").alias("C2X"),
    )
    # Make (C1W,C2X) and (C1C,C2W) tie at score 2. The latter wins lexically.
    bias = pl.DataFrame(
        {
            "station": [None, None],
            "prn": ["G01", "G01"],
            "obs1": ["C1W", "C1C"],
            "obs2": ["C2X", "C2W"],
            "bias_start": [datetime(2024, 1, 10, tzinfo=UTC).replace(tzinfo=None)] * 2,
            "estimated_value": [0.0, 0.0],
        }
    ).with_columns(pl.col("prn", "obs1", "obs2").cast(pl.Categorical))
    raw = raw.filter((pl.col("prn") == "G01") & (pl.col("time").dt.day() == 10))
    selected = tc._coalesce_observations(
        raw.lazy().with_columns(pl.col("prn").cast(pl.Categorical)),
        bias.lazy(),
        gt.TECConfig(rx_bias=None),
        "3",
    ).collect()
    assert selected["C1_code"].unique().to_list() == ["C1C"]
    assert selected["C2_code"].unique().to_list() == ["C2W"]
    # Without bias filtering, score 0 must still win over any tie.
    selected = tc._coalesce_observations(
        raw.lazy().with_columns(pl.col("prn").cast(pl.Categorical)),
        None,
        gt.TECConfig(),
        "3",
    ).collect()
    assert selected["C1_code"].unique().to_list() == ["C1W"]
    assert selected["C2_code"].unique().to_list() == ["C2W"]


def test_duplicate_bias_keys_do_not_multiply_observations(
    observations, engine, monkeypatch
):
    header, raw = observations
    bias = pl.DataFrame(
        {
            "station": [None, None],
            "prn": ["G01", "G01"],
            "obs1": ["C1C", "C1C"],
            "obs2": ["C2W", "C2W"],
            "bias_start": [datetime(2024, 1, 10, tzinfo=UTC).replace(tzinfo=None)] * 2,
            "estimated_value": [1.0, 2.0],
        }
    ).with_columns(pl.col("prn", "obs1", "obs2").cast(pl.Categorical))
    monkeypatch.setattr(tc, "read_bias", lambda _: bias.lazy())
    with pytest.raises(pl.exceptions.ComputeError, match="validation"):
        gt.calc_tec_from_df(
            raw, header, Path("unused"), gt.TECConfig(rx_bias=None)
        ).collect()


@pytest.mark.parametrize("method", ["mstd", "lsq"])
@pytest.mark.parametrize("cadence", [1, 5])
def test_receiver_bias_high_rate_order(
    observations, engine, monkeypatch, method: Literal["mstd", "lsq"], cadence
):
    header, raw = observations
    start = raw["time"].item(0)
    raw = raw.with_columns(
        pl.Series(
            "time", [start + (time - start) / (30 / cadence) for time in raw["time"]]
        )
    )
    bias = pl.DataFrame(
        {
            "station": [None, None],
            "prn": ["G01", "G02"],
            "obs1": ["C1C", "C1C"],
            "obs2": ["C2W", "C2W"],
            "bias_start": [datetime(2024, 1, 10, tzinfo=UTC).replace(tzinfo=None)] * 2,
            "estimated_value": [1.0, 1.0],
        }
    ).with_columns(pl.col("prn", "obs1", "obs2").cast(pl.Categorical))
    monkeypatch.setattr(tc, "read_bias", lambda _: bias.lazy())
    config = gt.TECConfig(
        rx_bias=method, missing_bias="keep_uncorrected", retain_intermediate="all"
    )
    header = replace(header, sampling_interval=cadence)
    expected = gt.calc_tec_from_df(raw, header, Path("unused"), config).collect()
    actual = gt.calc_tec_from_df(
        raw.sample(fraction=1, shuffle=True, seed=6), header, Path("unused"), config
    ).collect()
    assert_frame_equal(actual, expected, check_exact=False, rel_tol=0, abs_tol=1e-8)


@pytest.mark.parametrize("policy", ["drop", "warn", "error", "keep_uncorrected"])
def test_missing_band_bias_diagnostics(observations, engine, bias, policy):
    header, raw = observations
    missing = raw.drop("C2W", "L2W")
    config = gt.TECConfig(rx_bias=None, missing_bias=policy)
    if policy == "error":
        with pytest.raises(ValueError, match="missing required bias columns"):
            gt.calc_tec_from_df(missing, header, bias, config)
    elif policy == "warn":
        with pytest.warns(UserWarning, match="missing required bias columns"):
            result = gt.calc_tec_from_df(missing, header, bias, config).collect()
        assert result.is_empty()
    else:
        assert gt.calc_tec_from_df(missing, header, bias, config).collect().is_empty()


def test_single_point_and_all_missing_phase(observations, engine):
    header, raw = observations
    single = _calculate(raw.head(1), header)
    assert single["stec"].item() == pytest.approx(30.0, abs=1e-12)
    missing = raw.with_columns(pl.lit(None, dtype=pl.Float64).alias("L1C"))
    assert _calculate(missing, header).is_empty()


def test_cycle_slip_threshold_and_long_arc():
    time = np.arange(100_000, dtype=np.float64)
    phase = np.zeros_like(time)
    phase[20:] = 0.5
    # The threshold is strict; an equal-sized jump is retained.
    np.testing.assert_array_equal(tc._correct_cycle_slip(time, phase, 0.5, 20), phase)
    phase[20:] = 0.500001
    np.testing.assert_array_equal(
        tc._correct_cycle_slip(time, phase, 0.5, 20), np.zeros_like(time)
    )


def test_external_dcb_sign_and_units(observations, engine, monkeypatch):
    header, raw = observations
    raw = raw.filter(pl.col("time").dt.day() == 10)
    bias = pl.DataFrame(
        {
            "station": [None, None, "TEST"],
            "prn": ["G01", "G02", "G"],
            "obs1": ["C1C"] * 3,
            "obs2": ["C2W"] * 3,
            "bias_start": [datetime(2024, 1, 10, tzinfo=UTC).replace(tzinfo=None)] * 3,
            "estimated_value": [1.0, 1.0, 2.0],
        }
    ).with_columns(pl.col("prn", "obs1", "obs2").cast(pl.Categorical))
    monkeypatch.setattr(tc, "read_bias", lambda _: bias.lazy())
    result = gt.calc_tec_from_df(
        raw, header, Path("unused"), gt.TECConfig(retain_intermediate="all")
    ).collect()
    f1, f2 = 1575.42e6, 1227.60e6
    tecu_per_ns = 1e-9 * c * f1**2 * f2**2 / (f1**2 - f2**2) / 40.3e16
    np.testing.assert_allclose(
        result["tx_bias"].to_numpy(), -tecu_per_ns, rtol=0, atol=1e-12
    )
    np.testing.assert_allclose(
        result["rx_bias"].to_numpy(), -2 * tecu_per_ns, rtol=0, atol=1e-12
    )
    np.testing.assert_allclose(
        result["stec_dcb_corrected"].to_numpy(),
        result["stec"].to_numpy() + 3 * tecu_per_ns,
        rtol=0,
        atol=1e-12,
    )


@pytest.mark.parametrize("method", [_mstd_rx_bias, _lsq_rx_bias])
def test_receiver_solver_known_bias_and_residual(method):
    rng = np.random.default_rng(13)
    times = [
        datetime(2024, 1, 10, 18, tzinfo=UTC).replace(tzinfo=None)
        + timedelta(minutes=i * 3)
        for i in range(240)
        for _ in range(4)
    ]
    mf = rng.uniform(1.0, 2.0, len(times))
    known_bias = 12.0
    data = pl.DataFrame(
        {
            "time": times,
            "stec": 20 * mf + 1 + known_bias,
            "tx_bias": [1.0] * len(times),
            "mf": mf,
            "ipp_lat": rng.uniform(35, 45, len(times)),
            "ipp_lon": [0.0] * len(times),
            "rx_lat": [40.0] * len(times),
        }
    )
    estimate = method(data.select(pl.struct(pl.all())).to_series())
    assert estimate == pytest.approx(known_bias, abs=1e-5)
    residual = (data["stec"].to_numpy() - 1 - estimate) / mf - 20
    assert np.max(np.abs(residual)) < 1e-5
