import gzip

import numpy as np
import polars as pl
import pytest
from polars.testing import assert_frame_equal
from synthetic_observations import calculate, physical_observations, write_minimal_rinex

import gnss_tec as gt
from gnss_tec.calculation.observation_geometry import _prepare_observations
from gnss_tec.io.rinex import RinexObsHeader


@pytest.mark.parametrize("retain", [None, "all", ["azimuth", "qc_valid"]])
def test_tec_output_omits_internal_and_legacy_helpers(retain):
    header, frame = physical_observations(np.full(8, 30.0))
    frame = frame.with_columns(
        pl.lit(0, dtype=pl.UInt32).alias("receiver_state"),
        pl.lit("serial").alias("receiver_id"),
        pl.lit("[]").alias("epoch_events"),
        pl.lit(1.0).alias("sat_x"),
        pl.lit(True).alias("half_cycle_valid"),
        pl.lit(1).alias("_private_helper"),
    )
    result = gt.calc_tec_from_df(
        frame, header, config=gt.TECConfig(rx_bias=None, retain_diagnostics=retain)
    ).collect(engine="in-memory")
    assert result.height == 8
    assert not any(column.startswith("_") for column in result.columns)
    assert {
        "receiver_state",
        "receiver_id",
        "epoch_events",
        "sat_x",
        "half_cycle_valid",
    }.isdisjoint(result.columns)
    assert {"azimuth", "elevation"}.issubset(result.columns)


@pytest.mark.parametrize("version", [2, 3])
@pytest.mark.parametrize("pivot", [True, False])
def test_real_fractional_rinex_preserves_quality_events_and_metadata(
    tmp_path, version, pivot
):
    path = tmp_path / "quality.rnx"
    write_minimal_rinex(path, version)
    header, frame = gt.read_rinex_obs(
        path, codes=["L1" if version == 2 else "L1C"], pivot=pivot, include_lli=True
    )
    data = frame.collect(engine="in-memory")
    assert header.sampling_interval == 0.1
    assert data["time"].dtype == pl.Datetime("ns", "UTC")
    np.testing.assert_array_equal(
        np.diff(data["time"].dt.epoch("ns")), [100_000_000] * 3
    )
    lli = "L1_lli" if version == 2 else "L1C_lli"
    assert data[lli if pivot else "lli"].to_list() == [0, 2, 1, 0]
    assert data["epoch_flag"].to_list() == [0, 0, 0, 1]
    assert [e[1] for e in header.epoch_events] == [4, 1]
    assert "Receiver event preserved" in header.epoch_events[0][2]
    assert RinexObsHeader.from_metadata(header.to_metadata()) == header
    assert {"source_file", "receiver_id", "receiver_state", "epoch_events"}.isdisjoint(
        data.columns
    )


@pytest.mark.parametrize("changed_receiver", [False, True])
@pytest.mark.parametrize("pivot", [False, True])
def test_multifile_receiver_identity_is_preserved_in_header(
    tmp_path, changed_receiver, pivot
):
    paths = [tmp_path / "a.rnx", tmp_path / "b.rnx"]
    for index, path in enumerate(paths):
        write_minimal_rinex(path, 3, flagged=False)
        identity = "B" if index and changed_receiver else "A"
        receiver_line = (
            f"{identity:<20}{'TEST MODEL':<20}{'1.0':<20}REC # / TYPE / VERS\n"
        )
        text = path.read_text().replace(
            f"{'':60}END OF HEADER\n", receiver_line + f"{'':60}END OF HEADER\n"
        )
        if index:
            for epoch in range(4):
                text = text.replace(
                    f"> 2024 01 10 00 00 {epoch * 0.1:10.7f}",
                    f"> 2024 01 10 00 00 {(epoch + 4) * 0.1:10.7f}",
                )
        path.write_text(text)

    header, frame = gt.read_rinex_obs(paths[::-1], pivot=pivot, include_lli=True)
    data = frame.collect(engine="in-memory")
    assert {"source_file", "receiver_id", "_receiver_index"}.isdisjoint(data.columns)
    assert "receiver_state" not in data.columns
    assert len({entry[2] for entry in header.receiver_history}) == 1 + changed_receiver
    assert header.receiver_id == (None if changed_receiver else "A|TEST MODEL|1.0")
    assert RinexObsHeader.from_metadata(header.to_metadata()) == header
    if pivot:
        result = calculate(
            header,
            data.with_columns(
                pl.lit(90.0).alias("azimuth"), pl.lit(60.0).alias("elevation")
            ),
        )
        assert result["arc_id"].n_unique() == 1 + changed_receiver


