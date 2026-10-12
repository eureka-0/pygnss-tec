import math
from typing import cast

import polars as pl
import pytest
from helpers import assert_has_columns, assert_prns_start_with, assert_valid_tec_frame
from polars.testing import assert_frame_equal

import gnss_tec as gt


def _median(df: pl.DataFrame, column: str) -> float:
    return cast(float, df.get_column(column).median())


def _assert_corrected_relationship(df: pl.DataFrame) -> None:
    max_abs_error = df.select(
        (pl.col("stec_dcb_corrected") / pl.col("mf") - pl.col("vtec")).abs().max()
    ).item()
    assert max_abs_error < 1e-10


@pytest.fixture(scope="module")
def full_day_observations(rinex_obs_v3, rinex_nav_v3):
    """Share all signals across the two whole-day receiver-estimation methods."""
    header, lf = gt.read_rinex_obs(rinex_obs_v3, constellations="CG")
    return header, lf.collect(engine="in-memory")


def test_calc_tec_from_rinex_matches_hatanaka(
    rinex_obs_v3_hatanaka, rinex_obs_v3, rinex_nav_v3, bias
):
    # Whole-day mixed constellations exercise real signal fallback and long arcs.
    config = gt.TECConfig(retain_intermediate="mf")
    df = gt.calc_tec_from_rinex(rinex_obs_v3, rinex_nav_v3, bias, config).collect(
        engine="in-memory"
    )
    df_hatanaka = gt.calc_tec_from_rinex(
        rinex_obs_v3_hatanaka, rinex_nav_v3, bias, config
    ).collect(engine="in-memory")

    assert isinstance(df, pl.DataFrame)
    assert isinstance(df_hatanaka, pl.DataFrame)
    assert df.height == 50315
    assert_prns_start_with(df, "CG")
    assert set(df["prn"].cast(pl.String).str.slice(0, 1)) == {"C", "G"}
    assert_frame_equal(df_hatanaka, df, check_exact=False, rel_tol=0, abs_tol=1e-8)
    assert_has_columns(df, ["qc_valid", "qc_reason", "calibration_status"])
    assert {"source_file", "receiver_id"}.isdisjoint(df.columns)
    assert_valid_tec_frame(df)
    assert 35 < _median(df, "vtec") < 50
    assert -50 < _median(df, "stec") < -25
    _assert_corrected_relationship(df)


def test_calc_tec_from_df_matches_rinex(short_rinex_v3, rinex_nav_v3, bias):
    header, lf = gt.read_rinex_obs(short_rinex_v3, constellations="G")
    config = gt.TECConfig(constellations="G", retain_intermediate="mf")
    from_df = gt.calc_tec_from_df(
        lf, header, bias, config, nav_fn=rinex_nav_v3
    ).collect(engine="in-memory")
    from_rinex = gt.calc_tec_from_rinex(
        short_rinex_v3, rinex_nav_v3, bias, config
    ).collect(engine="in-memory")
    assert isinstance(from_df, pl.DataFrame)
    assert isinstance(from_rinex, pl.DataFrame)

    assert_frame_equal(from_df, from_rinex, check_exact=False, rel_tol=0, abs_tol=1e-8)
    assert_valid_tec_frame(from_df)


def test_calc_tec_from_df_accepts_gps_time(small_observations, bias, rinex_nav_v3):
    header, observations = small_observations
    gps_observations = observations.with_columns(
        (pl.col("time") + pl.duration(seconds=18, time_unit="ns"))
        .dt.replace_time_zone(None)
        .alias("time")
    )
    config = gt.TECConfig(retain_intermediate="mf")

    from_utc = gt.calc_tec_from_df(
        observations, header, bias, config, nav_fn=rinex_nav_v3
    ).collect(engine="in-memory")
    from_gps = gt.calc_tec_from_df(
        gps_observations, header, bias, config, nav_fn=rinex_nav_v3
    ).collect(engine="in-memory")
    assert isinstance(from_utc, pl.DataFrame)
    assert isinstance(from_gps, pl.DataFrame)

    assert_frame_equal(from_gps, from_utc, check_exact=False, rel_tol=0, abs_tol=1e-8)


def test_calc_tec_from_df_rejects_non_utc_timezone(small_observations, rinex_nav_v3):
    header, observations = small_observations
    observations = observations.with_columns(
        pl.col("time").dt.convert_time_zone("Asia/Shanghai")
    )

    with pytest.raises(ValueError, match="UTC timezone or be timezone-naive"):
        gt.calc_tec_from_df(observations, header, nav_fn=rinex_nav_v3).collect(
            engine="in-memory"
        )


