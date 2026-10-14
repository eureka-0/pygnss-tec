from __future__ import annotations

import copy
import math
import re
from collections.abc import Iterator, Mapping
from dataclasses import dataclass, field
from typing import Literal

import polars as pl

c = 299792458.0
"""Speed of light in m/s"""

Re = 6378.137e3
"""Earth radius in meters."""

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

DEFAULT_C1_CODES: dict[str, dict[str, list[str]]] = {
    "2": {"G": ["C1"]},
    "3": {
        "C": ["C2I", "C2D", "C2X", "C1I", "C1D", "C1X", "C2W", "C1C"],
        "G": ["C1W", "C1C", "C1X"],
    },
}

DEFAULT_C2_CODES: dict[str, dict[str, list[str]]] = {
    "2": {"G": ["C2", "C5"]},
    "3": {
        "C": ["C6I", "C6D", "C6X", "C7I", "C7D", "C7X", "C5I", "C5D", "C5X"],
        "G": ["C2W", "C2C", "C2X", "C5W", "C5C", "C5X"],
    },
}

VALID_RX_BIAS = {"external", "mstd", "lsq", None}
VALID_MAPPING_FUNCTIONS = {"slm", "mslm"}
VALID_MISSING_BIAS = {"drop", "warn", "keep_uncorrected", "error"}
CODE_PATTERN = re.compile(r"^C\d[A-Z]?$")

DIAGNOSTIC_COLUMNS = frozenset(
    {
        "epoch_flag",
        "L1_lli",
        "L2_lli",
        "qc_valid",
        "qc_reason",
        "calibration_status",
        "C1_freq",
        "C2_freq",
        "mf",
        "stec_g",
        "stec_p",
        "stec_p_raw",
        "stec_g_corrected",
        "arc_id",
        "mw",
        "C1_val",
        "C2_val",
        "L1_val",
        "L2_val",
        "S1",
        "S2",
        "tx_bias",
        "rx_bias",
    }
)
"""Optional public TEC diagnostics; availability also depends on bias inputs."""

INTERNAL_COLUMNS = frozenset(
    {
        "tx_bias_start",
        "tx_bias_end",
        "rx_bias_start",
        "rx_bias_end",
        "level_id",
        "offset",
        "weight",
    }
)
"""Leveling and bias state that must never appear in returned TEC tables."""


