"""Real multi-day TEC, bias and continuity checks."""

import json
import math
from dataclasses import dataclass, replace
from pathlib import Path
from typing import Literal

import numpy as np
import polars as pl
import pytest
from polars.testing import assert_frame_equal

import gnss_tec as gt
from gnss_tec.calculation.observation_geometry import _prepare_observations
from gnss_tec.calculation.tec import _coalesce_observations
from gnss_tec.calibration.receiver_bias import estimate_rx_bias
from gnss_tec.constants import c
from gnss_tec.io.rinex import RinexObsHeader
from tests.support.assertions import assert_valid_tec_frame
from tests.support.native import native
from tests.support.real_observations import OBSERVATION_CODES, collect_short_windows
from tests.support.slip_reference import assert_continuous, offsets


@dataclass
class StationData:
    nav: list[Path]
    header: RinexObsHeader
    injection_observations: pl.DataFrame
    # Midnight/nighttime windows for focused TEC assertions.
    observations: pl.DataFrame
    tec: pl.DataFrame
    bias: list[Path] | None


def _logical(df: pl.DataFrame) -> pl.DataFrame:
    return df.with_columns(pl.col(pl.Categorical).cast(pl.String)).sort(
        "time", "station", "prn"
    )


def _observation_paths(test_data_dir: Path, station: str) -> list[Path]:
    if station in {"DGAR", "POAL"}:
        return [
            test_data_dir / f"rinex_obs_v2/{station.lower()}{day:03d}0.24o.gz"
            for day in (10, 11)
        ]
    country = "IDN" if station == "CIBG" else "BRA"
    return [
        test_data_dir
        / f"rinex_obs_v3/{station}00{country}_R_2024{day:03d}0000_01D_30S_MO.crx.gz"
        for day in (10, 11)
    ]


@pytest.fixture(scope="module")
def multiday_data(test_data_dir) -> dict[str, StationData]:
    data: dict[str, StationData] = {}
    bias = [
        test_data_dir / f"bias/CAS0OPSRAP_2024{day:03d}0000_01D_01D_DCB.BIA.gz"
        for day in (10, 11)
    ]
    for station in ("DGAR", "POAL", "CIBG", "BELE"):
        v2 = station in {"DGAR", "POAL"}
        obs = _observation_paths(test_data_dir, station)
        nav = [
            test_data_dir / f"rinex_nav_v2/brdc{day:03d}0.24n.gz"
            if v2
            else test_data_dir
            / f"rinex_nav_v3/BRDC00IGS_R_2024{day:03d}0000_01D_MN.rnx.gz"
            for day in (10, 11)
        ]
        # Each reader/header belongs to one physical receiver. Mixed receivers
        # cannot share the single receiver position in RinexObsHeader.
        header, lf = gt.read_rinex_obs(
            obs[::-1],
            constellations="G" if v2 else "CG",
            codes=OBSERVATION_CODES["2" if v2 else "3"],
            include_lli=True,
        )
        full_observations = lf.collect(engine="in-memory")
        # Keep the materialized reference, releasing its native long-table input.
        del lf
        observations = collect_short_windows(full_observations)
        station_bias = None if v2 else bias
        tec = gt.calc_tec_from_df(
            observations,
            header,
            station_bias,
            gt.TECConfig(retain_diagnostics="all"),
            nav_fn=nav,
        ).collect(engine="in-memory")
        gps = pl.col("time") + pl.duration(seconds=18)
        selected = full_observations.filter(
            (gps.dt.hour() == 18) & (gps.dt.minute() < 20)
        )
        # Own compact buffers; no daily table or native query survives setup.
        injections = pl.DataFrame(
            selected.to_dict(as_series=False), schema=selected.schema
        )
        del full_observations, selected
        data[station] = StationData(
            nav=nav,
            header=header,
            injection_observations=injections,
            observations=observations,
            tec=tec,
            bias=station_bias,
        )
    return data


