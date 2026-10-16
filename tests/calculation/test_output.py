"""Reader and TEC output options preserve observations and scientific decisions."""

from dataclasses import replace
from datetime import datetime

import numpy as np
import polars as pl
import pytest
from polars.testing import assert_frame_equal

import gnss_tec as gt
import gnss_tec.calculation.tec as tc
from gnss_tec.calculation.observation_geometry import _prepare_observations
from gnss_tec.calculation.tec import INTERNAL_COLUMNS
from gnss_tec.configuration import DIAGNOSTIC_COLUMNS
from tests.support.observations import (
    bias_rows,
    physical_observations,
    write_minimal_rinex,
)


@pytest.mark.parametrize(
    "retained,empty",
    [
        (None, False),
        (("mw",), False),
        (["qc_valid", "L1_lli", "calibration_status"], False),
        ("all", False),
        (None, True),
        ("all", True),
    ],
)
def test_tec_projection_preserves_rows_values_and_parquet_contract(
    tmp_path, retained, empty
):
    h, obs = physical_observations(np.full(8, 30.0))
    obs = obs.with_columns(
        pl.Series("L1C_lli", [0, 1, 2, 0, 0, 0, 0, 0], dtype=pl.UInt8),
        pl.lit(0, dtype=pl.UInt32).alias("receiver_state"),
        pl.lit("serial").alias("receiver_id"),
        pl.lit("[]").alias("epoch_events"),
        pl.lit(1.0).alias("sat_x"),
        pl.lit(True).alias("half_cycle_valid"),
        pl.lit(1).alias("_private_helper"),
    )
    if empty:
        obs = obs.head(0)
    full = gt.calc_tec_from_df(
        obs, h, config=gt.TECConfig(rx_bias=None, retain_diagnostics="all")
    ).collect(engine="in-memory")
    config = gt.TECConfig(rx_bias=None, retain_diagnostics=retained)
    result = gt.calc_tec_from_df(obs, h, config=config).collect(engine="in-memory")
    assert {"azimuth", "elevation"}.issubset(result.columns)
    assert INTERNAL_COLUMNS.isdisjoint(result.columns)
    assert not any(name.startswith("_") for name in result.columns)
    assert {
        "receiver_state",
        "receiver_id",
        "epoch_events",
        "sat_x",
        "half_cycle_valid",
    }.isdisjoint(result.columns)
    expected_diagnostics = (
        DIAGNOSTIC_COLUMNS.intersection(full.columns)
        if retained == "all"
        else set(retained or ())
    )
    assert DIAGNOSTIC_COLUMNS.intersection(result.columns) == expected_diagnostics
    expected = full if retained == "all" else full.filter(pl.col("qc_valid"))
    assert_frame_equal(result, expected.select(result.columns), check_exact=True)
    path = tmp_path / "observations.parquet"
    obs.write_parquet(path, metadata=h.to_metadata())
    from_parquet = gt.calc_tec_from_parquet(path, config=config).collect(
        engine="in-memory"
    )
    assert_frame_equal(result, from_parquet, check_exact=True)
    if not empty:
        assert result.height == (8 if retained == "all" else 7)
        assert full["vtec"].item(2) is None
        assert "half_cycle_invalid" in full["qc_reason"].item(2)


def test_rinex_tec_explicitly_requests_lli_even_when_output_hides_it(
    tmp_path, monkeypatch
):
    path = tmp_path / "quality.rnx"
    write_minimal_rinex(path, 3)
    calls = []
    read = tc.read_rinex_obs

    def reader(*args, **kwargs):
        calls.append(kwargs.get("include_lli"))
        h, lf = read(*args, **kwargs)
        return h, lf.with_columns(
            pl.lit(90.0).alias("azimuth"), pl.lit(60.0).alias("elevation")
        )

    monkeypatch.setattr(tc, "read_rinex_obs", reader)
    # Only geometry is supplied by this fixture; exercise real reading and QC.
    monkeypatch.setattr(
        tc,
        "_prepare_observations",
        lambda lf, h, utc, nav: _prepare_observations(lf, h, utc, None),
    )
    full = gt.calc_tec_from_rinex(
        path, "unused", config=gt.TECConfig(rx_bias=None, retain_diagnostics="all")
    ).collect(engine="in-memory")
    normal = gt.calc_tec_from_rinex(
        path, "unused", config=gt.TECConfig(rx_bias=None)
    ).collect(engine="in-memory")
    assert calls == [True, True]
    assert full["L1_lli"].to_list() == [0, 2, 1, 0]
    assert not full["qc_valid"].item(1)
    assert "half_cycle_invalid" in full["qc_reason"].item(1)
    assert "loss_of_lock" in full["qc_reason"].item(2)
    assert_frame_equal(
        normal, full.filter(pl.col("qc_valid")).select(normal.columns), check_exact=True
    )
    assert DIAGNOSTIC_COLUMNS.isdisjoint(normal.columns)
    h, missing = read(path)
    # Without recorded LLI, DataFrame/Parquet inputs keep the existing policy.
    h = replace(h, epoch_events=())
    missing = missing.with_columns(
        pl.lit(90.0).alias("azimuth"), pl.lit(60.0).alias("elevation")
    )
    no_lli = gt.calc_tec_from_df(missing, h, config=gt.TECConfig(rx_bias=None)).collect(
        engine="in-memory"
    )
    assert no_lli.height == 4


@pytest.mark.parametrize(
    "retained,case",
    [
        (None, "matched"),
        (["mw", "tx_bias", "calibration_status"], "matched"),
        ("all", "missing"),
        (None, "missing"),
        ("all", "empty"),
    ],
)
def test_bias_projection_preserves_calibration_and_empty_schema(
    monkeypatch, retained, case
):
    h, obs = physical_observations(np.full(8, 30.0))
    product = bias_rows([datetime(2024, 1, 10)], [datetime(2024, 1, 11)], [0.0])
    if case == "missing":
        product = product.with_columns(pl.lit("G02").cast(pl.Categorical).alias("prn"))
    elif case == "empty":
        obs = obs.head(0)
    monkeypatch.setattr(tc, "read_bias", lambda _: product.lazy())
    full = gt.calc_tec_from_df(
        obs, h, "unused", gt.TECConfig(rx_bias=None, retain_diagnostics="all")
    ).collect(engine="in-memory")
    result = gt.calc_tec_from_df(
        obs, h, "unused", gt.TECConfig(rx_bias=None, retain_diagnostics=retained)
    ).collect(engine="in-memory")
    expected = full if retained == "all" else full.filter(pl.col("qc_valid"))
    assert_frame_equal(result, expected.select(result.columns), check_exact=True)
    assert {"azimuth", "elevation", "stec_dcb_corrected"}.issubset(result.columns)
    assert INTERNAL_COLUMNS.isdisjoint(result.columns)
    if case == "missing":
        assert full["stec_dcb_corrected"].null_count() == 8
        assert full["qc_reason"].str.contains("missing_required_bias").all()
    elif case == "matched":
        np.testing.assert_allclose(
            result["stec_dcb_corrected"], 30.0, rtol=0, atol=1e-6
        )


@pytest.mark.parametrize("retained", ["mw", ["weight"], [1], {}])
def test_unsupported_diagnostic_requests_are_rejected(retained):
    with pytest.raises(ValueError, match="retain_diagnostics|Unsupported diagnostic"):
        gt.TECConfig(retain_diagnostics=retained)
