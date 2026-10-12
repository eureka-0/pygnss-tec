"""Small observations derived from known TEC, plus minimal RINEX writers."""

from datetime import UTC, datetime, timedelta

import numpy as np
import polars as pl

import gnss_tec as gt
from gnss_tec.rinex import RinexObsHeader
from gnss_tec.tec.constants import TECConfig

F1, F2, C = 1575.42e6, 1227.60e6, 299792458.0
K = F1**2 * F2**2 / (F1**2 - F2**2) / 40.3e16


def physical_observations(tec, *, cadence=30, start=None):
    tec = np.asarray(tec, dtype=float)
    header = RinexObsHeader(
        "3.04", "G", "TEST", None, (6378137.0, 0.0, 0.0), (0.0, 0.0, 0.0), cadence, 18
    )
    start = start or datetime(2024, 1, 10, tzinfo=UTC)
    distance = 21_000_000.0
    return header, pl.DataFrame(
        {
            "time": [start + timedelta(seconds=i * cadence) for i in range(len(tec))],
            "station": ["TEST"] * len(tec),
            "prn": ["G01"] * len(tec),
            "azimuth": [90.0] * len(tec),
            "elevation": [60.0] * len(tec),
            "C1C": distance + 40.3e16 * tec / F1**2,
            "C2W": distance + 40.3e16 * tec / F2**2,
            "L1C": (distance - 40.3e16 * tec / F1**2) * F1 / C,
            "L2W": (distance - 40.3e16 * tec / F2**2) * F2 / C,
        }
    )


def calculate(header, observations, bias=None, **kwargs):
    return gt.calc_tec_from_df(
        observations,
        header,
        bias,
        TECConfig(rx_bias=None, retain_intermediate="all", **kwargs),
    ).collect(engine="in-memory")


def bias_rows(starts, ends, values, *, reverse=False):
    return pl.DataFrame(
        {
            "station": [None] * len(values),
            "prn": ["G01"] * len(values),
            "obs1": ["C2W" if reverse else "C1C"] * len(values),
            "obs2": ["C1C" if reverse else "C2W"] * len(values),
            "bias_start": starts,
            "bias_end": ends,
            "estimated_value": values,
            "bias": ["DSB"] * len(values),
            "unit": ["ns"] * len(values),
            "time_system": ["G"] * len(values),
        }
    ).with_columns(pl.col("prn", "station", "obs1", "obs2").cast(pl.Categorical))


def write_minimal_rinex(path, version, *, flagged=True):
    def header_line(text, label):
        return f"{text:<60}{label}\n"

    codes = ["C1", "L1", "C2", "L2"] if version == 2 else ["C1C", "L1C", "C2W", "L2W"]
    content = header_line(
        f"{version + 0.04:9.2f}           OBSERVATION DATA    G", "RINEX VERSION / TYPE"
    )
    content += header_line("TEST", "MARKER NAME")
    content += header_line(
        f"{6378137.0:14.4f}{0.0:14.4f}{0.0:14.4f}", "APPROX POSITION XYZ"
    )
    content += header_line("    0.100", "INTERVAL")
    content += header_line("    18", "LEAP SECONDS")
    content += header_line(
        "  2024     1    10     0     0    0.0000000     GPS", "TIME OF FIRST OBS"
    )
    content += (
        header_line(
            f"{4:6d}" + "".join(f"{c:>6}" for c in codes), "# / TYPES OF OBSERV"
        )
        if version == 2
        else header_line("G    4 " + " ".join(codes), "SYS / # / OBS TYPES")
    )
    content += header_line("", "END OF HEADER")
    _, obs = physical_observations(np.full(4, 30.0), cadence=0.1)
    for i in range(4):
        if i == 2 and flagged:
            event = (
                f" 24  1 10  0  0{0.15:11.7f}  4{1:3d}"
                if version == 2
                else "> 2024 01 10 00 00  0.1500000  4  1"
            )
            content += event + "\n" + header_line("Receiver event preserved", "COMMENT")
        flag = 1 if i == 3 and flagged else 0
        epoch = (
            f" 24  1 10  0  0{i * 0.1:11.7f}  {flag}{1:3d}G01"
            if version == 2
            else f"> 2024 01 10 00 00 {i * 0.1:10.7f}  {flag}  1"
        )
        phase_lli = {1: 2, 2: 1}.get(i, 0) if flagged else 0
        fields = []
        for name in ("C1C", "L1C", "C2W", "L2W"):
            lli = phase_lli if name == "L1C" else 0
            fields.append(f"{float(obs[name].item(i)):14.3f}{lli}7")
        content += (
            epoch + "\n" + ("G01" if version == 3 else "") + "".join(fields) + "\n"
        )
    path.write_text(content)