def test_multifile_event_state_carries_forward(tmp_path):
    a, b = tmp_path / "a.rnx", tmp_path / "b.rnx"
    write_minimal_rinex(a, 3)
    write_minimal_rinex(b, 3, flagged=False)
    b.write_text(b.read_text().replace("2024 01 10", "2024 01 11"))
    header, frame = gt.read_rinex_obs([b, a], include_lli=True)
    assert header.epoch_events
    prepared = _prepare_observations(frame, header, pl.col("time"), None).collect(
        engine="in-memory"
    )
    assert prepared["_event_state"].fill_null(0).to_list() == [0, 0, 0, 1, 1, 1, 1, 1]
    assert {"receiver_state", "epoch_events"}.isdisjoint(frame.collect_schema())


def test_receiver_positions_survive_gps_parquet_roundtrip(tmp_path):
    paths = [tmp_path / "a.rnx", tmp_path / "b.rnx"]
    for path in paths:
        write_minimal_rinex(path, 3, flagged=False)
    text = paths[1].read_text().replace("2024 01 10", "2024 01 11")
    text = text.replace(
        f"{6378137.0:14.4f}{0.0:14.4f}{0.0:14.4f}",
        f"{0.0:14.4f}{6378137.0:14.4f}{0.0:14.4f}",
    )
    paths[1].write_text(text)
    header, raw = gt.read_rinex_obs(paths[::-1], utc=False, include_lli=True)
    observations = raw.with_columns(
        pl.lit(90.0).alias("azimuth"), pl.lit(60.0).alias("elevation")
    ).collect(engine="in-memory")
    path = tmp_path / "receiver-positions.parquet"
    observations.write_parquet(path, metadata=header.to_metadata())
    result = gt.calc_tec_from_parquet(
        path, config=gt.TECConfig(rx_bias=None, retain_diagnostics="all")
    ).collect(engine="in-memory")
    np.testing.assert_allclose(result["rx_lat"], np.zeros(8), rtol=0, atol=1e-12)
    np.testing.assert_allclose(
        result["rx_lon"], [0.0] * 4 + [90.0] * 4, rtol=0, atol=1e-12
    )
    assert not any(column.startswith("_") for column in result.columns)
    assert {"receiver_state", "epoch_events", "sat_x", "sat_y", "sat_z"}.isdisjoint(
        result.columns
    )


@pytest.mark.parametrize("version", [2, 3])
@pytest.mark.parametrize("flag", [2, 3, 5])
def test_all_special_epoch_events_are_preserved(tmp_path, version, flag):
    path = tmp_path / "events.rnx"
    write_minimal_rinex(path, version)
    text = path.read_text()
    text = text.replace("0.1500000  4", f"0.1500000  {flag}")
    path.write_text(text)
    header, frame = gt.read_rinex_obs(path, include_lli=True)
    assert [event[1] for event in header.epoch_events] == [flag, 1]
    assert "receiver_state" not in frame.collect_schema()


@pytest.mark.parametrize("version", [2, 3])
@pytest.mark.parametrize("pivot", [True, False])
def test_cycle_slip_epoch_flag_is_preserved(tmp_path, version, pivot):
    path = tmp_path / "slip.rnx"
    write_minimal_rinex(path, version)
    path.write_text(path.read_text().replace("0.3000000  1", "0.3000000  6"))
    header, frame = gt.read_rinex_obs(path, pivot=pivot, include_lli=True)
    assert [event[1] for event in header.epoch_events] == [4, 6]
    data = frame.collect(engine="in-memory")
    assert 6 not in data["epoch_flag"].to_list()
    assert data["time"].n_unique() == 3
    assert len(header.epoch_events[-1][2].splitlines()) == 2


