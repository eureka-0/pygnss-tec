import polars as pl
import pytest
from helpers import assert_has_columns, assert_prns_start_with
from polars.testing import assert_frame_equal

import gnss_tec as gt


def test_read_rinex_obs_v2(rinex_obs_v2, rinex_nav_v2):
    header, lf = gt.read_rinex_obs(rinex_obs_v2, rinex_nav_v2)
    df = lf.collect()
    assert isinstance(df, pl.DataFrame)

    assert header.version.startswith("2.")
    assert header.marker_name == "DGAR"
    assert header.constellation == "MIXED"
    assert header.sampling_interval == 30
    assert df.shape[0] == 57198
    assert_has_columns(
        df, ["time", "station", "prn", "azimuth", "elevation", "C1", "L1"]
    )
    assert df.get_column("time").dtype == pl.Datetime("ms", "UTC")
    assert df.get_column("elevation").is_between(-90, 90).all()


def test_read_rinex_obs_v2_glonass_nav(rinex_obs_v2, rinex_nav_v2_glo):
    header, lf = gt.read_rinex_obs(rinex_obs_v2, rinex_nav_v2_glo, constellations="R")
    df = lf.collect()
    assert isinstance(df, pl.DataFrame)

    assert header.version.startswith("2.")
    assert df.height > 0
    assert_has_columns(
        df, ["time", "station", "prn", "azimuth", "elevation", "C1", "L1"]
    )
    assert_prns_start_with(df, "R")


def test_read_rinex_obs_v3(rinex_obs_v3_hatanaka, rinex_obs_v3, rinex_nav_v3):
    header1, lf_hatanaka = gt.read_rinex_obs(rinex_obs_v3_hatanaka, rinex_nav_v3)
    header2, lf = gt.read_rinex_obs(rinex_obs_v3, rinex_nav_v3)
    df_hatanaka = lf_hatanaka.collect()
    df = lf.collect()
    assert isinstance(df_hatanaka, pl.DataFrame)
    assert isinstance(df, pl.DataFrame)

    assert header1 == header2
    assert header1.version.startswith("3.")
    assert header1.marker_name == "CIBG"
    assert header1.leap_seconds == 18
    assert header1.sampling_interval == 30
    assert_frame_equal(df_hatanaka, df, check_exact=False, abs_tol=1e-8)
    assert df.shape == (180027, 73)
    assert_has_columns(
        df, ["time", "station", "prn", "azimuth", "elevation", "C1C", "L1C", "S1C"]
    )


def test_read_rinex_obs_v3_other_station(rinex_obs_v3_bele_hatanaka, rinex_nav_v3):
    header, lf = gt.read_rinex_obs(rinex_obs_v3_bele_hatanaka, rinex_nav_v3)
    df = lf.collect()
    assert isinstance(df, pl.DataFrame)

    assert header.version.startswith("3.")
    assert header.marker_name == "BELE"
    assert df.shape == (107287, 44)
    assert df.get_column("station").cast(pl.String).unique().to_list() == ["BELE"]
    assert_has_columns(
        df, ["time", "station", "prn", "azimuth", "elevation", "C1C", "L1C"]
    )


def test_read_rinex_obs_without_nav_excludes_angles(rinex_obs_v3):
    _, lf = gt.read_rinex_obs(rinex_obs_v3)
    df = lf.collect()
    assert isinstance(df, pl.DataFrame)

    assert_has_columns(df, ["time", "station", "prn", "C1C", "L1C"])
    assert "azimuth" not in df.columns
    assert "elevation" not in df.columns


def test_read_rinex_obs_gps_time_is_naive_and_leap_shifted(rinex_obs_v3):
    _, utc_lf = gt.read_rinex_obs(rinex_obs_v3)
    header, gps_lf = gt.read_rinex_obs(rinex_obs_v3, utc=False)
    utc_time = utc_lf.select("time").head(1).collect().item()  # ty:ignore[unresolved-attribute]
    gps_time = gps_lf.select("time").head(1).collect().item()  # ty:ignore[unresolved-attribute]

    assert gps_lf.collect_schema()["time"] == pl.Datetime("ms")
    assert (
        gps_time - utc_time.replace(tzinfo=None)
    ).total_seconds() == header.leap_seconds


def test_read_rinex_obs_long_format(rinex_obs_v3):
    _, lf = gt.read_rinex_obs(rinex_obs_v3, pivot=False)
    df = lf.collect()
    assert isinstance(df, pl.DataFrame)

    assert df.columns == ["time", "station", "prn", "code", "value"]
    assert df.height > 2_000_000
    assert {"C2I", "L2I", "S2I"}.issubset(set(df.get_column("code").unique()))


def test_read_rinex_obs_filters_codes_constellation_and_station(
    rinex_obs_v3, rinex_nav_v3
):
    header, lf = gt.read_rinex_obs(
        rinex_obs_v3,
        rinex_nav_v3,
        constellations="G",
        codes=["C1C", "L1C"],
        station="TEST",
    )
    df = lf.collect()
    assert isinstance(df, pl.DataFrame)

    assert header.marker_name == "TEST"
    assert df.columns == [
        "time",
        "station",
        "prn",
        "azimuth",
        "elevation",
        "C1C",
        "L1C",
    ]
    assert df.get_column("station").cast(pl.String).unique().to_list() == ["TEST"]
    assert_prns_start_with(df, "G")


def test_read_rinex_obs_rejects_bad_inputs(rinex_obs_v3):
    with pytest.raises(FileNotFoundError, match="RINEX file not found"):
        gt.read_rinex_obs("missing.rnx")

    with pytest.raises(ValueError, match="Unknown constellation code"):
        gt.read_rinex_obs(rinex_obs_v3, constellations="X")
