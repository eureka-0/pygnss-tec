from __future__ import annotations

from collections.abc import Iterable
from pathlib import Path
from typing import Literal

import numpy as np
import polars as pl
import polars.selectors as cs
from numpy.typing import NDArray

from ..calibration.receiver_bias import estimate_rx_bias
from ..configuration import DIAGNOSTIC_COLUMNS, TECConfig
from ..constants import c
from ..io.bias_sinex import read_bias
from ..io.rinex import RinexObsHeader, get_leap_seconds, read_rinex_obs
from ..signals.arcs import add_slip_arcs, align_stec
from ..signals.definitions import CODE_FREQUENCIES
from ..signals.selection import coalesce_observations as _coalesce_observations
from .mapping_functions import modified_single_layer_model, single_layer_model
from .observation_geometry import _prepare_observations

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


def _require_columns(lf: pl.LazyFrame, columns: Iterable[str], context: str) -> None:
    available = set(lf.collect_schema().names())
    missing = sorted(set(columns) - available)
    if missing:
        raise ValueError(
            f"{context} requires columns that are missing: {', '.join(missing)}."
        )


def _infer_time_kind(lf: pl.LazyFrame) -> Literal["utc", "gps"]:
    dtype = lf.collect_schema()["time"]
    if not isinstance(dtype, pl.Datetime):
        raise TypeError(
            "Input time column must be a Polars Datetime. Use timezone-aware UTC "
            "datetime values for UTC or naive datetime values for GPS time."
        )

    if dtype.time_zone == "UTC":
        return "utc"
    elif dtype.time_zone is None:
        return "gps"
    else:
        raise ValueError(
            "Input time column must use the UTC timezone or be timezone-naive "
            f"GPS time, got timezone {dtype.time_zone!r}."
        )


def _leap_seconds_duration(header: RinexObsHeader) -> pl.Expr:
    if header.leap_seconds is not None:
        return pl.duration(seconds=header.leap_seconds, time_unit="ns")
    return get_leap_seconds("time")


def _map_frequencies(lf: pl.LazyFrame) -> pl.LazyFrame:
    if "_C1_freq" in lf.collect_schema():
        return lf.with_columns(
            pl.col("_C1_freq").alias("C1_freq"), pl.col("_C2_freq").alias("C2_freq")
        ).drop("_C1_freq", "_C2_freq")

    def map_freq(col: str) -> pl.Expr:
        return pl.concat_str(
            pl.col("prn").cat.slice(0, 1), pl.lit("_"), pl.col(col).cat.slice(1, 1)
        ).replace_strict(CODE_FREQUENCIES, default=None)

    return lf.with_columns(
        map_freq("C1_code").alias("C1_freq"), map_freq("C2_code").alias("C2_freq")
    )


def _correct_cycle_slip(
    time: NDArray[np.float64],
    stec_p: NDArray[np.float64],
    tec_diff_tol: float,
    window_size: int,
) -> NDArray[np.float64]:
    """Return raw phase TEC; retained for private callers of the former helper.

    GF alone cannot distinguish ambiguity jumps from ionospheric changes.
    Segmentation now uses quality.py; the legacy tuning arguments are ignored.
    """
    if not np.isfinite(time).all() or np.any(np.diff(time) <= 0):
        raise ValueError(
            "Observation times must be finite and unique within each station/PRN."
        )
    return stec_p.copy()