def test_calc_tec_from_df_requires_navigation_for_raw_observations(small_observations):
    header, observations = small_observations

    with pytest.raises(ValueError, match="azimuth, elevation"):
        gt.calc_tec_from_df(observations, header).collect(engine="in-memory")


def test_calc_tec_from_parquet_matches_dataframe(
    tmp_path, small_observations, bias, rinex_nav_v3
):
    header, observations = small_observations
    parquet_fn = tmp_path / "obs.parquet"
    observations.write_parquet(parquet_fn, metadata=header.to_metadata())
    config = gt.TECConfig(retain_intermediate="mf")

    from_parquet = gt.calc_tec_from_parquet(
        parquet_fn, bias, config, nav_fn=rinex_nav_v3
    ).collect(engine="in-memory")
    from_df = gt.calc_tec_from_df(
        observations, header, bias, config, nav_fn=rinex_nav_v3
    ).collect(engine="in-memory")
    assert isinstance(from_parquet, pl.DataFrame)
    assert isinstance(from_df, pl.DataFrame)

    assert_frame_equal(
        from_parquet, from_df, check_exact=False, rel_tol=0, abs_tol=1e-8
    )


def test_calc_tec_from_parquet_preserves_gps_time(
    tmp_path, small_observations, bias, rinex_nav_v3
):
    header, observations = small_observations
    gps_observations = observations.with_columns(
        (pl.col("time") + pl.duration(seconds=18, time_unit="ns"))
        .dt.replace_time_zone(None)
        .alias("time")
    )
    parquet_fn = tmp_path / "gps_obs.parquet"
    gps_observations.write_parquet(parquet_fn, metadata=header.to_metadata())
    config = gt.TECConfig(retain_intermediate="mf")

    from_parquet = gt.calc_tec_from_parquet(
        parquet_fn, bias, config, nav_fn=rinex_nav_v3
    ).collect(engine="in-memory")
    from_df = gt.calc_tec_from_df(
        observations, header, bias, config, nav_fn=rinex_nav_v3
    ).collect(engine="in-memory")
    assert isinstance(from_parquet, pl.DataFrame)
    assert isinstance(from_df, pl.DataFrame)

    assert_frame_equal(
        from_parquet, from_df, check_exact=False, rel_tol=0, abs_tol=1e-8
    )


def test_calc_tec_from_parquet_rejects_missing_metadata(
    tmp_path, small_observations, rinex_nav_v3
):
    _, observations = small_observations
    parquet_fn = tmp_path / "missing_metadata.parquet"
    observations.write_parquet(parquet_fn)

    with pytest.raises(ValueError, match="Parquet metadata is missing"):
        gt.calc_tec_from_parquet(parquet_fn, nav_fn=rinex_nav_v3).collect(
            engine="in-memory"
        )


def test_calc_tec_without_bias_uses_uncorrected_stec(small_observations, rinex_nav_v3):
    header, observations = small_observations
    df = gt.calc_tec_from_df(
        observations,
        header,
        config=gt.TECConfig(rx_bias=None, retain_intermediate="mf"),
        nav_fn=rinex_nav_v3,
    ).collect(engine="in-memory")
    assert isinstance(df, pl.DataFrame)

    assert_valid_tec_frame(df, corrected=False)
    assert "stec_dcb_corrected" not in df.columns
    assert df.get_column("calibration_status").unique().to_list() == [
        "uncorrected_no_bias_product"
    ]
    max_abs_error = df.select(
        (pl.col("stec") / pl.col("mf") - pl.col("vtec")).abs().max()
    ).item()
    assert max_abs_error < 1e-10


def test_calc_tec_v2_without_bias_includes_recovered_observations(
    rinex_obs_v2, rinex_nav_v2
):
    df = gt.calc_tec_from_rinex(
        rinex_obs_v2, rinex_nav_v2, config=gt.TECConfig(rx_bias=None)
    ).collect(engine="in-memory")

    assert_valid_tec_frame(df, corrected=False)
    # rinex 0.22 skipped satellite records and produced only 9,166 TEC rows.
    assert df.height == 10933


@pytest.mark.parametrize("method", ["mstd", "lsq"])
def test_estimated_receiver_bias_methods(
    full_day_observations, bias, method, rinex_nav_v3
):
    header, observations = full_day_observations
    # Real data include missing epochs; require whole-day span rather than no gaps.
    observed_seconds = observations.select(
        (pl.col("time").max() - pl.col("time").min()).dt.total_seconds()
    ).item()
    assert observed_seconds > 23 * 3600
    df = gt.calc_tec_from_df(
        observations,
        header,
        bias,
        gt.TECConfig(rx_bias=method, retain_intermediate=["mf", "rx_bias"]),
        nav_fn=rinex_nav_v3,
    ).collect(engine="in-memory")
    assert isinstance(df, pl.DataFrame)

    assert_valid_tec_frame(df)
    assert_has_columns(df, ["mf", "rx_bias"])
    assert df.get_column("rx_bias").drop_nulls().len() > 0
    assert set(df["prn"].cast(pl.String).str.slice(0, 1)) == {"C", "G"}
    assert math.isfinite(_median(df, "vtec"))
    _assert_corrected_relationship(df)


