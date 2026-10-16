from dataclasses import replace
from datetime import UTC, datetime

import numpy as np
import polars as pl
import pytest

from tests.support.observations import F1, F2, C, K, calculate, physical_observations


@pytest.mark.parametrize("cadence", [0.1, 30])
def test_basic_mode_preserves_rapid_ionosphere(cadence):
    tec = np.r_[np.linspace(30, 31, 10), np.linspace(39, 41, 10)]
    h, obs = physical_observations(tec, cadence=cadence)
    result = calculate(h, obs, cycle_slip_mode="basic")
    np.testing.assert_allclose(result["stec_p_raw"], tec, atol=1e-6, rtol=0)
    np.testing.assert_allclose(result["stec"], tec, atol=1e-6, rtol=0)
    assert result["arc_id"].n_unique() == 1
    assert result["qc_reason"].item(10) == "ok"


@pytest.mark.parametrize("slips,both", [([1], False), ([2, 4, 7], True)])
def test_early_simultaneous_and_repeated_slips_split_without_rewriting(slips, both):
    h, obs = physical_observations(np.full(20, 30.0))
    jump = np.zeros(20)
    for index in slips:
        jump[index:] += 5
    obs = obs.with_columns(pl.Series("L1C", obs["L1C"].to_numpy() + jump))
    lock_flags = [int(index in slips) for index in range(20)]
    obs = obs.with_columns(pl.Series("L1C_lli", lock_flags, dtype=pl.UInt8))
    if both:
        obs = obs.with_columns(pl.Series("L2W", obs["L2W"].to_numpy() + jump))
        obs = obs.with_columns(pl.Series("L2W_lli", lock_flags, dtype=pl.UInt8))
    result = calculate(h, obs)
    assert result["arc_id"].n_unique() == len(slips) + 1
    expected_phase = (obs["L1C"] / F1 - obs["L2W"] / F2) * C * K
    np.testing.assert_allclose(result["stec_p_raw"], expected_phase, rtol=0, atol=1e-7)
    np.testing.assert_array_equal(result["stec_p_raw"], result["stec_p"])
    np.testing.assert_allclose(result["stec"], 30.0, atol=1e-6, rtol=0)


def test_unflagged_phase_jump_is_preserved_without_heuristic_segmentation():
    header, obs = physical_observations(np.full(20, 30.0))
    jump = np.r_[np.zeros(10), np.full(10, 5.0)]
    obs = obs.with_columns(pl.Series("L1C", obs["L1C"].to_numpy() + jump))
    result = calculate(header, obs, cycle_slip_mode="basic")
    assert result["arc_id"].n_unique() == 1
    assert result["qc_reason"].unique().to_list() == ["ok"]
    expected = (obs["L1C"] / F1 - obs["L2W"] / F2) * C * K
    np.testing.assert_allclose(result["stec_p_raw"], expected, rtol=0, atol=1e-7)


def test_receiver_state_breaks_arcs_but_midnight_alone_does_not():
    state_column = "receiver_state"
    start = datetime(2024, 1, 10, 23, 58, tzinfo=UTC)
    h, obs = physical_observations(np.full(10, 30.0), start=start)
    assert calculate(h, obs)["arc_id"].n_unique() == 1
    values = [0] * 5 + [1] * 5
    result = calculate(
        h,
        obs.with_columns(
            pl.Series(state_column, values), pl.lit("legacy.rnx").alias("source_file")
        ),
    )
    assert result["arc_id"].item(5) != result["arc_id"].item(4)
    assert {"source_file", "receiver_id"}.isdisjoint(result.columns)


@pytest.mark.parametrize(
    "flag,record,midnight",
    [(4, "COMMENT", False), (4, None, True), (5, "COMMENT", True), (5, None, False)],
)
def test_metadata_events_preserve_continuous_30_tecu(flag, record, midnight):
    start = datetime(2024, 1, 10, 23, 55, tzinfo=UTC) if midnight else None
    header, obs = physical_observations(np.full(20, 30.0), start=start)
    # Code noise averages to zero over the physical arc, but not over its halves.
    obs = obs.with_columns(
        pl.Series(
            "C2W",
            obs["C2W"].to_numpy() + np.r_[np.full(10, -1 / K), np.full(10, 1 / K)],
        )
    )
    records = "event epoch\n" + (
        f"{'External reset keyword is only text':<60}{record}\n" if record else ""
    )
    event = (obs["time"].dt.epoch("ns").item(10), flag, records)
    header = replace(header, epoch_events=(event,))
    result = calculate(header, obs)
    assert result["arc_id"].n_unique() == 1
    assert result["qc_reason"].unique().to_list() == ["ok"]
    np.testing.assert_allclose(result["stec"], 30.0, rtol=0, atol=1e-6)
    assert header.epoch_events == (event,)


@pytest.mark.parametrize(
    "flag,record",
    [(1, None), (2, None), (3, "MARKER NAME"), (4, "UNKNOWN HEADER"), (6, None)],
)
def test_reset_events_split_arcs_and_preserve_raw_phase(flag, record):
    header, obs = physical_observations(np.full(20, 30.0))
    obs = obs.with_columns(
        pl.Series("L1C", obs["L1C"].to_numpy() + np.r_[np.zeros(10), np.full(10, 5.0)])
    )
    records = "event epoch\n" + (
        f"{'Changed receiver/header':<60}{record}\n" if record else ""
    )
    event = (obs["time"].dt.epoch("ns").item(10), flag, records)
    # Duplicate/unsorted metadata must not introduce multiple state increments.
    header = replace(header, epoch_events=(event, event))
    result = calculate(header, obs)
    assert result["arc_id"].to_list() == [0] * 10 + [1] * 10
    assert "receiver_state_change" in result["qc_reason"].item(10)
    expected = (obs["L1C"] / F1 - obs["L2W"] / F2) * C * K
    np.testing.assert_allclose(result["stec_p_raw"], expected, rtol=0, atol=1e-7)
    np.testing.assert_allclose(result["stec"], 30.0, rtol=0, atol=1e-6)
