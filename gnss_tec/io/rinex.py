from __future__ import annotations

import json
import re
from collections.abc import Iterable
from dataclasses import dataclass, replace
from pathlib import Path

import polars as pl

from .._core import _ecef_to_geodetic, _read_obs

ReceiverHeader = tuple[int, tuple[float, float, float], str | None]

ALL_CONSTELLATIONS = {
    "C": "BDS",
    "G": "GPS",
    "E": "Galileo",
    "R": "GLONASS",
    "J": "QZSS",
    "I": "IRNSS",
    "S": "SBAS",
}
"""All supported GNSS constellations for RINEX file reading."""

LEAP_SECONDS = [
    (pl.datetime(1980, 1, 1), pl.duration(seconds=0, time_unit="ns")),
    (pl.datetime(1981, 7, 1), pl.duration(seconds=1, time_unit="ns")),
    (pl.datetime(1982, 7, 1), pl.duration(seconds=2, time_unit="ns")),
    (pl.datetime(1983, 7, 1), pl.duration(seconds=3, time_unit="ns")),
    (pl.datetime(1985, 7, 1), pl.duration(seconds=4, time_unit="ns")),
    (pl.datetime(1988, 1, 1), pl.duration(seconds=5, time_unit="ns")),
    (pl.datetime(1990, 1, 1), pl.duration(seconds=6, time_unit="ns")),
    (pl.datetime(1991, 1, 1), pl.duration(seconds=7, time_unit="ns")),
    (pl.datetime(1992, 7, 1), pl.duration(seconds=8, time_unit="ns")),
    (pl.datetime(1993, 7, 1), pl.duration(seconds=9, time_unit="ns")),
    (pl.datetime(1994, 7, 1), pl.duration(seconds=10, time_unit="ns")),
    (pl.datetime(1996, 1, 1), pl.duration(seconds=11, time_unit="ns")),
    (pl.datetime(1997, 7, 1), pl.duration(seconds=12, time_unit="ns")),
    (pl.datetime(1999, 1, 1), pl.duration(seconds=13, time_unit="ns")),
    (pl.datetime(2006, 1, 1), pl.duration(seconds=14, time_unit="ns")),
    (pl.datetime(2009, 1, 1), pl.duration(seconds=15, time_unit="ns")),
    (pl.datetime(2012, 7, 1), pl.duration(seconds=16, time_unit="ns")),
    (pl.datetime(2015, 7, 1), pl.duration(seconds=17, time_unit="ns")),
    (pl.datetime(2017, 1, 1), pl.duration(seconds=18, time_unit="ns")),
]
"""List of leap seconds as (datetime, duration) tuples."""


def get_leap_seconds(time_col: pl.Expr | str) -> pl.Expr:
    """Return a nanosecond leap-second duration expression for GPS epochs."""
    if isinstance(time_col, str):
        time_col = pl.col(time_col)
    time_col = time_col.dt.replace_time_zone(None)

    expr = None
    for dt, duration in LEAP_SECONDS[::-1]:
        if expr is None:
            expr = pl.when(time_col.ge(dt)).then(duration)
        else:
            expr = expr.when(time_col.ge(dt)).then(duration)

    if expr is None:
        raise ValueError("LEAP_SECONDS list is empty.")

    return expr


