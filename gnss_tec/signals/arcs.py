"""Ambiguity segmentation and continuity of phase and leveled TEC products."""

from __future__ import annotations

from collections.abc import Sequence

import polars as pl

from .._arrow import record_batch
from .._core import _basic_arcs, _slip_arcs, _smooth_stec

ARC_DTYPE = pl.Struct({"arc_id": pl.UInt32, "qc_reason": pl.String})


def _arc_expressions(
    lf: pl.LazyFrame,
    cadence: float | None,
    groups: Sequence[str] = ("station", "prn"),
    state_column: str = "_receiver_state",
) -> pl.LazyFrame:
    """Split on lock, event, gap, signal-pair and receiver evidence using expressions."""

    def partition(expression: pl.Expr) -> pl.Expr:
        return expression.over(*groups) if groups else expression

    time = pl.col("time").cast(pl.Int64)
    previous = partition(time.shift(1))
    lf = lf.with_columns(
        ((time - previous) / 1e9).alias("_qc_delta"),
        previous.is_not_null().alias("_qc_previous"),
    )
    interval = (
        pl.lit(cadence)
        if cadence is not None
        else partition(pl.col("_qc_delta").min()).fill_null(1.0)
    )
    half_cycle = ((pl.col("L1_lli").fill_null(0) // 2) % 2 != 0) | (
        (pl.col("L2_lli").fill_null(0) // 2) % 2 != 0
    )
    has_previous = pl.col("_qc_previous")
    valid = pl.col("_numeric_valid").fill_null(False)
    rules = {
        "invalid_observation_or_geometry": ~valid,
        "half_cycle_invalid": half_cycle,
        "loss_of_lock": (pl.col("L1_lli").fill_null(0) % 2 != 0)
        | (pl.col("L2_lli").fill_null(0) % 2 != 0),
        "epoch_event": pl.col("epoch_flag").fill_null(0) != 0,
        "reacquisition_gap": (pl.col("_qc_delta") > interval * 1.5) & has_previous,
        "signal_pair_change": (
            pl.col("C1_code").ne_missing(partition(pl.col("C1_code").shift(1)))
            | pl.col("C2_code").ne_missing(partition(pl.col("C2_code").shift(1)))
        )
        & has_previous,
        "receiver_state_change": pl.col(state_column).ne_missing(
            partition(pl.col(state_column).shift(1))
        )
        & has_previous,
        "reacquisition_after_rejection": partition((~valid | half_cycle).shift(1))
        & has_previous,
    }
    columns = ["_qc_rule_" + name for name in rules]
    lf = lf.with_columns(
        expression.fill_null(False).alias(column)
        for expression, column in zip(rules.values(), columns, strict=True)
    )
    return lf.with_columns(
        partition(
            (pl.any_horizontal(columns) & has_previous).cast(pl.UInt32).cum_sum()
        ).alias("arc_id"),
        pl.concat_str(
            [
                pl.when(pl.col(column)).then(pl.lit(name)).otherwise(None)
                for name, column in zip(rules, columns, strict=True)
            ],
            separator="|",
            ignore_nulls=True,
        )
        .replace({"": "ok"})
        .alias("qc_reason"),
    ).drop("_qc_delta", "_qc_previous", *columns)


def add_basic_arcs(lf: pl.LazyFrame, cadence: float | None) -> pl.LazyFrame:
    """Materialize once and evaluate basic ambiguity evidence in one Rust pass."""
    frame = lf.collect()
    fields = frame.select(
        pl.col("time").cast(pl.Int64),
        pl.col("station", "prn", "C1_code", "C2_code", "_receiver_state").cast(
            pl.String
        ),
        pl.col("_numeric_valid").fill_null(False),
        pl.col("L1_lli", "L2_lli").cast(pl.UInt8),
        pl.col("epoch_flag").cast(pl.Int64),
    )
    result = pl.from_arrow(_basic_arcs(record_batch(fields), cadence))
    assert isinstance(result, pl.DataFrame)
    return frame.with_columns(result.get_columns()).lazy()


def add_slip_arcs(
    lf: pl.LazyFrame, cadence: float | None, mode: str, *, integer_cycles: bool = True
) -> pl.LazyFrame:
    """Confirm complete logical groups across Arrow/Parquet chunk boundaries.

    Raw STEC and observations are retained. The private continuity identifier
    joins successfully repaired physical arcs only for code leveling.
    """
    if mode == "basic":
        return add_basic_arcs(lf, cadence).with_columns(
            pl.col("arc_id").alias("_continuity_id"),
            pl.col("stec_p_raw").alias("stec_p_corrected"),
            pl.lit("disabled").alias("slip_status"),
            pl.lit(None, dtype=pl.Int32).alias("slip_n1"),
            pl.lit(None, dtype=pl.Int32).alias("slip_n2"),
            pl.lit(None, dtype=pl.Float64).alias("slip_sigma_gf"),
            pl.lit(None, dtype=pl.Float64).alias("slip_sigma_mw"),
            pl.lit(None, dtype=pl.Float64).alias("slip_correction"),
            pl.lit(None, dtype=pl.Float64).alias("slip_sigma_phase"),
        )
    frame = lf.collect()
    fields = frame.select(
        pl.col("time").cast(pl.Int64),
        pl.col("station", "prn", "C1_code", "C2_code", "_receiver_state").cast(
            pl.String
        ),
        pl.col("_numeric_valid").fill_null(False),
        pl.col("L1_lli", "L2_lli").cast(pl.UInt8),
        pl.col("epoch_flag").cast(pl.Int64),
        pl.col("stec_p_raw", "stec_g", "mw", "C1_freq", "C2_freq").cast(pl.Float64),
    )
    result = pl.from_arrow(
        _slip_arcs(record_batch(fields), cadence, mode == "repair", integer_cycles)
    )
    assert isinstance(result, pl.DataFrame)
    return frame.with_columns(result.get_columns()).lazy()


def segment_arcs(
    samples: pl.Series, cadence: float | None, threshold: float, window: int
) -> pl.Series:
    """Compatibility wrapper; basic QC does not use GF/MW thresholds or windows."""
    frame = samples.struct.unnest()
    if not len(frame):
        return pl.Series([], dtype=ARC_DTYPE)
    invalid = frame.select((pl.col("time").diff() <= 0).any()).item()
    if invalid:
        raise ValueError(
            "Observation times must be finite and unique within each station/PRN."
        )
    return (
        _arc_expressions(
            frame.lazy(), cadence, groups=(), state_column="receiver_state"
        )
        .select("arc_id", "qc_reason")
        .collect()
        .to_struct()
    )


def align_stec(lf: pl.LazyFrame) -> pl.LazyFrame:
    """Align each final STEC product in its own code/calibration reference.

    Signal and bias-reference changes can reintroduce a step after the phase
    correction. Their offsets differ between raw and calibrated STEC, so each
    product needs its own alignment. VTEC follows the calibrated product when
    available. Input observations and bias estimates remain traceable.
    """
    frame = lf.with_columns(
        (
            pl.col("slip_status").is_in(["phase_repaired", "phase_continuous"])
            | pl.col("_level_key").ne_missing(
                pl.col("_level_key").shift(1).over("station", "prn")
            )
        ).alias("_stec_event")
    ).collect()
    fields = frame.select(
        pl.col("time").cast(pl.Int64),
        pl.col("station", "prn").cast(pl.String),
        pl.col("stec").cast(pl.Float64),
        pl.col("_stec_event").alias("event"),
    )
    result = pl.from_arrow(_smooth_stec(record_batch(fields)))
    assert isinstance(result, pl.DataFrame)
    frame = frame.with_columns(result.get_columns())
    source = "stec"
    expressions = [(pl.col("stec") - pl.col("_stec_adjustment")).alias("stec")]
    if "stec_dcb_corrected" in frame.columns:
        calibrated = pl.from_arrow(
            _smooth_stec(
                record_batch(
                    fields.with_columns(
                        frame["stec_dcb_corrected"].cast(pl.Float64).alias("stec")
                    )
                )
            )
        )
        assert isinstance(calibrated, pl.DataFrame)
        frame = frame.with_columns(
            calibrated["_stec_adjustment"].alias("_dcb_adjustment"),
            calibrated["slip_stec_correction"].alias("slip_dcb_correction"),
        )
        expressions.append(
            (pl.col("stec_dcb_corrected") - pl.col("_dcb_adjustment")).alias(
                "stec_dcb_corrected"
            )
        )
        source = "stec_dcb_corrected"
    else:
        frame = frame.with_columns(
            pl.lit(None, dtype=pl.Float64).alias("slip_dcb_correction")
        )
    return (
        frame.lazy()
        .with_columns(expressions)
        .with_columns((pl.col(source) / pl.col("mf")).alias("vtec"))
    )
