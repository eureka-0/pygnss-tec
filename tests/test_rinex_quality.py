import numpy as np
import polars as pl
import pytest
from synthetic_observations import calculate, physical_observations, write_minimal_rinex

import gnss_tec as gt
from gnss_tec.rinex import RinexObsHeader
from gnss_tec.tec.preparation import _prepare_observations


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
    assert prepared["_event_state"].fill_null(0).to_list() == [0, 0, 1, 2, 2, 2, 2, 2]
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
    assert 6 in frame.collect(engine="in-memory")["epoch_flag"].to_list()
