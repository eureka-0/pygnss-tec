"""Observation geometry and private receiver-state preparation."""

from __future__ import annotations

from collections.abc import Iterable
from pathlib import Path

import polars as pl

from .._arrow import record_batch
from .._core import (
    _azimuth_elevation,
    _ecef_to_geodetic,
    _satellite_positions,
    _satellite_positions_from_files,
)
from ..io.navigation import NavigationData
from ..io.rinex import RinexObsHeader, _handle_fn
from .observation_time import _utc_epoch


def _calculate_azimuth_elevation(samples: pl.Series) -> pl.Series:
    result = pl.from_arrow(_azimuth_elevation(record_batch(samples.struct.unnest())))
    assert isinstance(result, pl.DataFrame)
    return result.to_struct()


def _event_resets_ambiguity(flag: int, records: str) -> bool:
    """Apply the reviewed conservative policy to retained timestamped events."""
    if flag == 5:
        # External events do not define an ambiguity reset. Free text is not
        # machine-readable reset evidence; independent LLI/state still applies.
        return False
    if flag == 4:
        return any(line[60:].strip() != "COMMENT" for line in records.splitlines()[1:])
    return flag != 0


def _resolve_receiver(
    lf: pl.LazyFrame, header: RinexObsHeader, utc_epoch: pl.Expr
) -> pl.LazyFrame:
    """Resolve per-epoch coordinates with the existing header/column precedence."""
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
        )
        if len(history) == 1:
            # A single effective header needs no sort/join. Preserve the null
            # position before its first epoch, just as a backward as-of join does.
            lf = lf.with_columns(
                pl.when(pl.col("_utc_ns") >= history[0][0])
                .then(pl.lit(receivers[name][0], dtype=receivers.schema[name]))
                .alias(name)
                for name in receivers.columns
            )
        else:
            lf = lf.sort("_utc_ns").join_asof(
                receivers.lazy(),
                left_on="_utc_ns",
                right_on="_header_epoch",
                strategy="backward",
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
    return lf


def _prepare_observations(
    lf: pl.LazyFrame,
    header: RinexObsHeader,
    utc_epoch: pl.Expr,
    nav_fn: str | Path | Iterable[str | Path] | None,
) -> pl.LazyFrame:
    """Prepare receiver/event state and optional geometry for TEC."""
    schema = lf.collect_schema()
    reset_epochs = sorted(
        {
            epoch
            for epoch, flag, records in header.epoch_events
            if _event_resets_ambiguity(flag, records)
        }
    )
    lf = _resolve_receiver(lf, header, utc_epoch)
    if "receiver_state" in schema:
        lf = lf.with_columns(pl.col("receiver_state").alias("_event_state"))
    elif reset_epochs:
        events = pl.DataFrame(
            {
                "_event_epoch": pl.Series(reset_epochs, dtype=pl.Int64),
                "_event_state": pl.Series(
                    range(1, len(reset_epochs) + 1), dtype=pl.UInt32
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
        if {"azimuth", "elevation"} <= set(schema.names()):
            # Match the geometry-column order of the navigation preparation path.
            lf = lf.select(pl.exclude("azimuth", "elevation"), "azimuth", "elevation")
        return lf
    return _append_geometry(lf, nav_fn).fill_nan(None)


def _append_geometry(
    lf: pl.LazyFrame, navigation: NavigationData | str | Path | Iterable[str | Path]
) -> pl.LazyFrame:
    # Propagate once per epoch/satellite, even when rows contain multiple signals.
    keys = lf.select("_utc_ns", "prn").unique().sort("_utc_ns", "prn").collect()
    query = record_batch(keys.with_columns(pl.col("prn").cast(pl.String)))
    batch = (
        _satellite_positions(navigation._handle, query)
        if isinstance(navigation, NavigationData)
        else _satellite_positions_from_files(_handle_fn(navigation), query)
    )
    # Keep the join dtype identical for external String and reader Categorical PRNs.
    positions = pl.from_arrow(batch)
    assert isinstance(positions, pl.DataFrame)
    positions = positions.with_columns(pl.col("prn").cast(keys.schema["prn"]))
    lf = lf.drop("azimuth", "elevation", strict=False).join(
        positions.lazy(),
        on=["_utc_ns", "prn"],
        how="left",
        validate="m:1",
        maintain_order="left",
    )
    return lf.with_columns(
        pl.all_horizontal(pl.col("_sat_x", "_sat_y", "_sat_z").is_finite()).alias(
            "_geometry_available"
        ),
        pl.struct("_sat_x", "_sat_y", "_sat_z", "rx_lat", "rx_lon", "_rx_alt")
        .map_batches(
            _calculate_azimuth_elevation,
            return_dtype=pl.Struct({"azimuth": pl.Float64, "elevation": pl.Float64}),
            is_elementwise=True,
        )
        .alias("_aer"),
    ).unnest("_aer")


def compute_az_el(
    observations: pl.DataFrame | pl.LazyFrame,
    header: RinexObsHeader,
    navigation: NavigationData,
    *,
    overwrite: bool = False,
) -> pl.LazyFrame:
    """Append satellite azimuth and elevation to observations from one station.

    Parameters
    ----------
    observations : polars.DataFrame or polars.LazyFrame
        Wide or long observations with time, station and prn. Time must be
        timezone-aware UTC or timezone-naive GPS. Existing rx_lat/rx_lon
        columns override header coordinates in degrees; height follows the
        header's receiver history in metres.
    header : RinexObsHeader
        Observation time-scale and receiver-position metadata.
    navigation : NavigationData
        Broadcast ephemerides loaded by read_rinex_nav. Reuse this object
        across calls to avoid repeated decoding and indexing.
    overwrite : bool, default False
        Replace both angle columns if either already exists. False raises
        rather than mixing existing and newly computed angles.

    Returns
    -------
    polars.LazyFrame
        Original rows, columns and time values plus Float64 azimuth/elevation
        in degrees. Azimuth is clockwise from north in [0, 360); elevation
        is in [-90, 90]. Unavailable geometry is null; no elevation filter or
        TEC quality control is applied. Query collection and satellite
        propagation complete before return; angle evaluation remains lazy.

    Raises
    ------
    TypeError
        If navigation is not NavigationData or time is not Datetime.
    ValueError
        If required columns are absent, time/PRN is invalid, multiple stations
        are present, or existing angle columns would be overwritten.
    """
    if not isinstance(navigation, NavigationData):
        raise TypeError("navigation must be NavigationData from read_rinex_nav().")
    lf = observations.lazy()
    schema = lf.collect_schema()
    missing = sorted({"time", "station", "prn"} - set(schema.names()))
    if missing:
        raise ValueError(
            f"compute_az_el requires columns that are missing: {', '.join(missing)}."
        )
    if not overwrite and {"azimuth", "elevation"} & set(schema.names()):
        raise ValueError(
            "Angle columns already exist; use overwrite=True to replace both."
        )
    epoch = _utc_epoch(lf, header)
    invalid, stations = (
        lf.select(
            (
                epoch.is_null()
                | ~epoch.dt.epoch("us").is_between(
                    -(2**63) // 1000 + 1, (2**63 - 1) // 1000
                )
            ).any(),
            pl.col("station").n_unique(),
        )
        .collect()
        .row(0)
    )
    if invalid:
        raise ValueError(
            "Observation times must be non-null and within the signed nanosecond range."
        )
    if stations > 1:
        raise ValueError(
            "Observations must belong to one station; process stations separately."
        )
    original = schema.names()
    # Protect original columns if a caller retained private preparation diagnostics.
    working_columns = {
        "_utc_ns",
        "_header_epoch",
        "_header_lat",
        "_header_lon",
        "_header_alt",
        "_header_receiver",
        "_sat_x",
        "_sat_y",
        "_sat_z",
        "_geometry_available",
        "_aer",
    }
    saved = {}
    occupied = set(original)
    for name in sorted(working_columns & occupied):
        alias = f"_az_el_original{name}"
        while alias in occupied:
            alias += "_"
        occupied.add(alias)
        saved[name] = alias
    if saved:
        lf = lf.with_columns(
            pl.col(name).alias(alias) for name, alias in saved.items()
        ).drop(saved)
    # Receiver-history joins sort by UTC; only this branch needs row restoration.
    row_index = "_az_el_row"
    while row_index in occupied:
        row_index += "_"
    restore_order = len(header.receiver_history) > 1
    if restore_order:
        lf = lf.with_row_index(row_index)
    result = _append_geometry(_resolve_receiver(lf, header, epoch), navigation)
    if restore_order:
        result = result.sort(row_index)
    output = [
        pl.col(name).cast(schema[name])
        if name in {"rx_lat", "rx_lon", "_rx_alt"}
        else pl.col(saved.get(name, name)).alias(name)
        for name in original
        if name not in {"azimuth", "elevation"}
    ]
    return result.select(*output, pl.col("azimuth", "elevation").fill_nan(None))
