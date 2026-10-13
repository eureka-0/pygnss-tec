"""Compare the native segmentation pass with an independent expression model."""

import polars as pl
import pytest
from polars.testing import assert_frame_equal

from gnss_tec._core import _basic_arcs
from gnss_tec.tec._arrow import record_batch
from gnss_tec.tec.quality import _arc_expressions, add_basic_arcs


@pytest.mark.parametrize("cadence", [None, 30.0])
def test_native_arcs_preserve_grouped_quality_evidence(cadence):
    samples = []
    for station in ["A", "B", None]:
        for prn in ["G01", "G02"]:
            for index in range(10):
                samples.append(
                    {
                        "time": (index * 30 + (60 if index >= 7 else 0)) * 10**9,
                        "station": station,
                        "prn": prn,
                        "C1_code": None if index == 6 else "C1C",
                        "C2_code": "C2W" if index < 8 else "C5X",
                        "_receiver_state": "old" if index < 9 else None,
                        "_numeric_valid": index != 6,
                        "L1_lli": {1: 1, 2: 2, 3: None, 5: 3}.get(index, 0),
                        "L2_lli": 1 if index == 4 else None,
                        "epoch_flag": 1 if index == 5 else 0,
                    }
                )
    frame = (
        pl.DataFrame(samples)
        .with_columns(pl.col("L1_lli", "L2_lli").cast(pl.UInt8))
        .sort("time", "station", "prn")
    )
    expected = (
        _arc_expressions(frame.lazy(), cadence).select("arc_id", "qc_reason").collect()
    )
    actual = (
        add_basic_arcs(frame.lazy(), cadence).select("arc_id", "qc_reason").collect()
    )
    assert_frame_equal(actual, expected, check_exact=True)
    assert "reacquisition_after_rejection" in actual["qc_reason"].item(18)


@pytest.mark.parametrize("cadence", [0.0, -1.0, float("nan"), float("inf")])
def test_native_arcs_reject_invalid_cadence(cadence):
    frame = pl.DataFrame(
        schema={
            "time": pl.Int64,
            "station": pl.String,
            "prn": pl.String,
            "C1_code": pl.String,
            "C2_code": pl.String,
            "_receiver_state": pl.String,
            "_numeric_valid": pl.Boolean,
            "L1_lli": pl.UInt8,
            "L2_lli": pl.UInt8,
            "epoch_flag": pl.Int64,
        }
    )
    with pytest.raises(ValueError, match="Cadence"):
        _basic_arcs(record_batch(frame), cadence)
