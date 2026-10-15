"""Validate and normalize external code-bias products."""

from __future__ import annotations

import polars as pl


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
