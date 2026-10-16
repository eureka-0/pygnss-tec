"""Native entry points preserve recoverable file errors and event text."""

import gzip
import subprocess
import sys

import pytest
from polars.testing import assert_frame_equal

import gnss_tec as gt
from tests.support.observations import write_minimal_rinex


def test_native_file_open_error_is_recoverable(tmp_path):
    # Check in a child process: panic=abort must not terminate the pytest process.
    code = """
import sys
from gnss_tec import _core
for suffix in (".rnx", ".rnx.gz"):
    path = sys.argv[1] + suffix
    for entry in ("_read_obs", "_satellite_positions"):
        try:
            if entry == "_read_obs":
                _core._read_obs([path], None, None, True)
            else:
                _core._satellite_positions([path], [], [])
        except OSError:
            pass
        else:
            raise AssertionError((entry, path, "Expected a recoverable OSError"))
"""
    result = subprocess.run(
        [sys.executable, "-c", code, str(tmp_path / "missing")],
        capture_output=True,
        text=True,
        timeout=30,
        check=False,
    )
    assert result.returncode == 0, result.stderr


@pytest.mark.parametrize("version,compressed", [(2, False), (3, True)])
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
