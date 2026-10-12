from dataclasses import replace

import numpy as np
import polars as pl
import pytest
from synthetic_observations import calculate, physical_observations


def test_inferred_cadence_is_specific_to_each_satellite():
    h, fast = physical_observations(np.full(20, 30.0), cadence=0.5)
    _, slow = physical_observations(np.full(20, 30.0), cadence=1)
    slow = slow.with_columns(pl.lit("G02").alias("prn"))
    result = calculate(replace(h, sampling_interval=None), pl.concat([fast, slow]))
    assert result.group_by("prn").agg(pl.col("arc_id").n_unique())[
        "arc_id"
    ].to_list() == [1, 1]
    np.testing.assert_allclose(result["stec"], 30.0, atol=1e-6, rtol=0)


def test_missing_constellation_pair_remains_diagnosable():
    h, gps = physical_observations(np.full(6, 30.0))
    bds = gps.with_columns(pl.lit("C01").alias("prn"))
    result = calculate(h, pl.concat([gps, bds]))
    rejected = result.filter(pl.col("prn") == "C01")
    assert rejected.height == 6
    assert not rejected["qc_valid"].any()
    assert rejected["stec"].null_count() == rejected.height
    np.testing.assert_allclose(
        result.filter("qc_valid")["stec"], 30.0, atol=1e-6, rtol=0
    )


@pytest.mark.parametrize("column", ["C1C", "C2W", "L1C", "L2W", "azimuth", "elevation"])
@pytest.mark.parametrize("bad", [float("nan"), float("inf"), -float("inf")])
def test_one_nonfinite_value_cannot_poison_an_arc(column, bad):
    h, obs = physical_observations(np.full(8, 30.0))
    values = obs[column].to_list()
    values[3] = bad
    obs = obs.with_columns(pl.Series(column, values))
    result = calculate(h, obs)
    assert result["stec"].item(3) is None
    assert not result["qc_valid"].item(3)
    np.testing.assert_allclose(
        result.filter("qc_valid")["stec"], 30.0, rtol=0, atol=1e-6
    )
    assert "invalid" in result["qc_reason"].item(3) or "nonfinite" in result[
        "qc_reason"
    ].item(3)


def test_complete_pair_fallback_and_signal_switch():
    h, obs = physical_observations(np.full(10, 30.0))
    obs = obs.with_columns(pl.col("C1C").alias("C1W"))
    assert calculate(h, obs)["C1_code"].unique().to_list() == ["C1C"]
    obs = obs.with_columns(pl.Series("L1W", [None] * 5 + obs["L1C"].to_list()[5:]))
    result = calculate(h, obs)
    # Joint daily coverage wins while both pairs remain usable.
    assert result["C1_code"].unique().to_list() == ["C1C"]
    obs = obs.with_columns(pl.Series("L1C", obs["L1C"].to_list()[:5] + [None] * 5))
    result = calculate(h, obs)
    assert result["C1_code"].to_list() == ["C1C"] * 5 + ["C1W"] * 5
    assert result["arc_id"].n_unique() == 2
    assert "signal_pair_change" in result["qc_reason"].item(5)


def test_finite_input_overflow_is_rejected_before_leveling():
    h, obs = physical_observations(np.full(6, 30.0))
    values = obs["C1C"].to_list()
    values[2] = 1e308
    result = calculate(h, obs.with_columns(pl.Series("C1C", values)))
    assert not result["qc_valid"].item(2)
    np.testing.assert_allclose(
        result.filter("qc_valid")["stec"], 30.0, rtol=0, atol=1e-6
    )