@dataclass
class RinexObsHeader:
    """Dataclass for RINEX observation file header metadata."""

    version: str
    """RINEX version."""

    constellation: str | None
    """Constellation for which the RINEX file contains observations."""

    marker_name: str
    """Marker name."""

    marker_type: str | None
    """Marker type."""

    rx_ecef: tuple[float, float, float]
    """Approximate receiver position in ECEF coordinates (X, Y, Z) in meters."""

    rx_geodetic: tuple[float, float, float]
    """Approximate receiver position in geodetic coordinates (latitude, longitude,
        altitude) in degrees and meters."""

    sampling_interval: float | None
    """Sampling interval in seconds."""

    leap_seconds: int | None
    """Number of leap seconds."""

    epoch_resolution: str = "ns"
    """Integer epoch resolution; parsed observations use nanoseconds."""

    epoch_events: tuple[tuple[int, int, str], ...] = ()
    """Timestamped events: UTC ns, RINEX flag and original logical records.

    Blank-epoch special events and their payloads are omitted. Flag-6 slip
    payloads are retained here and excluded from observation values.
    """

    receiver_id: str | None = None
    """Receiver serial number, model and firmware identity, if supplied."""

    receiver_history: tuple[ReceiverHeader, ...] = ()
    """Per-file first UTC epoch, original ECEF position and receiver identity."""

    def to_dict(
        self,
    ) -> dict[
        str,
        str
        | int
        | float
        | tuple[float, float, float]
        | tuple[tuple[int, int, str], ...]
        | tuple[ReceiverHeader, ...]
        | None,
    ]:
        return {
            "version": self.version,
            "constellation": self.constellation,
            "marker_name": self.marker_name,
            "marker_type": self.marker_type,
            "rx_ecef": self.rx_ecef,
            "rx_geodetic": self.rx_geodetic,
            "sampling_interval": self.sampling_interval,
            "leap_seconds": self.leap_seconds,
            "epoch_resolution": self.epoch_resolution,
            "epoch_events": self.epoch_events,
            "receiver_id": self.receiver_id,
            "receiver_history": self.receiver_history,
        }

    def to_metadata(self) -> dict[str, str]:
        """
        Convert the RinexObsHeader to a dictionary suitable for storing as Parquet file
        metadata using Polars.
        """
        return {
            "version": self.version,
            "constellation": self.constellation or "",
            "marker_name": self.marker_name,
            "marker_type": self.marker_type or "",
            "rx_ecef_x": str(self.rx_ecef[0]),
            "rx_ecef_y": str(self.rx_ecef[1]),
            "rx_ecef_z": str(self.rx_ecef[2]),
            "rx_geodetic_lat": str(self.rx_geodetic[0]),
            "rx_geodetic_lon": str(self.rx_geodetic[1]),
            "rx_geodetic_alt": str(self.rx_geodetic[2]),
            "sampling_interval": ""
            if self.sampling_interval is None
            else str(self.sampling_interval),
            "leap_seconds": "" if self.leap_seconds is None else str(self.leap_seconds),
            "epoch_resolution": self.epoch_resolution,
            "epoch_events": json.dumps(self.epoch_events),
            "receiver_id": self.receiver_id or "",
            "receiver_history": json.dumps(self.receiver_history),
        }

    @staticmethod
    def validate_metadata(metadata: dict[str, str]) -> None:
        required = {
            "version",
            "constellation",
            "marker_name",
            "marker_type",
            "rx_ecef_x",
            "rx_ecef_y",
            "rx_ecef_z",
            "rx_geodetic_lat",
            "rx_geodetic_lon",
            "rx_geodetic_alt",
            "sampling_interval",
            "leap_seconds",
        }
        missing = sorted(required - set(metadata))
        if missing:
            raise ValueError(
                "Parquet metadata is missing required RINEX header fields: "
                f"{', '.join(missing)}. Save parsed observations with "
                "`metadata=header.to_metadata()`."
            )

    @staticmethod
    def from_metadata(metadata: dict[str, str]) -> RinexObsHeader:
        """
        Create a RinexObsHeader from a dictionary of Parquet file metadata.
        """
        RinexObsHeader.validate_metadata(metadata)
        sampling_interval = (
            float(metadata["sampling_interval"])
            if metadata["sampling_interval"]
            else None
        )
        leap_seconds = (
            int(metadata["leap_seconds"]) if metadata["leap_seconds"] else None
        )
        return RinexObsHeader(
            version=metadata["version"],
            constellation=metadata["constellation"] or None,
            marker_name=metadata["marker_name"],
            marker_type=metadata["marker_type"] or None,
            rx_ecef=(
                float(metadata["rx_ecef_x"]),
                float(metadata["rx_ecef_y"]),
                float(metadata["rx_ecef_z"]),
            ),
            rx_geodetic=(
                float(metadata["rx_geodetic_lat"]),
                float(metadata["rx_geodetic_lon"]),
                float(metadata["rx_geodetic_alt"]),
            ),
            sampling_interval=sampling_interval,
            leap_seconds=leap_seconds,
            epoch_resolution=metadata.get("epoch_resolution", "ms"),
            epoch_events=tuple(
                (int(event[0]), int(event[1]), str(event[2]))
                for event in json.loads(metadata.get("epoch_events", "[]"))
            ),
            receiver_id=metadata.get("receiver_id") or None,
            receiver_history=tuple(
                (
                    int(item[0]),
                    (float(item[1][0]), float(item[1][1]), float(item[1][2])),
                    item[2],
                )
                for item in json.loads(metadata.get("receiver_history", "[]"))
            ),
        )