def test_mapping_function_choice_changes_vtec(small_observations, bias, rinex_nav_v3):
    header, observations = small_observations
    slm = gt.calc_tec_from_df(
        observations,
        header,
        bias,
        gt.TECConfig(mapping_function="slm", retain_intermediate=["mf"]),
        nav_fn=rinex_nav_v3,
    ).collect(engine="in-memory")
    mslm = gt.calc_tec_from_df(
        observations,
        header,
        bias,
        gt.TECConfig(mapping_function="mslm", retain_intermediate=["mf"]),
        nav_fn=rinex_nav_v3,
    ).collect(engine="in-memory")
    assert isinstance(slm, pl.DataFrame)
    assert isinstance(mslm, pl.DataFrame)

    assert slm.height == mslm.height
    assert _median(mslm, "vtec") > _median(slm, "vtec")
    assert not slm.get_column("mf").equals(mslm.get_column("mf"))


def test_retain_intermediate_controls_output_columns(
    small_observations, bias, rinex_nav_v3
):
    header, observations = small_observations
    all_cols = gt.calc_tec_from_df(
        observations,
        header,
        bias,
        gt.TECConfig(retain_intermediate="all"),
        nav_fn=rinex_nav_v3,
    ).collect(engine="in-memory")
    selected_cols = gt.calc_tec_from_df(
        observations,
        header,
        bias,
        gt.TECConfig(retain_intermediate=["mf", "tx_bias"]),
        nav_fn=rinex_nav_v3,
    ).collect(engine="in-memory")
    assert isinstance(all_cols, pl.DataFrame)
    assert isinstance(selected_cols, pl.DataFrame)

    assert_has_columns(
        all_cols, ["mf", "stec_g", "stec_p", "arc_id", "offset", "tx_bias", "rx_bias"]
    )
    assert_has_columns(selected_cols, ["mf", "tx_bias"])
    assert "stec_g" not in selected_cols.columns
    assert "rx_bias" not in selected_cols.columns


@pytest.mark.parametrize("constellation", ["G", "C"])
def test_constellation_filter_limits_tec_output(
    small_observations, bias, constellation, rinex_nav_v3
):
    header, observations = small_observations
    df = gt.calc_tec_from_df(
        observations,
        header,
        bias,
        gt.TECConfig(constellations=constellation),
        nav_fn=rinex_nav_v3,
    ).collect(engine="in-memory")
    assert isinstance(df, pl.DataFrame)

    assert_valid_tec_frame(df)
    assert_prns_start_with(df, constellation)


def test_min_elevation_filters_tec_output(small_observations, bias, rinex_nav_v3):
    header, observations = small_observations
    baseline = gt.calc_tec_from_df(
        observations,
        header,
        bias,
        gt.TECConfig(retain_intermediate="elevation"),
        nav_fn=rinex_nav_v3,
    ).collect(engine="in-memory")
    high_elevation = gt.calc_tec_from_df(
        observations,
        header,
        bias,
        gt.TECConfig(min_elevation=60, retain_intermediate="elevation"),
        nav_fn=rinex_nav_v3,
    ).collect(engine="in-memory")
    assert isinstance(baseline, pl.DataFrame)
    assert isinstance(high_elevation, pl.DataFrame)

    assert high_elevation.height < baseline.height
    assert cast(float, high_elevation.get_column("elevation").min()) >= 60


def test_missing_external_receiver_bias_can_be_kept_uncorrected(
    small_observations, bias, rinex_nav_v3
):
    header, observations = small_observations
    observations = observations.with_columns(pl.lit("TEST").alias("station"))
    dropped = gt.calc_tec_from_df(
        observations,
        header,
        bias,
        gt.TECConfig(retain_intermediate="rx_bias"),
        nav_fn=rinex_nav_v3,
    ).collect(engine="in-memory")
    kept = gt.calc_tec_from_df(
        observations,
        header,
        bias,
        gt.TECConfig(
            missing_bias="keep_uncorrected", retain_intermediate=["rx_bias", "tx_bias"]
        ),
        nav_fn=rinex_nav_v3,
    ).collect(engine="in-memory")
    assert isinstance(dropped, pl.DataFrame)
    assert isinstance(kept, pl.DataFrame)

    assert dropped.height == 0
    assert kept.height > 0
    assert kept.get_column("rx_bias").null_count() == kept.height
