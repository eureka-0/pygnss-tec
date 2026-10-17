from dataclasses import replace

import numpy as np
import polars as pl
import pytest
from polars.testing import assert_frame_equal

import gnss_tec as gt
from gnss_tec.calculation.tec import _tec_observation_codes
from gnss_tec.configuration import TECConfig
from tests.support.native import native
from tests.support.observations import (
    calculate,
    physical_observations,
    write_minimal_rinex,
)
from tests.support.slip_reference import assert_continuous, detection_events
from tests.support.slip_scenarios import CASES, scenario


def test_detector_matches_numpy_reference_across_reset():
    """Independent statistics also check cue history and receiver resets."""
    for case in ("equal", "cancelling", "repeated", "code-step"):
        frame, *_ = scenario(noise="quiet", case=case)
        frame = frame.with_columns(
            pl.when(pl.int_range(pl.len()) >= 20)
            .then(pl.lit("B"))
            .otherwise(pl.lit("A"))
            .alias("_receiver_state")
        )
        boundaries = np.zeros(len(frame), dtype=bool)
        boundaries[20] = True
        expected, _, _ = detection_events(
            frame["time"].to_numpy(),
            frame["stec_p_raw"].to_numpy(),
            frame["mw"].to_numpy(),
            frame["C1_freq"][0],
            frame["C2_freq"][0],
            boundaries=boundaries,
        )
        actual = native(frame)["slip_correction"].is_not_null().to_numpy()
        np.testing.assert_array_equal(actual, expected)


def test_reader_projection_keeps_custom_fallbacks_and_mode_validation():
    config = TECConfig(c2_codes={"3": {"G": ["C5Q", "C2W"]}})
    codes = set(_tec_observation_codes(config))
    assert {"C5Q", "L5Q", "S5Q", "C2W", "L2W", "S2W", "C1", "L1", "S1"} <= codes
    with pytest.raises(ValueError, match="cycle_slip_mode"):
        TECConfig(cycle_slip_mode="unknown")  # ty: ignore[invalid-argument-type]


@pytest.mark.parametrize("cadence", [0.1, 120])
def test_cadence_scaling_and_irregular_epoch_spacing(cadence):
    frame, _truth, increments, _ = scenario(cadence=cadence, case="repeated")
    spacings = cadence * np.resize([0.9, 1.1, 1.0], len(frame) - 1)
    times = (np.r_[0, np.cumsum(spacings)] * 1e9).round().astype(np.int64)
    result = native(frame.with_columns(pl.Series("time", times)), cadence=None)
    accepted, _ = assert_continuous(
        result, frame.with_columns(pl.Series("time", times))
    )
    np.testing.assert_array_equal(accepted, np.any(increments != 0, axis=1))


@pytest.mark.parametrize(
    "pair,cadence,noise,seed",
    [
        ("GPS", 1, "clean", 17),
        ("GPS", 30, "clean", 17),
        ("BDS", 30, "clean", 17),
        ("GPS-L1L5", 5, "quiet", 155921),
        ("GPS-L2L5", 30, "moderate", 15485863),
        ("BDS-B2IB3I", 1, "stress", 15485887),
    ],
)
def test_independent_physical_matrix(pair, cadence, noise, seed):
    """Cover frequency pairs and cadence/noise regimes without their product.

    Repeating all seeds across their Cartesian product adds Monte Carlo volume,
    rather than new continuity contracts. Broad sensitivity studies belong in
    research runs; this regression keeps all 17 distinct event scenarios.
    """
    for case in CASES:
        frame, _, increments, _ = scenario(pair, cadence, noise, seed, case)
        original = frame.clone()
        result = native(frame, cadence)
        events, _ = assert_continuous(result, frame)
        assert set(result["slip_status"]) <= {
            "none",
            "boundary",
            "phase_repaired",
            "phase_continuous",
        }
        assert result["slip_n1"].null_count() == len(frame)
        assert result["slip_n2"].null_count() == len(frame)
        if noise == "clean" and case in (
            "l1",
            "l2",
            "equal",
            "five",
            "repeated",
            "early",
        ):
            assert np.all(events[np.any(increments != 0, axis=1)])
        assert_frame_equal(frame, original)


@pytest.mark.parametrize("mode", ["basic", "detect", "repair"])
def test_production_raw_phase_leveling_and_default(mode):
    frame, _truth, _increments, values = scenario(case="repeated")
    header, obs = physical_observations(np.full(len(frame), 30.0))
    obs = obs.with_columns(pl.Series(name, value) for name, value in values.items())
    result = calculate(header, obs, cycle_slip_mode=mode)
    np.testing.assert_allclose(result["stec_p_raw"], frame["stec_p_raw"], atol=1e-7)
    np.testing.assert_array_equal(result["stec_p_raw"], result["stec_p"])
    if mode == "repair":
        assert TECConfig().cycle_slip_mode == "repair"
        events, _ = assert_continuous(result, frame)
        np.testing.assert_allclose(
            np.diff(result["stec"].to_numpy()),
            np.diff(result["stec_p_corrected"].to_numpy()),
            atol=1e-7,
        )
        np.testing.assert_allclose(
            result["vtec"] * result["mf"], result["stec"], atol=2e-6
        )
        assert result["arc_id"].n_unique() == 4
        assert events.sum() == 3
    else:
        np.testing.assert_array_equal(result["stec_p_raw"], result["stec_p_corrected"])
        assert result["arc_id"].n_unique() == (1 if mode == "basic" else 4)
    assert not any(name.startswith("_") for name in result.columns)


