"""Select complete signal pairs and attach valid code biases without candidate tables."""

from __future__ import annotations

import re
import warnings
from hashlib import sha256
from typing import Literal

import polars as pl

from .._arrow import record_batch
from .._core import _select_observations
from ..calibration.code_bias import prepare_code_bias
from ..configuration import TECConfig
from .definitions import CODE_FREQUENCIES


def _selected_snr_validity(min_snr: float) -> pl.Expr:
    """Apply the existing SNR policy within the actual selected pair groups."""
    return (
        pl.all_horizontal(
            [
                (pl.col(name).is_finite() & (pl.col(name) >= min_snr))
                | (
                    pl.col(name).is_null()
                    & (
                        pl.col(name)
                        .is_null()
                        .mean()
                        .over("station", "C1_code", "C2_code")
                        > 0.5
                    )
                )
                for name in ("S1", "S2")
            ]
        )
        .fill_null(False)
        .alias("_snr_valid")
    )


def _candidate_missing_snr_validity(
    first: str, second: str, fields: set[str]
) -> pl.Expr:
    """Reassess null SNR against each candidate's currently selected group."""
    selected = (pl.col("C1_code") == first) & (pl.col("C2_code") == second)
    rules = [
        pl.col(name).is_not_null()
        | (
            pl.col(name).is_null().filter(selected).mean().over("station") > 0.5
        ).fill_null(True)
        for name in ("S" + first[1:], "S" + second[1:])
        if name in fields
    ]
    # An unselected pair has no group yet; allow it to compete, then validate
    # its actual selected group on the next pass.
    return pl.all_horizontal(rules) if rules else pl.lit(True)


def coalesce_observations(
    lf: pl.LazyFrame,
    bias_lf: pl.LazyFrame | None,
    config: TECConfig,
    version: Literal["2", "3"],
) -> pl.LazyFrame:
    """Prefer usable pairs before completeness, bias, coverage and priority.

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
    # Reject recorded SNR/half-cycle failures before ranking. A null SNR needs
    # the actual selected-pair group, so defer its majority check until selection.
    eligibility = []
    for constellation, first, second, *_ in pairs:
        rules = []
        for code in (first, second):
            snr_name = "S" + code[1:]
            if snr_name in fields:
                snr = pl.col(snr_name)
                rules.append(
                    (snr.is_finite() & (snr >= config.min_snr)) | snr.is_null()
                )
            lli_name = "L" + code[1:] + "_lli"
            if lli_name in fields:
                rules.append((pl.col(lli_name).fill_null(0) // 2) % 2 == 0)
        eligibility.append(
            (pl.all_horizontal(rules) if rules else pl.lit(True))
            .fill_null(False)
            .alias(f"_usable_{constellation}_{first}_{second}")
        )
    data = data.with_columns(eligibility)
    base = data
    masks = [expr.meta.output_name() for expr in eligibility]
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
    seen_masks: set[bytes] = set()
    monotonic = False
    while True:
        output = pl.from_arrow(
            _select_observations(
                record_batch(data), pairs, product, config.rx_bias == "external"
            )
        )
        assert isinstance(output, pl.DataFrame)
        snr_valid = (
            data.select("station")
            .with_columns(output.get_columns())
            .select(_selected_snr_validity(config.min_snr))
            .to_series()
        )
        output = output.with_columns(snr_valid)
        # Group membership can cycle, particularly when the two SNR bands have
        # different missing rows. After repeated masks, only remove rejected
        # choices so termination and final grouped acceptance remain guaranteed.
        if not monotonic:
            # Retain compact fingerprints rather than per-row mask snapshots.
            fingerprint = sha256()
            for mask in masks:
                fingerprint.update(data[mask].to_numpy().tobytes())
            state = fingerprint.digest()
            monotonic = state in seen_masks
            seen_masks.add(state)
        reassessed = None
        if not monotonic:
            reassessed = base.with_columns(output.select("C1_code", "C2_code")).select(
                (
                    pl.col(f"_usable_{constellation}_{first}_{second}")
                    & _candidate_missing_snr_validity(first, second, fields)
                ).alias(f"_usable_{constellation}_{first}_{second}")
                for constellation, first, second, *_ in pairs
            )
        updates = []
        for constellation, first, second, *_ in pairs:
            mask = f"_usable_{constellation}_{first}_{second}"
            rejected = (
                (output["C1_code"] == first)
                & (output["C2_code"] == second)
                & data["prn"].str.starts_with(constellation)
                & ~snr_valid
            ).fill_null(False)
            usable = data[mask]
            if reassessed is not None:
                # Restore candidates accepted by their current group, but let
                # untried null-SNR candidates form a group before rejecting them.
                usable = usable | reassessed[mask]
            usable = usable & ~rejected
            if not usable.equals(data[mask]):
                updates.append(usable.alias(mask))
        if not updates:
            break
        data = data.with_columns(updates)
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
    return selected.with_columns(
        (
            ~pl.col("_bias_available")
            & pl.lit(config.missing_bias != "keep_uncorrected")
        ).alias("_bias_rejected")
    ).drop(
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
