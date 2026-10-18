"""Broadcast eligibility is checked before nearest-record selection."""

import gzip
from datetime import UTC, datetime, timedelta

import numpy as np
import polars as pl
import pytest

import gnss_tec as gt
from gnss_tec._arrow import record_batch
from gnss_tec._core import _satellite_positions


@pytest.fixture
def gps_record(rinex_nav_v3):
    with gzip.open(rinex_nav_v3, "rt") as source:
        lines = source.readlines()
    index = next(i for i, line in enumerate(lines) if line.startswith("G01 "))
    record = lines[index : index + 8]
    # The source G01 is explicitly unhealthy; setting zero creates a controlled
    # healthy counterpart with exactly the same independently fixed orbit.
    record[6] = record[6][:23] + f"{0.0:19.12E}" + record[6][42:]
    return record


def _write_nav(path, records):
    path.write_text(
        f"{'     3.04           NAVIGATION DATA     M':<60}RINEX VERSION / TYPE\n"
        + f"{'':<60}END OF HEADER\n"
        + "".join("".join(record) for record in records)
    )
    return gt.read_rinex_nav(path)


def _positions(navigation, seconds, prn="G01"):
    reference = datetime(2024, 1, 10, tzinfo=UTC)
    query = pl.DataFrame(
        {
            "time": [reference + timedelta(seconds=s) for s in seconds],
            "prn": [prn] * len(seconds),
        }
    )
    return pl.from_arrow(
        _satellite_positions(
            navigation._handle,
            record_batch(
                query.select(pl.col("time").dt.epoch("ns").alias("_utc_ns"), "prn")
            ),
        )
    )


def test_gps_validity_boundaries_health_and_fit(tmp_path, gps_record):
    navigation = _write_nav(tmp_path / "gps.nav", [gps_record])
    # Toe = GPST 00:00 = UTC 23:59:42 on the previous day.
    seconds = [-7218.000001, -7218, -18, 7182, 7182.000001, 366 * 86400]
    result = _positions(navigation, seconds)
    finite = np.isfinite(result["_sat_x"].to_numpy())
    assert finite.tolist() == [False, True, True, True, False, False]
    unhealthy = gps_record.copy()
    unhealthy[6] = unhealthy[6][:23] + f"{63.0:19.12E}" + unhealthy[6][42:]
    assert not np.isfinite(
        _positions(_write_nav(tmp_path / "bad.nav", [unhealthy]), [0])["_sat_x"][0]
    )
    short_fit = gps_record.copy()
    short_fit[7] = short_fit[7][:23] + f"{2.0:19.12E}" + "\n"
    finite = np.isfinite(
        _positions(
            _write_nav(tmp_path / "short.nav", [short_fit]), [3582, 3582.000001]
        )["_sat_x"].to_numpy()
    )
    assert finite.tolist() == [True, False]


def test_unhealthy_nearest_does_not_hide_valid_alternative(tmp_path, gps_record):
    unhealthy = gps_record.copy()
    unhealthy[0] = unhealthy[0].replace("00 00 00", "01 00 00")
    unhealthy[6] = unhealthy[6][:23] + f"{63.0:19.12E}" + unhealthy[6][42:]
    expected = _positions(_write_nav(tmp_path / "valid.nav", [gps_record]), [3582])
    actual = _positions(
        _write_nav(tmp_path / "mixed.nav", [gps_record, unhealthy]), [3582]
    )
    np.testing.assert_array_equal(actual["_sat_x"], expected["_sat_x"])
    assert np.isfinite(actual["_sat_x"][0])


@pytest.mark.parametrize(
    "system,week,offset,limit", [("C", 940, -4, 21600), ("E", 2296, -18, 10800)]
)
def test_constellation_specific_validity_and_time_scale(
    tmp_path, gps_record, system, week, offset, limit
):
    record = gps_record.copy()
    record[0] = system + record[0][1:]
    record[5] = record[5][:42] + f"{float(week):19.12E}" + record[5][61:]
    navigation = _write_nav(tmp_path / "constellation.nav", [record])
    result = _positions(
        navigation,
        [
            offset - limit - 1e-6,
            offset - limit,
            offset,
            offset + limit,
            offset + limit + 1e-6,
        ],
        system + "01",
    )
    assert np.isfinite(result["_sat_x"].to_numpy()).tolist() == [
        False,
        True,
        True,
        True,
        False,
    ]


@pytest.mark.parametrize("line,start", [(3, 4), (5, 42), (6, 23)])
def test_missing_toe_week_or_health_is_ineligible(tmp_path, gps_record, line, start):
    record = gps_record.copy()
    record[line] = record[line][:start] + " " * 19 + record[line][start + 19 :]
    navigation = _write_nav(tmp_path / "missing.nav", [record])
    assert not np.isfinite(_positions(navigation, [0])["_sat_x"][0])


def test_unsupported_qzss_propagation_remains_unavailable(tmp_path, gps_record):
    record = gps_record.copy()
    record[0] = "J" + record[0][1:]
    record[7] = record[7][:23] + f"{0.0:19.12E}\n"
    navigation = _write_nav(tmp_path / "qzss.nav", [record])
    assert navigation.satellites == ("J01",)
    assert not np.isfinite(_positions(navigation, [-18], "J01")["_sat_x"][0])
