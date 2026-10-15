"""Estimate receiver code biases with the existing mstd and lsq methods."""

from __future__ import annotations

from typing import Literal

import numpy as np
import polars as pl
from scipy.optimize import lsq_linear, minimize_scalar


def estimate_rx_bias(
    df: pl.DataFrame | pl.LazyFrame, method: Literal["mstd", "lsq"], downsample: bool
) -> pl.LazyFrame:
    """Estimate receiver code bias after satellite correction.

    Parameters
    ----------
    df : polars.DataFrame or polars.LazyFrame
        Sorted TEC measurements with satellite bias, geometry, mapping
        factors and selected code pairs. Invalid rows cannot contribute
        to calibration.
    method : {'mstd', 'lsq'}
        Minimum standard deviation or least squares estimation.
    downsample : bool
        Use the first observation in each 30-second station/PRN bin for
        estimation, joining estimates back to the original observations.

    Returns
    -------
    polars.LazyFrame
        Input measurements with rx_bias in TECU. Failed or unsupported
        estimates remain null rather than becoming zero corrections.

    Raises
    ------
    ValueError
        If method is unknown.
    """
    match method:
        case "mstd":
            estimate_func = _mstd_rx_bias
        case "lsq":
            estimate_func = _lsq_rx_bias
        case _:
            raise ValueError(f"Unknown bias correction method: {method}")

    lf = df.lazy().drop("rx_bias", strict=False)
    # Diagnostic rows stay in the result, but cannot contribute to calibration.
    bias_lf = lf.filter(
        pl.all_horizontal(
            pl.col("stec", "tx_bias", "mf", "ipp_lat", "ipp_lon", "rx_lat").is_finite()
        )
        & (pl.col("mf") > 0)
        & pl.col("time").is_not_null()
        & pl.col("C1_code").is_not_null()
        & pl.col("C2_code").is_not_null()
    )
    if downsample:
        bias_lf = bias_lf.group_by_dynamic(
            "time", every="30s", group_by=["station", "prn"]
        ).agg(pl.all().first())

    bias_lf = bias_lf.with_columns(
        pl.col("time").dt.date().alias("date"),
        pl.col("prn").cat.slice(0, 1).alias("constellation"),
    )
    bias_lf = bias_lf.group_by(
        "date", "station", "constellation", "C1_code", "C2_code"
    ).agg(
        pl.struct("time", "stec", "tx_bias", "mf", "ipp_lat", "ipp_lon", "rx_lat")
        .map_batches(estimate_func, return_dtype=pl.Float64, returns_scalar=True)
        .alias("rx_bias")
    )

    return (
        lf.with_columns(
            pl.col("time").dt.date().alias("date"),
            pl.col("prn").cat.slice(0, 1).alias("constellation"),
        )
        .join(
            bias_lf,
            on=["date", "station", "constellation", "C1_code", "C2_code"],
            how="left",
            validate="m:1",
            maintain_order="left",
        )
        .fill_nan(None)
        .drop("date", "constellation")
    )


def _mstd_rx_bias(s: pl.Series) -> float:
    df = s.struct.unnest()
    df = (
        df.with_columns(
            pl.col("time").add(pl.duration(hours=pl.col("ipp_lon") / 15)).alias("lt")
        )
        .with_columns(
            pl.col("lt")
            .sub(pl.col("lt").dt.truncate("1d"))
            .dt.total_hours(fractional=True)
        )
        .filter((pl.col("lt") >= 18) | (pl.col("lt") <= 6))
        .filter(pl.len().over("time") >= 2)
    )
    if df.height < 10:
        return np.nan

    def mean_std(bias: float) -> float:
        corrected = df.with_columns(
            (pl.col("stec").sub(pl.col("tx_bias") + bias) / pl.col("mf")).alias("vtec")
        ).with_columns(pl.col("vtec").std().over("time").mean().alias("mean_std"))

        value = corrected.get_column("mean_std").item(0)
        return float(value) if value is not None and np.isfinite(value) else np.inf

    if not np.isfinite(mean_std(0.0)):
        return np.nan
    result = minimize_scalar(mean_std, bounds=(-500, 500), method="bounded")
    return (
        float(result.x)
        if result.success and np.isfinite(result.x) and np.isfinite(result.fun)
        else np.nan
    )


def _lsq_rx_bias(s: pl.Series) -> float:
    df = s.struct.unnest()
    if df.is_empty():
        return np.nan
    A = (
        df.with_columns(
            (pl.col("time") - pl.col("time").dt.truncate("1d"))
            .dt.total_hours(fractional=True)
            .mul(np.pi / 12)
            .alias("h"),
            (pl.col("ipp_lat") - pl.col("rx_lat")).mul(np.pi / 180).alias("phi"),
        )
        .with_columns(
            (pl.col("mf") * pl.col("h")).alias("h1"),
            (pl.col("mf") * pl.col("phi")).alias("phi1"),
            (pl.col("mf") * pl.col("h").pow(2)).alias("h2"),
            (pl.col("mf") * pl.col("phi").pow(2)).alias("phi2"),
            (pl.col("mf") * pl.col("h") * pl.col("phi")).alias("hphi"),
            (pl.col("mf") * pl.col("h").pow(2) * pl.col("phi")).alias("h2phi"),
            (pl.col("mf") * pl.col("h") * pl.col("phi").pow(2)).alias("hphi2"),
            (pl.col("mf") * pl.col("h").pow(2) * pl.col("phi").pow(2)).alias("h2phi2"),
            (pl.col("mf") * pl.col("h").cos()).alias("cosh"),
            (pl.col("mf") * pl.col("h").sin()).alias("sinh"),
            (pl.col("mf") * pl.col("h").mul(2).cos()).alias("cos2h"),
            (pl.col("mf") * pl.col("h").mul(2).sin()).alias("sin2h"),
            (pl.col("mf") * pl.col("h").mul(3).cos()).alias("cos3h"),
            (pl.col("mf") * pl.col("h").mul(3).sin()).alias("sin3h"),
            (pl.col("mf") * pl.col("h").mul(4).cos()).alias("cos4h"),
            (pl.col("mf") * pl.col("h").mul(4).sin()).alias("sin4h"),
        )
        .select(
            pl.lit(1).alias("intercept"),
            pl.col(
                "mf", "h1", "phi1", "h2", "phi2", "hphi", "h2phi", "hphi2", "h2phi2"
            ),
            pl.col(
                "cosh", "sinh", "cos2h", "sin2h", "cos3h", "sin3h", "cos4h", "sin4h"
            ),
        )
        .fill_null(np.nan)
        .to_numpy()
    )
    b = (
        df.select(pl.col("stec") - pl.col("tx_bias"))
        .get_column("stec")
        .fill_null(np.nan)
        .to_numpy()
    )
    if not np.isfinite(A).all() or not np.isfinite(b).all():
        return np.nan
    try:
        result = lsq_linear(A, b)
    except np.linalg.LinAlgError:
        return np.nan
    return (
        float(result.x[0]) if result.success and np.isfinite(result.x).all() else np.nan
    )
