"""Sparse signals must preserve values and LLI in both observation layouts."""

from datetime import UTC, datetime, timedelta

import polars as pl
from polars.testing import assert_frame_equal

import gnss_tec as gt
from tests.support.observations import write_minimal_rinex


def test_sparse_signals_preserve_layout_values_and_lli(tmp_path):
    path = tmp_path / "sparse.rnx"
    write_minimal_rinex(path, 3, flagged=False)
    header_text = path.read_text().split("END OF HEADER")[0] + "END OF HEADER\n"
    # Satellite order changes, C2W appears late, and missing LLI differs from zero.
    epochs = [
        [
            ("G02", [(22_000_000, 0), (115_000_000, 2), None, None]),
            ("G01", [(21_000_000, None), None, None, None]),
        ],
        [
            ("G01", [(21_000_001, 0), None, None, None]),
            ("G02", [None, (115_000_001, 0), (23_000_002, None), None]),
        ],
        [
            ("G02", [(22_000_002, None), None, None, None]),
            ("G01", [None, (110_000_002, 1), None, None]),
        ],
        [
            ("G01", [(21_000_003, 0), (110_000_003, 0), (23_000_003, None), None]),
            ("G02", [(22_000_003, None), None, None, None]),
        ],
    ]
    text = header_text
    for index, satellites in enumerate(epochs):
        text += f"> 2024 01 10 00 00 {index * 0.1:10.7f}  0  2\n"
        for prn, signals in satellites:
            fields = []
            for signal in signals:
                if signal is None:
                    fields.append(" " * 16)
                else:
                    value, lli = signal
                    fields.append(f"{value:14.3f}{' ' if lli is None else lli}7")
            text += prn + "".join(fields) + "\n"
    path.write_text(text)

    wide_header, wide = gt.read_rinex_obs(path, include_lli=True)
    long_header, long = gt.read_rinex_obs(path, pivot=False, include_lli=True)
    assert wide_header == long_header
    origin = datetime(2024, 1, 9, 23, 59, 42, tzinfo=UTC)
    expected = pl.DataFrame(
        {
            "time": [
                origin + timedelta(milliseconds=i * 100)
                for i in range(4)
                for _ in range(2)
            ],
            "prn": ["G01", "G02"] * 4,
            "C1C": [
                21_000_000,
                22_000_000,
                21_000_001,
                None,
                None,
                22_000_002,
                21_000_003,
                22_000_003,
            ],
            "L1C": [
                None,
                115_000_000,
                None,
                115_000_001,
                110_000_002,
                None,
                110_000_003,
                None,
            ],
            "C2W": [None, None, None, 23_000_002, None, None, 23_000_003, None],
            "C1C_lli": [None, 0, 0, None, None, None, 0, None],
            "L1C_lli": [None, 2, None, 0, 1, None, 0, None],
            "C2W_lli": [None] * 8,
            "epoch_flag": [0] * 8,
        },
        schema_overrides={
            "time": pl.Datetime("ns", "UTC"),
            "prn": pl.Categorical,
            "C1C": pl.Float64,
            "L1C": pl.Float64,
            "C2W": pl.Float64,
            "C1C_lli": pl.UInt8,
            "L1C_lli": pl.UInt8,
            "C2W_lli": pl.UInt8,
            "epoch_flag": pl.UInt8,
        },
    )
    selected = ["C1C", "L1C", "C2W"]
    long_rows = [
        {
            "time": row["time"],
            "prn": row["prn"],
            "code": code,
            "value": row[code],
            "lli": row[code + "_lli"],
            "epoch_flag": row["epoch_flag"],
        }
        for row in expected.to_dicts()
        for code in selected
        if row[code] is not None
    ]
    expected_long = pl.DataFrame(
        long_rows,
        schema_overrides={
            "time": expected.schema["time"],
            "prn": pl.Categorical,
            "value": pl.Float64,
            "lli": pl.UInt8,
            "epoch_flag": pl.UInt8,
        },
    ).sort("time", "prn", "code")
    columns = [
        "time",
        "prn",
        *sorted(selected),
        *sorted(code + "_lli" for code in selected),
        "epoch_flag",
    ]
    assert_frame_equal(
        wide.select(columns).collect(engine="in-memory"),
        expected.select(columns),
        check_exact=True,
    )
    assert_frame_equal(
        long.drop("station").collect(engine="in-memory"),
        expected_long,
        check_exact=True,
    )
