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


def test_calc_tec_from_rinex_matches_hatanaka(
    rinex_obs_v3_hatanaka, rinex_obs_v3, rinex_nav_v3, bias
):
    config = gt.TECConfig(retain_intermediate="mf")
    df = gt.calc_tec_from_rinex(rinex_obs_v3, rinex_nav_v3, bias, config).collect()
    df_hatanaka = gt.calc_tec_from_rinex(
        rinex_obs_v3_hatanaka, rinex_nav_v3, bias, config
    ).collect()

    assert isinstance(df, pl.DataFrame)
    assert isinstance(df_hatanaka, pl.DataFrame)
    assert_frame_equal(df_hatanaka, df, check_exact=False, abs_tol=1e-8)
    assert df.shape == (50147, 13)
    assert_valid_tec_frame(df)
    assert 35 < _median(df, "vtec") < 50
    assert -50 < _median(df, "stec") < -25
    _assert_corrected_relationship(df)


def test_calc_tec_from_df_matches_rinex(rinex_obs_v3, rinex_nav_v3, bias):
    header, lf = gt.read_rinex_obs(rinex_obs_v3, rinex_nav_v3)
    config = gt.TECConfig(retain_intermediate="mf")
    from_df = gt.calc_tec_from_df(lf, header, bias, config).collect()
    from_rinex = gt.calc_tec_from_rinex(
        rinex_obs_v3, rinex_nav_v3, bias, config
    ).collect()
    assert isinstance(from_df, pl.DataFrame)
    assert isinstance(from_rinex, pl.DataFrame)

    assert_frame_equal(from_df, from_rinex, check_exact=False, abs_tol=1e-8)
    assert_valid_tec_frame(from_df)


def test_calc_tec_from_df_accepts_gps_time(rinex_obs_v3, rinex_nav_v3, bias):
    utc_header, utc_lf = gt.read_rinex_obs(rinex_obs_v3, rinex_nav_v3)
    gps_header, gps_lf = gt.read_rinex_obs(rinex_obs_v3, rinex_nav_v3, utc=False)
    config = gt.TECConfig(retain_intermediate="mf")

    from_utc = gt.calc_tec_from_df(utc_lf, utc_header, bias, config).collect()
    from_gps = gt.calc_tec_from_df(gps_lf, gps_header, bias, config).collect()
    assert isinstance(from_utc, pl.DataFrame)
    assert isinstance(from_gps, pl.DataFrame)

    assert_frame_equal(from_gps, from_utc, check_exact=False, abs_tol=1e-8)


def test_calc_tec_from_df_rejects_non_utc_timezone(rinex_obs_v3, rinex_nav_v3):
    header, lf = gt.read_rinex_obs(rinex_obs_v3, rinex_nav_v3)
    lf = lf.with_columns(pl.col("time").dt.convert_time_zone("Asia/Shanghai"))

    with pytest.raises(ValueError, match="UTC timezone or be timezone-naive"):
        gt.calc_tec_from_df(lf, header).collect()


def test_calc_tec_from_df_requires_navigation_columns(rinex_obs_v3):
    header, lf = gt.read_rinex_obs(rinex_obs_v3)

    with pytest.raises(ValueError, match="azimuth, elevation"):
        gt.calc_tec_from_df(lf, header).collect()


def test_calc_tec_from_parquet_matches_dataframe(
    tmp_path, rinex_obs_v3, rinex_nav_v3, bias
):
    header, lf = gt.read_rinex_obs(rinex_obs_v3, rinex_nav_v3)
    parquet_fn = tmp_path / "obs.parquet"
    lf.sink_parquet(parquet_fn, metadata=header.to_metadata())
    config = gt.TECConfig(retain_intermediate="mf")

    from_parquet = gt.calc_tec_from_parquet(parquet_fn, bias, config).collect()
    from_df = gt.calc_tec_from_df(lf, header, bias, config).collect()
    assert isinstance(from_parquet, pl.DataFrame)
    assert isinstance(from_df, pl.DataFrame)

    assert_frame_equal(from_parquet, from_df, check_exact=False, abs_tol=1e-8)


def test_calc_tec_from_parquet_preserves_gps_time(
    tmp_path, rinex_obs_v3, rinex_nav_v3, bias
):
    header, lf = gt.read_rinex_obs(rinex_obs_v3, rinex_nav_v3)
    gps_header, gps_lf = gt.read_rinex_obs(rinex_obs_v3, rinex_nav_v3, utc=False)
    parquet_fn = tmp_path / "gps_obs.parquet"
    gps_lf.sink_parquet(parquet_fn, metadata=gps_header.to_metadata())
    config = gt.TECConfig(retain_intermediate="mf")

    from_parquet = gt.calc_tec_from_parquet(parquet_fn, bias, config).collect()
    from_df = gt.calc_tec_from_df(lf, header, bias, config).collect()
    assert isinstance(from_parquet, pl.DataFrame)
    assert isinstance(from_df, pl.DataFrame)

    assert_frame_equal(from_parquet, from_df, check_exact=False, abs_tol=1e-8)


