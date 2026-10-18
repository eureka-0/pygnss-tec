"""Unsupported effective-header changes must never relabel raw observations."""

import gzip

import pytest

import gnss_tec as gt
from tests.io.test_events import _event_record
from tests.support.observations import write_minimal_rinex


def _with_update(path, version, payload, *, timed=True, flag=4):
    write_minimal_rinex(path, version, flagged=False)
    lines = path.read_text().splitlines(keepends=True)
    start = next(i for i, line in enumerate(lines) if "END OF HEADER" in line) + 1
    # One complete observation epoch precedes the update; its code/phase fields
    # have independently known identities. No prefix may escape as a result.
    return (
        "".join(lines[: start + 2])
        + _event_record(version, flag, 1, seconds=0.05 if timed else None)
        + payload
        + "".join(lines[start + 2 :])
    )


@pytest.mark.parametrize(
    "version,pivot,lli",
    [(2, False, False), (2, True, True), (3, False, True), (3, True, False)],
)
def test_observation_reorder_is_rejected_before_return(tmp_path, version, pivot, lli):
    path = tmp_path / "reordered.rnx"
    label = "# / TYPES OF OBSERV" if version == 2 else "SYS / # / OBS TYPES"
    content = (
        "     4    C2    L2    C1    L1" if version == 2 else "G    4 C2W L2W C1C L1C"
    )
    path.write_text(_with_update(path, version, f"{content:<60}{label}\n"))
    with pytest.raises(ValueError, match="Unsupported RINEX header update") as error:
        gt.read_rinex_obs(path, pivot=pivot, include_lli=lli)
    assert str(path) in str(error.value)
    assert label in str(error.value)
    assert "2024-01-10" in str(error.value)
    with pytest.raises(ValueError, match="header update"):
        gt.compute_tec_from_rinex(path, tmp_path / "unused.nav")


@pytest.mark.parametrize(
    "label",
    [
        "APPROX POSITION XYZ",
        "MARKER NAME",
        "REC # / TYPE / VERS",
        "SYS / SCALE FACTOR",
        "SYS / PHASE SHIFT",
        "WAVELENGTH FACT L1/2",
        "TIME OF FIRST OBS",
        "LEAP SECONDS",
        "UNKNOWN UPDATE",
        "",
    ],
)
def test_significant_unknown_and_malformed_updates_fail(tmp_path, label):
    path = tmp_path / "changed.rnx"
    path.write_text(_with_update(path, 3, f"{'changed':<60}{label}\n"))
    with pytest.raises(ValueError, match="header update"):
        gt.read_rinex_obs(path)


@pytest.mark.parametrize("version,flag", [(2, 4), (3, 3), (3, 5)])
def test_untimed_and_multifile_updates_cannot_silently_reuse_header(
    tmp_path, version, flag
):
    clean = tmp_path / "a.rnx"
    write_minimal_rinex(clean, version, flagged=False)
    changed = tmp_path / "b.rnx"
    content = _with_update(
        changed,
        version,
        f"{'changed':<60}APPROX POSITION XYZ\n",
        timed=False,
        flag=flag,
    )
    compressed = tmp_path / "b.rnx.gz"
    compressed.write_bytes(gzip.compress(content.encode()))
    for paths in (compressed, [clean, compressed]):
        with pytest.raises(ValueError, match="untimed event") as error:
            gt.read_rinex_obs(paths)
        assert str(compressed) in str(error.value)


@pytest.mark.parametrize("version", [2, 3])
def test_compact_header_update_is_rejected_before_decoder_reuses_order(
    tmp_path, version
):
    path = tmp_path / "reference.rnx"
    write_minimal_rinex(path, version, flagged=False)
    lines = path.read_text().splitlines(keepends=True)
    end = next(i for i, line in enumerate(lines) if "END OF HEADER" in line) + 1
    compact = (
        f"{1 if version == 2 else 3}.0                 COMPACT RINEX FORMAT                    CRINEX VERS   / TYPE\n"
        "RNX2CRX ver.4.1.0                       15-Oct-26 00:00     CRINEX PROG / DATE\n"
        + "".join(lines[:end])
    )
    epoch = lines[end].rstrip("\n")
    compact += (("&" + epoch[1:]) if version == 2 else epoch + "      G01") + "\n\n"
    compact += "3&21000004871 3&110355719242 3&21000008023 3&85991456635 07070707\n"
    event = _event_record(version, 4, 1, seconds=0.05)
    label = "# / TYPES OF OBSERV" if version == 2 else "SYS / # / OBS TYPES"
    content = (
        "     4    C2    L2    C1    L1" if version == 2 else "G    4 C2W L2W C1C L1C"
    )
    compact += (
        ("&" + event[1:]) if version == 2 else event
    ) + f"{content:<60}{label}\n"
    target = tmp_path / "changed.crx.gz"
    target.write_bytes(gzip.compress(compact.encode()))
    with pytest.raises(ValueError, match="header update") as error:
        gt.read_rinex_obs(target, include_lli=True)
    assert label in str(error.value)
