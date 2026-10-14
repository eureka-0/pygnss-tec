"""Native entry points preserve recoverable file errors and event text."""

import gzip
import subprocess
import sys

import pytest
from polars.testing import assert_frame_equal
from synthetic_observations import write_minimal_rinex

import gnss_tec as gt


@pytest.mark.parametrize("entry", ["_read_obs", "_satellite_positions"])
@pytest.mark.parametrize("suffix", [".rnx", ".rnx.gz"])
def test_native_file_open_error_is_recoverable(tmp_path, entry, suffix):
    # Check in a child process: panic=abort must not terminate the pytest process.
    code = """
import sys
from gnss_tec import _core
try:
    if sys.argv[1] == "_read_obs":
        _core._read_obs([sys.argv[2]], None, None, True)
    else:
        _core._satellite_positions([sys.argv[2]], [], [])
except OSError:
    pass
else:
    raise AssertionError("Expected a recoverable OSError")
"""
    result = subprocess.run(
        [sys.executable, "-c", code, entry, str(tmp_path / ("missing" + suffix))],
        capture_output=True,
        text=True,
        timeout=30,
        check=False,
    )
    assert result.returncode == 0, result.stderr


@pytest.mark.parametrize("version", [2, 3])
@pytest.mark.parametrize("compressed", [False, True])
def test_event_text_survives_crlf_and_unterminated_last_line(
    tmp_path, version, compressed
):
    original = tmp_path / "original.rnx"
    write_minimal_rinex(original, version)
    text = original.read_text().rstrip("\n").replace("\n", "\r\n")
    variant = tmp_path / ("variant.rnx.gz" if compressed else "variant.rnx")
    variant.write_bytes(gzip.compress(text.encode()) if compressed else text.encode())
    expected_header, expected = gt.read_rinex_obs(original, include_lli=True)
    actual_header, actual = gt.read_rinex_obs(variant, include_lli=True)
    assert actual_header.epoch_events == expected_header.epoch_events
    assert_frame_equal(
        actual.collect(engine="in-memory"),
        expected.collect(engine="in-memory"),
        check_exact=True,
    )
