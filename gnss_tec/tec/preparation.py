"""Private receiver metadata and navigation preparation for TEC calculations."""

from __future__ import annotations

from collections.abc import Iterable
from pathlib import Path

import polars as pl

from .._core import _azimuth_elevation, _ecef_to_geodetic, _satellite_positions
from ..rinex import RinexObsHeader
from ..rinex.read_rinex import _handle_fn
from ._arrow import record_batch


def _calculate_azimuth_elevation(samples: pl.Series) -> pl.Series:
    result = pl.from_arrow(_azimuth_elevation(record_batch(samples.struct.unnest())))
    assert isinstance(result, pl.DataFrame)
    return result.to_struct()


def _prepare_observations(
    lf: pl.LazyFrame,
    header: RinexObsHeader,
    utc_epoch: pl.Expr,
    nav_fn: str | Path | Iterable[str | Path] | None,
) -> pl.LazyFrame:
    """Generate state and geometry without adding them to the raw reader schema."""
    schema = lf.collect_schema()
    lf = lf.with_columns(utc_epoch.dt.epoch("ns").alias("_utc_ns"))
    if header.receiver_history:
        history = sorted(set(header.receiver_history), key=lambda item: item[0])
        if len({item[0] for item in history}) != len(history):
            raise ValueError("Conflicting receiver headers at the same epoch.")
        positions = [_ecef_to_geodetic(*item[1]) for item in history]
        receivers = pl.DataFrame(
            {
                "_header_epoch": pl.Series(
                    [item[0] for item in history], dtype=pl.Int64
                ),
                "_header_lat": pl.Series([float(p[0]) for p in positions]),
                "_header_lon": pl.Series([float(p[1]) for p in positions]),
                "_header_alt": pl.Series([float(p[2]) for p in positions]),
                "_header_receiver": pl.Series(
                    [item[2] for item in history], dtype=pl.String
                ),
            }
        ).lazy()
        lf = lf.sort("_utc_ns").join_asof(
            receivers, left_on="_utc_ns", right_on="_header_epoch", strategy="backward"
        )
    else:
        lf = lf.with_columns(
            pl.lit(header.rx_geodetic[0]).alias("_header_lat"),
            pl.lit(header.rx_geodetic[1]).alias("_header_lon"),
            pl.lit(header.rx_geodetic[2]).alias("_header_alt"),
            pl.lit(header.receiver_id, dtype=pl.String).alias("_header_receiver"),
        )
    lf = lf.with_columns(
        *[
            pl.col(name).cast(pl.Float64)
            if name in schema
            else pl.col(source).alias(name)
            for name, source in (
                ("rx_lat", "_header_lat"),
                ("rx_lon", "_header_lon"),
                ("_rx_alt", "_header_alt"),
            )
        ]
    )
    if "receiver_state" in schema:
        lf = lf.with_columns(pl.col("receiver_state").alias("_event_state"))
    elif header.epoch_events:
        events = pl.DataFrame(
            {
                "_event_epoch": pl.Series(
                    [event[0] for event in header.epoch_events], dtype=pl.Int64
                ),
                "_event_state": pl.Series(
                    range(1, len(header.epoch_events) + 1), dtype=pl.UInt32
                ),
            }
        ).lazy()
        lf = lf.sort("_utc_ns").join_asof(
            events, left_on="_utc_ns", right_on="_event_epoch", strategy="backward"
        )
    else:
        lf = lf.with_columns(pl.lit(0, dtype=pl.UInt32).alias("_event_state"))
    identity = (
        pl.col("receiver_id") if "receiver_id" in schema else pl.col("_header_receiver")
    )
    lf = lf.with_columns(
        pl.concat_str(
            pl.col("_event_state").fill_null(0),
            identity.fill_null("unknown"),
            separator="|",
        ).alias("_receiver_state")
    )
    if nav_fn is None:
        return lf

    # Propagate once per epoch/satellite, even when rows contain multiple signals.
    keys = lf.select("_utc_ns", "prn").unique().sort("_utc_ns", "prn").collect()
    positions = pl.DataFrame(
        _satellite_positions(
            _handle_fn(nav_fn),
            keys["_utc_ns"].to_list(),
            keys["prn"].cast(pl.String).to_list(),
        )
    ).with_columns(pl.col("prn").cast(pl.Categorical))
    lf = lf.drop("azimuth", "elevation", strict=False).join(
        positions.lazy(),
        on=["_utc_ns", "prn"],
        how="left",
        validate="m:1",
        maintain_order="left",
    )
    return (
        lf.with_columns(
            pl.all_horizontal(pl.col("_sat_x", "_sat_y", "_sat_z").is_finite()).alias(
                "_geometry_available"
            ),
            pl.struct("_sat_x", "_sat_y", "_sat_z", "rx_lat", "rx_lon", "_rx_alt")
            .map_batches(
                _calculate_azimuth_elevation,
                return_dtype=pl.Struct(
                    {"azimuth": pl.Float64, "elevation": pl.Float64}
                ),
                is_elementwise=True,
            )
            .alias("_aer"),
        )
        .unnest("_aer")
        .fill_nan(None)
    )