@dataclass(frozen=True, kw_only=True)
class TECConfig:
    """Configure signal selection, geometry, calibration and TEC output.

    Parameters
    ----------
    constellations : str, default 'CG'
        Nonempty, case-insensitive constellation letters: C (BeiDou) and
        G (GPS). RINEX 2 defaults provide GPS pairs only.
    ipp_height : float, default 400
        Finite, positive shell height in km for the single layer model.
        The modified model uses a fixed 506.7 km height instead.
    min_elevation : float, default 30
        Minimum accepted satellite elevation in degrees, within [0, 90].
    min_snr : float, default 30
        Finite, nonnegative minimum SNR in dB-Hz. For each band, null SNR
        is accepted only when more than half its values are null within
        the station/selected-code-pair group. Otherwise null SNR is rejected;
        nonfinite or recorded values below the threshold also reject the row.
    c1_codes : mapping, optional
        First-band code priorities, keyed by RINEX major version ('2' or
        '3'), then constellation. Lists contain C-prefixed observation
        codes, in priority order starting at zero. Empty input uses the
        defaults; missing versions/constellations inherit defaults and
        supplied lists replace that constellation's list. Inputs are copied.
        RINEX 2: G=[C1]. RINEX 3: G=[C1W, C1C, C1X];
        C=[C2I, C2D, C2X, C1I, C1D, C1X, C2W, C1C].
    c2_codes : mapping, optional
        Second-band priorities with the same mapping/merge rules as
        `c1_codes`. RINEX 2: G=[C2, C5]. RINEX 3:
        G=[C2W, C2C, C2X, C5W, C5C, C5X];
        C=[C6I, C6D, C6X, C7I, C7D, C7X, C5I, C5D, C5X].
        Selected constellations require supported frequency bands
        (GPS: 1/2/5; BeiDou: 1/2/5/6/7/8), distinct between the two lists.
    rx_bias : {'external', 'mstd', 'lsq', None}, default 'external'
        Receiver code-bias correction from a supplied bias product, or
        estimation by minimum standard deviation/least squares after
        satellite correction. None skips receiver correction. Without a
        bias file this option is inactive. Failed estimation leaves null
        TEC and a failure status, rather than a zero correction.
    mapping_function : {'slm', 'mslm'}, default 'slm'
        Single layer model or modified single layer model. The latter uses
        a fixed 506.7 km shell and dimensionless correction factor 0.9782.
    retain_diagnostics : None, list of str, tuple of str, or 'all', default None
        None returns accepted rows and base results, including azimuth and
        elevation. A list/tuple adds only the named supported diagnostics
        on accepted rows. 'all' adds all available diagnostics and retains
        rejected rows with null public TEC and rejection reasons.
        Selectable fields are epoch_flag, L1_lli, L2_lli, qc_valid,
        qc_reason, calibration_status, C1_freq, C2_freq, mf, stec_g,
        stec_p, stec_p_raw, stec_g_corrected, arc_id, mw, C1_val, C2_val,
        L1_val, L2_val, S1, S2, tx_bias and rx_bias. Bias diagnostics exist
        only when bias data are supplied. Geometry requests are allowed
        but redundant. `mw` is Melbourne-Wuebbena in wide-lane cycles;
        basic QC checks finiteness without detecting unflagged slips.
        tx_bias_start/end, rx_bias_start/end, level_id, offset and weight
        are internal and unavailable in every output mode.
    missing_bias : {'drop', 'warn', 'keep_uncorrected', 'error'}, default 'drop'
        Policy for required bias matches when a product is supplied.
        'drop' rejects unmatched rows; 'warn' also warns; 'error' raises.
        'keep_uncorrected' applies available corrections and marks missing
        calibration as uncorrected_missing_bias. Rejected rows are visible
        only with complete diagnostics. Without a product, TEC is retained
        as uncorrected_no_bias_product regardless of this setting.

    Raises
    ------
    ValueError
        If values, code mappings/frequencies or diagnostic names violate
        the constraints above.

    Notes
    -----
    Construction is keyword-only and the dataclass is frozen: fields cannot
    be reassigned. Nested code mappings are copied but remain mutable.
    Hiding calibration diagnostics does not imply absolute or fully
    calibrated TEC. Output selection does not change QC or calibration.
    """

    constellations: str = field(
        default_factory=lambda: "".join(SUPPORTED_CONSTELLATIONS.keys())
    )
    ipp_height: float = 400.0
    min_elevation: float = 30.0
    min_snr: float = 30.0

    c1_codes: Mapping[str, Mapping[str, list[str]]] = field(default_factory=dict)
    c2_codes: Mapping[str, Mapping[str, list[str]]] = field(default_factory=dict)

    rx_bias: Literal["external", "mstd", "lsq"] | None = "external"
    mapping_function: Literal["slm", "mslm"] = "slm"
    retain_diagnostics: Literal["all"] | list[str] | tuple[str, ...] | None = None
    missing_bias: Literal["drop", "warn", "keep_uncorrected", "error"] = "drop"

    @property
    def ipp_height_m(self) -> float:
        """Return the configured SLM shell height.

        Returns
        -------
        float
            Height in meters, equal to ipp_height * 1000.
        """
        return self.ipp_height * 1e3

    @property
    def mslm_height_m(self) -> float:
        """Return the fixed MSLM shell height.

        Returns
        -------
        float
            Height in meters (506700), independent of ipp_height.
        """
        return 506.7e3

    @property
    def alpha(self) -> float:
        """Return the MSLM angular correction factor.

        Returns
        -------
        float
            Dimensionless factor 0.9782.
        """
        return 0.9782

    def iter_c1_codes(
        self, version: Literal["2", "3"]
    ) -> Iterator[tuple[str, str, int]]:
        """Iterate first-band code priorities for a RINEX major version.

        Parameters
        ----------
        version : {'2', '3'}
            RINEX major version key.

        Yields
        ------
        tuple of (str, str, int)
            Constellation, observation code and zero-based priority.
        """
        for constellation, codes in self.c1_codes.get(version, {}).items():
            for i, code in enumerate(codes):
                yield constellation, code, i

    def iter_c2_codes(
        self, version: Literal["2", "3"]
    ) -> Iterator[tuple[str, str, int]]:
        """Iterate second-band code priorities for a RINEX major version.

        Parameters
        ----------
        version : {'2', '3'}
            RINEX major version key.

        Yields
        ------
        tuple of (str, str, int)
            Constellation, observation code and zero-based priority.
        """
        for constellation, codes in self.c2_codes.get(version, {}).items():
            for i, code in enumerate(codes):
                yield constellation, code, i

    def code2band(self, version: Literal["2", "3"]) -> Mapping[str, int]:
        """Map codes to first/second selection slots.

        Parameters
        ----------
        version : {'2', '3'}
            RINEX major version key.

        Returns
        -------
        mapping of str to int
            Constellation_code keys mapped to selection slots 1 or 2,
            rather than physical RINEX frequency-band numbers.
        """
        code_band: dict[str, int] = {}
        for const, code, _ in self.iter_c1_codes(version):
            code_band[f"{const}_{code}"] = 1  # C1 band
        for const, code, _ in self.iter_c2_codes(version):
            code_band[f"{const}_{code}"] = 2  # C2 band
        return code_band

    def c1_priority(self, version: Literal["2", "3"]) -> Mapping[str, int]:
        """Return first-band priority indices.

        Parameters
        ----------
        version : {'2', '3'}
            RINEX major version key.

        Returns
        -------
        mapping of str to int
            Constellation_code keys mapped to zero-based priorities.
        """
        priority: dict[str, int] = {}
        for const, code, i in self.iter_c1_codes(version):
            priority[f"{const}_{code}"] = i
        return priority

    def c2_priority(self, version: Literal["2", "3"]) -> Mapping[str, int]:
        """Return second-band priority indices.

        Parameters
        ----------
        version : {'2', '3'}
            RINEX major version key.

        Returns
        -------
        mapping of str to int
            Constellation_code keys mapped to zero-based priorities.
        """
        priority: dict[str, int] = {}
        for const, code, i in self.iter_c2_codes(version):
            priority[f"{const}_{code}"] = i
        return priority

    @staticmethod
    def validate_codes(codes, default) -> dict[str, dict[str, list[str]]]:
        """Copy and merge partial observation-code priorities.

        Parameters
        ----------
        codes : mapping
            Overrides keyed by RINEX version, then constellation. Empty
            input uses all defaults; supplied constellation lists replace
            their defaults.
        default : mapping
            Complete default version/constellation priority lists.

        Returns
        -------
        dict of str to dict of str to list of str
            Independent merged mappings with copied observation-code lists.

        Raises
        ------
        ValueError
            If version/constellation keys or C-prefixed code formats are
            invalid. Frequency-pair constraints are checked at construction.
        """
        if not codes:
            return copy.deepcopy(default)

        codes = dict(codes)
        unknown = codes.keys() - SUPPORTED_RINEX_VERSIONS
        if unknown:
            raise ValueError(
                f"Invalid RINEX versions in codes: {unknown}. "
                f"Allowed versions are {SUPPORTED_RINEX_VERSIONS}."
            )

        validated_codes = {}
        for ver in SUPPORTED_RINEX_VERSIONS:
            if ver not in codes:
                validated_codes[ver] = copy.deepcopy(default[ver])
                continue

            allowed = set(SUPPORTED_CONSTELLATIONS.keys())
            invalid = codes[ver].keys() - allowed
            if invalid:
                raise ValueError(
                    f"Invalid constellations in codes: {invalid}. "
                    f"Allowed constellations are {allowed}."
                )
            validated_codes[ver] = copy.deepcopy(default[ver]) | {
                const: list(code_list) for const, code_list in codes[ver].items()
            }

            for const, code_list in validated_codes[ver].items():
                invalid_codes = [
                    code for code in code_list if not CODE_PATTERN.match(code)
                ]
                if invalid_codes:
                    raise ValueError(
                        f"Invalid observation codes for RINEX {ver} {const}: "
                        f"{invalid_codes}. Codes must look like 'C1C' or 'C1'."
                    )
        return validated_codes

    def __post_init__(self):
        # Validate constellations
        allowed = set(SUPPORTED_CONSTELLATIONS.keys())
        constellations = self.constellations.upper()
        actual = set(constellations)

        invalid = actual - allowed
        if invalid:
            raise ValueError(
                f"Invalid constellations {self.constellations!r}; "
                f"allowed letters are subset of {''.join(sorted(allowed))!r}."
            )
        if not constellations:
            raise ValueError(
                "constellations must contain at least one constellation code."
            )

        if not 0 <= self.min_elevation <= 90:
            raise ValueError("min_elevation must be between 0 and 90 degrees.")
        if not math.isfinite(self.min_snr) or self.min_snr < 0:
            raise ValueError("min_snr must be non-negative.")
        if not math.isfinite(self.ipp_height) or self.ipp_height <= 0:
            raise ValueError("ipp_height must be positive.")
        if self.rx_bias not in VALID_RX_BIAS:
            raise ValueError(
                f"Invalid rx_bias {self.rx_bias!r}; expected one of {VALID_RX_BIAS}."
            )
        if self.mapping_function not in VALID_MAPPING_FUNCTIONS:
            raise ValueError(
                f"Invalid mapping_function {self.mapping_function!r}; "
                f"expected one of {VALID_MAPPING_FUNCTIONS}."
            )
        if self.missing_bias not in VALID_MISSING_BIAS:
            raise ValueError(
                f"Invalid missing_bias {self.missing_bias!r}; "
                f"expected one of {VALID_MISSING_BIAS}."
            )

        if self.retain_diagnostics is not None and self.retain_diagnostics != "all":
            if not isinstance(self.retain_diagnostics, (list, tuple)) or any(
                not isinstance(name, str) for name in self.retain_diagnostics
            ):
                raise ValueError(
                    "retain_diagnostics must be None, 'all', or a list/tuple of column names."
                )
            # Geometry is always public; requesting it remains a harmless no-op.
            unsupported = (
                set(self.retain_diagnostics)
                - DIAGNOSTIC_COLUMNS
                - {"azimuth", "elevation"}
            )
            if unsupported:
                raise ValueError(
                    f"Unsupported diagnostic columns: {', '.join(sorted(unsupported))}."
                )

        object.__setattr__(self, "constellations", constellations)

        # Set default codes if not provided
        object.__setattr__(
            self, "c1_codes", self.validate_codes(self.c1_codes, DEFAULT_C1_CODES)
        )
        object.__setattr__(
            self, "c2_codes", self.validate_codes(self.c2_codes, DEFAULT_C2_CODES)
        )

        for version in SUPPORTED_RINEX_VERSIONS:
            for constellation in self.constellations:
                first = self.c1_codes.get(version, {}).get(constellation, [])
                second = self.c2_codes.get(version, {}).get(constellation, [])
                supported_bands = {"G": set("125"), "C": set("125678")}[constellation]
                if any(code[1] not in supported_bands for code in first + second):
                    raise ValueError(
                        "Observation codes require supported positive frequencies."
                    )
                if {code[1] for code in first} & {code[1] for code in second}:
                    raise ValueError(
                        "Code pairs must use positive, distinct frequencies."
                    )


@dataclass(frozen=True)
class SamplingConfig:
    """Legacy sampling settings; basic QC uses cadence, not GF/MW tuning."""

    arc_interval: pl.Expr
    """Minimum time interval for arc segmentation (pl.duration)."""

    slip_tec_threshold: float
    """Legacy GF/MW threshold, unused by default basic QC."""

    slip_correction_window: int
    """Legacy GF/MW window, unused by default basic QC."""


def get_sampling_config(sampling_interval: float) -> SamplingConfig:
    """Return legacy arc settings for a finite positive cadence in seconds.

    Basic QC uses the cadence directly; these GF/MW thresholds and windows
    do not enable slip detection.
    """
    if not math.isfinite(sampling_interval) or sampling_interval <= 0:
        raise ValueError("sampling_interval must be finite and positive.")
    if sampling_interval <= 5:
        return SamplingConfig(
            arc_interval=pl.duration(minutes=1),
            slip_tec_threshold=0.5,
            slip_correction_window=20,
        )
    else:
        return SamplingConfig(
            arc_interval=pl.duration(minutes=5),
            slip_tec_threshold=2.0,
            slip_correction_window=10,
        )