def calc_tec_from_df(
    df: pl.DataFrame | pl.LazyFrame,
    header: RinexObsHeader,
    bias_fn: str | Path | Iterable[str | Path] | None = None,
    config: TECConfig | None = None,
    *,
    nav_fn: str | Path | Iterable[str | Path] | None = None,
) -> pl.LazyFrame:
    """Calculate TEC from wide GNSS observations.

    Parameters
    ----------
    df : polars.DataFrame or polars.LazyFrame
        Wide observations with time, station and prn. Time must be
        timezone-aware UTC or timezone-naive GPS, unique per station/PRN.
        Reader inputs require pivot=True. Missing LLI is accepted but
        supplies no recorded loss-of-lock or half-cycle information.
    header : RinexObsHeader
        Version, sampling and receiver/event metadata. Existing rx_lat and
        rx_lon columns take precedence over the header position.
    bias_fn : str, Path, iterable of str or Path, or None, default None
        Optional DCB products. Without them, retained TEC is uncorrected;
        hiding calibration_status does not imply complete calibration.
    config : TECConfig or None, default None
        Configuration; None constructs TECConfig(). Output selection
        follows retain_diagnostics without changing QC/calibration.
    nav_fn : str, Path, iterable of str or Path, or None, default None
        Navigation files for raw-observation geometry, required unless
        azimuth and elevation are already present in degrees.

    Returns
    -------
    polars.LazyFrame
        UTC epochs, identifiers, receiver/IPP coordinates in degrees,
        azimuth/elevation in degrees, selected codes and TEC in TECU.
        Default/selected diagnostics return accepted rows. Complete
        diagnostics also retains rejected rows with null public TEC.
        Internal leveling/weight/bias-interval fields are never returned.

    Raises
    ------
    TypeError
        If time is not a Polars Datetime.
    ValueError
        If required columns, time scale/uniqueness, RINEX version or
        sampling cadence are invalid, or requested bias semantics fail.
    """
    if config is None:
        config = TECConfig()
    keep_all = config.retain_diagnostics == "all"
    retained = set() if keep_all else set(config.retain_diagnostics or ())
    input_lf = df.lazy()
    _require_columns(input_lf, ["time", "station", "prn"], "calc_tec_from_df")
    input_schema = input_lf.collect_schema()
    if "code" in input_schema and "value" in input_schema:
        raise ValueError("TEC calculations require wide observations; use pivot=True.")
    if nav_fn is None:
        _require_columns(input_lf, ["azimuth", "elevation"], "calc_tec_from_df")
    # RINEX geometry is already Float64. Normalize external DataFrame/Parquet
    # inputs once so all later trigonometry and weighting use the same precision.
    geometry_casts = [
        pl.col(name).cast(pl.Float64)
        for name in ("azimuth", "elevation", "rx_lat", "rx_lon")
        if name in input_schema and input_schema[name] != pl.Float64
    ]
    if geometry_casts:
        input_lf = input_lf.with_columns(geometry_casts)
    time_kind = _infer_time_kind(input_lf)
    bounds = np.iinfo(np.int64)
    out_of_range, invalid_time, duplicated = (
        input_lf.select(
            (
                ~pl.col("time")
                .dt.epoch("us")
                .is_between(bounds.min // 1000 + 1, bounds.max // 1000)
            )
            .any()
            .alias("_out_of_range"),
            pl.col("time").is_null().any().alias("_null_time"),
            pl.struct("time", "station", "prn")
            .is_duplicated()
            .any()
            .alias("_duplicated"),
        )
        .collect()
        .row(0)
    )
    if out_of_range:
        raise ValueError("Observation epoch is outside the signed nanosecond range.")
    if invalid_time or duplicated:
        raise ValueError(
            "Observation times must be finite and unique within each station/PRN."
        )
    input_lf = input_lf.with_columns(pl.col("time").dt.cast_time_unit("ns"))

    lf = (
        input_lf.with_columns(pl.col("prn").cast(pl.Categorical))
        # QC keeps rejected geometry rows for the optional diagnostic output.
        .filter(pl.col("prn").cat.slice(0, 1).is_in(list(config.constellations)))
        # drop D-code observations
        .drop(cs.matches(r"^D\d[A-Z]{0,1}$"))
    )

    utc_epoch = (
        pl.col("time")
        if time_kind == "utc"
        else (pl.col("time") - _leap_seconds_duration(header)).dt.replace_time_zone(
            "UTC"
        )
    )
    lf = _prepare_observations(lf, header, utc_epoch, nav_fn)
    sampling_interval = header.sampling_interval
    if sampling_interval is None:
        # Use positive per-group cadences, including fractional seconds. A mean
        # across satellites would misclassify mixed high/low-rate observations.
        delta = pl.col("time").diff().dt.total_nanoseconds().over("station", "prn")
        interval_ns, regimes = (
            lf.select("time", "station", "prn")
            .sort("time")
            .with_columns(delta.alias("_delta_ns"))
            .group_by("station", "prn")
            .agg(pl.col("_delta_ns").filter(pl.col("_delta_ns") > 0).min())
            .drop_nulls("_delta_ns")
            .select(
                interval_ns=pl.col("_delta_ns").min(),
                regimes=(
                    (pl.col("_delta_ns") > 5e9).cast(pl.UInt8) * 2
                    + (pl.col("_delta_ns") >= 10e9).cast(pl.UInt8)
                ).n_unique(),
            )
            .collect()
            .row(0)
        )
        if interval_ns is None:
            raise ValueError(
                "Cannot infer sampling interval without two distinct times in a "
                "station/PRN; provide header.sampling_interval."
            )
        if regimes > 1:
            raise ValueError(
                "Inferred sampling intervals require different arc/cycle-slip "
                "settings; process sampling groups separately or provide the "
                "known header.sampling_interval."
            )
        sampling_interval = interval_ns / 1e9
    if not np.isfinite(sampling_interval) or sampling_interval <= 0:
        raise ValueError("sampling_interval must be finite and positive.")

    lf = lf.with_columns(_leap_seconds_duration(header).alias("_leap_seconds"))
    leap_seconds = pl.col("_leap_seconds")
    if time_kind == "utc":
        lf = lf.with_columns(
            # Adjust UTC to GPS time for correctly joining with bias data
            pl.col("time").add(leap_seconds).dt.replace_time_zone(None)
        )
    else:
        lf = lf.with_columns(pl.col("time").dt.replace_time_zone(None))

    bias_lf = None if bias_fn is None else read_bias(bias_fn)
    if header.version.startswith("2"):
        version = "2"
    elif header.version.startswith("3"):
        version = "3"
    else:
        raise ValueError(f"Unsupported RINEX version: {header.version}")
    lf = _coalesce_observations(lf, bias_lf, config, version)
    lf = _map_frequencies(lf)

    match config.mapping_function:
        case "slm":
            mapping_function = single_layer_model
        case "mslm":
            mapping_function = modified_single_layer_model

    mf, ipp_lat, ipp_lon = mapping_function(
        pl.col("azimuth"),
        pl.col("elevation"),
        pl.col("rx_lat"),
        pl.col("rx_lon"),
        config,
    )
    lf = lf.with_columns(
        # Mapping function
        mf.alias("mf"),
        # IPP Latitude in degrees
        ipp_lat.alias("ipp_lat"),
        # IPP Longitude in degrees
        ipp_lon.alias("ipp_lon"),
    )

    f1 = pl.col("C1_freq")
    f2 = pl.col("C2_freq")
    coeff = f1**2 * f2**2 / (f1**2 - f2**2) / 40.3e16
    tecu_per_ns = 1e-9 * c * coeff

    # Raw observations and phase remain available for diagnostics.
    available = set(lf.collect_schema().names())
    defaults = [pl.lit(0, dtype=pl.UInt8).alias("epoch_flag")]
    lf = lf.with_columns([e for e in defaults if e.meta.output_name() not in available])
    lf = lf.sort("time", "station", "prn").with_columns(
        (pl.col("C2_val") - pl.col("C1_val")).mul(coeff).alias("stec_g"),
        (pl.col("L1_val") / f1 - pl.col("L2_val") / f2)
        .mul(c * coeff)
        .alias("stec_p_raw"),
        (
            pl.col("L1_val")
            - pl.col("L2_val")
            - (f1 * pl.col("C1_val") + f2 * pl.col("C2_val"))
            / (f1 + f2)
            / (c / (f1 - f2))
        ).alias("mw"),
        pl.all_horizontal(pl.col("C1_val", "C2_val", "L1_val", "L2_val").is_finite())
        .fill_null(False)
        .alias("_observations_valid"),
        pl.all_horizontal(
            pl.col("C1_freq", "C2_freq").is_finite()
            & (pl.col("C1_freq", "C2_freq") > 0)
        )
        .fill_null(False)
        .alias("_frequencies_valid"),
        (
            pl.all_horizontal(
                pl.col(
                    "azimuth",
                    "elevation",
                    "rx_lat",
                    "rx_lon",
                    "mf",
                    "ipp_lat",
                    "ipp_lon",
                ).is_finite()
            )
            & pl.col("elevation").is_between(0, 90)
            & pl.col("rx_lat").is_between(-90, 90)
            & (pl.col("mf") > 0)
        )
        .fill_null(False)
        .alias("_geometry_valid"),
        pl.col("elevation").radians().sin().pow(2).alias("weight"),
        (
            ((pl.col("L1_lli").fill_null(0) // 2) % 2 == 0)
            & ((pl.col("L2_lli").fill_null(0) // 2) % 2 == 0)
        ).alias("_half_cycle_valid"),
    )
    # Known frequencies are positive and distinct; configuration validates pairs.
    lf = (
        lf.with_columns(
            (
                pl.col("_observations_valid")
                & pl.col("_frequencies_valid")
                & pl.col("_geometry_valid")
                & pl.all_horizontal(pl.col("stec_g", "stec_p_raw", "mw").is_finite())
                & pl.col("_snr_valid")
                & (pl.col("elevation") >= config.min_elevation)
                & ~pl.col("_bias_rejected")
                & pl.col("epoch_flag").is_in([0, 1])
            )
            .fill_null(False)
            .alias("_numeric_valid")
        )
        .with_columns(
            (pl.col("_numeric_valid") & pl.col("_half_cycle_valid")).alias("qc_valid")
        )
        .with_columns(pl.col("stec_p_raw").alias("stec_p"))
    )
    lf = add_slip_arcs(
        lf,
        sampling_interval if header.sampling_interval is not None else None,
        config.cycle_slip_mode,
        integer_cycles=header.phase_integer_cycles,
    )
    if not keep_all:
        # Rejected rows have already contributed to arc boundaries. They carry
        # no leveling weight and need not traverse the remaining TEC expressions.
        lf = lf.filter(pl.col("qc_valid"))
    lf = lf.with_columns(
        pl.concat_str(
            pl.col("qc_reason"),
            pl.when(~pl.col("_observations_valid"))
            .then(pl.lit("nonfinite_or_missing_observation"))
            .otherwise(None),
            pl.when(~pl.col("_geometry_valid"))
            .then(pl.lit("invalid_geometry"))
            .otherwise(None),
            pl.when(~pl.col("_snr_valid")).then(pl.lit("snr_rejected")).otherwise(None),
            pl.when(pl.col("elevation") < config.min_elevation)
            .then(pl.lit("below_min_elevation"))
            .otherwise(None),
            pl.when(pl.col("_bias_rejected"))
            .then(pl.lit("missing_required_bias"))
            .otherwise(None),
            separator="|",
            ignore_nulls=True,
        ).alias("qc_reason")
    )
    if bias_fn is not None:
        lf = lf.with_columns(pl.col("tx_bias").mul(tecu_per_ns))
        if config.rx_bias == "external":
            lf = lf.with_columns(pl.col("rx_bias").mul(tecu_per_ns))
        else:
            lf = lf.with_columns(pl.lit(None, dtype=pl.Float64).alias("rx_bias"))
        code_bias = pl.col("tx_bias").fill_null(0)
        if config.rx_bias == "external":
            code_bias = code_bias + pl.col("rx_bias").fill_null(0)
        interval_cols = ["tx_bias_start", "tx_bias_end"]
        if config.rx_bias == "external":
            interval_cols += ["rx_bias_start", "rx_bias_end"]
        lf = lf.with_columns(
            pl.when(pl.col("_bias_available"))
            .then(
                pl.lit(
                    "external_code_corrected"
                    if config.rx_bias == "external"
                    else "satellite_code_corrected"
                )
            )
            .otherwise(pl.lit("uncorrected_missing_bias"))
            .alias("calibration_status"),
            pl.struct(*interval_cols, "_bias_available").alias("_level_key"),
            code_bias.alias("_code_bias"),
        )
    else:
        lf = lf.with_columns(
            pl.lit("uncorrected_no_bias_product").alias("calibration_status"),
            pl.lit(False).alias("_level_key"),
            pl.lit(0.0).alias("_code_bias"),
        )
    # Calibrate the code reference BEFORE leveling. Physical arcs are independent
    # of bias validity intervals, which delimit separate leveling estimates.
    lf = (
        lf.with_columns(
            (pl.col("stec_g") - pl.col("_code_bias")).alias("stec_g_corrected")
        )
        .with_columns(
            (
                pl.col("qc_valid")
                & (pl.col("stec_g_corrected") - pl.col("stec_p_corrected")).is_finite()
            ).alias("qc_valid"),
            pl.concat_str(
                pl.col("qc_reason"),
                pl.when(
                    ~(pl.col("stec_g_corrected") - pl.col("stec_p_corrected"))
                    .is_finite()
                    .fill_null(False)
                )
                .then(pl.lit("invalid_code_phase_offset"))
                .otherwise(None),
                separator="|",
                ignore_nulls=True,
            ).alias("qc_reason"),
        )
        .with_columns(
            pl.when(pl.col("qc_valid") & (pl.col("weight") > 0))
            .then(
                (pl.col("stec_g_corrected") - pl.col("stec_p_corrected"))
                * pl.col("weight")
            )
            .otherwise(None)
            .alias("_weighted_offset"),
            pl.when(pl.col("qc_valid") & (pl.col("weight") > 0))
            .then(pl.col("weight"))
            .otherwise(None)
            .alias("_valid_weight"),
        )
        .with_columns(
            (pl.col("_weighted_offset").sum() / pl.col("_valid_weight").sum())
            .over("station", "prn", "_continuity_id", "_level_key")
            .fill_nan(None)
            .alias("offset")
        )
        .with_columns(
            pl.when(pl.col("qc_valid") & pl.col("offset").is_finite())
            .then(pl.col("stec_p_corrected") + pl.col("offset"))
            .otherwise(None)
            .alias("_leveled")
        )
        .with_columns(
            # Preserve the public raw STEC relationship without subtracting DCB twice.
            (pl.col("_leveled") + pl.col("_code_bias")).alias("stec")
        )
    )
    if bias_fn is not None:
        if config.rx_bias in {"mstd", "lsq"}:
            # The solver sees only valid rows; join estimates back for diagnostics.
            estimates = estimate_rx_bias(
                lf.filter(pl.col("_leveled").is_finite()).drop("rx_bias"),
                method=config.rx_bias,
                downsample=sampling_interval < 10,
            ).select("time", "station", "prn", "rx_bias")
            lf = lf.drop("rx_bias").join(
                estimates,
                on=["time", "station", "prn"],
                how="left",
                validate="1:1",
                maintain_order="left",
            )
            lf = lf.with_columns(
                pl.when(pl.col("rx_bias").is_finite() & pl.col("_bias_available"))
                .then(
                    pl.lit(
                        f"satellite_code_corrected_receiver_{config.rx_bias}_estimated"
                    )
                )
                .when(pl.col("rx_bias").is_finite())
                .then(pl.col("calibration_status"))
                .otherwise(pl.lit("receiver_estimation_failed"))
                .alias("calibration_status")
            )
            corrected = pl.col("_leveled") - pl.col("rx_bias")
        else:
            corrected = pl.col("_leveled")
        lf = lf.with_columns(corrected.alias("stec_dcb_corrected"))
        vtec_source = pl.col("stec_dcb_corrected")
    else:
        vtec_source = pl.col("_leveled")
    lf = lf.with_columns(
        (vtec_source / pl.col("mf")).alias("vtec"),
        pl.col("time").sub(leap_seconds).dt.replace_time_zone("UTC"),
    ).with_columns(
        pl.concat_str(
            pl.col("qc_reason"),
            pl.when(pl.col("qc_valid") & ~pl.col("offset").is_finite().fill_null(False))
            .then(pl.lit("no_weight_support"))
            .otherwise(None),
            pl.when(pl.col("calibration_status") == "receiver_estimation_failed")
            .then(pl.lit("receiver_estimation_failed"))
            .otherwise(None),
            separator="|",
            ignore_nulls=True,
        ).alias("qc_reason"),
        (pl.col("qc_valid") & pl.col("vtec").is_finite().fill_null(False)).alias(
            "qc_valid"
        ),
    )
    # Rejected diagnostics retain raw intermediates, with null public TEC values.
    lf = lf.with_columns(
        pl.when(pl.col("qc_valid")).then(pl.col(name)).otherwise(None).alias(name)
        for name in ("stec", "vtec", "stec_dcb_corrected")
        if name in lf.collect_schema()
    )
    if config.cycle_slip_mode == "repair":
        lf = align_stec(lf)
    else:
        lf = lf.with_columns(
            pl.lit(None, dtype=pl.Float64).alias(name)
            for name in ("slip_stec_correction", "slip_dcb_correction")
        )
    private_cols = [
        name
        for name in lf.collect_schema().names()
        if name.startswith("_") and name != "_leap_seconds"
    ]
    lf = lf.drop(private_cols)

    lf = lf.drop("_leap_seconds", *INTERNAL_COLUMNS, strict=False)

    if not keep_all:
        lf = lf.filter(pl.col("qc_valid"))
        cols_available = set(lf.collect_schema().names())
        cols_to_drop = cols_available.intersection(DIAGNOSTIC_COLUMNS) - retained
        lf = lf.drop(cols_to_drop)

    # Filters, group-to-row windows and receiver-bias joins preserve the arc sort.
    # Legacy inputs may carry provenance columns; use identity for arcs, then omit it.
    return lf.drop(
        "source_file",
        "receiver_id",
        "receiver_state",
        "epoch_events",
        "sat_x",
        "sat_y",
        "sat_z",
        "geometry_status",
        "half_cycle_valid",
        strict=False,
    )


def calc_tec_from_parquet(
    parquet_fn: str | Path,
    bias_fn: str | Path | Iterable[str | Path] | None = None,
    config: TECConfig | None = None,
    *,
    nav_fn: str | Path | Iterable[str | Path] | None = None,
) -> pl.LazyFrame:
    """Calculate TEC from stored wide observations and RINEX metadata.

    Parameters
    ----------
    parquet_fn : str or Path
        Parquet file saved with header.to_metadata(), including sampling
        interval and receiver coordinates. Missing LLI is accepted but
        cannot supply recorded lock/half-cycle QC.
    bias_fn : str, Path, iterable of str or Path, or None, default None
        Optional DCB products; without them TEC remains uncorrected.
    config : TECConfig or None, default None
        Configuration; None constructs TECConfig().
    nav_fn : str, Path, iterable of str or Path, or None, default None
        Navigation files, required unless stored azimuth/elevation exist.

    Returns
    -------
    polars.LazyFrame
        TEC in TECU and geometry in degrees with UTC epochs. Column/row
        selection follows calc_tec_from_df and retain_diagnostics.

    Raises
    ------
    ValueError
        If required RINEX metadata are missing or observation/bias
        constraints in calc_tec_from_df are violated.
    """
    lf = pl.scan_parquet(parquet_fn)
    metadata = pl.read_parquet_metadata(parquet_fn)
    header = RinexObsHeader.from_metadata(metadata)

    return calc_tec_from_df(lf, header, bias_fn, config, nav_fn=nav_fn)


def calc_tec_from_rinex(
    obs_fn: str | Path | Iterable[str | Path],
    nav_fn: str | Path | Iterable[str | Path],
    bias_fn: str | Path | Iterable[str | Path] | None = None,
    config: TECConfig | None = None,
    *,
    station: str | None = None,
) -> pl.LazyFrame:
    """Calculate TEC from RINEX observations and navigation files.

    Parameters
    ----------
    obs_fn : str, Path, or iterable of str or Path
        Observation files from the same station and RINEX major version.
        The reader explicitly enables LLI for recorded lock/half-cycle QC.
    nav_fn : str, Path, or iterable of str or Path
        Navigation files for satellite propagation and receiver geometry.
    bias_fn : str, Path, iterable of str or Path, or None, default None
        Optional DCB products; without them TEC remains uncorrected.
    config : TECConfig or None, default None
        Configuration; None constructs TECConfig().
    station : str or None, default None
        Override the station identifier; None uses the observation header.

    Returns
    -------
    polars.LazyFrame
        TEC in TECU and geometry in degrees with UTC epochs. Column/row
        selection follows calc_tec_from_df and retain_diagnostics; LLI
        still contributes to QC when omitted from the final output.

    Raises
    ------
    FileNotFoundError
        If an observation file does not exist.
    ValueError
        If reader or TEC input/bias constraints are violated.
    """
    if config is None:
        config = TECConfig()
    header, lf = read_rinex_obs(
        obs_fn,
        config.constellations,
        _tec_observation_codes(config),
        station=station,
        include_lli=True,
    )

    return calc_tec_from_df(lf, header, bias_fn, config, nav_fn=nav_fn)


def _tec_observation_codes(config: TECConfig) -> list[str]:
    """Project every configured fallback with its phase, SNR and LLI.

    Union both RINEX versions because the version is known after reading the
    header. Keeping only defaults would silently remove custom fallbacks.
    """
    codes = {
        code
        for mapping in (config.c1_codes, config.c2_codes)
        for version in mapping.values()
        for constellation in config.constellations
        for code in version.get(constellation, [])
    }
    return sorted(
        {name for code in codes for name in (code, "L" + code[1:], "S" + code[1:])}
    )
