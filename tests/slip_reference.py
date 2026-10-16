"""Independent NumPy reference for the STEC continuity objective."""

import numpy as np


def detection_events(times, phase, mw, f1, f2, *, variant="joint", boundaries=None):
    """Independent scalar NumPy localization reference, with explicit cue arms."""
    times = np.asarray(times)
    time = (times - times[0]).astype(float) / 1e9
    phase, mw = np.asarray(phase), np.asarray(mw)
    f1, f2 = np.broadcast_arrays(f1, f2, phase)[:2]
    events = np.zeros(len(phase), dtype=bool)
    boundaries = np.zeros(len(phase), dtype=bool) if boundaries is None else boundaries
    gf = np.zeros(len(phase), dtype=bool)
    melbourne = np.zeros(len(phase), dtype=bool)
    start = 0

    def median(values):
        return float(np.median(values)) if len(values) else 0.0

    def spread(values):
        return 1.4826 * median(np.abs(values - median(values)))

    for k in range(1, len(phase)):
        if boundaries[k]:
            events[k] = True
            start = k
            continue
        lo = max(start, k - 32)
        history = np.arange(lo + 1, k)
        history = history[~events[history]]
        slopes = (phase[history] - phase[history - 1]) / (
            time[history] - time[history - 1]
        )
        deltas = mw[history] - mw[history - 1]
        if len(history):
            rate = median(slopes[-3:])
        else:
            future = []
            for q in range(k + 1, min(k + 4, len(phase))):
                if boundaries[q]:
                    break
                future.append((phase[q] - phase[q - 1]) / (time[q] - time[q - 1]))
            rate = median(future)
        dt = time[k] - time[k - 1]
        a, b = f1[k] ** 2, f2[k] ** 2
        coeff = a * b / (a - b) / 40.3e16
        floor = abs(coeff * (299792458.0 / f1[k] - 299792458.0 / f2[k])) / 4
        phase_scale = spread(np.diff(phase[lo:k], n=2)) / np.sqrt(6)
        limit = max(floor, 6 * spread(slopes) * dt, 6 * phase_scale)
        gf[k] = abs(phase[k] - phase[k - 1] - rate * dt) > limit
        melbourne[k] = len(history) >= 3 and abs(
            mw[k] - mw[k - 1] - median(deltas)
        ) > max(0.5, 6 * spread(deltas))
        events[k] = (
            gf[k]
            if variant == "gf"
            else melbourne[k]
            if variant == "mw"
            else gf[k] or melbourne[k]
        )
    return events, gf, melbourne


def offsets(times, phase, candidates):
    """Minimize each localized edge's departure from its normal local rate."""
    times = np.asarray(times, dtype=float)
    phase = np.asarray(phase, dtype=float)
    candidates = np.asarray(candidates, dtype=bool)
    rates = np.diff(phase) / np.diff(times)
    centers = (times[1:] + times[:-1]) / 2
    edges = np.arange(1, len(phase))
    changes = np.zeros(len(phase))
    for event in np.flatnonzero(candidates):
        available = edges[~candidates[1:]]
        left = available[(available < event) & (available >= event - 32)][-3:]
        right = available[(available > event) & (available <= event + 32)][:3]
        if len(left) and len(right):
            a, b = np.median(rates[left - 1]), np.median(rates[right - 1])
            ta, tb = np.mean(centers[left - 1]), np.mean(centers[right - 1])
            weight = np.clip((centers[event - 1] - ta) / (tb - ta), 0, 1)
            target = (1 - weight) * a + weight * b
        elif len(left) or len(right):
            side = left if len(left) else right
            target = np.median(rates[side - 1])
        else:
            target = 0
        changes[event] = (
            phase[event] - phase[event - 1] - target * (times[event] - times[event - 1])
        )
    return changes


def assert_continuous(result, frame, atol=1e-7):
    """All reported events are corrected; final edge-rate residuals vanish."""
    status = result["slip_status"].to_numpy()
    events = np.isin(status, ["phase_repaired", "phase_continuous"])
    before = frame["stec_p_raw"].to_numpy()
    after = result["stec_p_corrected"].to_numpy()
    time = frame["time"].to_numpy().astype(float) / 1e9
    expected = offsets(time, before, events)
    np.testing.assert_allclose(after, before - np.cumsum(expected), rtol=0, atol=atol)
    # Normal increments inside each segment are preserved by constant offsets.
    np.testing.assert_allclose(
        np.diff(after)[~events[1:]], np.diff(before)[~events[1:]], rtol=0, atol=atol
    )
    residual = offsets(time, after, events)
    np.testing.assert_allclose(residual[events], 0, rtol=0, atol=atol)
    return events, expected
