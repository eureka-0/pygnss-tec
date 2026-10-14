"""Reader and TEC output options preserve observations and scientific decisions."""

import gzip
from dataclasses import replace
from datetime import datetime

import numpy as np
import polars as pl
import pytest
from polars.testing import assert_frame_equal
from synthetic_observations import bias_rows, physical_observations, write_minimal_rinex

import gnss_tec as gt
import gnss_tec.tec.tec_calculation as tc
from gnss_tec._core import _read_obs
from gnss_tec.tec.constants import DIAGNOSTIC_COLUMNS, INTERNAL_COLUMNS
from gnss_tec.tec.preparation import _prepare_observations


@pytest.mark.parametrize("version", [2, 3])
@pytest.mark.parametrize("pivot", [False, True])
@pytest.mark.parametrize("compressed", [False, True])
@pytest.mark.parametrize("utc", [False, True])
@pytest.mark.parametrize("codes", [None, "[CL]1.*", []])
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
    native_codes = [codes] if isinstance(codes, str) else codes
    native_default_h, native_default = _read_obs([str(path)], "G", native_codes, pivot)
    for flag in (False, True):
        native_h, batch = _read_obs([str(path)], "G", native_codes, pivot, flag)
        assert native_h == native_default_h
        names = [n for n in batch.schema.names if n == "lli" or n.endswith("_lli")]
        assert bool(names) == (flag and (not pivot or codes != []))
        assert batch.num_rows == native_default.num_rows
        assert_frame_equal(
            pl.DataFrame(batch).drop(names).fill_nan(None),
            pl.DataFrame(native_default).fill_nan(None),
            check_exact=True,
        )


@pytest.mark.parametrize("pivot", [False, True])
@pytest.mark.parametrize("include_lli", [False, True])
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


@pytest.mark.parametrize("fixture", ["rinex_obs_v2", "rinex_obs_v3_hatanaka"])
@pytest.mark.parametrize("pivot", [False, True])
def test_real_compressed_lli_toggle_preserves_values(request, fixture, pivot):
    path = request.getfixturevalue(fixture)
    h, enabled = gt.read_rinex_obs(path, codes="[CL]1.*", pivot=pivot, include_lli=True)
    other_h, disabled = gt.read_rinex_obs(path, codes="[CL]1.*", pivot=pivot)
    assert h == other_h
    lli = [
        n for n in enabled.collect_schema().names() if n == "lli" or n.endswith("_lli")
    ]
    assert_frame_equal(
        enabled.drop(lli).collect(engine="in-memory"),
        disabled.collect(engine="in-memory"),
        check_exact=True,
    )


@pytest.mark.parametrize(
    "retained",
    [None, [], ["mw"], ("mw",), ["qc_valid", "L1_lli", "calibration_status"], "all"],
)
@pytest.mark.parametrize("empty", [False, True])
def test_tec_projection_preserves_rows_values_and_parquet_contract(
    tmp_path, retained, empty
):
    h, obs = physical_observations(np.full(8, 30.0))
    obs = obs.with_columns(
        pl.Series("L1C_lli", [0, 1, 2, 0, 0, 0, 0, 0], dtype=pl.UInt8)
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
    "retained", [None, ["mw", "tx_bias", "calibration_status"], ("mw",), "all"]
)
@pytest.mark.parametrize("case", ["matched", "missing", "empty"])
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


@pytest.mark.parametrize(
    "retained",
    [
        "mw",
        ["unknown"],
        ["sat_x"],
        ["level_id"],
        ["offset"],
        ["weight"],
        ["tx_bias_start"],
        ["tx_bias_end"],
        ["rx_bias_start"],
        ["rx_bias_end"],
        [1],
        {},
    ],
)
def test_unsupported_diagnostic_requests_are_rejected(retained):
    with pytest.raises(ValueError, match="retain_diagnostics|Unsupported diagnostic"):
        gt.TECConfig(retain_diagnostics=retained)


@pytest.mark.parametrize("kwargs", [{"retain_intermediate": "all"}])
def test_old_configuration_keyword_is_removed(kwargs):
    with pytest.raises(TypeError, match="retain_intermediate"):
        gt.TECConfig(**kwargs)
