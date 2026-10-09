"""Types for the Arrow-based Rust RINEX reader."""

from typing import TypedDict

from pyarrow import RecordBatch

class _ObsHeader(TypedDict):
    version: str
    constellation: str | None
    sampling_interval: int | None
    leap_seconds: int | None
    station: str
    marker_type: str | None
    rx_x: float
    rx_y: float
    rx_z: float

def _read_obs(
    obs_fn: list[str],
    nav_fn: list[str] | None,
    constellations: str | None,
    codes: list[str] | None,
    pivot: bool,
) -> tuple[_ObsHeader, RecordBatch]: ...
