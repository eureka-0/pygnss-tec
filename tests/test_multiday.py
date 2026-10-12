"""Full two-day reader comparisons and compact TEC windows from four receivers."""

import math
from dataclasses import dataclass, replace
from datetime import date
from pathlib import Path
from typing import Literal

import numpy as np
import polars as pl
import pytest
from helpers import assert_valid_tec_frame
from polars.testing import assert_frame_equal
from real_observations import OBSERVATION_CODES, collect_short_windows

import gnss_tec as gt
from gnss_tec.rinex import RinexObsHeader
from gnss_tec.tec.bias import estimate_rx_bias
from gnss_tec.tec.constants import c
from gnss_tec.tec.preparation import _prepare_observations
from gnss_tec.tec.tec_calculation import _coalesce_observations


@dataclass
class StationData:
    obs: list[Path]
    nav: list[Path]
    header: RinexObsHeader
    full_observations: pl.DataFrame
    individual_readers: tuple[pl.LazyFrame, ...]
    # Midnight/nighttime windows for focused TEC assertions.
    observations: pl.DataFrame
    tec: pl.DataFrame
    bias: list[Path] | None


def _logical(df: pl.DataFrame) -> pl.DataFrame:
    return df.with_columns(pl.col(pl.Categorical).cast(pl.String)).sort(
        "time", "station", "prn"
    )


@pytest.fixture(scope="module")
def multiday_data(test_data_dir) -> dict[str, StationData]:
    data: dict[str, StationData] = {}
    bias = [
        test_data_dir / f"bias/CAS0OPSRAP_2024{day:03d}0000_01D_01D_DCB.BIA.gz"
        for day in (10, 11)
    ]
    for station in ("DGAR", "POAL", "CIBG", "BELE"):
        v2 = station in {"DGAR", "POAL"}
        country = "IDN" if station == "CIBG" else "BRA"
        obs = [
            test_data_dir / f"rinex_obs_v2/{station.lower()}{day:03d}0.24o.gz"
            if v2
            else test_data_dir
            / f"rinex_obs_v3/{station}00{country}_R_2024{day:03d}0000_01D_30S_MO.crx.gz"
            for day in (10, 11)
        ]
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
            gt.TECConfig(retain_intermediate="all"),
            nav_fn=nav,
        ).collect(engine="in-memory")
        individual_readers = []
        for path in obs:
            individual_header, part = gt.read_rinex_obs(
                path,
                constellations="G" if v2 else "CG",
                codes=OBSERVATION_CODES["2" if v2 else "3"],
            )
            assert individual_header.marker_name == station
            individual_readers.append(part)
        data[station] = StationData(
            obs=obs,
            nav=nav,
            header=header,
            full_observations=full_observations,
            individual_readers=tuple(individual_readers),
            observations=observations,
            tec=tec,
            bias=station_bias,
        )
    return data


@pytest.mark.parametrize("station", ["DGAR", "POAL", "CIBG", "BELE"])
def test_multiday_reader_matches_individual_files(multiday_data, station):
    data = multiday_data[station]
    # Compare the complete cached individual-file queries with the merged input.
    individual = (
        pl.concat(data.individual_readers, how="diagonal")
        .select(data.full_observations.columns)
        .collect(engine="in-memory")
    )
    assert_frame_equal(
        _logical(individual),
        _logical(data.full_observations),
        check_exact=False,
        rel_tol=0,
        abs_tol=1e-8,
    )
    keys = data.full_observations.select("time", "station", "prn")
    assert keys.unique().height == keys.height
    gps_days = (
        data.full_observations.select(
            (pl.col("time") + pl.duration(seconds=18)).dt.date()
        )
        .to_series()
        .unique()
        .sort()
        .to_list()
    )
    assert gps_days == [date(2024, 1, 10), date(2024, 1, 11)]
    assert data.header.sampling_interval == (15 if station == "POAL" else 30)


@pytest.mark.parametrize("station", ["DGAR", "POAL"])
def test_multiday_glonass_navigation(test_data_dir, station):
    obs = [
        test_data_dir / f"rinex_obs_v2/{station.lower()}{day:03d}0.24o.gz"
        for day in (10, 11)
    ]
    nav = [test_data_dir / f"rinex_nav_v2/brdc{day:03d}0.24g.gz" for day in (10, 11)]
    header, lf = gt.read_rinex_obs(obs[::-1], constellations="R", codes=["C1", "L1"])
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
        header, part = gt.read_rinex_obs(path, constellations="R", codes=["C1", "L1"])
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


@pytest.mark.parametrize("station", ["DGAR", "POAL", "CIBG", "BELE"])
def test_multiday_shuffled_gps_and_parquet(multiday_data, station, tmp_path):
    data = multiday_data[station]
    config = gt.TECConfig(retain_intermediate="all")
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
    data = multiday_data[station]
    result = gt.calc_tec_from_df(
        data.observations,
        data.header,
        data.bias,
        gt.TECConfig(retain_intermediate="all"),
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
    for level in result.partition_by("station", "prn", "arc_id", "level_id"):
        weights = np.sin(np.deg2rad(level["elevation"].to_numpy())) ** 2
        expected = math.fsum(
            (level["stec_g_corrected"] - level["stec_p"]).to_numpy() * weights
        ) / math.fsum(weights)
        np.testing.assert_allclose(
            level["offset"].to_numpy(), expected, rtol=0, atol=1e-9
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
def test_reader_rejects_mixed_receivers(multiday_data, version):
    first, second = ("DGAR", "POAL") if version == "2" else ("CIBG", "BELE")
    a, b = multiday_data[first], multiday_data[second]
    with pytest.raises(ValueError, match="same station"):
        gt.read_rinex_obs(
            [a.obs[0], b.obs[0]], station="OVERRIDE", codes=OBSERVATION_CODES[version]
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
