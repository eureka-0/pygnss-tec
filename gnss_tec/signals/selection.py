"""Select complete signal pairs and attach valid code biases without candidate tables."""

from __future__ import annotations

import re
import warnings
from typing import Literal

import polars as pl

from .._arrow import record_batch
from .._core import _select_observations
from ..calibration.code_bias import prepare_code_bias
from ..configuration import TECConfig
from .definitions import CODE_FREQUENCIES


def coalesce_observations(
    lf: pl.LazyFrame,
    bias_lf: pl.LazyFrame | None,
    config: TECConfig,
    version: Literal["2", "3"],
) -> pl.LazyFrame:
    """Prefer complete pairs, bias coverage, daily coverage, then configured priority.

    Rust evaluates candidates in place and preserves lexical ties and per-epoch
    fallback. Materialize once so geometry and observation preparation are shared.
    """
    schema = lf.collect_schema()
    meta = [
        name
        for name in schema
        if not re.match(r"^[A-Z]\d[A-Z]?(?:_lli|_half_cycle_valid)?$", name)
    ]
    pairs = [
        (
            constellation,
            first,
            second,
            2 * i + j,
            CODE_FREQUENCIES.get(constellation + "_" + first[1], float("nan")),
            CODE_FREQUENCIES.get(constellation + "_" + second[1], float("nan")),
        )
        for constellation in config.constellations
        for i, first in enumerate(
            config.c1_codes.get(version, {}).get(constellation, [])
        )
        for j, second in enumerate(
            config.c2_codes.get(version, {}).get(constellation, [])
        )
        if all(
            code in schema
            for code in (first, second, "L" + first[1:], "L" + second[1:])
        )
    ]
    fields = {
        code
        for _, first, second, *_ in pairs
        for code in (
            first,
            second,
            "L" + first[1:],
            "L" + second[1:],
            "S" + first[1:],
            "S" + second[1:],
            "L" + first[1:] + "_lli",
            "L" + second[1:] + "_lli",
        )
        if code in schema
    }
    frame = lf.collect()
    data = frame.select(
        pl.col("time").dt.epoch("ns"),
        pl.col("station", "prn").cast(pl.String),
        *[
            pl.col(code).cast(pl.UInt8 if code.endswith("_lli") else pl.Float64)
            for code in sorted(fields)
        ],
    )
    product = None
    if bias_lf is not None:
        product = record_batch(
            prepare_code_bias(bias_lf)
            .select(
                pl.col("station", "prn", "obs1", "obs2").cast(pl.String),
                pl.col("bias_start", "bias_end").dt.epoch("ns"),
                pl.col("estimated_value").cast(pl.Float64),
            )
            .collect()
        )
    output = pl.from_arrow(
        _select_observations(
            record_batch(data), pairs, product, config.rx_bias == "external"
        )
    )
    assert isinstance(output, pl.DataFrame)
    output = output.with_columns(pl.col("C1_code", "C2_code").cast(pl.Categorical))
    intervals = [
        name for name in output.columns if name.endswith(("_bias_start", "_bias_end"))
    ]
    output = output.with_columns(pl.col(intervals).cast(pl.Datetime("ns")))
    selected = frame.select(meta).with_columns(output.get_columns()).lazy()

    required = (
        []
        if bias_lf is None
        else ["tx_bias"] + (["rx_bias"] if config.rx_bias == "external" else [])
    )
    if required and config.missing_bias in {"warn", "error"}:
        missing = int((~output["_bias_available"]).sum())
        if missing:
            message = (
                f"{missing} observations are missing required bias columns: "
                + ", ".join(required)
                + "."
            )
            if config.missing_bias == "error":
                raise ValueError(message)
            warnings.warn(message, stacklevel=3)
    # SNR absence is assessed per receiver and selected pair, never across stations.
    return (
        selected.with_columns(
            *[
                (
                    pl.col(name).is_null().mean().over("station", "C1_code", "C2_code")
                    > 0.5
                ).alias(name + "_missing")
                for name in ("S1", "S2")
            ]
        )
        .with_columns(
            pl.all_horizontal(
                [
                    (pl.col(name).is_finite() & (pl.col(name) >= config.min_snr))
                    | (pl.col(name).is_null() & pl.col(name + "_missing"))
                    for name in ("S1", "S2")
                ]
            )
            .fill_null(False)
            .alias("_snr_valid"),
            (
                ~pl.col("_bias_available")
                & pl.lit(config.missing_bias != "keep_uncorrected")
            ).alias("_bias_rejected"),
        )
        .drop(
            "_obs1",
            "_obs2",
            "_priority",
            "_coverage",
            "_complete",
            "date",
            "constellation",
            "S1_missing",
            "S2_missing",
            strict=False,
        )
    )
