"""Supported TEC signal families and their carrier frequencies."""

from __future__ import annotations

SUPPORTED_RINEX_VERSIONS = ["2", "3"]
"""Supported RINEX major versions."""

SUPPORTED_CONSTELLATIONS = {"C": "BDS", "G": "GPS"}
"""Supported GNSS constellations for TEC calculation."""

SIGNAL_FREQ: dict[str, dict[str, float]] = {
    "C": {
        "B1-2": 1561.098e6,
        "B1": 1575.42e6,
        "B2a": 1176.45e6,
        "B2b": 1207.14e6,
        "B2": 1191.795e6,
        "B3": 1268.52e6,
    },
    "G": {"L1": 1575.42e6, "L2": 1227.60e6, "L5": 1176.45e6},
}
"""Signal frequencies for supported constellations and signals in Hz."""

CODE_FREQUENCIES = {
    "C_1": SIGNAL_FREQ["C"]["B1"],
    "C_2": SIGNAL_FREQ["C"]["B1-2"],
    "C_5": SIGNAL_FREQ["C"]["B2a"],
    "C_6": SIGNAL_FREQ["C"]["B3"],
    "C_7": SIGNAL_FREQ["C"]["B2b"],
    "C_8": SIGNAL_FREQ["C"]["B2"],
    "G_1": SIGNAL_FREQ["G"]["L1"],
    "G_2": SIGNAL_FREQ["G"]["L2"],
    "G_5": SIGNAL_FREQ["G"]["L5"],
}