@pytest.mark.parametrize(
    "kind", ["gap", "receiver", "signal", "frequency", "rejection", "half", "event"]
)
def test_valid_segments_are_aligned_across_recorded_boundaries(kind):
    frame, *_ = scenario(case="five")
    change = pl.int_range(pl.len()) >= 40
    if kind == "gap":
        frame = frame.with_columns(
            (pl.col("time") + change.cast(pl.Int64) * 120_000_000_000).alias("time")
        )
    elif kind == "receiver":
        frame = frame.with_columns(
            pl.when(change)
            .then(pl.lit("B"))
            .otherwise(pl.col("_receiver_state"))
            .alias("_receiver_state")
        )
    elif kind == "signal":
        frame = frame.with_columns(
            pl.when(change)
            .then(pl.lit("C1W"))
            .otherwise(pl.col("C1_code"))
            .alias("C1_code")
        )
    elif kind == "frequency":
        frame = frame.with_columns(
            pl.when(change)
            .then(1575.42e6 + 1e6)
            .otherwise(pl.col("C1_freq"))
            .alias("C1_freq")
        )
    else:
        name, value = {
            "rejection": ("_numeric_valid", False),
            "half": ("L1_lli", 2),
            "event": ("epoch_flag", 1),
        }[kind]
        frame = frame.with_columns(
            pl.when(pl.int_range(pl.len()) == 40)
            .then(value)
            .otherwise(pl.col(name))
            .cast(frame.schema[name])
            .alias(name)
        )
    result = native(frame)
    event = 41 if kind in ("rejection", "half") else 40
    assert result["slip_status"][event] in ("phase_repaired", "phase_continuous")
    assert result["arc_id"][40] != result["arc_id"][39]
    assert result["_continuity_id"].n_unique() == 1
    if event == 41:
        assert result["stec_p_corrected"][40] == frame["stec_p_raw"][40]


def test_chunk_parquet_and_station_partition_invariance(tmp_path):
    _, _, _, values = scenario(case="five")
    header, obs = physical_observations(np.full(120, 30.0))
    obs = obs.with_columns(pl.Series(name, value) for name, value in values.items())
    config = TECConfig(rx_bias=None, retain_diagnostics="all")
    expected = gt.compute_tec(obs, header, config=config).collect()
    chunks = pl.concat([obs[:39], obs[39:41], obs[41:]], rechunk=False)
    assert_frame_equal(
        gt.compute_tec(chunks.lazy(), header, config=config).collect(
            engine="streaming"
        ),
        expected,
    )
    path = tmp_path / "observations.parquet"
    chunks.write_parquet(path, row_group_size=17, metadata=header.to_metadata())
    assert_frame_equal(
        gt.compute_tec_from_parquet(path, config=config).collect(), expected
    )
    station_b = obs.with_columns(pl.lit("NEXT").alias("station"))
    merged = gt.compute_tec(
        pl.concat([obs, station_b]), header, config=config
    ).collect()
    assert_frame_equal(merged.filter(pl.col("station") == "TEST"), expected)
    # Derived diagnostics supplied by a caller cannot cause double correction.
    again = obs.with_columns(
        expected.select("stec_p_corrected", "slip_n1", "slip_status")
    )
    assert_frame_equal(
        gt.compute_tec(again, header, config=config).collect().select(expected.columns),
        expected,
    )
    legacy = header.to_metadata()
    del legacy["phase_integer_cycles"]
    assert not type(header).from_metadata(legacy).phase_integer_cycles
    assert not replace(header, phase_integer_cycles=False).phase_integer_cycles


@pytest.mark.parametrize("version", [2, 3])
def test_rinex_entrypoint_repairs_across_file_boundary(tmp_path, monkeypatch, version):
    import gnss_tec.calculation.tec as module

    original = module._prepare_observations

    def geometry(lf, header, utc, nav):
        # Isolate observation decoding/projection/state from orbit propagation.
        return original(
            lf.with_columns(
                pl.lit(90.0).alias("azimuth"), pl.lit(60.0).alias("elevation")
            ),
            header,
            utc,
            None,
        )

    monkeypatch.setattr(module, "_prepare_observations", geometry)
    _, _, _, values = scenario(cadence=1, case="five", size=80)
    single, first, second = (
        tmp_path / name for name in ("single.rnx", "first.rnx", "second.rnx")
    )
    write_minimal_rinex(single, version, flagged=False)
    header_text = single.read_text().split("END OF HEADER\n")[0] + "END OF HEADER\n"
    header_text = header_text.replace("    0.100", "    1.000")
    rows = []
    for i in range(80):
        minute, seconds = divmod(i, 60)
        epoch = (
            f" 24  1 10  0{minute:3d}{seconds:11.7f}  0{1:3d}G01"
            if version == 2
            else f"> 2024 01 10 00 {minute:02d} {seconds:10.7f}  0  1"
        )
        fields = "".join(
            f"{float(values[name][i]):14.3f}07" for name in ("C1C", "L1C", "C2W", "L2W")
        )
        rows.append(epoch + "\n" + ("G01" if version == 3 else "") + fields + "\n")
    for path, body in ((single, rows), (first, rows[:40]), (second, rows[40:])):
        path.write_text(header_text + "".join(body))
    config = TECConfig(rx_bias=None, retain_diagnostics="all")
    expected = gt.compute_tec_from_rinex(single, [], config=config).collect()
    merged = gt.compute_tec_from_rinex([second, first], [], config=config).collect()
    assert_frame_equal(merged, expected)
    assert expected.filter(pl.col("slip_status") == "phase_repaired").height == 1
    assert expected["slip_n1"].null_count() == len(expected)
    header, obs = gt.read_rinex_obs(single, include_lli=True)
    assert_frame_equal(
        gt.compute_tec(obs, header, config=config, nav_fn=[]).collect(), expected
    )
