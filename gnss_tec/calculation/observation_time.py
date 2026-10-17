"""Shared UTC/GPS observation-time contracts for geometry and TEC."""

from __future__ import annotations

from typing import Literal

import polars as pl

from ..io.rinex import RinexObsHeader, get_leap_seconds


def _infer_time_kind(lf: pl.LazyFrame) -> Literal["utc", "gps"]:
    dtype = lf.collect_schema()["time"]
    if not isinstance(dtype, pl.Datetime):
        raise TypeError(
            "Input time column must be a Polars Datetime. Use timezone-aware UTC "
            "datetime values for UTC or naive datetime values for GPS time."
        )
    if dtype.time_zone == "UTC":
        return "utc"
    elif dtype.time_zone is None:
        return "gps"
    else:
        raise ValueError(
            "Input time column must use the UTC timezone or be timezone-naive "
            f"GPS time, got timezone {dtype.time_zone!r}."
        )


def _leap_seconds_duration(header: RinexObsHeader) -> pl.Expr:
    if header.leap_seconds is not None:
        return pl.duration(seconds=header.leap_seconds, time_unit="ns")
    return get_leap_seconds("time")


def _utc_epoch(lf: pl.LazyFrame, header: RinexObsHeader) -> pl.Expr:
    if _infer_time_kind(lf) == "utc":
        return pl.col("time")
    return (pl.col("time") - _leap_seconds_duration(header)).dt.replace_time_zone("UTC")