def _event_record(version, flag, count, *, seconds=0.15, satellites=""):
    if version == 2:
        date = " " * 26 if seconds is None else f" 24  1 10  0  0{seconds:11.7f}"
        return f"{date}  {flag}{count:3d}{satellites}\n"
    date = " " * 29 if seconds is None else f"> 2024 01 10 00 00 {seconds:10.7f}"
    return f"{('>' + date[1:]) if seconds is None else date}  {flag}{count:3d}\n"


@pytest.mark.parametrize("version", [2, 3])
@pytest.mark.parametrize("pivot", [True, False])
@pytest.mark.parametrize("include_lli", [True, False])
def test_same_epoch_slip_counts_never_replace_observations(
    tmp_path, version, pivot, include_lli
):
    path = tmp_path / "same_epoch.rnx"
    write_minimal_rinex(path, version, flagged=False)
    lines = path.read_text().splitlines(keepends=True)
    end = next(i for i, line in enumerate(lines) if "END OF HEADER" in line) + 1
    phase = "L1" if version == 2 else "L1C"
    # The normal carrier measurement must survive a same-epoch slip count of 5.
    prefix = "G01" if version == 3 else ""
    normal = lines[end + 1]
    lines[end + 1] = (
        normal[: len(prefix) + 16]
        + f"{110355719.242:14.3f}07"
        + normal[len(prefix) + 32 :]
    )
    slip = prefix + f"{'':16}{5.0:14.3f}  {'':32}\n"
    event = (
        _event_record(
            version, 6, 1, seconds=0.0, satellites="G01" if version == 2 else ""
        )
        + slip
    )
    lines.insert(end + 2, event)
    path.write_text("".join(lines))
    header, lf = gt.read_rinex_obs(path, pivot=pivot, include_lli=include_lli)
    data = lf.collect(engine="in-memory")
    assert [event[1] for event in header.epoch_events] == [6]
    assert slip.strip() in header.epoch_events[0][2]
    assert 6 not in data["epoch_flag"].to_list()
    keys = ["time", "station", "prn"] + ([] if pivot else ["code"])
    assert data.unique(keys).height == data.height
    values = data[phase] if pivot else data.filter(pl.col("code") == phase)["value"]
    assert values.item(0) == 110355719.242
    assert values.len() == 4


@pytest.mark.parametrize("version", [2, 3])
@pytest.mark.parametrize("pivot", [True, False])
@pytest.mark.parametrize("compressed", [False, True])
def test_epoch_like_comment_records_are_not_parsed_as_epochs(
    tmp_path, version, pivot, compressed
):
    clean = tmp_path / "clean.rnx"
    write_minimal_rinex(clean, version, flagged=False)
    _, expected = gt.read_rinex_obs(clean, pivot=pivot, include_lli=True)
    lines = clean.read_text().splitlines(keepends=True)
    end = next(i for i, line in enumerate(lines) if "END OF HEADER" in line) + 1
    comment = f"{'> Receiver tracking resumed':<60}COMMENT\n"
    # Standalone comments before, between and after complete observation blocks
    # must not enter epoch parsing or event metadata.
    text = (
        "".join(lines[:end])
        + comment
        + "".join(lines[end : end + 2])
        + comment
        + "".join(lines[end + 2 :])
        + comment
    )
    path = tmp_path / ("comments.rnx.gz" if compressed else "comments.rnx")
    path.write_bytes(gzip.compress(text.encode()) if compressed else text.encode())
    header, actual = gt.read_rinex_obs(path, pivot=pivot, include_lli=True)
    assert_frame_equal(
        actual.collect(engine="in-memory"), expected.collect(engine="in-memory")
    )
    assert header.epoch_events == ()


