"""Independent range/ionosphere/ambiguity controls for batch slip acceptance.

No production combination, prediction or integer-estimation helper is used.
Truth is paired noisy carrier with the injected integer ambiguities removed.
"""

import numpy as np
import polars as pl

C = 299792458.0
PAIRS = {
    "GPS": (1575.42e6, 1227.60e6),
    "BDS": (1561.098e6, 1268.52e6),
    "GPS-L1L5": (1575.42e6, 1176.45e6),
    "GPS-L2L5": (1227.60e6, 1176.45e6),
    "BDS-B2IB3I": (1207.14e6, 1268.52e6),
}
NOISE = {
    "clean": (0, 0),
    "quiet": (0.001, 0.02),
    "moderate": (0.003, 0.30),
    "stress": (0.010, 1.0),
}


def background_noise(phase, event, window=32):
    """Independent control-only phase scale and three-sigma step envelope.

    Use the uninjected paired phase, never corrected output or native fit
    residuals. Separate ordinary least-squares detrending on each side leaves
    background residuals; MAD of increments supplies an additional scale floor.
    Positive residual autocorrelation inflates the effective noise scale.
    This envelope is an engineering criterion, not a confidence probability.
    """
    phase = np.asarray(phase)
    lo, hi = max(0, event - window), min(len(phase), event + window)
    values = phase[lo:hi]
    delta = np.diff(values)
    increment_scale = 1.4826 * np.median(np.abs(delta - np.median(delta))) / np.sqrt(2)
    residuals = []
    dof = 0
    for side in (phase[lo:event], phase[event:hi]):
        t = np.linspace(-1, 1, len(side))
        trend = np.polynomial.polynomial.polyfit(t, side, min(2, len(side) - 1))
        residuals.append(side - np.polynomial.polynomial.polyval(t, trend))
        dof += len(side) - min(3, len(side))
    residual = np.concatenate(residuals)
    residual -= np.median(residual)
    residual_scale = 1.4826 * np.median(np.abs(residual))
    # Detrending estimates three coefficients per side. Retain its finite-
    # sample degrees-of-freedom correction when estimating background variance.
    residual_scale *= np.sqrt(len(residual) / max(1, dof))
    scale = max(float(residual_scale), float(increment_scale), 1e-6)
    # The sides are separate controls: do not correlate across the event.
    covariance = np.zeros(8)
    variance = 0.0
    for side in residuals:
        side = np.clip(side - np.median(side), -3 * scale, 3 * scale)
        variance += side @ side
        for lag in range(1, min(8, len(side) // 4) + 1):
            covariance[lag - 1] += side[lag:] @ side[:-lag]
    inflation = 1.0
    if variance > 0:
        for cov in covariance:
            if cov <= 0:
                break
            inflation += 2 * cov / variance
    effective = scale * np.sqrt(inflation)
    return effective, 3 * np.sqrt(2) * effective


CASES = (
    "none",
    "l1",
    "l2",
    "equal",
    "five",
    "repeated",
    "cancelling",
    "half",
    "early",
    "tec-step",
    "tec-ramp",
    "multipath",
    "outlier",
    "code-step",
    "correlated",
    "coincident",
    "large",
)


def scenario(pair="GPS", cadence=30, noise="clean", seed=17, case="none", size=120):
    rng = np.random.default_rng(seed)
    f1, f2 = PAIRS[pair]
    phase_noise, code_noise = NOISE[noise]
    index = np.arange(size)
    tec = 30 + 0.001 * index + 0.03 * np.sin(index / 19)
    if case in ("tec-step", "coincident"):
        tec[40:] += 8
    if case == "tec-ramp":
        tec[40:60] += np.linspace(0, 15, 20)
        tec[60:] += 15
    distance = 21e6 + 800 * np.sin(index / 80)
    p1 = distance + 40.3e16 * tec / f1**2 + rng.normal(0, code_noise, size)
    p2 = distance + 40.3e16 * tec / f2**2 + rng.normal(0, code_noise, size)
    a = distance - 40.3e16 * tec / f1**2 + rng.normal(0, phase_noise, size)
    b = distance - 40.3e16 * tec / f2**2 + rng.normal(0, phase_noise, size)
    if case == "multipath":
        p1 += 0.5 * np.sin(index / 7)
        p2 += 0.5 * np.cos(index / 9)
    if case == "outlier":
        p1[40] += 5
    if case == "code-step":
        p1[40:] += 0.5
    if case == "correlated":
        drift = np.zeros(size)
        for i in range(1, size):
            drift[i] = 0.9 * drift[i - 1] + rng.normal(0, max(0.02, code_noise))
        p1 += drift
        p2 -= drift
    increments = np.zeros((size, 2))
    if case in ("l1", "coincident"):
        increments[40] = (1, 0)
    elif case == "l2":
        increments[40] = (0, -1)
    elif case == "equal":
        increments[40] = (1, 1)
    elif case == "five":
        increments[40] = (5, 0)
    elif case == "repeated":
        increments[30], increments[60], increments[90] = (5, 0), (-5, 0), (1, 1)
    elif case == "cancelling":
        divisor = np.gcd(int(f1), int(f2))
        increments[40] = int(f1) // divisor, int(f2) // divisor
    elif case == "half":
        increments[40] = (0.5, 0)
    elif case == "early":
        increments[2] = (5, 0)
    elif case == "large":
        increments[40] = (129, 0)
    k = f1**2 * f2**2 / (f1**2 - f2**2) / 40.3e16
    truth_l1, truth_l2 = a * f1 / C, b * f2 / C
    cumulative = increments.cumsum(axis=0)
    l1, l2 = truth_l1 + cumulative[:, 0], truth_l2 + cumulative[:, 1]
    raw = (l1 / f1 - l2 / f2) * C * k
    truth = (truth_l1 / f1 - truth_l2 / f2) * C * k
    codes = (
        {1575.42e6: "C1C", 1227.60e6: "C2W", 1176.45e6: "C5Q"}
        if pair.startswith("GPS")
        else {1561.098e6: "C2I", 1268.52e6: "C6I", 1207.14e6: "C7I"}
    )
    frame = pl.DataFrame(
        {
            "time": (index * cadence * 1e9).astype(np.int64),
            "station": ["TEST"] * size,
            "prn": ["G01" if pair.startswith("GPS") else "C01"] * size,
            "C1_code": [codes[f1]] * size,
            "C2_code": [codes[f2]] * size,
            "_receiver_state": ["A"] * size,
            "_numeric_valid": [True] * size,
            "L1_lli": pl.Series([0] * size, dtype=pl.UInt8),
            "L2_lli": pl.Series([0] * size, dtype=pl.UInt8),
            "epoch_flag": pl.Series([0] * size, dtype=pl.Int64),
            "stec_p_raw": raw,
            "stec_g": (p2 - p1) * k,
            "mw": l1 - l2 - (f1 * p1 + f2 * p2) / (f1 + f2) / (C / (f1 - f2)),
            "C1_freq": [f1] * size,
            "C2_freq": [f2] * size,
        }
    )
    observations = {"C1C": p1, "C2W": p2, "L1C": l1, "L2W": l2}
    return frame, truth, increments, observations
