"""Observation code filters preserve raw wide/long values and quality flags."""

import pytest
from polars.testing import assert_frame_equal

import gnss_tec as gt
from tests.support.observations import write_minimal_rinex


@pytest.mark.parametrize(
    "version,pivot,patterns", [(2, True, "[CL]1.*"), (3, False, ["C1.*", "L1.*"])]
)
def test_observation_regex_matches_literal_selection(
    tmp_path, version, pivot, patterns
):
    path = tmp_path / "codes.rnx"
    write_minimal_rinex(path, version)
    codes = ["C1", "L1"] if version == 2 else ["C1C", "L1C"]
    actual = gt.read_rinex_obs(path, codes=patterns, pivot=pivot, include_lli=True)[
        1
    ].collect(engine="in-memory")
    expected = gt.read_rinex_obs(path, codes=codes, pivot=pivot, include_lli=True)[
        1
    ].collect(engine="in-memory")
    assert_frame_equal(actual, expected)
    assert actual.height == (4 if pivot else 8)
    expected_columns = (
        {
            "time",
            "station",
            "prn",
            *codes,
            *(code + "_lli" for code in codes),
            "epoch_flag",
        }
        if pivot
        else {"time", "station", "prn", "code", "value", "lli", "epoch_flag"}
    )
    assert set(actual.columns) == expected_columns


@pytest.mark.parametrize("pivot,patterns", [(True, []), (False, "L1")])
def test_empty_or_unmatched_code_patterns_return_empty_frame(tmp_path, pivot, patterns):
    path = tmp_path / "codes.rnx"
    write_minimal_rinex(path, 3)
    assert (
        gt.read_rinex_obs(path, codes=patterns, pivot=pivot, include_lli=True)[1]
        .collect(engine="in-memory")
        .is_empty()
    )


def test_invalid_observation_regex_has_clear_error(tmp_path):
    path = tmp_path / "codes.rnx"
    write_minimal_rinex(path, 3)
    with pytest.raises(ValueError, match="Invalid observation code pattern"):
        gt.read_rinex_obs(path, codes="[", include_lli=True)


def test_tec_requires_wide_observations(tmp_path):
    path = tmp_path / "codes.rnx"
    write_minimal_rinex(path, 3)
    header, frame = gt.read_rinex_obs(path, pivot=False, include_lli=True)
    with pytest.raises(ValueError, match="pivot=True"):
        gt.compute_tec(frame, header)


def test_code_pattern_generator_is_reused_across_files(tmp_path):
    paths = [tmp_path / "a.rnx", tmp_path / "b.rnx"]
    for path in paths:
        write_minimal_rinex(path, 3)
    paths[1].write_text(paths[1].read_text().replace("2024 01 10", "2024 01 11"))
    patterns = (pattern for pattern in ["C1.*", "L1.*"])
    result = gt.read_rinex_obs(paths, codes=patterns, include_lli=True)[1].collect(
        engine="in-memory"
    )
    assert result.height == 8
    assert result["time"].dt.date().n_unique() == 2