@pytest.mark.parametrize("version", [2, 3])
@pytest.mark.parametrize("pivot", [True, False])
@pytest.mark.parametrize("compressed", [False, True])
def test_untimed_events_are_consumed_without_values_or_state(
    tmp_path, version, pivot, compressed
):
    clean = tmp_path / "clean.rnx"
    write_minimal_rinex(clean, version, flagged=False)
    _, expected = gt.read_rinex_obs(clean, pivot=pivot, include_lli=True)
    lines = clean.read_text().splitlines(keepends=True)
    end = next(i for i, line in enumerate(lines) if "END OF HEADER" in line) + 1
    comment = f"{'Retained before':<60}COMMENT\n"
    timed_before = _event_record(version, 4, 1, seconds=0.05) + comment
    # A skipped special payload may itself resemble complete observation records.
    skipped = _event_record(version, 5, 2, seconds=None) + "".join(lines[end : end + 2])
    skipped += _event_record(version, 2, 0, seconds=None)
    skipped += (
        _event_record(version, 3, 1, seconds=None)
        + f"{'Omitted site':<60}MARKER NAME\n"
    )
    skipped += (
        _event_record(version, 4, 1, seconds=None) + f"{'Skipped comment':<60}COMMENT\n"
    )
    skipped += (
        _event_record(
            version, 6, 1, seconds=None, satellites="G01" if version == 2 else ""
        )
        + lines[end + 1]
    )
    timed_after = _event_record(version, 5, 0, seconds=0.15)
    text = (
        "".join(lines[: end + 2])
        + timed_before
        + skipped
        + timed_after
        + "".join(lines[end + 2 :])
    )
    # Also exercise a zero-length skipped record at end-of-file.
    text += _event_record(version, 4, 0, seconds=None)
    path = tmp_path / ("events.rnx.gz" if compressed else "events.rnx")
    path.write_bytes(gzip.compress(text.encode()) if compressed else text.encode())
    header, actual = gt.read_rinex_obs(path, pivot=pivot, include_lli=True)
    assert_frame_equal(
        actual.collect(engine="in-memory"), expected.collect(engine="in-memory")
    )
    assert [event[1] for event in header.epoch_events] == [4, 5]
    assert header.epoch_events[0][2] == timed_before
    assert header.epoch_events[1][2] == timed_after
    assert RinexObsHeader.from_metadata(header.to_metadata()) == header


@pytest.mark.parametrize("version", [2, 3])
def test_malformed_nonblank_event_epoch_is_not_silently_skipped(tmp_path, version):
    path = tmp_path / "bad_event.rnx"
    write_minimal_rinex(path, version)
    path.write_text(
        path.read_text().replace("  1 10  0  0", " 13 10  0  0")
        if version == 2
        else path.read_text().replace(
            "2024 01 10 00 00  0.1500000", "2024 13 10 00 00  0.1500000"
        )
    )
    with pytest.raises(ValueError, match="epoch"):
        gt.read_rinex_obs(path)


@pytest.mark.parametrize("version", [2, 3])
@pytest.mark.parametrize("pivot", [True, False])
@pytest.mark.parametrize("gzip_wrapper", [True, False])
def test_compact_events_preserve_framing_and_skip_untimed_records(
    tmp_path, version, pivot, gzip_wrapper
):
    path = tmp_path / "reference.rnx"
    write_minimal_rinex(path, version, flagged=False)
    header, expected = gt.read_rinex_obs(path, pivot=pivot, include_lli=True)
    lines = path.read_text().splitlines(keepends=True)
    end = next(i for i, line in enumerate(lines) if "END OF HEADER" in line) + 1
    compact = (
        f"{1 if version == 2 else 3}.0                 COMPACT RINEX FORMAT                    CRINEX VERS   / TYPE\n"
        "RNX2CRX ver.4.1.0                       15-Oct-26 00:00     CRINEX PROG / DATE\n"
        + "".join(lines[:end])
    )
    # Independent encoding checked against RNX2CRX 4.1.0: reset each numerical
    # kernel, store 10^-3 units and original two-character LLI/SSI per signal.
    numeric = "3&21000004871 3&110355719242 3&21000008023 3&85991456635 07070707\n"
    retained = []
    for i in range(4):
        epoch = lines[end + 2 * i].rstrip("\n")
        compact += (
            (("&" + epoch[1:]) if version == 2 else epoch + "      G01")
            + "\n\n"
            + numeric
        )
        if i == 0:
            # Untimed flag-4 special records are forwarded verbatim by CRINEX.
            event = _event_record(version, 4, 1, seconds=None)
            compact += (
                ("&" + event[1:]) if version == 2 else event
            ) + f"{'Skipped metadata':<60}COMMENT\n"
        if i == 1:
            event = _event_record(version, 5, 1, seconds=0.15)
            comment = f"{'Retained external event':<60}COMMENT\n"
            compact += (("&" + event[1:]) if version == 2 else event) + comment
            retained.append(event + comment)
        if i == 2:
            # An untimed cycle-slip block uses satellite/observation framing.
            event = _event_record(
                version, 6, 1, seconds=None, satellites="G01" if version == 2 else ""
            )
            compact += (
                (
                    ("&" + event[1:]).rstrip("\n")
                    if version == 2
                    else event.rstrip("\n") + "      G01"
                )
                + "\n\n"
                + numeric
            )
    compact += "\n"
    target = tmp_path / ("events.crx.gz" if gzip_wrapper else "events.crx")
    target.write_bytes(
        gzip.compress(compact.encode()) if gzip_wrapper else compact.encode()
    )
    actual_header, actual = gt.read_rinex_obs(target, pivot=pivot, include_lli=True)
    assert_frame_equal(
        actual.collect(engine="in-memory"), expected.collect(engine="in-memory")
    )
    assert [event[1] for event in actual_header.epoch_events] == [5]
    assert [event[2] for event in actual_header.epoch_events] == retained
    assert actual_header.sampling_interval == header.sampling_interval


