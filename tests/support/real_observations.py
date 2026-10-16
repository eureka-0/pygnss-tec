"""Compact windows of real observations for integration assertions."""

import polars as pl

OBSERVATION_CODES = {
    "2": ["C1", "L1", "C2", "L2", "S1", "S2"],
    "3": [
        "C1C",
        "L1C",
        "C2W",
        "L2W",
        "S1C",
        "S2W",
        "C2I",
        "L2I",
        "C6I",
        "L6I",
        "S2I",
        "S6I",
    ],
}


def collect_short_windows(frame: pl.DataFrame | pl.LazyFrame) -> pl.DataFrame:
    # Ten minutes across GPS midnight exercise continuity and daily bias changes.
    # Five minutes at 18:00 on each day also give the eastern receiver night data.
    gps = pl.col("time") + pl.duration(seconds=18, time_unit="ns")
    midnight = gps.is_between(
        pl.datetime(2024, 1, 10, 23, 55, time_zone="UTC"),
        pl.datetime(2024, 1, 11, 0, 5, time_zone="UTC"),
        closed="left",
    )
    night = (gps.dt.hour() == 18) & (gps.dt.minute() < 5)
    selected = frame.lazy().filter(midnight | night).collect(engine="in-memory")
    # Own the small buffers: a slice alone could retain the entire daily input.
    return pl.DataFrame(selected.to_dict(as_series=False), schema=selected.schema)
