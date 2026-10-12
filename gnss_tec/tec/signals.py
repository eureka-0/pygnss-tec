"""Select complete signal pairs and match external code-bias validity intervals."""

from __future__ import annotations

import re
import warnings
from typing import Literal

import polars as pl

from .bias import prepare_code_bias
from .constants import TECConfig


def _match_bias(lf: pl.LazyFrame, bias: pl.LazyFrame, kind: str) -> pl.LazyFrame:
    receiver = kind == "rx_bias"
    keys = ["_obs1", "_obs2", "constellation" if receiver else "prn"]
    if receiver:
        keys.append("station")
    observation_schema = lf.collect_schema()
    time_dtype = observation_schema["time"]
    if not isinstance(time_dtype, pl.Datetime) or time_dtype.time_zone is not None:
        raise ValueError("Bias matching requires timezone-naive GPS observation times.")
    product = bias.filter(
        pl.col("station").is_not_null() if receiver else pl.col("station").is_null()
    )
    product = product.select(
        *(
            [pl.col("station"), pl.col("prn").alias("constellation")]
            if receiver
            else [pl.col("prn")]
        ),
        pl.col("obs1").alias("_obs1"),
        pl.col("obs2").alias("_obs2"),
        pl.col("bias_start")
        .cast(pl.Datetime(time_dtype.time_unit))
        .alias(kind + "_start"),
        pl.col("bias_end").cast(pl.Datetime(time_dtype.time_unit)).alias(kind + "_end"),
        pl.col("estimated_value").alias(kind),
    ).with_columns(pl.col(key).cast(observation_schema[key]) for key in keys)
    lf = lf.sort("time").join_asof(
        product.sort(kind + "_start"),
        left_on="time",
        right_on=kind + "_start",
        by=keys,
        strategy="backward",
        check_sortedness=False,
    )
    covered = (pl.col("time") < pl.col(kind + "_end")).fill_null(False)
    return lf.with_columns(
        pl.when(covered)
        .then(
            pl.when(
                pl.col("C1_code").cast(pl.String) < pl.col("C2_code").cast(pl.String)
            )
            .then(-pl.col(kind))
            .otherwise(pl.col(kind))
        )
        .otherwise(None)
        .alias(kind),
        pl.when(covered)
        .then(pl.col(kind + "_start"))
        .otherwise(None)
        .alias(kind + "_start"),
        pl.when(covered)
        .then(pl.col(kind + "_end"))
        .otherwise(None)
        .alias(kind + "_end"),
    )


