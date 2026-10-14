from __future__ import annotations

import gzip
import io
import re
from collections.abc import Iterable
from pathlib import Path
from typing import Literal

import numpy as np
import polars as pl
from scipy.optimize import lsq_linear, minimize_scalar


def _read_bias_file(fn: str | Path) -> pl.LazyFrame:
    if str(fn).endswith(".gz"):
        with gzip.open(fn, "rt", encoding="utf-8") as f:
            lines = f.readlines()
    else:
        with open(fn, "r", encoding="utf-8") as f:
            lines = f.readlines()

    if not lines:
        raise ValueError(f"Bias file {fn} is empty.")

    try:
        header_marker_idx = next(
            i for i, line in enumerate(lines) if "+BIAS/SOLUTION" in line
        )
    except StopIteration:
        raise ValueError("Header '+BIAS/SOLUTION' not found in the file.")

    header_line_idx = header_marker_idx + 1
    if header_line_idx >= len(lines):
        raise ValueError("No header line found after '+BIAS/SOLUTION' marker.")

    header_str = lines[header_line_idx].rstrip("\n")

    footer_line_idx = None
    for i in range(len(lines) - 1, header_line_idx, -1):
        if "-BIAS/SOLUTION" in lines[i]:
            footer_line_idx = i
            break

    if footer_line_idx is None:
        footer_line_idx = len(lines)

    if footer_line_idx <= header_line_idx + 1:
        buf = io.StringIO("")
    else:
        buf = io.StringIO("".join(lines[header_line_idx + 1 : footer_line_idx]))

    colspecs = [(m.start(), m.end()) for m in re.finditer(r"\S+", header_str)]
    cols = [col.strip("*_").lower() for col in header_str.split()]
    schema = {
        "prn": pl.Categorical,
        "station": pl.Categorical,
        "obs1": pl.Categorical,
        "obs2": pl.Categorical,
        "unit": pl.Categorical,
        "estimated_value": pl.Float64,
        "std_dev": pl.Float64,
    }
    lf = (
        pl.scan_csv(buf, has_header=False, new_columns=["full_str"])
        .with_columns(
            [
                pl.col("full_str")
                .str.slice(colspec[0], colspec[1] - colspec[0])
                .str.strip_chars()
                .replace("", None)
                .cast(schema.get(col, pl.String))
                .alias(col)
                for colspec, col in zip(colspecs, cols)
            ]
        )
        .drop("full_str")
    )

    for col in ["bias_start", "bias_end"]:
        lf = (
            lf.with_columns(pl.col(col).str.split(":").alias("parts"))
            .with_columns(
                pl.col("parts").list.get(0).alias("year"),
                pl.col("parts").list.get(1).alias("doy"),
                pl.col("parts").list.get(2).cast(pl.Int64).alias("sod"),
            )
            .with_columns(
                pl.concat_str(pl.col("year"), pl.lit("-"), pl.col("doy"))
                .str.strptime(pl.Date, "%Y-%j")
                .cast(pl.Datetime)
                .add(pl.col("sod") * pl.duration(seconds=1))
                .alias(col)
            )
            .drop("parts", "year", "doy", "sod")
        )

    descriptors = {}
    for line in lines[:header_marker_idx]:
        parts = line.split()
        if parts and parts[0] in {"TIME_SYSTEM", "BIAS_MODE", "DETERMINATION_METHOD"}:
            descriptors[parts[0]] = " ".join(parts[1:])
    if descriptors.get("TIME_SYSTEM") != "G":
        raise ValueError(
            "Only Bias-SINEX TIME_SYSTEM G (GPS) is supported; metadata is required."
        )
    return lf.with_columns(
        pl.lit(descriptors["TIME_SYSTEM"]).alias("time_system"),
        pl.lit(descriptors.get("BIAS_MODE")).alias("bias_mode"),
        pl.lit(descriptors.get("DETERMINATION_METHOD")).alias("determination_method"),
    )