@pytest.mark.parametrize("station", ["DGAR", "CIBG"])
def test_real_paired_injections_across_stations_and_days(multiday_data, station):
    """Check a fixed real sample across two GPS days and selected signal pairs."""
    hour, minute_start = 18, 0
    data = multiday_data[station]
    gps = pl.col("time") + pl.duration(seconds=18)
    windows = data.injection_observations.filter(
        (gps.dt.hour() == hour)
        & gps.dt.minute().is_between(minute_start, minute_start + 20, closed="left")
    )
    observed = gt.calc_tec_from_df(
        windows,
        data.header,
        data.bias,
        gt.TECConfig(retain_diagnostics="all", cycle_slip_mode="basic"),
        nav_fn=data.nav,
    ).collect(engine="in-memory")
    # Fixed GPS/BeiDou windows retain two real days without a cohort sweep.
    ledger_path = (
        Path(__file__).resolve().parents[1] / "fixtures/cycle-slip-windows.json"
    )
    ledger = json.loads(ledger_path.read_text())
    identities = {}
    for record in ledger:
        if record["station"] == station:
            identity = (record["day"], record["prn"], *record["codes"])
            identities[identity] = record
    covered = set()
    repairs = 0
    for (day, prn, first, second), identity in identities.items():
        samples = identity["samples"]
        group = observed.filter(
            pl.col("qc_valid")
            & (gps.dt.date().cast(pl.String) == day)
            & (pl.col("prn") == prn)
            & (pl.col("C1_code") == first)
            & (pl.col("C2_code") == second)
        )
        if "first_time_ns" in identity:
            group = group.filter(
                pl.col("time")
                .cast(pl.Int64)
                .is_between(identity["first_time_ns"], identity["last_time_ns"])
            )
        if len(group) != samples:
            matching = [
                part for part in group.partition_by("arc_id") if len(part) == samples
            ]
            assert len(matching) == 1, (station, day, prn, samples, len(group))
            group = matching[0]
        key = (day, first, second)
        frame = group.select(
            pl.col("time").cast(pl.Int64),
            pl.col("station", "prn", "C1_code", "C2_code").cast(pl.String),
            pl.lit("A").alias("_receiver_state"),
            pl.lit(True).alias("_numeric_valid"),
            pl.col("L1_lli", "L2_lli").cast(pl.UInt8),
            pl.col("epoch_flag").cast(pl.Int64),
            "stec_p_raw",
            "stec_g",
            "mw",
            "C1_freq",
            "C2_freq",
        )
        covered.add(key)
        event = len(frame) // 2
        f1, f2 = frame["C1_freq"][0], frame["C2_freq"][0]
        k = f1**2 * f2**2 / (f1**2 - f2**2) / 40.3e16
        for n1, n2 in ((5, 0), (0, -1), (1, 1)):
            after = (pl.int_range(pl.len()) >= event).cast(pl.Float64)
            injected = frame.with_columns(
                (pl.col("stec_p_raw") + after * k * c * (n1 / f1 - n2 / f2)).alias(
                    "stec_p_raw"
                ),
                (pl.col("mw") + after * (n1 - n2)).alias("mw"),
            )
            result = native(injected)
            is_detected = result["arc_id"][event] != result["arc_id"][event - 1]
            is_repaired = result["slip_status"][event] in (
                "phase_repaired",
                "phase_continuous",
            )
            repairs += int(is_repaired)
            events, _ = assert_continuous(result, injected)
            assert int(is_repaired) == is_detected
            assert result["slip_n1"].null_count() == len(frame)
            assert result["slip_n2"].null_count() == len(frame)
            times = injected["time"].to_numpy().astype(float) / 1e9
            residual = offsets(times, result["stec_p_corrected"].to_numpy(), events)
            np.testing.assert_allclose(residual[events], 0, rtol=0, atol=1e-7)
            # Verify the user-facing STEC, including code leveling, from selected
            # real code/carrier measurements rather than only the native phase.
            selected_obs = group.select(
                "time",
                "station",
                "prn",
                "azimuth",
                "elevation",
                "rx_lat",
                "rx_lon",
                pl.col("C1_val").alias(first),
                pl.col("C2_val").alias(second),
                (pl.col("L1_val") + after * n1).alias("L" + first[1:]),
                (pl.col("L2_val") + after * n2).alias("L" + second[1:]),
                pl.col("L1_lli").alias("L" + first[1:] + "_lli"),
                pl.col("L2_lli").alias("L" + second[1:] + "_lli"),
            )
            system = str(prn)[0]
            version = data.header.version[0]
            public = gt.calc_tec_from_df(
                selected_obs,
                data.header,
                config=gt.TECConfig(
                    constellations=system,
                    rx_bias=None,
                    retain_diagnostics="all",
                    c1_codes={version: {system: [first]}},
                    c2_codes={version: {system: [second]}},
                ),
            ).collect(engine="in-memory")
            public_events = (
                public["slip_status"]
                .is_in(["phase_repaired", "phase_continuous"])
                .to_numpy()
            )
            public_residual = offsets(times, public["stec"].to_numpy(), public_events)
            np.testing.assert_allclose(
                public_residual[public_events], 0, rtol=0, atol=1e-6
            )
    assert len({key[0] for key in covered}) == 2, (station, covered)
    if hour == 18 and minute_start == 0:
        assert repairs > 0, (
            f"{station}: real noisy development controls must exercise correction"
        )


