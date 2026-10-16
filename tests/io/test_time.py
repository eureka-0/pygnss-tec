import numpy as np
import polars as pl
import pytest

import gnss_tec as gt
from tests.support.observations import write_minimal_rinex


def test_nanosecond_epochs_survive_time_conversion_and_parquet(tmp_path):
    path = tmp_path / "precise.rnx"
    write_minimal_rinex(path, 3, flagged=False)
    text = path.read_text()
    for i in range(1, 4):
        text = text.replace(f"{i / 10:.7f}", f"{i / 1e7:.7f}")
    path.write_text(text)
    header, utc = gt.read_rinex_obs(path, include_lli=True)
    _, gps = gt.read_rinex_obs(path, utc=False, include_lli=True)
    assert gps.collect_schema()["time"] == pl.Datetime("ns")
    utc_time = utc.select("time").head(1).collect(engine="in-memory").item()
    gps_time = gps.select("time").head(1).collect(engine="in-memory").item()
    assert (
        gps_time - utc_time.replace(tzinfo=None)
    ).total_seconds() == header.leap_seconds
    for frame in (utc, gps):
        np.testing.assert_array_equal(
            np.diff(frame.collect(engine="in-memory")["time"].dt.epoch("ns")), [100] * 3
        )
    parquet = tmp_path / "precise.parquet"
    utc.collect(engine="in-memory").write_parquet(
        parquet, metadata=header.to_metadata()
    )
    np.testing.assert_array_equal(
        pl.read_parquet(parquet)["time"].dt.epoch("ns"),
        utc.collect(engine="in-memory")["time"].dt.epoch("ns"),
    )


def test_finer_than_nanosecond_precision_is_rejected(tmp_path):
    path = tmp_path / "unsupported_precision.rnx"
    write_minimal_rinex(path, 3, flagged=False)
    path.write_text(path.read_text().replace("0.1000000", "0.0000000001"))
    with pytest.raises(ValueError, match="precision finer than nanoseconds"):
        gt.read_rinex_obs(path, include_lli=True)