def prepare_code_bias(lf: pl.LazyFrame) -> pl.LazyFrame:
    """Validate supported DSB/ns/GPS semantics and unambiguous half-open intervals.

    Reverse pairs are canonicalized with a sign reversal. Validation precedes
    matching, so an overlap cannot silently multiply or shadow observations.
    """
    required = {
        "bias",
        "unit",
        "time_system",
        "prn",
        "station",
        "obs1",
        "obs2",
        "bias_start",
        "bias_end",
        "estimated_value",
    }
    missing = required - set(lf.collect_schema().names())
    if missing:
        raise ValueError(
            f"Bias metadata is missing required fields: {', '.join(sorted(missing))}."
        )
    schema = lf.collect_schema()
    for name in ("bias_start", "bias_end"):
        dtype = schema[name]
        if not isinstance(dtype, pl.Datetime) or dtype.time_zone is not None:
            raise ValueError("Bias validity times must be timezone-naive GPS Datetime.")
    slope = (
        pl.col("estimated_slope").cast(pl.Float64).fill_null(0) != 0
        if "estimated_slope" in schema
        else pl.lit(False)
    )
    supported = (
        (pl.col("bias") == "DSB")
        & (pl.col("unit") == "ns")
        & (pl.col("time_system") == "G")
        & pl.col("obs1").cast(pl.String).str.contains(r"^C\d[A-Z]?$")
        & pl.col("obs2").cast(pl.String).str.contains(r"^C\d[A-Z]?$")
        & (pl.col("obs1") != pl.col("obs2"))
        & pl.col("estimated_value").is_finite()
        & (pl.col("bias_end") > pl.col("bias_start"))
    )
    reverse = pl.col("obs1").cast(pl.String) > pl.col("obs2").cast(pl.String)
    keys = ["station", "prn", "obs1", "obs2"]
    df = (
        lf.with_columns(
            (~supported.fill_null(False)).alias("_unsupported_bias"),
            slope.alias("_unsupported_slope"),
            pl.when(reverse)
            .then(pl.col("obs2"))
            .otherwise(pl.col("obs1"))
            .alias("_obs1"),
            pl.when(reverse)
            .then(pl.col("obs1"))
            .otherwise(pl.col("obs2"))
            .alias("_obs2"),
            pl.when(reverse)
            .then(-pl.col("estimated_value"))
            .otherwise(pl.col("estimated_value"))
            .alias("estimated_value"),
        )
        .drop("obs1", "obs2")
        .rename({"_obs1": "obs1", "_obs2": "obs2"})
        .with_columns(
            (
                pl.col("bias_start")
                < pl.col("bias_end")
                .cum_max()
                .shift(1)
                .over(keys, order_by="bias_start")
            ).alias("_overlap")
        )
        .collect()
    )
    if df["_unsupported_slope"].any():
        raise ValueError(
            "Unsupported bias semantics: time-varying bias slopes are not supported."
        )
    if df["_unsupported_bias"].any():
        raise ValueError(
            "Unsupported bias semantics: require code DSB, ns, GPS G, finite values and valid start/end intervals."
        )
    if df["_overlap"].any():
        raise ValueError(
            "Overlapping bias validity intervals for the same station/PRN/signal pair."
        )
    return df.drop("_unsupported_slope", "_unsupported_bias", "_overlap").lazy()


def read_bias(fn: str | Path | Iterable[str | Path]) -> pl.LazyFrame:
    """Read GNSS bias products into a lazy table.

    Parameters
    ----------
    fn : str, Path, or iterable of str or Path
        Bias product files, including supported compressed inputs.

    Returns
    -------
    polars.LazyFrame
        Decoded bias records and product metadata. TEC code-bias
        preparation separately validates DSB/ns/GPS semantics and
        half-open validity intervals before applying corrections.

    Raises
    ------
    FileNotFoundError
        If a bias file does not exist.
    TypeError
        If fn is not a path or iterable of paths.
    """
    if isinstance(fn, (str, Path)):
        fn_list = [str(fn)]
    elif isinstance(fn, Iterable):
        fn_list = [str(f) for f in fn]
    else:
        raise TypeError("fn must be a str, Path, or Iterable of str/Path.")

    for f in fn_list:
        if not Path(f).exists():
            raise FileNotFoundError(f"Bias file not found: {f}")

    return pl.concat([_read_bias_file(f) for f in fn_list])


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
