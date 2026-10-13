from __future__ import annotations

from collections.abc import Iterable
from pathlib import Path
from typing import Literal

import numpy as np
import polars as pl
import polars.selectors as cs
from numpy.typing import NDArray

from ..rinex import RinexObsHeader, get_leap_seconds, read_rinex_obs
from .bias import estimate_rx_bias, read_bias
from .constants import CODE_FREQUENCIES, TECConfig, c
from .mapping_func import modified_single_layer_model, single_layer_model
from .preparation import _prepare_observations
from .quality import add_basic_arcs
from .signals import coalesce_observations as _coalesce_observations


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
    """
    Calculate the Total Electron Content (TEC) from a Polars DataFrame or LazyFrame
    containing GNSS observations.

    Args:
        df (pl.DataFrame | pl.LazyFrame): Input DataFrame or LazyFrame containing GNSS
            observations.
        header (RinexObsHeader): RINEX observation file header. It is used to infer the
            RINEX metadata such as version, receiver position, and sampling interval.
            Existing rx_lat/rx_lon columns take precedence over the header position.
        bias_fn (str | Path | Iterable[str | Path] | None, optional): Path(s) to the
            bias file(s). If provided, DCB biases will be applied to the TEC
            calculation. Defaults to None.
        config (TECConfig, optional): Configuration parameters for TEC calculation.
            Defaults to TECConfig().
        nav_fn: Navigation file(s) for computing geometry from raw observations.
            Required unless the input already provides azimuth and elevation.
            Reader output must use pivot=True.

    Returns:
        pl.LazyFrame: A LazyFrame containing the calculated TEC values.
    """
    if config is None:
        config = TECConfig()
    keep_all = config.retain_intermediate == "all"
    retained = (
        {config.retain_intermediate}
        if isinstance(config.retain_intermediate, str)
        else set(config.retain_intermediate or ())
    )
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
    lf = add_basic_arcs(
        lf, sampling_interval if header.sampling_interval is not None else None
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
    if keep_all or "level_id" in retained:
        # Reserve the existing public column position; format interval IDs later.
        lf = lf.with_columns(
            pl.lit(
                None if bias_fn is not None else "no_bias_product", dtype=pl.String
            ).alias("level_id")
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
                & (pl.col("stec_g_corrected") - pl.col("stec_p_raw")).is_finite()
            ).alias("qc_valid"),
            pl.concat_str(
                pl.col("qc_reason"),
                pl.when(
                    ~(pl.col("stec_g_corrected") - pl.col("stec_p_raw"))
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
                (pl.col("stec_g_corrected") - pl.col("stec_p_raw")) * pl.col("weight")
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
            .over("station", "prn", "arc_id", "_level_key")
            .fill_nan(None)
            .alias("offset")
        )
        .with_columns(
            pl.when(pl.col("qc_valid") & pl.col("offset").is_finite())
            .then(pl.col("stec_p_raw") + pl.col("offset"))
            .otherwise(None)
            .alias("_leveled")
        )
        .with_columns(
            # Preserve the public raw STEC relationship without subtracting DCB twice.
            (pl.col("_leveled") + pl.col("_code_bias")).alias("stec")
        )
    )
    if bias_fn is not None and (keep_all or "level_id" in retained):
        # Format each distinct public interval ID once, preserving its string form.
        interval_keys = [*interval_cols, "_bias_available"]
        levels = (
            lf.select(*interval_keys)
            .unique()
            .with_columns(
                pl.concat_str(
                    *[
                        pl.col(name).cast(pl.String).fill_null("missing")
                        for name in interval_cols
                    ],
                    pl.col("_bias_available").cast(pl.String),
                    separator="|",
                ).alias("_formatted_level_id")
            )
        )
        lf = (
            lf.join(
                levels,
                on=interval_keys,
                how="left",
                nulls_equal=True,
                validate="m:1",
                maintain_order="left",
            )
            .with_columns(pl.col("_formatted_level_id").alias("level_id"))
            .drop("_formatted_level_id")
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
    intermediate_cols = {
        "azimuth",
        "elevation",
        "C1_freq",
        "C2_freq",
        "mf",
        "stec_g",
        "stec_p",
        "stec_p_raw",
        "stec_g_corrected",
        "arc_id",
        "level_id",
        "offset",
        "weight",
        "mw",
        "C1_val",
        "C2_val",
        "L1_val",
        "L2_val",
        "S1",
        "S2",
        "tx_bias",
        "rx_bias",
        "tx_bias_start",
        "tx_bias_end",
        "rx_bias_start",
        "rx_bias_end",
    }
    private_cols = [
        name
        for name in lf.collect_schema().names()
        if name.startswith("_") and name != "_leap_seconds"
    ]
    lf = lf.drop(private_cols)

    lf = lf.drop("_leap_seconds")

    if not keep_all:
        lf = lf.filter(pl.col("qc_valid"))
        cols_available = set(lf.collect_schema().names())
        cols_to_drop = cols_available.intersection(intermediate_cols) - retained
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
    """
    Calculate the Total Electron Content (TEC) from a Parquet file containing GNSS
    observations. Make sure the Parquet file contains necessary metadata such as
    sampling interval and receiver geodetic coordinates.

    Args:
        parquet_fn (str | Path): Path to the Parquet file.
        bias_fn (str | Path | Iterable[str | Path] | None, optional): Path(s) to the
            bias file(s). If provided, DCB biases will be applied to the TEC
            calculation. Defaults to None.
        config (TECConfig, optional): Configuration parameters for TEC calculation.
            Defaults to TECConfig().
        nav_fn (str | Path | Iterable[str | Path] | None, optional): Navigation
            file(s) for raw observations saved with header.to_metadata(). Required
            unless the stored observations already contain azimuth and elevation.

    Returns:
        pl.LazyFrame: A LazyFrame containing the calculated TEC values.
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
    """
    Calculate the Total Electron Content (TEC) from RINEX observation and navigation
    files.

    Args:
        obs_fn (str | Path | Iterable[str | Path]): Path(s) to the RINEX observation
            file(s). These files must be from the same station.
        nav_fn (str | Path | Iterable[str | Path]): Path(s) to the RINEX navigation
            file(s).
        bias_fn (str | Path | Iterable[str | Path] | None, optional): Path(s) to the
            bias file(s). If provided, DCB biases will be applied to the TEC
            calculation. Defaults to None.
        config (TECConfig, optional): Configuration parameters for TEC calculation.
            Defaults to TECConfig().
        station (str | None, optional): Custom station name to assign to the data. If
            None, the station name from the RINEX header is used. Defaults to None.

    Returns:
        pl.LazyFrame: A LazyFrame containing the calculated TEC values.
    """
    if config is None:
        config = TECConfig()
    header, lf = read_rinex_obs(obs_fn, config.constellations, station=station)

    return calc_tec_from_df(lf, header, bias_fn, config, nav_fn=nav_fn)
