from datetime import UTC, datetime, timedelta

import numpy as np
import polars as pl
import pytest
from synthetic_observations import C, K, bias_rows, calculate, physical_observations

import gnss_tec as gt
import gnss_tec.tec.tec_calculation as tc
from gnss_tec.tec.bias import prepare_code_bias
from gnss_tec.tec.constants import TECConfig


@pytest.mark.parametrize("span", ["daily", "subdaily", "monthly"])
@pytest.mark.parametrize("reverse", [False, True])
def test_code_bias_is_removed_before_leveling(monkeypatch, span, reverse):
    start = datetime(2024, 1, 10, 23, 58, tzinfo=UTC)
    h, obs = physical_observations(np.full(10, 30.0), start=start)
    boundary = datetime(2024, 1, 11)
    if span == "subdaily":
        boundary = start.replace(tzinfo=None) + timedelta(seconds=150 + 18)
    starts = [boundary - timedelta(days=30), boundary]
    ends = [boundary, boundary + timedelta(days=30)]
    code_bias = np.array(
        [
            1.0 if t.replace(tzinfo=None) + timedelta(seconds=18) < boundary else 2.0
            for t in obs["time"]
        ]
    )
    if span == "monthly":
        starts, ends = starts[:1], ends[-1:]
        code_bias[:] = 1.0
    obs = obs.with_columns(pl.Series("C2W", obs["C2W"].to_numpy() + code_bias / K))
    # SINEX DSB is P1-P2; our observed P2-P1 bias therefore has negative sign.
    ns = np.unique(code_bias) / (-C * 1e-9 * K)
    product = bias_rows(starts, ends, -ns if reverse else ns, reverse=reverse)
    monkeypatch.setattr(tc, "read_bias", lambda _: product.lazy())
    result = calculate(h, obs, "unused")
    np.testing.assert_allclose(result["stec_dcb_corrected"], 30.0, rtol=0, atol=1e-6)
    assert result["arc_id"].n_unique() == 1
    assert result["level_id"].n_unique() == (1 if span == "monthly" else 2)
    assert result["calibration_status"].unique().to_list() == [
        "satellite_code_corrected"
    ]


def test_external_satellite_and_receiver_biases_are_not_subtracted_twice(monkeypatch):
    h, obs = physical_observations(np.full(20, 30.0))
    obs = obs.with_columns(pl.Series("C2W", obs["C2W"].to_numpy() + 5 / K))
    satellite = bias_rows(
        [datetime(2024, 1, 10)], [datetime(2024, 1, 11)], [-1 / (C * 1e-9 * K)]
    )
    receiver = satellite.with_columns(
        pl.lit("TEST").cast(pl.Categorical).alias("station"),
        pl.lit("G").cast(pl.Categorical).alias("prn"),
        pl.lit(-4 / (C * 1e-9 * K)).alias("estimated_value"),
    )
    monkeypatch.setattr(
        tc, "read_bias", lambda _: pl.concat([satellite, receiver]).lazy()
    )
    result = gt.calc_tec_from_df(
        obs, h, "unused", TECConfig(retain_intermediate="all")
    ).collect(engine="in-memory")
    np.testing.assert_allclose(result["stec"], 35.0, rtol=0, atol=1e-6)
    np.testing.assert_allclose(result["stec_dcb_corrected"], 30.0, rtol=0, atol=1e-6)
    assert result["calibration_status"].unique().to_list() == [
        "external_code_corrected"
    ]


@pytest.mark.parametrize("method", ["mstd", "lsq"])
def test_receiver_estimation_recovers_independent_known_bias(monkeypatch, method):
    observations = []
    for index, elevation in enumerate([30.0, 60.0], 1):
        # Independent spherical mapping, with a known 20 TECU vertical signal.
        mf = 1 / np.sqrt(
            1
            - (6378137.0 / (6378137.0 + 400000.0) * np.cos(np.deg2rad(elevation))) ** 2
        )
        h, obs = physical_observations(np.full(20, 20 * mf))
        observations.append(
            obs.with_columns(
                pl.lit(f"G{index:02}").alias("prn"),
                pl.lit(elevation).alias("elevation"),
                pl.Series("C2W", obs["C2W"].to_numpy() + 6 / K),
            )
        )
    satellite = bias_rows(
        [datetime(2024, 1, 10)], [datetime(2024, 1, 11)], [-1 / (C * 1e-9 * K)]
    )
    product = pl.concat(
        [
            satellite,
            satellite.with_columns(pl.lit("G02").cast(pl.Categorical).alias("prn")),
        ]
    )
    monkeypatch.setattr(tc, "read_bias", lambda _: product.lazy())
    result = gt.calc_tec_from_df(
        pl.concat(observations),
        h,
        "unused",
        TECConfig(rx_bias=method, retain_intermediate="all"),
    ).collect(engine="in-memory")
    np.testing.assert_allclose(result["rx_bias"], 5.0, rtol=0, atol=1e-5)
    np.testing.assert_allclose(result["vtec"], 20.0, rtol=0, atol=1e-5)
    assert result["qc_valid"].all()
    assert result["calibration_status"].unique().to_list() == [
        f"satellite_code_corrected_receiver_{method}_estimated"
    ]


@pytest.mark.parametrize(
    "column,value",
    [
        ("bias", "OSB"),
        ("unit", "cyc"),
        ("unit", "m"),
        ("time_system", "U"),
        ("obs1", "L1C"),
        ("estimated_value", float("nan")),
    ],
)
def test_unsupported_bias_semantics_are_rejected(column, value):
    product = bias_rows(
        [datetime(2024, 1, 10)], [datetime(2024, 1, 11)], [1.0]
    ).with_columns(pl.lit(value).alias(column))
    with pytest.raises(ValueError, match="Unsupported bias semantics"):
        prepare_code_bias(product.lazy())


def test_overlap_and_expired_bias_are_explicit(monkeypatch):
    product = bias_rows(
        [datetime(2024, 1, 10)] * 2, [datetime(2024, 1, 11)] * 2, [1.0, 2.0]
    )
    with pytest.raises(ValueError, match="Overlapping"):
        prepare_code_bias(product.lazy())
    h, obs = physical_observations(np.full(10, 30.0))
    expired = product.head(1).with_columns(
        (pl.col("bias_end") - pl.duration(days=1)).alias("bias_end"),
        (pl.col("bias_start") - pl.duration(days=1)).alias("bias_start"),
    )
    monkeypatch.setattr(tc, "read_bias", lambda _: expired.lazy())
    result = calculate(h, obs, "unused", missing_bias="keep_uncorrected")
    assert result["calibration_status"].unique().to_list() == [
        "uncorrected_missing_bias"
    ]
    assert result["tx_bias"].null_count() == result.height


def test_failed_receiver_estimation_is_not_a_zero_correction(monkeypatch):
    h, obs = physical_observations(np.full(6, 30.0))
    product = bias_rows([datetime(2024, 1, 10)], [datetime(2024, 1, 11)], [0.0])
    monkeypatch.setattr(tc, "read_bias", lambda _: product.lazy())
    result = gt.calc_tec_from_df(
        obs, h, "unused", TECConfig(rx_bias="mstd", retain_intermediate="all")
    ).collect(engine="in-memory")
    assert result["rx_bias"].null_count() == result.height
    assert result["stec"].null_count() == result.height
    assert result["vtec"].null_count() == result.height
    assert not result["qc_valid"].any()
    assert result["calibration_status"].unique().to_list() == [
        "receiver_estimation_failed"
    ]