def test_multiday_glonass_navigation(test_data_dir):
    station = "POAL"
    obs = [
        test_data_dir / f"rinex_obs_v2/{station.lower()}{day:03d}0.24o.gz"
        for day in (10, 11)
    ]
    nav = [test_data_dir / f"rinex_nav_v2/brdc{day:03d}0.24g.gz" for day in (10, 11)]
    header, lf = gt.read_rinex_obs(
        obs[::-1], constellations="R", codes=["C1", "L1"], include_lli=True
    )
    columns = [
        *lf.collect_schema(),
        "azimuth",
        "elevation",
        "rx_lat",
        "rx_lon",
        "_sat_x",
        "_sat_y",
        "_sat_z",
        "_geometry_available",
    ]
    combined = (
        _prepare_observations(lf, header, pl.col("time"), nav)
        .select(columns)
        .collect(engine="in-memory")
    )
    individual = []
    for path in obs:
        header, part = gt.read_rinex_obs(
            path, constellations="R", codes=["C1", "L1"], include_lli=True
        )
        individual.append(
            _prepare_observations(part, header, pl.col("time"), nav)
            .select(columns)
            .collect(engine="in-memory")
        )
    assert combined.height > 0
    assert combined["_geometry_available"].any()
    assert combined["prn"].cast(pl.String).str.starts_with("R").all()
    assert combined.select("time", "station", "prn").unique().height == combined.height
    assert combined.select(
        pl.col("azimuth").is_between(0, 360).all(),
        pl.col("elevation").is_between(-90, 90).all(),
    ).row(0) == (True, True)
    assert_frame_equal(
        _logical(combined),
        _logical(pl.concat(individual)),
        check_exact=False,
        rel_tol=0,
        abs_tol=1e-8,
    )


@pytest.mark.parametrize("station", ["DGAR", "CIBG"])
def test_multiday_shuffled_gps_and_parquet(multiday_data, station, tmp_path):
    data = multiday_data[station]
    assert data.header.marker_name == station
    assert data.header.sampling_interval == (15 if station == "POAL" else 30)
    config = gt.TECConfig(retain_diagnostics="all")
    shuffled = data.observations.sample(fraction=1, shuffle=True, seed=29)
    inferred = replace(data.header, sampling_interval=None)
    from_shuffled = gt.calc_tec_from_df(
        shuffled.lazy(), inferred, data.bias, config, nav_fn=data.nav
    ).collect(engine="in-memory")
    gps = shuffled.with_columns(
        (pl.col("time") + pl.duration(seconds=18)).dt.replace_time_zone(None)
    )
    path = tmp_path / f"{station}-two-days.parquet"
    gps.write_parquet(path, metadata=inferred.to_metadata())
    from_parquet = gt.calc_tec_from_parquet(
        path, data.bias, config, nav_fn=data.nav
    ).collect(engine="in-memory")
    for result in (from_shuffled, from_parquet):
        assert_valid_tec_frame(result, corrected=data.bias is not None)
        assert_frame_equal(
            _logical(result),
            _logical(data.tec),
            check_exact=False,
            rel_tol=0,
            abs_tol=1e-8,
        )
        assert result["rx_lat"].is_finite().all()
        assert result["rx_lon"].is_finite().all()


