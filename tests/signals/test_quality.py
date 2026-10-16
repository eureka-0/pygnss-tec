from dataclasses import replace

import numpy as np
import polars as pl
import pytest

import gnss_tec as gt
from tests.support.observations import (
    calculate,
    physical_observations,
    write_minimal_rinex,
)


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


@pytest.mark.parametrize(
    "column,bad",
    [
        ("C1C", float("nan")),
        ("C2W", float("inf")),
        ("L1C", -float("inf")),
        ("L2W", float("nan")),
        ("azimuth", float("inf")),
        ("elevation", -float("inf")),
    ],
)
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


@pytest.mark.parametrize("bad", ["half_cycle", "low_snr", "nan_snr"])
def test_usable_pair_wins_before_priority(bad):
    h, obs = physical_observations(np.full(20, 30.0))
    obs = obs.with_columns(
        pl.col("C1C").alias("C1W"),
        pl.col("L1C").alias("L1W"),
        pl.lit(45.0).alias("S1C"),
        pl.lit(45.0).alias("S1W"),
    )
    if bad == "half_cycle":
        obs = obs.with_columns(pl.lit(2, dtype=pl.UInt8).alias("L1W_lli"))
    else:
        value = {"low_snr": 10.0, "nan_snr": float("nan"), "inf_snr": float("inf")}[bad]
        obs = obs.with_columns(pl.lit(value).alias("S1W"))
    result = calculate(h, obs)
    assert result.height == 20
    assert result["qc_valid"].all()
    assert result["C1_code"].to_list() == ["C1C"] * 20
    np.testing.assert_allclose(result["stec"], 30.0, atol=1e-6, rtol=0)


def test_loss_of_lock_does_not_disqualify_a_preferred_pair():
    h, obs = physical_observations(np.full(20, 30.0))
    obs = obs.with_columns(
        pl.col("C1C").alias("C1W"),
        pl.col("L1C").alias("L1W"),
        pl.Series("L1W_lli", [0] * 10 + [1] + [0] * 9, dtype=pl.UInt8),
    )
    result = calculate(h, obs)
    assert result["qc_valid"].all()
    assert result["C1_code"].to_list() == ["C1W"] * 20
    assert result["arc_id"].n_unique() == 2
    assert "loss_of_lock" in result["qc_reason"].item(10)


def test_no_usable_pair_keeps_rejection_diagnostics():
    h, obs = physical_observations(np.full(20, 30.0))
    result = calculate(h, obs.with_columns(pl.lit(2, dtype=pl.UInt8).alias("L1C_lli")))
    assert result.height == 20
    assert not result["qc_valid"].any()
    assert result["stec"].null_count() == 20
    assert result["qc_reason"].str.contains("half_cycle_invalid").all()


@pytest.mark.parametrize("null_count", [5, 6])
def test_snr_null_policy_keeps_the_strict_majority_and_station_groups(null_count):
    h, obs = physical_observations(np.full(10, 30.0))
    first = obs.with_columns(
        pl.Series("S1C", [None] * null_count + [45.0] * (10 - null_count))
    )
    second = obs.with_columns(
        pl.lit("OTHER").alias("station"), pl.lit(45.0).alias("S1C")
    )
    result = calculate(h, pl.concat([first, second]))
    first = result.filter(pl.col("station") == "TEST")
    assert first["qc_valid"].sum() == (10 if null_count > 5 else 10 - null_count)
    assert result.filter(pl.col("station") == "OTHER")["qc_valid"].all()


