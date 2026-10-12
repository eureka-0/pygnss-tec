"""Conservative ambiguity segmentation; carrier phase is never rewritten."""

from __future__ import annotations

import numpy as np
import polars as pl

ARC_DTYPE = pl.Struct({"arc_id": pl.UInt32, "qc_reason": pl.String})


def _prior_statistics(values: np.ndarray, width: int) -> tuple[np.ndarray, np.ndarray]:
    """Rolling median/MAD of prior innovations, excluding the current sample."""
    prior = np.lib.stride_tricks.sliding_window_view(
        np.r_[np.full(width, np.nan), values[:-1]], width
    )
    populated = np.isfinite(prior).any(axis=1)
    center = np.zeros(len(values))
    spread = np.zeros(len(values))
    center[populated] = np.nanmedian(prior[populated], axis=1)
    spread[populated] = np.nanmedian(
        np.abs(prior[populated] - center[populated, None]), axis=1
    )
    return center, spread


def segment_arcs(
    samples: pl.Series, cadence: float | None, threshold: float, window: int
) -> pl.Series:
    """Combine lock/state flags with cadence-aware GF and robust MW innovations.

    GF alone is sensitive to ionospheric changes. A stable MW combination
    supports retaining such changes; missing or noisy MW leaves the boundary
    uncertain. Neither case justifies modifying the original carrier phase.
    """
    df = samples.struct.unnest()
    time = df["time"].to_numpy()
    phase = df["stec_p_raw"].fill_null(np.nan).to_numpy()
    code = df["stec_g"].fill_null(np.nan).to_numpy()
    mw = df["mw"].fill_null(np.nan).to_numpy()
    valid = df["_numeric_valid"].fill_null(False).to_numpy()
    lli1 = df["L1_lli"].fill_null(0).to_numpy()
    lli2 = df["L2_lli"].fill_null(0).to_numpy()
    flags = df["epoch_flag"].fill_null(0).to_numpy()
    state = df["receiver_state"].fill_null(0).to_list()
    pair = list(zip(df["C1_code"].to_list(), df["C2_code"].to_list(), strict=True))
    arcs = np.zeros(len(df), dtype=np.uint32)
    reasons: list[str] = []
    arc = 0
    start = 0

    if len(df) == 0:
        return pl.Series([], dtype=ARC_DTYPE)
    if cadence is None:
        # Different satellites may have different rates within the same regime.
        # Infer each group's cadence so slower groups do not acquire false gaps.
        cadence = float(np.min(np.diff(time))) / 1e9 if len(df) > 1 else 1.0
    # Bulk statistics keep long arcs inexpensive. Near each new boundary the
    # shorter local history below prevents evidence from crossing ambiguities.
    clean_phase = np.where(valid, phase, np.nan)
    clean_mw = np.where(valid, mw, np.nan)
    slope_history = np.r_[np.nan, np.diff(clean_phase) / (np.diff(time) / 1e9)]
    mw_history = np.r_[np.nan, np.diff(clean_mw)]
    slopes, _ = _prior_statistics(slope_history, window - 1)
    mw_centers, mw_mads = _prior_statistics(mw_history, window - 1)

    for i in range(len(df)):
        reason = []
        boundary = False
        half_cycle = bool((int(lli1[i]) | int(lli2[i])) & 2)
        if not valid[i]:
            reason.append("invalid_observation_or_geometry")
        if half_cycle:
            reason.append("half_cycle_invalid")
        if (int(lli1[i]) | int(lli2[i])) & 1:
            reason.append("loss_of_lock")
            boundary = True
        if flags[i] != 0:
            reason.append("epoch_event")
            boundary = True
        if i:
            dt = (int(time[i]) - int(time[i - 1])) / 1e9
            if dt <= 0:
                raise ValueError(
                    "Observation times must be finite and unique within each station/PRN."
                )
            if dt > cadence * 1.5:
                reason.append("reacquisition_gap")
                boundary = True
            if pair[i] != pair[i - 1]:
                reason.append("signal_pair_change")
                boundary = True
            if state[i] != state[i - 1]:
                reason.append("receiver_state_change")
                boundary = True
            if not valid[i - 1] or ((int(lli1[i - 1]) | int(lli2[i - 1])) & 2):
                reason.append("reacquisition_after_rejection")
                boundary = True
            boundary |= not valid[i] or half_cycle
            if not boundary and valid[i] and valid[i - 1]:
                lo = max(start, i - window)
                if i - start >= window:
                    slope = slopes[i]
                else:
                    t = time[lo:i].astype(np.int64)
                    local_slopes = np.diff(phase[lo:i]) / (np.diff(t) / 1e9)
                    local_slopes = local_slopes[np.isfinite(local_slopes)]
                    slope = (
                        float(np.median(local_slopes))
                        if len(local_slopes) >= 3
                        else 0.0
                    )
                innovation = phase[i] - phase[i - 1] - slope * dt
                gf_jump = abs(innovation) > threshold * max(1.0, dt / cadence)
                history = mw[lo:i]
                history = history[np.isfinite(history)]
                differences = np.diff(history)
                center = (
                    mw_centers[i]
                    if i - start >= window
                    else (
                        float(np.median(differences)) if len(differences) >= 3 else 0.0
                    )
                )
                mad = (
                    mw_mads[i]
                    if i - start >= window
                    else (
                        float(np.median(np.abs(differences - center)))
                        if len(differences)
                        else 0.0
                    )
                )
                mw_jump = (
                    np.isfinite(mw[i])
                    and len(history) > 0
                    and abs(mw[i] - history[-1] - center) > max(0.75, 6 * 1.4826 * mad)
                )
                if mw_jump:
                    reason.append("mw_slip" if not gf_jump else "gf_mw_slip")
                    boundary = True
                elif gf_jump:
                    # At least three stable prior MW values support a physical GF change.
                    code_change = code[i] - code[i - 1]
                    agrees_with_code = (
                        abs(code_change - (phase[i] - phase[i - 1])) <= threshold
                    )
                    if len(history) >= 3 and mad < 0.1 and agrees_with_code:
                        reason.append("gf_change_mw_stable")
                    else:
                        reason.append("uncertain_gf_jump")
                        boundary = True
        if i and boundary:
            arc += 1
            start = i
        arcs[i] = arc
        reasons.append("|".join(reason) if reason else "ok")
    return pl.DataFrame({"arc_id": arcs, "qc_reason": reasons}).to_struct()