def coalesce_observations(
    lf: pl.LazyFrame,
    bias_lf: pl.LazyFrame | None,
    config: TECConfig,
    version: Literal["2", "3"],
) -> pl.LazyFrame:
    """Prefer complete finite pairs, bias coverage, joint daily coverage, then priority.

    Configured priority remains 2*C1_priority + C2_priority; lexical code names
    resolve ties. Per-epoch fallback preserves usable observations and the
    selected code names allow the ambiguity segmenter to identify every switch.
    """
    schema = lf.collect_schema()
    meta = [
        name
        for name in schema
        if not re.match(r"^[A-Z]\d[A-Z]?(?:_lli|_half_cycle_valid)?$", name)
    ]

    def optional(name: str, dtype: pl.DataType | type[pl.DataType]) -> pl.Expr:
        return pl.col(name).cast(dtype) if name in schema else pl.lit(None, dtype=dtype)

    candidates = []
    represented = set()
    for constellation in config.constellations:
        for i, first in enumerate(
            config.c1_codes.get(version, {}).get(constellation, [])
        ):
            for j, second in enumerate(
                config.c2_codes.get(version, {}).get(constellation, [])
            ):
                if any(
                    code not in schema
                    for code in (first, second, "L" + first[1:], "L" + second[1:])
                ):
                    continue
                candidates.append(
                    lf.filter(
                        pl.col("prn").cast(pl.String).str.starts_with(constellation)
                    ).select(
                        *meta,
                        pl.lit(first).cast(pl.Categorical).alias("C1_code"),
                        pl.lit(second).cast(pl.Categorical).alias("C2_code"),
                        pl.col(first).cast(pl.Float64).alias("C1_val"),
                        pl.col(second).cast(pl.Float64).alias("C2_val"),
                        pl.col("L" + first[1:]).cast(pl.Float64).alias("L1_val"),
                        pl.col("L" + second[1:]).cast(pl.Float64).alias("L2_val"),
                        optional("S" + first[1:], pl.Float64).alias("S1"),
                        optional("S" + second[1:], pl.Float64).alias("S2"),
                        optional("L" + first[1:] + "_lli", pl.UInt8).alias("L1_lli"),
                        optional("L" + second[1:] + "_lli", pl.UInt8).alias("L2_lli"),
                        pl.lit(2 * i + j).alias("_priority"),
                    )
                )
                represented.add(constellation)
    # A constellation with no complete candidate columns still contributes
    # diagnostic rows, even when another constellation has usable signals.
    missing = lf.filter(
        ~pl.col("prn").cast(pl.String).str.slice(0, 1).is_in(sorted(represented))
    )
    candidates.append(
        missing.select(*meta).with_columns(
            *[
                pl.lit(None, dtype=pl.Categorical).alias(n)
                for n in ("C1_code", "C2_code")
            ],
            *[
                pl.lit(None, dtype=pl.Float64).alias(n)
                for n in ("C1_val", "C2_val", "L1_val", "L2_val", "S1", "S2")
            ],
            *[pl.lit(None, dtype=pl.UInt8).alias(n) for n in ("L1_lli", "L2_lli")],
            pl.lit(0).alias("_priority"),
        )
    )
    selected = pl.concat(candidates)
    selected = selected.with_columns(
        pl.col("prn")
        .cast(pl.String)
        .str.slice(0, 1)
        .cast(pl.Categorical)
        .alias("constellation"),
        pl.col("time").dt.date().alias("date"),
        pl.all_horizontal(pl.col("C1_val", "C2_val", "L1_val", "L2_val").is_finite())
        .fill_null(False)
        .alias("_complete"),
    ).with_columns(
        pl.col("_complete")
        .mean()
        .over("date", "station", "prn", "C1_code", "C2_code")
        .alias("_coverage"),
        pl.when(pl.col("C1_code").cast(pl.String) < pl.col("C2_code").cast(pl.String))
        .then(pl.col("C1_code"))
        .otherwise(pl.col("C2_code"))
        .alias("_obs1"),
        pl.when(pl.col("C1_code").cast(pl.String) < pl.col("C2_code").cast(pl.String))
        .then(pl.col("C2_code"))
        .otherwise(pl.col("C1_code"))
        .alias("_obs2"),
    )
    required = []
    if bias_lf is not None:
        bias_lf = prepare_code_bias(bias_lf)
        required.append("tx_bias")
        selected = _match_bias(selected, bias_lf, "tx_bias")
        if config.rx_bias == "external":
            required.append("rx_bias")
            selected = _match_bias(selected, bias_lf, "rx_bias")
    selected = (
        selected.with_columns(
            pl.all_horizontal([pl.col(n).is_not_null() for n in required]).alias(
                "_bias_available"
            )
            if required
            else pl.lit(True).alias("_bias_available")
        )
        .sort(
            [
                "_complete",
                "_bias_available",
                "_coverage",
                "_priority",
                "C1_code",
                "C2_code",
            ],
            descending=[True, True, True, False, False, False],
        )
        .group_by("time", "station", "prn", maintain_order=True)
        .agg(pl.all().first())
    )

    if required and config.missing_bias in {"warn", "error"}:
        missing = (
            selected.filter(~pl.col("_bias_available"))
            .select(pl.len())
            .collect()
            .item()
        )
        if missing:
            message = f"{missing} observations are missing required bias columns: {', '.join(required)}."
            if config.missing_bias == "error":
                raise ValueError(message)
            warnings.warn(message, stacklevel=3)
    # SNR absence is assessed per receiver and selected pair, never across stations.
    selected = selected.with_columns(
        *[
            (
                pl.col(n).is_null().mean().over("station", "C1_code", "C2_code") > 0.5
            ).alias(n + "_missing")
            for n in ("S1", "S2")
        ]
    ).with_columns(
        pl.all_horizontal(
            [
                (pl.col(n).is_finite() & (pl.col(n) >= config.min_snr))
                | (pl.col(n).is_null() & pl.col(n + "_missing"))
                for n in ("S1", "S2")
            ]
        )
        .fill_null(False)
        .alias("_snr_valid"),
        (
            ~pl.col("_bias_available")
            & pl.lit(config.missing_bias != "keep_uncorrected")
        ).alias("_bias_rejected"),
    )
    return selected.drop(
        "_obs1",
        "_obs2",
        "_priority",
        "_coverage",
        "_complete",
        "date",
        "constellation",
        "S1_missing",
        "S2_missing",
    )
