"""Observation code filters preserve raw wide/long values and quality flags."""

import pytest
from polars.testing import assert_frame_equal
from synthetic_observations import write_minimal_rinex

import gnss_tec as gt


@pytest.mark.parametrize(
    "version,pivot,patterns",
    [
        (2, True, "[CL]1.*"),
        (2, False, ["C1.*", "L1.*"]),
        (3, True, ["C1.*", "L1.*"]),
        (3, False, "[CL]1.*"),
    ],
)
def test_observation_regex_matches_literal_selection(
    tmp_path, version, pivot, patterns
):
    path = tmp_path / "codes.rnx"
    write_minimal_rinex(path, version)
    codes = ["C1", "L1"] if version == 2 else ["C1C", "L1C"]
    actual = gt.read_rinex_obs(path, codes=patterns, pivot=pivot)[1].collect(
        engine="in-memory"
    )
    expected = gt.read_rinex_obs(path, codes=codes, pivot=pivot)[1].collect(
        engine="in-memory"
    )
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


@pytest.mark.parametrize("pivot", [True, False])
@pytest.mark.parametrize("patterns", [[], "L1"])
def test_empty_or_unmatched_code_patterns_return_empty_frame(tmp_path, pivot, patterns):
    path = tmp_path / "codes.rnx"
    write_minimal_rinex(path, 3)
    assert (
        gt.read_rinex_obs(path, codes=patterns, pivot=pivot)[1]
        .collect(engine="in-memory")
        .is_empty()
    )


def test_invalid_observation_regex_has_clear_error(tmp_path):
    path = tmp_path / "codes.rnx"
    write_minimal_rinex(path, 3)
    with pytest.raises(ValueError, match="Invalid observation code pattern"):
        gt.read_rinex_obs(path, codes="[")


def test_tec_requires_wide_observations(tmp_path):
    path = tmp_path / "codes.rnx"
    write_minimal_rinex(path, 3)
    header, frame = gt.read_rinex_obs(path, pivot=False)
    with pytest.raises(ValueError, match="pivot=True"):
        gt.calc_tec_from_df(frame, header)


@pytest.mark.parametrize("pivot", [True, False])
def test_code_pattern_generator_is_reused_across_files(tmp_path, pivot):
    paths = [tmp_path / "a.rnx", tmp_path / "b.rnx"]
    for path in paths:
        write_minimal_rinex(path, 3)
    paths[1].write_text(paths[1].read_text().replace("2024 01 10", "2024 01 11"))
    patterns = (pattern for pattern in ["C1.*", "L1.*"])
    result = gt.read_rinex_obs(paths, codes=patterns, pivot=pivot)[1].collect(
        engine="in-memory"
    )
    assert result.height == (8 if pivot else 16)
    assert result["time"].dt.date().n_unique() == 2