def test_calc_tec_from_parquet_rejects_missing_metadata(tmp_path, rinex_obs_v3):
    _, lf = gt.read_rinex_obs(rinex_obs_v3)
    parquet_fn = tmp_path / "missing_metadata.parquet"
    lf.sink_parquet(parquet_fn)

    with pytest.raises(ValueError, match="Parquet metadata is missing"):
        gt.calc_tec_from_parquet(parquet_fn).collect()


def test_calc_tec_without_bias_uses_uncorrected_stec(rinex_obs_v3, rinex_nav_v3):
    df = gt.calc_tec_from_rinex(
        rinex_obs_v3,
        rinex_nav_v3,
        config=gt.TECConfig(rx_bias=None, retain_intermediate="mf"),
    ).collect()
    assert isinstance(df, pl.DataFrame)

    assert_valid_tec_frame(df, corrected=False)
    assert "stec_dcb_corrected" not in df.columns
    assert 55_000 < df.height < 60_000
    max_abs_error = df.select(
        (pl.col("stec") / pl.col("mf") - pl.col("vtec")).abs().max()
    ).item()
    assert max_abs_error < 1e-10
    assert _median(df, "vtec") < 0


@pytest.mark.parametrize("method", ["mstd", "lsq"])
def test_estimated_receiver_bias_methods(rinex_obs_v3, rinex_nav_v3, bias, method):
    df = gt.calc_tec_from_rinex(
        rinex_obs_v3,
        rinex_nav_v3,
        bias,
        gt.TECConfig(rx_bias=method, retain_intermediate=["mf", "rx_bias"]),
    ).collect()
    assert isinstance(df, pl.DataFrame)

    assert_valid_tec_frame(df)
    assert_has_columns(df, ["mf", "rx_bias"])
    assert df.get_column("rx_bias").drop_nulls().len() > 0
    assert math.isfinite(_median(df, "vtec"))
    _assert_corrected_relationship(df)


def test_mapping_function_choice_changes_vtec(rinex_obs_v3, rinex_nav_v3, bias):
    slm = gt.calc_tec_from_rinex(
        rinex_obs_v3,
        rinex_nav_v3,
        bias,
        gt.TECConfig(mapping_function="slm", retain_intermediate=["mf"]),
    ).collect()
    mslm = gt.calc_tec_from_rinex(
        rinex_obs_v3,
        rinex_nav_v3,
        bias,
        gt.TECConfig(mapping_function="mslm", retain_intermediate=["mf"]),
    ).collect()
    assert isinstance(slm, pl.DataFrame)
    assert isinstance(mslm, pl.DataFrame)

    assert slm.height == mslm.height
    assert _median(mslm, "vtec") > _median(slm, "vtec")
    assert not slm.get_column("mf").equals(mslm.get_column("mf"))


def test_retain_intermediate_controls_output_columns(rinex_obs_v3, rinex_nav_v3, bias):
    all_cols = gt.calc_tec_from_rinex(
        rinex_obs_v3, rinex_nav_v3, bias, gt.TECConfig(retain_intermediate="all")
    ).collect()
    selected_cols = gt.calc_tec_from_rinex(
        rinex_obs_v3,
        rinex_nav_v3,
        bias,
        gt.TECConfig(retain_intermediate=["mf", "tx_bias"]),
    ).collect()
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
    rinex_obs_v3, rinex_nav_v3, bias, constellation
):
    df = gt.calc_tec_from_rinex(
        rinex_obs_v3, rinex_nav_v3, bias, gt.TECConfig(constellations=constellation)
    ).collect()
    assert isinstance(df, pl.DataFrame)

    assert_valid_tec_frame(df)
    assert_prns_start_with(df, constellation)


def test_min_elevation_filters_tec_output(rinex_obs_v3, rinex_nav_v3, bias):
    baseline = gt.calc_tec_from_rinex(
        rinex_obs_v3, rinex_nav_v3, bias, gt.TECConfig(retain_intermediate="elevation")
    ).collect()
    high_elevation = gt.calc_tec_from_rinex(
        rinex_obs_v3,
        rinex_nav_v3,
        bias,
        gt.TECConfig(min_elevation=60, retain_intermediate="elevation"),
    ).collect()
    assert isinstance(baseline, pl.DataFrame)
    assert isinstance(high_elevation, pl.DataFrame)

    assert high_elevation.height < baseline.height
    assert cast(float, high_elevation.get_column("elevation").min()) >= 60


def test_missing_external_receiver_bias_can_be_kept_uncorrected(
    rinex_obs_v3, rinex_nav_v3, bias
):
    dropped = gt.calc_tec_from_rinex(
        rinex_obs_v3,
        rinex_nav_v3,
        bias,
        gt.TECConfig(retain_intermediate="rx_bias"),
        station="TEST",
    ).collect()
    kept = gt.calc_tec_from_rinex(
        rinex_obs_v3,
        rinex_nav_v3,
        bias,
        gt.TECConfig(
            missing_bias="keep_uncorrected", retain_intermediate=["rx_bias", "tx_bias"]
        ),
        station="TEST",
    ).collect()
    assert isinstance(dropped, pl.DataFrame)
    assert isinstance(kept, pl.DataFrame)

    assert dropped.height == 0
    assert kept.height > 0
    assert kept.get_column("rx_bias").null_count() == kept.height
