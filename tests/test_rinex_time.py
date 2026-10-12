import numpy as np
import polars as pl
import pytest
from synthetic_observations import calculate, write_minimal_rinex

import gnss_tec as gt


@pytest.mark.parametrize("version", [2, 3])
def test_fractional_rinex_completes_tec(tmp_path, version):
    path = tmp_path / "fractional.rnx"
    write_minimal_rinex(path, version, flagged=False)
    header, obs = gt.read_rinex_obs(path)
    result = calculate(
        header,
        obs.with_columns(
            pl.lit(60.0).alias("elevation"), pl.lit(90.0).alias("azimuth")
        ),
    )
    assert result["qc_valid"].all()
    assert result.height == 4
    assert result["stec"].is_finite().all()


def test_nanosecond_epochs_survive_time_conversion_and_parquet(tmp_path):
    path = tmp_path / "precise.rnx"
    write_minimal_rinex(path, 3, flagged=False)
    text = path.read_text()
    for i in range(1, 4):
        text = text.replace(f"{i / 10:.7f}", f"{i / 1e7:.7f}")
    path.write_text(text)
    header, utc = gt.read_rinex_obs(path)
    _, gps = gt.read_rinex_obs(path, utc=False)
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
        gt.read_rinex_obs(path)