@pytest.mark.parametrize("version", [2, 3])
def test_multifile_untimed_events_do_not_change_ambiguity_state(tmp_path, version):
    paths = [tmp_path / "a.rnx", tmp_path / "b.rnx"]
    for i, path in enumerate(paths):
        write_minimal_rinex(path, version, flagged=False)
        text = path.read_text()
        if i:
            text = (
                text.replace("24  1 10", "24  1 11")
                if version == 2
                else text.replace("2024 01 10", "2024 01 11")
            )
        path.write_text(
            text
            + _event_record(version, 4, 1, seconds=None)
            + f"{'Omitted event':<60}COMMENT\n"
        )
    header, lf = gt.read_rinex_obs(paths[::-1], include_lli=True)
    assert header.epoch_events == ()
    assert lf.collect(engine="in-memory")["time"].n_unique() == 8
    prepared = _prepare_observations(lf, header, pl.col("time"), None).collect(
        engine="in-memory"
    )
    assert prepared["_event_state"].to_list() == [0] * 8
    assert RinexObsHeader.from_metadata(header.to_metadata()) == header


@pytest.mark.parametrize("timed", [True, False])
def test_rinex2_slip_blocks_consume_satellite_and_observation_continuations(
    tmp_path, timed
):
    path = tmp_path / "continued.rnx"
    write_minimal_rinex(path, 2, flagged=False)
    lines = path.read_text().splitlines(keepends=True)
    end = next(i for i, line in enumerate(lines) if "END OF HEADER" in line) + 1
    code_header = next(
        i for i, line in enumerate(lines) if "# / TYPES OF OBSERV" in line
    )
    lines[code_header] = (
        f"{6:6d}{'C1':>6}{'L1':>6}{'C2':>6}{'L2':>6}{'C5':>6}{'L5':>6}{'':18}# / TYPES OF OBSERV\n"
    )
    body = []
    for i in range(4):
        body.extend(
            [
                lines[end + 2 * i],
                lines[end + 2 * i + 1].rstrip("\n") + f"{1.0:14.3f}07\n",
                f"{2.0:14.3f}07\n",
            ]
        )
    clean = "".join(lines[:end] + body)
    path.write_text(clean)
    _, expected = gt.read_rinex_obs(path, include_lli=True)
    satellite_ids = "".join(f"G{i:02d}" for i in range(1, 14))
    slip = _event_record(
        2, 6, 13, seconds=0.05 if timed else None, satellites=satellite_ids[:36]
    )
    slip += " " * 32 + satellite_ids[36:] + "\n"
    slip += (f"{5.0:14.3f}  " * 5 + "\n" + f"{5.0:14.3f}  \n") * 13
    path.write_text("".join(lines[:end] + body[:3]) + slip + "".join(body[3:]))
    header, actual = gt.read_rinex_obs(path, include_lli=True)
    assert_frame_equal(
        actual.collect(engine="in-memory"), expected.collect(engine="in-memory")
    )
    assert len(header.epoch_events) == int(timed)
    if timed:
        assert header.epoch_events[0][2] == slip
