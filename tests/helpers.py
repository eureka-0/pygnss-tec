import math
from typing import cast

import polars as pl


def assert_has_columns(df: pl.DataFrame, columns: list[str]) -> None:
    missing = set(columns) - set(df.columns)
    assert not missing, f"Missing columns: {sorted(missing)}"


def assert_prns_start_with(df: pl.DataFrame, prefixes: str) -> None:
    prns = df.get_column("prn").cast(pl.String).unique().to_list()
    assert prns
    assert all(prn[0] in prefixes for prn in prns)


def assert_valid_tec_frame(df: pl.DataFrame, *, corrected: bool = True) -> None:
    columns = [
        "time",
        "station",
        "prn",
        "rx_lat",
        "rx_lon",
        "C1_code",
        "C2_code",
        "ipp_lat",
        "ipp_lon",
        "stec",
        "vtec",
    ]
    if corrected:
        columns.append("stec_dcb_corrected")
    assert_has_columns(df, columns)
    assert df.height > 0
    assert df.get_column("time").is_sorted()
    assert df.get_column("time").dtype == pl.Datetime("ms", "UTC")
    assert df.get_column("ipp_lat").is_between(-90, 90).all()
    assert df.get_column("ipp_lon").is_between(-180, 180).all()
    assert df.get_column("stec").drop_nulls().len() > 0
    assert df.get_column("vtec").drop_nulls().len() > 0
    assert math.isfinite(cast(float, df.get_column("vtec").median()))
