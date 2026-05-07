import gzip
from datetime import datetime

import polars as pl
import pytest
from helpers import assert_has_columns

import gnss_tec as gt


@pytest.mark.parametrize(
    ("fixture_name", "expected_rows", "expected_end"),
    [
        ("bias", 6082, datetime(2024, 1, 11)),
        ("bias_gfz", 3730, datetime(2024, 1, 10, 23, 59, 59)),
    ],
)
def test_read_bias_schema_and_dates(request, fixture_name, expected_rows, expected_end):
    df = gt.read_bias(request.getfixturevalue(fixture_name)).collect()
    assert isinstance(df, pl.DataFrame)

    assert df.shape == (expected_rows, 9)
    assert_has_columns(
        df,
        [
            "prn",
            "station",
            "obs1",
            "obs2",
            "bias_start",
            "bias_end",
            "unit",
            "estimated_value",
            "std_dev",
        ],
    )
    assert df.schema["prn"] == pl.Categorical
    assert df.schema["station"] == pl.Categorical
    assert df.schema["estimated_value"] == pl.Float64
    assert df.get_column("bias_start").min() == datetime(2024, 1, 10)
    assert df.get_column("bias_end").max() == expected_end
    assert df.get_column("unit").cast(pl.String).unique().to_list() == ["ns"]
    assert df.get_column("station").null_count() > 0
    assert df.get_column("station").null_count() < df.height


def test_read_bias_accepts_multiple_files(bias, bias_gfz):
    cas = gt.read_bias(bias).collect()
    gfz = gt.read_bias(bias_gfz).collect()
    combined = gt.read_bias([bias, bias_gfz]).collect()
    assert isinstance(cas, pl.DataFrame)
    assert isinstance(gfz, pl.DataFrame)
    assert isinstance(combined, pl.DataFrame)

    assert combined.height == cas.height + gfz.height
    assert combined.width == cas.width


def test_read_bias_reads_utf8_gzip_header(tmp_path):
    bias_file = tmp_path / "utf8_header.BIA.gz"
    bias_file.write_bytes(
        gzip.compress(
            "\n".join(
                [
                    "%=BIA 1.00 GFZ 2024:011:61866 IGS 2024:010:00000 2024:010:86399 R 00000001",
                    "* Operational Multi ‐ GNSS Global Ionosphere Maps",
                    "+BIAS/SOLUTION",
                    "*BIAS SVN_ PRN STATION__ OBS1 OBS2 BIAS_START____ BIAS_END______ UNIT __ESTIMATED_VALUE____ _STD_DEV___",
                    " DSB       G01           C1C  C2W  2024:010:00000 2024:010:86399 ns   1.000000000000000E+00 1.000000E-01",
                    "-BIAS/SOLUTION",
                ]
            ).encode()
        )
    )

    df = gt.read_bias(bias_file).collect()
    assert isinstance(df, pl.DataFrame)

    assert df.height == 1
    assert df.get_column("bias_end").item() == datetime(2024, 1, 10, 23, 59, 59)


def test_read_bias_rejects_bad_inputs(tmp_path):
    with pytest.raises(FileNotFoundError, match="Bias file not found"):
        gt.read_bias(tmp_path / "missing.BIA")

    empty = tmp_path / "empty.BIA"
    empty.write_text("")
    with pytest.raises(ValueError, match="empty"):
        gt.read_bias(empty).collect()

    malformed = tmp_path / "malformed.BIA"
    malformed.write_text("not a bias file\n")
    with pytest.raises(ValueError, match=r"\+BIAS/SOLUTION"):
        gt.read_bias(malformed).collect()
