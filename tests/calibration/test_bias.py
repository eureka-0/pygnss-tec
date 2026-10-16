from datetime import UTC, datetime, timedelta

import numpy as np
import polars as pl
import pytest

import gnss_tec as gt
import gnss_tec.calculation.tec as tc
from gnss_tec.calibration.code_bias import prepare_code_bias
from gnss_tec.configuration import TECConfig
from tests.support.observations import (
    F1,
    C,
    K,
    bias_rows,
    calculate,
    physical_observations,
)


@pytest.mark.parametrize(
    "span,reverse", [("daily", False), ("subdaily", True), ("monthly", False)]
)
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
    assert {"level_id", "offset", "weight", "tx_bias_start", "tx_bias_end"}.isdisjoint(
        result.columns
    )
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
        obs, h, "unused", TECConfig(retain_diagnostics="all")
    ).collect(engine="in-memory")
    np.testing.assert_allclose(result["stec"], 35.0, rtol=0, atol=1e-6)
    np.testing.assert_allclose(result["stec_dcb_corrected"], 30.0, rtol=0, atol=1e-6)
    assert result["calibration_status"].unique().to_list() == [
        "external_code_corrected"
    ]


def test_repair_continuity_preserves_independent_bias_levels(monkeypatch):
    """Align raw and calibrated STEC independently after bias-reference changes."""
    h, obs = physical_observations(np.full(120, 30.0))
    code_bias = np.r_[np.ones(80), np.full(40, 2.0)]
    code_noise = np.r_[np.full(40, -0.02), np.full(40, 0.02), np.zeros(40)]
    phase_jump = np.r_[np.zeros(40), np.full(80, 5.0)]
    obs = obs.with_columns(
        pl.Series("C2W", obs["C2W"].to_numpy() + (code_bias + code_noise) / K),
        pl.Series("L1C", obs["L1C"].to_numpy() + phase_jump),
    )
    boundary = obs["time"][80].replace(tzinfo=None) + timedelta(seconds=18)
    product = bias_rows(
        [datetime(2024, 1, 10), boundary],
        [boundary, datetime(2024, 1, 11)],
        [-1 / (C * 1e-9 * K), -2 / (C * 1e-9 * K)],
    )
    monkeypatch.setattr(tc, "read_bias", lambda _: product.lazy())
    result = calculate(h, obs, "unused")
    assert result["slip_status"][40] == "phase_repaired"
    assert result["slip_n1"][40] is None
    assert result["arc_id"][40] != result["arc_id"][39]
    np.testing.assert_allclose(result["stec_dcb_corrected"], 30, rtol=0, atol=1e-6)
    np.testing.assert_allclose(result["stec"], 31, rtol=0, atol=1e-6)
    assert result["slip_stec_correction"][80] == pytest.approx(1, abs=1e-6)
    assert result["slip_dcb_correction"][80] == pytest.approx(0, abs=1e-6)
    np.testing.assert_allclose(result["vtec"] * result["mf"], 30, rtol=0, atol=1e-6)


@pytest.mark.parametrize("duration,bias_error", [(1, None), (6, 0.0), (1, 3.0)])
def test_signal_switch_keeps_each_final_product_continuous(
    monkeypatch, duration, bias_error
):
    """A temporary fallback has different frequencies, ambiguities and DCBs."""
    truth = 30 + np.arange(80) * 0.01
    header, obs = physical_observations(truth)
    switched = (np.arange(len(obs)) >= 40) & (np.arange(len(obs)) < 40 + duration)
    f5 = 1176.45e6
    k15 = F1**2 * f5**2 / (F1**2 - f5**2) / 40.3e16
    distance = 21_000_000.0
    obs = obs.with_columns(
        pl.Series("C1X", np.where(switched, obs["C1C"].to_numpy(), np.nan)),
        pl.Series("L1X", np.where(switched, obs["L1C"].to_numpy() + 7, np.nan)),
        pl.Series(
            "C5X",
            np.where(switched, distance + 40.3e16 * truth / f5**2 + 83 / k15, np.nan),
        ),
        pl.Series(
            "L5X",
            np.where(
                switched, (distance - 40.3e16 * truth / f5**2) * f5 / C - 2, np.nan
            ),
        ),
        pl.Series("C1C", np.where(switched, np.nan, obs["C1C"].to_numpy())),
        pl.Series("L1C", np.where(switched, np.nan, obs["L1C"].to_numpy())),
        pl.Series("C2W", np.where(switched, np.nan, obs["C2W"].to_numpy() + 1 / K)),
        pl.Series("L2W", np.where(switched, np.nan, obs["L2W"].to_numpy())),
    )
    if bias_error is not None:
        primary = bias_rows(
            [datetime(2024, 1, 10)], [datetime(2024, 1, 11)], [-1 / (C * 1e-9 * K)]
        )
        fallback = primary.with_columns(
            pl.lit("C1X").cast(pl.Categorical).alias("obs1"),
            pl.lit("C5X").cast(pl.Categorical).alias("obs2"),
            pl.lit(-(83 - bias_error) / (C * 1e-9 * k15)).alias("estimated_value"),
        )
        monkeypatch.setattr(
            tc, "read_bias", lambda _: pl.concat([primary, fallback]).lazy()
        )
    result = calculate(header, obs, "unused" if bias_error is not None else None)
    assert result["C2_code"][40] == "C5X"
    assert result["C2_code"][40 + duration] == "C2W"
    for name in ("stec_p_corrected", "stec", "stec_dcb_corrected"):
        if name in result.columns:
            np.testing.assert_allclose(
                np.diff(result[name]), np.diff(truth), rtol=0, atol=1e-6
            )
    source = "stec_dcb_corrected" if bias_error is not None else "stec"
    np.testing.assert_allclose(
        result["vtec"] * result["mf"], result[source], rtol=0, atol=1e-12
    )
    if bias_error == 0:
        assert result["slip_stec_correction"][40] == pytest.approx(82, abs=1e-6)
        assert result["slip_dcb_correction"][40] == pytest.approx(0, abs=1e-6)


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
        TECConfig(rx_bias=method, retain_diagnostics="all"),
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
        obs, h, "unused", TECConfig(rx_bias="mstd", retain_diagnostics="all")
    ).collect(engine="in-memory")
    assert result["rx_bias"].null_count() == result.height
    assert result["stec"].null_count() == result.height
    assert result["vtec"].null_count() == result.height
    assert not result["qc_valid"].any()
    assert result["calibration_status"].unique().to_list() == [
        "receiver_estimation_failed"
    ]
