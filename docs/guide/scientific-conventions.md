# Scientific Conventions

This page describes the time systems, units, quality control and calibration used in TEC calculation.
When interpreting the results, consider the selected signals, QC settings, calibration status and processing mode.
Diagnostic columns are omitted by default, so the output alone does not show whether calibration is complete or physical ionospheric structure has been preserved.

## Supported scope

TEC calculation currently supports GPS and BeiDou, with GPS code preferences provided by default for RINEX 2.
The RINEX reader can decode observations from additional constellations, but these are not currently supported for TEC calculation.
See the [Roadmap](https://github.com/Eureka-0/pygnss-tec/blob/main/ROADMAP.md) for planned signal modes and reliability improvements.

## Time and units

| Quantity | Convention |
|---|---|
| TEC | STEC/VTEC in TECU; $1\,\mathrm{TECU} = 10^{16}\,\mathrm{electrons}/\mathrm{m}^{2}$. |
| Receiver and IPP latitude/longitude | Degrees. |
| Azimuth and elevation | Degrees. |
| `TECConfig.ipp_height` | Kilometers. |
| Raw code and carrier phase | Original RINEX units; code in meters and ordinary carrier phase in cycles. |
| `mw` | Melbourne–Wübbena combination in wide-lane cycles. |
| Phase/final-STEC continuity offsets | TECU. |

By default, the reader returns UTC-aware timestamps with nanosecond resolution.
Use `read_rinex_obs(..., utc=False)` to return timezone-naive GPS timestamps.
For TEC calculation from a DataFrame or Parquet file, UTC-aware datetimes are interpreted as UTC and timezone-naive datetimes as GPS; other timezones are rejected.
TEC results always use UTC.
Parquet preserves the Polars timezone information, while `header.to_metadata()` preserves the accompanying RINEX metadata.
Fractional sampling intervals retain their precision and are not rounded to integer seconds.

## Header changes and broadcast navigation

The reader does not apply dynamic observation headers.
Flag-3/4 header records other than COMMENT, including unknown or malformed labels, raise `ValueError` before observations are returned.
Changes to observation order/count, scale/phase/wavelength conventions, time declarations and receiver/site/antenna metadata cannot silently reuse the initial header.
Recognized significant header fields in other special events are also rejected.
Errors identify the source file, event epoch (or an untimed event) and field label.
Split or normalize these files with the correct effective headers before processing.
COMMENT-only and empty events retain their existing behavior; harmless blank-epoch events are consumed without inventing a timestamp or receiver state.
The same checks apply to gzip/Hatanaka, wide/long layouts, both LLI settings and multi-file input.

Broadcast selection filters unhealthy or expired records before selecting the nearest reference epoch.
Equal-distance and duplicate eligible records retain source-order precedence; an invalid nearest record cannot hide an eligible alternative.
Absolute time differences use the constellation's broadcast time scale, without reducing a year-old difference modulo one week.

| Broadcast system | Maximum absolute difference from toe | Additional rules |
|---|---|---|
| GPS | 2 hours, inclusive | A positive RINEX fit interval in hours narrows the limit to half that interval; a missing/zero interval retains the 2-hour cap. |
| BeiDou | 6 hours, inclusive | toe uses BDT and the broadcast week. |
| Galileo | 3 hours, inclusive | All broadcast health/data-validity bits must be clear because geometry has no signal selector. |
| GLONASS | 900 seconds from the broadcast reference epoch, inclusive | Retain the validated state-vector propagation window. |
| QZSS, SBAS and unsupported toe representations | Unavailable | Propagation is not supported by the current implementation. |

Kepler records require finite toe in `[0, 604800)` and a parsed broadcast week; absent health or invalid validity fields make a record ineligible.
GPS/BeiDou/GLONASS health follows the parsed broadcast flags.
The age caps follow the pinned parser's policies, narrowed by the supported fit rules above; they do not certify orbit accuracy throughout each interval.
See [RINEX 3.05](https://files.igs.org/pub/data/format/rinex305.pdf) for field meanings and [RTKLIB](https://github.com/tomojitakasu/RTKLIB/blob/master/src/rtklib.h) for the corresponding constellation-specific age caps.
Retrospective selection permits future reference epochs inside these windows and does not assert that a message was already available in real time.
When no eligible record exists, `compute_az_el` returns null angles and the TEC path rejects those rows; requesting all diagnostics retains them with null public TEC.
`NavigationData.epoch_range` describes file coverage rather than per-record validity.

## Quality and continuity

LLI records loss-of-lock and phase-state information from the original RINEX observations.
Set `include_lli=True` when reading observations to retain `<code>_lli` in wide output or `lli` in long output.
The RINEX-to-TEC function enables this automatically.
DataFrame and Parquet inputs without LLI are accepted, but the calculation cannot reconstruct the missing recorded information.
The original bits are preserved, including the different wavelength-factor and half-cycle meanings in RINEX 2 and RINEX 3.
See the [RINEX specification](https://files.igs.org/pub/data/format/rinex305.pdf) for the format definitions.

Basic quality control checks observation and geometry validity, SNR, elevation, and recorded lock and epoch state.
Data gaps, rejected rows, signal or frequency changes, and receiver events can start a new arc.
When all diagnostics are requested, invalid or half-cycle rows are retained with null public TEC values.
The original carrier observations are preserved in every mode.

The SNR check groups observations by station and selected code pair, and evaluates each band separately.
Null SNR values are accepted only when more than half the group's values on that band are null.
Otherwise, rows with null SNR are rejected, as are rows with recorded nonfinite or below-threshold SNR.
Code-to-phase leveling uses the internal dimensionless weight:

$$
w = \sin^2 e.
$$

Here, $e$ is the satellite elevation.
SNR filtering and code-to-phase leveling are separate from cycle-slip detection.

The default `cycle_slip_mode="repair"` processes discontinuities in the following steps:

1. Locate discontinuities using GF/MW and recorded boundary information.
2. Estimate ordinary time rates from the nearest non-event intervals on each side, searching up to 32 intervals and falling back to a one-sided estimate or zero rate when needed.
3. Apply cumulative continuity offsets to the working phase, then independently align the final raw and calibrated STEC after code leveling.

This method uses future observations and is intended for offline batch processing.
It uses temporal continuity at localized edges as the correction criterion, without rejecting an alignment based on code observations, MW ambiguity, integer conventions or uncertainty.
As a result, a genuine physical step can also be aligned, while an undetected slip remains in the output.
Sensitivity to small or equal carrier slips is limited, and natural discontinuities do not have externally established cause labels.
A smooth result therefore does not establish integer ambiguity recovery or preservation of every physical ionospheric feature.

Use `"detect"` to locate discontinuities and split arcs without numerical correction, or `"basic"` to use recorded QC and per-arc leveling.
These modes still apply code-phase leveling and calibration; their output is not raw observation data.
The `arc_id` column records physical arc boundaries.
You can request phase, raw-STEC and calibrated-STEC correction diagnostics to inspect the applied offsets; carrier integer diagnostics remain null.
Selecting diagnostic columns is independent of the processing mode.

## Bias correction and calibration

External correction supports constant code DSB products expressed in nanoseconds with GPS validity times.
Validity intervals are half-open; overlapping intervals, nonzero slopes and unsupported bias semantics are rejected.
See [Bias-SINEX](https://files.igs.org/pub/data/format/sinex_bias_100.pdf) for the exchange format.
`read_bias` decodes the product, but TEC correction accepts only records that meet these requirements.

The calculation corrects external code biases before code-to-phase leveling, using an independent code-reference estimate for each bias validity interval.
In repair mode, it then aligns the final `stec` and `stec_dcb_corrected` independently at localized discontinuities and bias-reference boundaries.
The difference between these columns can therefore include alignment offsets as well as the original DCB corrections.
VTEC uses the aligned calibrated STEC when available, or the aligned uncalibrated STEC otherwise.
The `slip_stec_correction` and `slip_dcb_correction` diagnostics contain these additional per-event offsets in TECU.

Request `calibration_status` to check which corrections were applied:

| Status | Meaning |
|---|---|
| `uncorrected_no_bias_product` | No external bias product was supplied. |
| `uncorrected_missing_bias` | Some required biases were missing; only available corrections were applied. |
| `satellite_code_corrected` | Satellite code bias was corrected; receiver bias was not. |
| `external_code_corrected` | Satellite and receiver code biases were corrected externally. |
| `satellite_code_corrected_receiver_mstd_estimated` | Satellite correction and MSTD receiver estimation succeeded. |
| `satellite_code_corrected_receiver_lsq_estimated` | Satellite correction and LSQ receiver estimation succeeded. |
| `receiver_estimation_failed` | Estimation lacked usable support or failed; public TEC is null. |

Results with absent or incomplete bias corrections remain relative or partially corrected TEC products.
Receiver bias estimation follows satellite correction, and a failed estimate is never treated as zero bias.
MSTD requires the existing simultaneous night-time support and numerically distinct within-epoch inverse mapping factors; flat objectives, failed optimization and solutions at the +/-500 TECU search bounds fail explicitly.
LSQ scales its nuisance basis and checks whether the receiver coefficient is distinguishable from that basis using SVD.
Redundant nuisance columns alone do not invalidate an independently identifiable receiver coefficient; roundoff-only columns are not amplified into artificial information.
The relative separation floor is the square root of floating-point machine epsilon after normalization; the SVD rank tolerance also accounts for matrix size.
These are numerical identifiability checks, not a statistical uncertainty estimate or independent validation of the ionospheric model.
Failed estimates emit a `RuntimeWarning` naming the method and reason, retain null `rx_bias` and public TEC under `receiver_estimation_failed`, and cannot be recovered as accepted products by final continuity alignment.
See the [configuration guide](configuration.md#calibration) for receiver bias options and how missing products are handled.

## Mapping assumptions

SLM and MSLM use thin-shell models to map slant TEC to vertical TEC.
SLM uses the configured `ipp_height`, while MSLM uses a fixed height of 506.7 km and a dimensionless angular factor of 0.9782.
These settings describe the assumed model and do not measure the effective ionospheric height.
When reporting an analysis, include the mapping model and settings together with the selected signals, calibration status, QC settings and continuity mode.
