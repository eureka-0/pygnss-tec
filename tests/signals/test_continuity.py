import numpy as np
import polars as pl
import pytest

from tests.support.native import native
from tests.support.slip_reference import assert_continuous
from tests.support.slip_scenarios import C, scenario


@pytest.mark.parametrize("size,event", [(2, 1), (12, 11)])
def test_short_or_terminal_segments_are_corrected(size, event):
    frame, *_ = scenario(size=size)
    after = (pl.int_range(pl.len()) >= event).cast(pl.Float64)
    frame = frame.with_columns(
        (pl.col("stec_p_raw") + after * 19.25).alias("stec_p_raw"),
        (pl.int_range(pl.len()) == event).cast(pl.UInt8).alias("L1_lli"),
    )
    result = native(frame)
    assert result["slip_status"][event] == "phase_repaired"
    assert_continuous(result, frame)


@pytest.mark.parametrize("jumps", [[40, 41, 42], [40, 119]])
def test_linear_stec_is_restored_across_clustered_noninteger_steps(jumps):
    # The offset estimator operates in TECU; frequency conversion is covered by
    # the physical matrix. Repeating this analytic identity for each pair adds
    # no distinct behavior.
    frame, *_ = scenario()
    baseline = 30 + np.arange(len(frame)) * 0.02
    added = np.zeros(len(frame))
    for event, amount in zip(jumps, [13.123, -8.75, 4.2], strict=False):
        added[event:] += amount
    frame = frame.with_columns(
        pl.Series("stec_p_raw", baseline + added),
        pl.Series("L1_lli", np.isin(np.arange(len(frame)), jumps).astype(np.uint8)),
        pl.lit(0.0).alias("mw"),
    )
    result = native(frame)
    assert_continuous(result, frame)
    np.testing.assert_allclose(result["stec_p_corrected"], baseline, rtol=0, atol=1e-10)


def test_code_and_integer_metadata_cannot_veto_smoothing():
    noise = "moderate"
    frame, *_ = scenario("GPS", 30, noise, 7919, "five")
    expected = native(frame)
    changed = frame.with_columns((pl.col("stec_g") + 1e6).alias("stec_g"))
    actual = native(changed, integer_cycles=False)
    np.testing.assert_array_equal(
        actual["stec_p_corrected"], expected["stec_p_corrected"]
    )
    assert actual["slip_status"].to_list() == expected["slip_status"].to_list()
    assert_continuous(actual, changed)


@pytest.mark.parametrize(
    "pair,distribution,seed",
    [
        ("GPS", "heavy_tail", 155921),
        ("BDS", "correlated", 196613),
        ("GPS-L1L5", "burst", 262147),
        ("GPS-L2L5", "common_code_step", 17),
        ("BDS-B2IB3I", "phase_spike", 17),
    ],
)
def test_shifted_noise_controls_remain_temporally_continuous(pair, seed, distribution):
    for case in ("none", "five"):
        frame, _truth, _increments, values = scenario(
            pair, 30, "quiet", seed, case, size=160
        )
        rng = np.random.default_rng(seed)
        f1, f2 = frame["C1_freq"][0], frame["C2_freq"][0]
        p1, p2 = values["C1C"].copy(), values["C2W"].copy()
        if distribution == "heavy_tail":
            p1 += rng.standard_t(3, len(frame)) * 0.15
            p2 += rng.standard_t(3, len(frame)) * 0.15
        elif distribution == "correlated":
            for p in (p1, p2):
                noise = np.zeros(len(frame))
                for i in range(1, len(frame)):
                    noise[i] = 0.9 * noise[i - 1] + rng.normal(0, 0.03)
                p += noise
        elif distribution == "burst":
            scale = np.full(len(frame), 0.03)
            scale[28:37] = 0.5
            p1 += rng.normal(0, scale)
            p2 += rng.normal(0, scale)
        elif distribution == "common_code_step":
            p1[40:] += 2
            p2[40:] += 2
        k = f1**2 * f2**2 / (f1**2 - f2**2) / 40.3e16
        frame = frame.with_columns(
            pl.Series("stec_g", (p2 - p1) * k),
            pl.Series(
                "mw",
                values["L1C"]
                - values["L2W"]
                - (f1 * p1 + f2 * p2) / (f1 + f2) / (C / (f1 - f2)),
            ),
        )
        if distribution == "phase_spike":
            spike = (np.arange(len(frame)) == 80).astype(float) * 5
            frame = frame.with_columns(
                (pl.col("stec_p_raw") + pl.Series(spike) * C / f1 * k).alias(
                    "stec_p_raw"
                ),
                (pl.col("mw") + pl.Series(spike)).alias("mw"),
            )
        result = native(frame)
        assert_continuous(result, frame)