def _handle_fn(fn: str | Path | Iterable[str | Path]) -> list[str]:
    if isinstance(fn, (str, Path)):
        fn_list = [str(fn)]
    elif isinstance(fn, Iterable):
        fn_list = [str(f) for f in fn]
    else:
        raise TypeError(
            f"The file path must be a str, Path, or Iterable of str/Path, not {fn}."
        )

    for f in fn_list:
        if not Path(f).exists():
            raise FileNotFoundError(f"RINEX file not found: {f}")

    return fn_list


def _match_code(code: str) -> bool:
    return re.match(r"[A-Z]\d[A-Z]{0,1}$", code) is not None


def read_rinex_obs(
    obs_fn: str | Path | Iterable[str | Path],
    constellations: str | None = None,
    codes: str | Iterable[str] | None = None,
    *,
    utc: bool = True,
    station: str | None = None,
    pivot: bool = True,
    include_lli: bool = False,
) -> tuple[RinexObsHeader, pl.LazyFrame]:
    """Decode raw RINEX observations with optional lock indicators.

    Parameters
    ----------
    obs_fn : str, Path, or iterable of str or Path
        Observation files from one station and RINEX major version (2/3).
        RINEX, Hatanaka and supported compressed files are accepted.
    constellations : str or None, default None
        Constellation letters to include; None includes all supported ones.
    codes : str, iterable of str, or None, default None
        Case-sensitive Python regular expressions matching whole observation
        codes. Literal codes such as ["C1C", "L1C"] work; "[CL]1.*" selects
        code/phase on band 1. None includes all codes; no matches produce
        an empty frame.
    utc : bool, default True
        Return UTC epochs; False returns timezone-naive GPS epochs.
    station : str or None, default None
        Override the station identifier derived from the header.
    pivot : bool, default True
        Return one column per observation code. False returns code/value
        columns with one row per observation.
    include_lli : bool, default False
        Extract and emit all selected observations' raw lock indicators:
        <code>_lli in wide output or lli in long output. UInt8 values and
        missing indicators (null) retain their version-specific meaning.
        False omits native LLI buffers/columns. Epoch flags, observations,
        time and retained event metadata are independent of this switch.

    Returns
    -------
    header : RinexObsHeader
        Header metadata including per-file positions/receiver identities and
        timestamped event records, preserved by header.to_metadata().
    observations : polars.LazyFrame
        Nanosecond time, station/prn, Float64 observations in RINEX units,
        epoch_flag and optional UInt8/null LLI. Geometry and TEC state are
        prepared by the TEC functions. Only flag-0/1 records contribute values;
        timestamped flag-6 payloads are retained in header events. Special
        records with blank epoch fields are consumed and omitted without
        assigning a timestamp or receiver state. Parsing completes before return.

    Raises
    ------
    FileNotFoundError
        If an observation file does not exist.
    ValueError
        If code expressions/constellations are invalid, or files mix
        stations, RINEX major versions or inconsistent GPS scales.

    Notes
    -----
    Request include_lli=True before DataFrame/Parquet TEC processing when
    recorded lock/half-cycle QC is intended. Absent LLI cannot be
    reconstructed. calc_tec_from_rinex opts in automatically. This option
    does not reduce source-file I/O or upstream inline-indicator parsing.
    """
    obs_fn_list = _handle_fn(obs_fn)
    observation_codes = (
        None if codes is None else [codes] if isinstance(codes, str) else list(codes)
    )
    if constellations is not None:
        constellations = constellations.upper()
        for constellation in constellations:
            if constellation not in ALL_CONSTELLATIONS:
                raise ValueError(
                    f"Unknown constellation code: {constellation}. "
                    f"Valid codes are: {', '.join(ALL_CONSTELLATIONS)}"
                )

    if len(obs_fn_list) > 1:
        parts = [
            read_rinex_obs(
                fn,
                constellations,
                observation_codes,
                utc=utc,
                pivot=pivot,
                include_lli=include_lli,
            )
            for fn in obs_fn_list
        ]
        headers = [header for header, _ in parts]
        if len({header.marker_name for header in headers}) != 1:
            raise ValueError(
                "Observation files must belong to the same station; process stations separately."
            )
        if len({header.version.split(".")[0] for header in headers}) != 1:
            raise ValueError("Observation files must use the same RINEX major version.")
        if not utc and len({header.leap_seconds for header in headers}) != 1:
            raise ValueError(
                "GPS-time observation files must use consistent leap seconds."
            )
        history = tuple(
            sorted(
                (item for header in headers for item in header.receiver_history),
                key=lambda item: item[0],
            )
        )
        header = replace(
            headers[0],
            sampling_interval=headers[0].sampling_interval
            if len({header.sampling_interval for header in headers}) == 1
            else None,
            leap_seconds=headers[0].leap_seconds
            if len({header.leap_seconds for header in headers}) == 1
            else None,
            receiver_id=headers[0].receiver_id
            if len({header.receiver_id for header in headers}) == 1
            else None,
            receiver_history=history,
            epoch_events=tuple(
                sorted(
                    {event for header in headers for event in header.epoch_events},
                    key=lambda event: event[0],
                )
            ),
        )
        frame = pl.concat([frame for _, frame in parts], how="diagonal")
        if station is not None:
            header = replace(header, marker_name=station)
            frame = frame.with_columns(
                pl.lit(station).cast(pl.Categorical).alias("station")
            )
        return header, frame.sort(
            ["time", "station", "prn"] + ([] if pivot else ["code"])
        )

    header_dict, batch = _read_obs(
        obs_fn_list, constellations, observation_codes, pivot, include_lli
    )
    rx_ecef = (header_dict["rx_x"], header_dict["rx_y"], header_dict["rx_z"])
    rx_lat, rx_lon, rx_alt = _ecef_to_geodetic(*rx_ecef)
    first_epoch = header_dict["first_epoch"]
    header = RinexObsHeader(
        version=header_dict["version"],
        constellation=header_dict["constellation"],
        marker_name=header_dict["station"][:4].strip() if station is None else station,
        marker_type=header_dict["marker_type"],
        rx_ecef=rx_ecef,
        rx_geodetic=(float(rx_lat), float(rx_lon), float(rx_alt)),
        sampling_interval=header_dict["sampling_interval"],
        leap_seconds=header_dict["leap_seconds"],
        epoch_events=tuple(header_dict["epoch_events"]),
        receiver_id=header_dict["receiver_id"],
        receiver_history=()
        if first_epoch is None
        else ((first_epoch, rx_ecef, header_dict["receiver_id"]),),
    )
    frame = pl.DataFrame(batch)
    observation_columns = (
        sorted(name for name in frame.columns if _match_code(name))
        + sorted(name for name in frame.columns if name.endswith("_lli"))
        if pivot
        else ["code", "value"] + (["lli"] if include_lli else [])
    )
    lf = (
        frame.lazy()
        .with_columns(
            pl.col("time").cast(pl.Datetime("ns", "UTC")),
            pl.lit(header.marker_name).cast(pl.Categorical).alias("station"),
            pl.col("prn").cast(pl.Categorical),
        )
        .fill_nan(None)
        .select("time", "station", "prn", *observation_columns, "epoch_flag")
        .sort(["time", "station", "prn"] + ([] if pivot else ["code"]))
    )
    if not utc:
        lf = lf.with_columns(
            (
                pl.col("time")
                + (
                    get_leap_seconds("time")
                    if header.leap_seconds is None
                    else pl.duration(seconds=header.leap_seconds, time_unit="ns")
                )
            ).dt.replace_time_zone(None)
        )
    return header, lf