@pytest.mark.parametrize("station", ["DGAR", "POAL", "CIBG", "BELE"])
def test_multiday_arc_and_daily_dcb_reference(multiday_data, station):
    # Frozen basic-mode contract: each physical arc has its own code level.
    # Repair-mode continuity is tested against paired known-integer injections.
    data = multiday_data[station]
    result = gt.calc_tec_from_df(
        data.observations,
        data.header,
        data.bias,
        gt.TECConfig(retain_diagnostics="all", cycle_slip_mode="basic"),
        nav_fn=data.nav,
    ).collect(engine="in-memory")
    result = result.filter("qc_valid")
    crosses_midnight = False
    for group in result.partition_by("station", "prn"):
        times = group["time"].dt.epoch("ms").to_numpy()
        # QC boundaries include lock/state changes and rejected observations.
        arcs = group["arc_id"].to_numpy()
        assert (np.diff(arcs.astype(np.int64)) >= 0).all()
        gaps = np.diff(times) > data.header.sampling_interval * 1500
        assert (np.diff(arcs.astype(np.int64))[gaps] > 0).all()
    for arc in result.partition_by("station", "prn", "arc_id"):
        days = arc.select(
            (pl.col("time") + pl.duration(seconds=18)).dt.date().n_unique()
        ).item()
        crosses_midnight |= days > 1
    # These fixtures use daily products. Group by the independently known GPS
    # validity day instead of exposing private leveling IDs and offsets.
    levels = result.with_columns(
        (
            (pl.col("time") + pl.duration(seconds=18)).dt.date()
            if data.bias is not None
            else pl.lit(None, dtype=pl.Date)
        ).alias("_bias_day")
    )
    for level in levels.partition_by("station", "prn", "arc_id", "_bias_day"):
        weights = np.sin(np.deg2rad(level["elevation"].to_numpy())) ** 2
        expected = math.fsum(
            (level["stec_g_corrected"] - level["stec_p"]).to_numpy() * weights
        ) / math.fsum(weights)
        np.testing.assert_allclose(
            (
                level["stec"]
                - level["stec_p"]
                - (level["stec_g"] - level["stec_g_corrected"])
            ).to_numpy(),
            expected,
            rtol=0,
            atol=1e-9,
        )
    assert crosses_midnight, f"{station} must exercise an arc spanning GPS midnight"
    if data.bias is None:
        np.testing.assert_allclose(
            result["vtec"], result["stec"] / result["mf"], rtol=0, atol=1e-12
        )
        return

    # DCB validity is in GPS days, including the 18 s before UTC midnight.
    biases = (
        gt.read_bias(data.bias)
        .collect(engine="in-memory")
        .with_columns(
            pl.col("bias_start").dt.date().alias("date"),
            pl.col("obs1").alias("C1_code"),
            pl.col("obs2").alias("C2_code"),
            pl.col("prn").cast(pl.String).str.slice(0, 1).alias("constellation"),
        )
    )
    tagged = result.with_columns(
        (pl.col("time") + pl.duration(seconds=18)).dt.date().alias("date"),
        pl.col("prn").cast(pl.String).str.slice(0, 1).alias("constellation"),
    )
    for kind, keys, condition in (
        ("tx_bias", ["date", "prn", "C1_code", "C2_code"], pl.col("station").is_null()),
        (
            "rx_bias",
            ["date", "station", "constellation", "C1_code", "C2_code"],
            pl.col("station").is_not_null(),
        ),
    ):
        reference = tagged.join(
            biases.filter(condition).select(*keys, "estimated_value"),
            on=keys,
            how="left",
            validate="m:1",
            maintain_order="left",
        )
        assert reference["estimated_value"].null_count() == 0
        f1, f2 = reference["C1_freq"], reference["C2_freq"]
        tecu_per_ns = f1**2 * f2**2 / (f1**2 - f2**2) / 40.3e16 * c * 1e-9
        np.testing.assert_allclose(
            reference[kind],
            -reference["estimated_value"] * tecu_per_ns,
            rtol=0,
            atol=1e-12,
        )
    np.testing.assert_allclose(
        result["stec_dcb_corrected"],
        result["stec"] - result["tx_bias"] - result["rx_bias"],
        rtol=0,
        atol=1e-12,
    )
    np.testing.assert_allclose(
        result["vtec"], result["stec_dcb_corrected"] / result["mf"], rtol=0, atol=1e-12
    )


@pytest.mark.parametrize("version", ["2", "3"])
def test_multistation_code_and_bias_joins(multiday_data, version):
    stations = ("DGAR", "POAL") if version == "2" else ("CIBG", "BELE")
    config = gt.TECConfig()
    frames = [multiday_data[s].observations for s in stations]
    bias_files = multiday_data[stations[0]].bias
    bias = None if bias_files is None else gt.read_bias(bias_files)

    def coalesce(df: pl.DataFrame) -> pl.DataFrame:
        gps = df.lazy().with_columns(
            (pl.col("time") + pl.duration(seconds=18)).dt.replace_time_zone(None)
        )
        return _coalesce_observations(gps, bias, config, version).collect(
            engine="in-memory"
        )

    separate = pl.concat([coalesce(df) for df in frames], how="diagonal")
    combined = coalesce(pl.concat(frames, how="diagonal"))
    assert_frame_equal(
        _logical(combined),
        _logical(separate),
        check_exact=False,
        rel_tol=0,
        abs_tol=1e-8,
    )


@pytest.mark.parametrize("method", ["mstd", "lsq"])
def test_multistation_receiver_estimates_are_independent(
    multiday_data, method: Literal["mstd", "lsq"]
):
    # Positions and satellite biases already belong to their own receivers.
    frames = [
        multiday_data[s].tec.drop("rx_bias", "stec_dcb_corrected", "vtec")
        for s in ("CIBG", "BELE")
    ]
    frames = [
        df.with_columns(
            (pl.col("time") + pl.duration(seconds=18)).dt.replace_time_zone(None)
        )
        for df in frames
    ]
    separate = pl.concat(
        [
            estimate_rx_bias(df, method, False).collect(engine="in-memory")
            for df in frames
        ]
    )
    combined = estimate_rx_bias(
        pl.concat(frames).sort("time", "station", "prn"), method, False
    ).collect(engine="in-memory")
    # mstd's bounded solver uses a 1e-5 TECU absolute convergence tolerance.
    assert_frame_equal(
        _logical(combined),
        _logical(separate),
        check_exact=False,
        rel_tol=0,
        abs_tol=1e-5 if method == "mstd" else 1e-8,
    )
