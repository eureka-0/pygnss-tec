# Configuration

Use `TECConfig` to select signals, geometry settings, quality thresholds, calibration and diagnostic output.
Pass the configuration to any TEC calculation function, or omit it to create a fresh configuration with the default settings.
Parameters are supplied by keyword, and configuration objects are frozen.
Supplied code mappings are copied, although their nested contents remain mutable.
See the [configuration API](../api/configuration.md) for all defaults, field descriptions and validation rules.

## Geometry and observation quality

Set the constellations, mapping model and quality thresholds when creating a configuration:

```python
import gnss_tec as gt

config = gt.TECConfig(
    constellations="CG",
    ipp_height=400.0,
    min_elevation=30.0,
    min_snr=30.0,
    mapping_function="slm",
)
```

TEC calculation supports `C` (BeiDou) and `G` (GPS), and accepts either uppercase or lowercase letters.
The default code preferences for RINEX 2 include GPS pairs only.
Specify `min_elevation` in degrees and `min_snr` in dB-Hz.
The SLM shell height is expressed in kilometers; MSLM uses a fixed height and angular factor.
See [scientific conventions](scientific-conventions.md) for the mapping assumptions and how missing SNR values are handled.

## Signal preferences

Use `c1_codes` and `c2_codes` to specify observation code preferences for each RINEX major version and constellation.
The calculation selects the first complete code and phase pair that meets the QC and bias-coverage requirements.
The two selections must use supported, distinct frequency bands.

For example, set the preferred GPS codes for RINEX 3:

```python
config = gt.TECConfig(
    constellations="G",
    c1_codes={"3": {"G": ["C1C", "C1W"]}},
    c2_codes={"3": {"G": ["C2W", "C2C"]}},
)
```

You only need to supply the versions and constellations you want to change; unspecified entries retain their defaults.
A supplied code list replaces the default list for that constellation.
These preferences select among supported signals and do not add new constellation or signal-mode support.
See [TECConfig](../api/configuration.md#gnss_tec.TECConfig) for the complete defaults.

## Calibration

Use `rx_bias` to choose how receiver code bias is handled after satellite correction with a supplied bias product:

| Value | Behavior |
|---|---|
| `"external"` | Match receiver corrections from the external product. |
| `"mstd"` | Estimate receiver bias by minimum standard deviation. |
| `"lsq"` | Estimate receiver bias by least squares. |
| `None` | Leave receiver bias uncorrected. |

If no bias product is supplied, this option has no effect and the result remains uncorrected.
If receiver bias estimation fails, the output records a failure status and leaves public TEC values null instead of applying a zero correction.

Use `missing_bias` to choose what happens when a supplied product lacks a required satellite or receiver match:

| Value | Behavior |
|---|---|
| `"drop"` | Reject unmatched rows. |
| `"warn"` | Reject unmatched rows and emit a warning. |
| `"keep_uncorrected"` | Apply available corrections and record incomplete calibration. |
| `"error"` | Raise immediately. |

Check [calibration status](scientific-conventions.md#bias-correction-and-calibration) to determine which corrections were applied.
A non-null TEC value can still be uncorrected or partially corrected.

## Continuity mode

Use `cycle_slip_mode` to choose how phase discontinuities are handled:

| `cycle_slip_mode` | Behavior |
|---|---|
| `"repair"` (default) | Localize GF/MW and recorded-boundary discontinuities, correct working phase, then align final STEC products in time. |
| `"detect"` | Localize and split without numerical phase correction. |
| `"basic"` | Use recorded lock/event/gap QC and per-arc leveling without GF/MW localization. |

All modes preserve the raw observations.
The repair mode uses ordinary rates from neighboring past and future intervals, so it processes observations as an offline batch.
It aligns every localized edge; code observations, noise estimates and integer constraints do not reject a correction.
The correction does not recover per-carrier integers or identify the physical cause of an event.
See [quality and continuity](scientific-conventions.md#quality-and-continuity) for the method and its limits when studying ionospheric structure.

## Diagnostic retention

Use `retain_diagnostics` to include the diagnostic columns needed for your analysis:

```python
config = gt.TECConfig(retain_diagnostics=["mw", "qc_reason", "calibration_status"])
```

| `retain_diagnostics` | Rows and columns |
|---|---|
| `None` | Accepted rows with base results and azimuth/elevation. |
| A list or tuple | Accepted rows plus the named supported diagnostics. |
| `"all"` | All available diagnostics, including rejected rows with null public TEC. |

The default output omits `epoch_flag`, `L1_lli`, `L2_lli`, `qc_valid`, `qc_reason` and `calibration_status`; include them by name or select `"all"`.
You can also select `mw`, which is expressed in wide-lane cycles.
Bias diagnostics are available when bias inputs are supplied.
Geometry is always included, and selecting output columns does not change the calculation.

The internal columns `tx_bias_start`, `tx_bias_end`, `rx_bias_start`, `rx_bias_end`, `level_id`, `offset` and `weight` are excluded in every mode.
Selecting an unsupported diagnostic name raises `ValueError`.
The former `retain_intermediate` constructor argument is no longer accepted.
See [DIAGNOSTIC_COLUMNS](../api/configuration.md#gnss_tec.DIAGNOSTIC_COLUMNS) for all supported diagnostic names.
