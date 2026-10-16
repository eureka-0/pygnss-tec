# TEC Calculation

PyGNSS-TEC calculates TEC from RINEX files, Polars DataFrames or LazyFrames, and cached Parquet observations.
All calculation functions return a Polars LazyFrame and use the same configuration, quality control and calibration settings.
The following examples use the sample files shown in [Quick Start](../quick-start.md).

## From RINEX

Calculate TEC from observation, navigation and bias files:

```python
import gnss_tec as gt

obs = "data/rinex_obs_v3/CIBG00IDN_R_20240100000_01D_30S_MO.crx.gz"
nav = "data/rinex_nav_v3/BRDC00IGS_R_20240100000_01D_MN.rnx.gz"
bias = "data/bias/CAS0OPSRAP_20240100000_01D_01D_DCB.BIA.gz"

tec = gt.calc_tec_from_rinex(obs, nav, bias)
result = tec.collect(engine="in-memory")
```

You can omit the bias file to calculate uncorrected TEC.
In that case, satellite and receiver biases remain uncorrected and are not assumed to be zero.
The RINEX calculation function reads LLI for quality control even when diagnostic columns are omitted from the output.

## From a DataFrame or LazyFrame

Read the observations once, then pass the wide table and its header to `calc_tec_from_df`:

```python
header, observations = gt.read_rinex_obs(obs, include_lli=True)

# Apply any observation preprocessing while preserving keys and quality evidence.
tec = gt.calc_tec_from_df(observations, header, bias, nav_fn=nav)
result = tec.collect(engine="in-memory")
```

The input table must meet the following requirements:

- Use a wide layout with a unique combination of `time`, `station` and `prn` for each row.
- Store time as UTC-aware datetimes or timezone-naive GPS datetimes; other timezones are rejected.
- Supply navigation files unless the table already contains `azimuth` and `elevation` in degrees.

If receiver latitude and longitude columns are present, they take precedence over the header position.
Tables without LLI are accepted, but the calculation cannot use the missing recorded lock and half-cycle information.

## Cache observations in Parquet

You can save parsed observations to Parquet when repeating calculations with different settings.
Include the header metadata to preserve receiver history, sampling intervals and time/phase conventions:

```python
header, observations = gt.read_rinex_obs(obs, include_lli=True)
observations.sink_parquet("observations.parquet", metadata=header.to_metadata())

tec = gt.calc_tec_from_parquet("observations.parquet", bias, nav_fn=nav)
result = tec.collect(engine="in-memory")
```

Subsequent calls read the cached observations without decoding the original RINEX files again.
You still need navigation files unless the cached table contains the required geometry.
Polars preserves the `time` column's timezone, and `calc_tec_from_parquet` also requires the saved header metadata.

## Output and diagnostics

By default, the output contains rows accepted by quality control, with UTC time, station/satellite identifiers, selected `C1_code`/`C2_code`, receiver/IPP coordinates, azimuth/elevation and TEC values.
STEC and VTEC are expressed in TECU, and coordinates and angles are in degrees.
When a bias product is supplied, the output also includes `stec_dcb_corrected`.

Use `retain_diagnostics` to include selected diagnostic columns and `collect_schema()` to inspect the result:

```python
config = gt.TECConfig(retain_diagnostics=["mw", "qc_reason", "calibration_status"])
selected = gt.calc_tec_from_rinex(obs, nav, bias, config)
print(selected.collect_schema())
```

The `mw` column contains the Melbourne–Wübbena combination in wide-lane cycles.
The default output and list/tuple selections contain accepted rows only.
To include rejected rows and all available diagnostics, use:

```python
config = gt.TECConfig(retain_diagnostics="all")
diagnostic_result = gt.calc_tec_from_rinex(obs, nav, bias, config).collect(
    engine="in-memory"
)
rejected = diagnostic_result.filter(~diagnostic_result["qc_valid"])
```

Rejected rows include their rejection reasons and have null public TEC values.
Selecting diagnostic columns does not change detection, correction or calibration.
Internal bias-interval, leveling and weight columns are excluded even with `"all"`.
See [configuration](configuration.md#diagnostic-retention) for the available output options and [scientific conventions](scientific-conventions.md) for how to interpret calibration and continuity corrections.

## Execution and memory

You can select the Polars execution engine for internal queries and the final result:

```python
import polars as pl

with pl.Config(engine_affinity="in-memory"):
    tec = gt.calc_tec_from_rinex(obs, nav, bias)
    result = tec.collect(engine="in-memory")

tec.sink_parquet("tec.parquet", engine="streaming")
```

For data that fit in memory, start with `in-memory` and compare engine performance on your workload.
`pl.Config(engine_affinity=...)` controls internal queries as well as the final collection; setting the engine only in `collect` affects the final query.
Both engines keep observation data in memory, and the RINEX reader fully decodes the files before returning.
Streaming can reduce memory used by some intermediate operations, but RINEX decoding still requires memory for the full input.

If you split a calculation into parts, keep complete observation groups and arcs together.
The batch detector uses past and future observations, so independently processing arbitrary chunks loses the context at their boundaries.
Use `sink_parquet` to write the result without collecting the entire output into a Python-visible DataFrame.

The published [benchmark results](https://github.com/Eureka-0/pygnss-tec/blob/main/benchmarks/benchmark.md) include the measured workloads and environment.
See the [TEC API](../api/tec.md) for function parameters and input errors.
