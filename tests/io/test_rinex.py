import polars as pl
import pytest
from polars.testing import assert_frame_equal

import gnss_tec as gt
from tests.support.assertions import assert_has_columns, assert_prns_start_with
from tests.support.real_observations import OBSERVATION_CODES


def test_read_rinex_obs_v2(rinex_obs_v2):
    header, lf = gt.read_rinex_obs(rinex_obs_v2, include_lli=True)
    df = lf.collect(engine="in-memory")
    assert isinstance(df, pl.DataFrame)

    assert header.version.startswith("2.")
    assert header.marker_name == "DGAR"
    assert header.constellation == "MIXED"
    assert header.sampling_interval == 30
    # Sum of the satellite counts in the 2,880 original epoch headers.
    assert df.shape[0] == 81810
    assert_has_columns(df, ["time", "station", "prn", "C1", "L1"])
    assert df.get_column("time").dtype == pl.Datetime("ns", "UTC")
    assert all(df.schema[name] == pl.Float64 for name in ("C1", "L1"))

    # These fields are blank in the original RINEX 2 records. rinex 0.22
    # incorrectly populated them when parsing the final observation line.
    # The epoch headers use GPS time, 18 seconds ahead of UTC.
    e07 = df.filter(
        pl.col("prn") == "E07",
        pl.col("time") == pl.datetime(2024, 1, 10, 17, 14, 12, time_zone="UTC"),
    )
    r17 = df.filter(
        pl.col("prn") == "R17",
        pl.col("time") == pl.datetime(2024, 1, 10, 18, 29, 42, time_zone="UTC"),
    )
    assert e07.select("L7").item() is None
    assert r17.select("C7").item() is None


def test_read_rinex_obs_v3(rinex_obs_v3_hatanaka, rinex_obs_v3):
    # Compare a complete day of TEC signals, including SNR and recorded LLI.
    header1, lf_hatanaka = gt.read_rinex_obs(
        rinex_obs_v3_hatanaka,
        constellations="CG",
        codes=OBSERVATION_CODES["3"],
        include_lli=True,
    )
    df_hatanaka = lf_hatanaka.collect(engine="in-memory")
    del lf_hatanaka
    header2, lf = gt.read_rinex_obs(
        rinex_obs_v3,
        constellations="CG",
        codes=OBSERVATION_CODES["3"],
        include_lli=True,
    )
    df = lf.collect(engine="in-memory")
    del lf
    assert isinstance(df_hatanaka, pl.DataFrame)
    assert isinstance(df, pl.DataFrame)

    assert header1 == header2
    assert header1.version.startswith("3.")
    assert header1.marker_name == "CIBG"
    assert header1.leap_seconds == 18
    assert header1.sampling_interval == 30
    assert_frame_equal(df_hatanaka, df, check_exact=False, rel_tol=0, abs_tol=1e-8)
    # Selected CG records in the original full-signal reader baseline.
    assert df.height == 101663
    assert set(df["prn"].cast(pl.String).str.slice(0, 1)) == {"C", "G"}
    assert_has_columns(df, ["L1C_lli", "epoch_flag"])
    assert {"source_file", "receiver_id"}.isdisjoint(df.columns)
    assert {"azimuth", "elevation"}.isdisjoint(df.columns)
    assert all(df.schema[name] == pl.Float64 for name in ("C1C", "L1C"))
    assert_has_columns(df, ["time", "station", "prn", "C1C", "L1C", "S1C"])


def test_read_rinex_obs_long_format(short_rinex_v3):
    # Layout/flag semantics need three signals, not a multi-million-row table.
    _, lf = gt.read_rinex_obs(
        short_rinex_v3,
        constellations="C",
        codes=["C2I", "L2I", "S2I"],
        pivot=False,
        include_lli=True,
    )
    df = lf.collect(engine="in-memory")
    assert isinstance(df, pl.DataFrame)

    assert df.columns == [
        "time",
        "station",
        "prn",
        "code",
        "value",
        "lli",
        "epoch_flag",
    ]
    assert df.height > 0
    assert df.select("time", "station", "prn", "code").unique().height == df.height
    assert df.schema["value"] == pl.Float64
    assert set(df.get_column("code").unique()) == {"C2I", "L2I", "S2I"}


def test_read_rinex_obs_filters_codes_constellation_and_station(short_rinex_v3):
    header, lf = gt.read_rinex_obs(
        short_rinex_v3,
        constellations="G",
        codes=["C1C", "L1C"],
        station="TEST",
        include_lli=True,
    )
    df = lf.collect(engine="in-memory")
    assert isinstance(df, pl.DataFrame)

    assert header.marker_name == "TEST"
    assert df.columns == [
        "time",
        "station",
        "prn",
        "C1C",
        "L1C",
        "C1C_lli",
        "L1C_lli",
        "epoch_flag",
    ]
    assert df.get_column("station").cast(pl.String).unique().to_list() == ["TEST"]
    assert_prns_start_with(df, "G")


def test_read_rinex_obs_rejects_bad_inputs(rinex_obs_v3):
    with pytest.raises(FileNotFoundError, match="RINEX file not found"):
        gt.read_rinex_obs("missing.rnx", include_lli=True)

    with pytest.raises(ValueError, match="Unknown constellation code"):
        gt.read_rinex_obs(rinex_obs_v3, constellations="X", include_lli=True)