def test_reader_lli_drives_twenty_epoch_half_cycle_fallback(tmp_path):
    path = tmp_path / "fallback.rnx"
    write_minimal_rinex(path, 3, flagged=False)
    text = path.read_text()
    end = text.index("END OF HEADER\n") + len("END OF HEADER\n")
    header = text[:end]
    code_line = next(
        line for line in header.splitlines() if "SYS / # / OBS TYPES" in line
    )
    header = header.replace(
        code_line, f"{'G    6 C1C L1C C2W L2W C1W L1W':<60}SYS / # / OBS TYPES"
    )
    _, obs = physical_observations(np.full(20, 30.0), cadence=0.1)
    records = []
    for i in range(20):
        records.append(f"> 2024 01 10 00 00 {i * 0.1:10.7f}  0  1\nG01")
        for j, code in enumerate(("C1C", "L1C", "C2W", "L2W", "C1C", "L1C")):
            lli = 2 if j == 5 else 0
            records.append(f"{obs[code].item(i):14.3f}{lli}7")
        records.append("\n")
    path.write_text(header + "".join(records))
    header, lf = gt.read_rinex_obs(path, include_lli=True)
    result = calculate(
        header,
        lf.with_columns(pl.lit(90.0).alias("azimuth"), pl.lit(60.0).alias("elevation")),
    )
    assert result.height == 20
    assert result["qc_valid"].all()
    assert result["C1_code"].to_list() == ["C1C"] * 20


def test_half_cycle_fallback_rechecks_selected_pair_snr_groups():
    h, obs = physical_observations(np.full(20, 30.0))
    obs = obs.with_columns(
        pl.col("C1C").alias("C1W"),
        pl.col("L1C").alias("L1W"),
        pl.lit(45.0).alias("S1C"),
        pl.Series("S1W", [None] * 12 + [45.0] * 8),
        pl.Series("L1W_lli", [2] * 10 + [0] * 10, dtype=pl.UInt8),
    )
    result = calculate(h, obs)
    assert result["qc_valid"].all()
    assert result["C1_code"].to_list() == ["C1C"] * 12 + ["C1W"] * 8
    np.testing.assert_allclose(result["stec"], 30.0, rtol=0, atol=1e-6)


def test_snr_fallback_restores_candidates_after_the_selected_group_changes():
    h, obs = physical_observations(np.full(10, 30.0))
    obs = obs.with_columns(
        pl.col("C1C").alias("C1W"),
        pl.col("L1C").alias("L1W"),
        pl.Series("S1W", [45.0, 45.0, None, None, None] + [45.0] * 5),
        pl.Series("S1C", [None, 45.0, None, None, None] + [45.0] * 5),
        pl.Series("L1W_lli", [2, 2] + [0] * 8, dtype=pl.UInt8),
    )
    result = calculate(h, obs)
    # C1C initially has one null in two selected rows. After fallback its four
    # nulls in five rows pass the unchanged strict-majority SNR policy.
    assert result["C1_code"].to_list() == ["C1C"] * 5 + ["C1W"] * 5
    assert result["qc_valid"].all()
    np.testing.assert_allclose(result["stec"], 30.0, rtol=0, atol=1e-6)


def test_cyclic_snr_groups_terminate_and_preserve_final_acceptance(monkeypatch):
    from gnss_tec.signals import selection

    h, obs = physical_observations(np.full(6, 30.0))
    obs = obs.with_columns(
        pl.col("C1C").alias("C1W"),
        pl.col("L1C").alias("L1W"),
        pl.Series("S1W", [45.0, None, 45.0, 45.0, None, 45.0]),
        pl.Series("S1C", [None, None, 45.0, 45.0, None, 45.0]),
        pl.Series("S2W", [None, 45.0, None, None, 45.0, None]),
        pl.Series("L1W_lli", [0, 2, 2, 0, 2, 2], dtype=pl.UInt8),
        pl.Series("L1C_lli", [0, 0, 0, 2, 0, 0], dtype=pl.UInt8),
    )
    select = selection._select_observations
    calls = 0

    def bounded_select(*args):
        nonlocal calls
        calls += 1
        assert calls <= 20, "SNR group reassessment did not converge"
        return select(*args)

    monkeypatch.setattr(selection, "_select_observations", bounded_select)
    result = calculate(h, obs)
    assert result.height == 6
    assert result["qc_valid"].any()
    for group in result.partition_by("station", "C1_code", "C2_code"):
        for name in ("S1", "S2"):
            if group[name].null_count() * 2 <= group.height:
                assert group.filter(pl.col("qc_valid"))[name].null_count() == 0
    valid = result.filter(pl.col("qc_valid"))
    np.testing.assert_allclose(valid["stec"], 30.0, rtol=0, atol=1e-6)
    assert result.filter(~pl.col("qc_valid"))["stec"].is_null().all()
