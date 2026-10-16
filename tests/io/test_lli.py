"""Optional LLI columns in native and public readers."""

import gzip

import numpy as np
import polars as pl
import pytest
from polars.testing import assert_frame_equal

import gnss_tec as gt
from gnss_tec._core import _read_obs
from tests.support.observations import physical_observations, write_minimal_rinex


@pytest.mark.parametrize(
    "version,pivot,compressed,utc,codes",
    [
        (2, True, False, True, None),
        (2, False, True, False, "[CL]1.*"),
        (3, True, True, False, None),
        (3, False, False, True, "[CL]1.*"),
    ],
)
def test_lli_switch_preserves_native_and_public_observations(
    tmp_path, version, pivot, compressed, utc, codes
):
    path = tmp_path / "quality.rnx"
    write_minimal_rinex(path, version)
    # Preserve a missing indicator as null rather than synthesizing recorded zero.
    _, obs = physical_observations(np.full(4, 30.0), cadence=0.1)
    value = f"{float(obs['L1C'].item(3)):14.3f}"
    prefix, suffix = path.read_text().rsplit(value + "07", 1)
    path.write_text(prefix + value + " 7" + suffix)
    if compressed:
        text = path.read_bytes()
        path = path.with_suffix(".rnx.gz")
        path.write_bytes(gzip.compress(text))
    h_default, default = gt.read_rinex_obs(
        path, constellations="G", codes=codes, pivot=pivot, utc=utc
    )
    h_false, disabled = gt.read_rinex_obs(
        path, constellations="G", codes=codes, pivot=pivot, utc=utc, include_lli=False
    )
    h_true, enabled = gt.read_rinex_obs(
        path, constellations="G", codes=codes, pivot=pivot, utc=utc, include_lli=True
    )
    assert h_default == h_false == h_true
    default, disabled, enabled = [
        frame.collect(engine="in-memory") for frame in (default, disabled, enabled)
    ]
    lli_columns = [n for n in enabled.columns if n == "lli" or n.endswith("_lli")]
    assert not any(n == "lli" or n.endswith("_lli") for n in default.columns)
    assert_frame_equal(default, disabled, check_exact=True)
    assert_frame_equal(default, enabled.drop(lli_columns), check_exact=True)
    assert all(enabled.schema[n] == pl.UInt8 for n in lli_columns)
    if codes != []:
        phase = "L1" if version == 2 else "L1C"
        indicators = (
            enabled[phase + "_lli"]
            if pivot
            else enabled.filter(pl.col("code") == phase)["lli"]
        )
        assert indicators.to_list() == [0, 2, 1, None]
        assert enabled["epoch_flag"].unique().sort().to_list() == [0, 1]
    else:
        assert enabled.is_empty()


def test_native_lli_default_omits_columns(tmp_path):
    pivot = True
    path = tmp_path / "quality.rnx"
    write_minimal_rinex(path, 3)
    header, default = _read_obs([str(path)], "G", None, pivot)
    for flag in (False, True):
        actual_header, batch = _read_obs([str(path)], "G", None, pivot, flag)
        assert actual_header == header
        names = [n for n in batch.schema.names if n == "lli" or n.endswith("_lli")]
        assert bool(names) == flag
        assert_frame_equal(
            pl.DataFrame(batch).drop(names), pl.DataFrame(default), check_exact=True
        )


@pytest.mark.parametrize("pivot,include_lli", [(False, True), (True, False)])
def test_multifile_lli_option_handles_empty_parts_and_station_override(
    tmp_path, pivot, include_lli
):
    paths = [tmp_path / "a.rnx", tmp_path / "b.rnx"]
    for path in paths:
        write_minimal_rinex(path, 3, flagged=False)
    paths[1].write_text(paths[1].read_text().replace("2024 01 10", "2024 01 11"))
    for codes in (["C1C", "L1C"], []):
        h, frame = gt.read_rinex_obs(
            paths[::-1],
            codes=codes,
            pivot=pivot,
            include_lli=include_lli,
            station="OVRD",
        )
        result = frame.collect(engine="in-memory")
        assert h.marker_name == "OVRD"
        assert len(h.receiver_history) == 2
        assert result.height == (0 if not codes else 8 if pivot else 16)
        if codes:
            assert result["station"].unique().to_list() == ["OVRD"]
            assert result["time"].dt.date().n_unique() == 2
        names = [n for n in result.columns if n == "lli" or n.endswith("_lli")]
        assert bool(names) == (include_lli and (not pivot or bool(codes)))
