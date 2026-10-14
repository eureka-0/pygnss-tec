"""Types for the Arrow-based Rust RINEX reader."""

from typing import TypedDict

from pyarrow import RecordBatch

class _ObsHeader(TypedDict):
    version: str
    constellation: str | None
    sampling_interval: float | None
    leap_seconds: int | None
    station: str
    marker_type: str | None
    rx_x: float
    rx_y: float
    rx_z: float
    epoch_events: list[tuple[int, int, str]]
    receiver_id: str | None
    first_epoch: int | None

def _read_obs(
    obs_fn: list[str], constellations: str | None, codes: list[str] | None, pivot: bool
) -> tuple[_ObsHeader, RecordBatch]: ...
def _satellite_positions(
    nav_fn: list[str], times: list[int], prns: list[str]
) -> RecordBatch: ...
def _select_observations(
    input: RecordBatch,
    pairs: list[tuple[str, str, str, int, float, float]],
    bias: RecordBatch | None,
    receiver: bool,
) -> RecordBatch: ...
def _basic_arcs(input: RecordBatch, cadence: float | None) -> RecordBatch: ...
def _azimuth_elevation(input: RecordBatch) -> RecordBatch: ...
def _ecef_to_geodetic(x: float, y: float, z: float) -> tuple[float, float, float]: ...
