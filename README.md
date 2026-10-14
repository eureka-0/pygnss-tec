# PyGNSS-TEC

[![PyPI - Version](https://img.shields.io/pypi/v/pygnss-tec)](https://pypi.org/project/pygnss-tec/)
![Supported Python Versions](https://img.shields.io/badge/python-%3E%3D3.12-blue)
![License](https://img.shields.io/badge/license-MIT-blue)
[![Test](https://github.com/Eureka-0/pygnss-tec/actions/workflows/test.yml/badge.svg)](https://github.com/Eureka-0/pygnss-tec/actions/workflows/test.yml)

PyGNSS-TEC is a high-performance Python package leveraging Rust acceleration, designed for processing and analyzing Total Electron Content (TEC) data derived from Global Navigation Satellite System (GNSS) observations. The package provides tools for RINEX file reading, TEC calculation, and DCB correction to support ionospheric studies.

> **Warning**: This package is under active development and may undergo significant changes. It is not recommended for production use until it reaches a stable release (v1.0.0).

## Features

- **RINEX File Reading**: Efficient reading and parsing of RINEX GNSS observation files using [rinex crate](https://crates.io/crates/rinex) (see [benchmarks](#benchmarks) for details).

- **Multiple File Formats**: Support for RINEX versions 2.x and 3.x, as well as Hatanaka compressed files (e.g., .Z, .crx, .crx.gz).

- **TEC Calculation**: Efficiently compute TEC from dual-frequency GNSS observations using [polars](https://pola.rs/) DataFrames and lazy evaluation (see [benchmarks](#benchmarks) for details).
- **Multi-GNSS Support**: Process observations from multiple GNSS constellations (see [Overview](#overview) for constellation support).

- **Open-Source**: Fully open-source under the MIT License, encouraging community contributions and collaboration.

## Installation

### Via pip

You can install PyGNSS-TEC via pip:

```bash
pip install pygnss-tec
```

### Via uv (recommended)

[uv](https://docs.astral.sh/uv/) is a modern Python package and project manager written in Rust. You can add PyGNSS-TEC to your uv project with:

```bash
uv add pygnss-tec
```

### From Source

Building from source requires Python 3.12 or later, Rust 1.88 or later (including Cargo), and uv:

```bash
git clone https://github.com/Eureka-0/pygnss-tec.git
cd pygnss-tec
uv run --with maturin maturin build --release

# Or enable custom memory allocation, which may improve performance but can increase memory usage
uv run --with maturin maturin build --release --features custom-alloc
```

The built package will be available in the `target/wheels` directory. You can then install it to your Python environment or uv project with:

```bash
# Using pip
pip install target/wheels/pygnss_tec-*.whl

# Or using uv
uv pip install target/wheels/pygnss_tec-*.whl
```

## Usage

### Overview

The following table summarizes the support for different GNSS constellations in PyGNSS-TEC:

| Constellation  | RINEX Reading  | TEC Calculation |
| -------------- | -------------- | --------------- |
| GPS (G)        | Yes            | Yes             |
| Beidou (C)     | Yes            | Yes             |
| Galileo (E)    | Yes            | No              |
| GLONASS (R)    | Yes            | No              |
| QZSS (J)       | Yes            | No              |
| IRNSS (I)      | Yes            | No              |
| SBAS (S)       | Yes            | No              |

The default TEC configuration supports GPS for RINEX 2, and GPS/BeiDou for RINEX 3.

### RINEX file reading

Read a RINEX observation file (supports RINEX v2.x, v3.x, and Hatanaka compressed files):

```python
import gnss_tec as gt

header, lf = gt.read_rinex_obs("./data/rinex_obs_v3/CIBG00IDN_R_20240100000_01D_30S_MO.crx.gz")

# You can read multiple files from the same station by passing a list of file paths
# header, lf = gt.read_rinex_obs(["./data/file1.crx.gz", "./data/file2.crx.gz"])
# Header metadata preserves receiver coordinates and identities for each file.

# header is a dataclass containing RINEX file header information
print(header)
# RinexObsHeader(version='3.04', constellation='MIXED', marker_name='CIBG', marker_type='GEODETIC', rx_ecef=(-1837003.1909, 6065631.1631, -716184.055), rx_geodetic=(-6.490367937958374, 106.84916836419953, 173.0000212144293), sampling_interval=30.0, leap_seconds=18, epoch_resolution='ns', epoch_events=(), receiver_id='6023R40127|TRIMBLE ALLOY|6.21', receiver_history=((1704844782000000000, (-1837003.1909, 6065631.1631, -716184.055), '6023R40127|TRIMBLE ALLOY|6.21'),))

# lf is a polars LazyFrame, you can collect it to get a DataFrame.
# By default, time is in UTC timezone. You can keep it in GPS time by passing `utc=False` to `read_rinex_obs`.
print(lf.collect())
# shape: (180_027, 72)
# ┌─────────────────────────┬─────────┬─────┬──────────┬───┬──────┬──────┬──────┬────────────┐
# │ time                    ┆ station ┆ prn ┆ C1C      ┆ … ┆ S7I  ┆ S7X  ┆ S8X  ┆ epoch_flag │
# │ ---                     ┆ ---     ┆ --- ┆ ---      ┆   ┆ ---  ┆ ---  ┆ ---  ┆ ---        │
# │ datetime[ns, UTC]       ┆ cat     ┆ cat ┆ f64      ┆   ┆ f64  ┆ f64  ┆ f64  ┆ u8         │
# ╞═════════════════════════╪═════════╪═════╪══════════╪═══╪══════╪══════╪══════╪════════════╡
# │ 2024-01-09 23:59:42 UTC ┆ CIBG    ┆ C01 ┆ null     ┆ … ┆ 44.1 ┆ null ┆ null ┆ 0          │
# │ 2024-01-09 23:59:42 UTC ┆ CIBG    ┆ C02 ┆ null     ┆ … ┆ 46.2 ┆ null ┆ null ┆ 0          │
# │ 2024-01-09 23:59:42 UTC ┆ CIBG    ┆ C03 ┆ null     ┆ … ┆ 46.3 ┆ null ┆ null ┆ 0          │
# │ 2024-01-09 23:59:42 UTC ┆ CIBG    ┆ C04 ┆ null     ┆ … ┆ 42.1 ┆ null ┆ null ┆ 0          │
# │ 2024-01-09 23:59:42 UTC ┆ CIBG    ┆ C05 ┆ null     ┆ … ┆ 41.3 ┆ null ┆ null ┆ 0          │
# │ …                       ┆ …       ┆ …   ┆ …        ┆ … ┆ …    ┆ …    ┆ …    ┆ …          │
# │ 2024-01-10 23:59:12 UTC ┆ CIBG    ┆ R16 ┆ 2.2936e7 ┆ … ┆ null ┆ null ┆ null ┆ 0          │
# │ 2024-01-10 23:59:12 UTC ┆ CIBG    ┆ R21 ┆ 2.1521e7 ┆ … ┆ null ┆ null ┆ null ┆ 0          │
# │ 2024-01-10 23:59:12 UTC ┆ CIBG    ┆ R22 ┆ 2.3833e7 ┆ … ┆ null ┆ null ┆ null ┆ 0          │
# │ 2024-01-10 23:59:12 UTC ┆ CIBG    ┆ S32 ┆ 3.6030e7 ┆ … ┆ null ┆ null ┆ null ┆ 0          │
# │ 2024-01-10 23:59:12 UTC ┆ CIBG    ┆ S37 ┆ 3.6282e7 ┆ … ┆ null ┆ null ┆ null ┆ 0          │
# └─────────────────────────┴─────────┴─────┴──────────┴───┴──────┴──────┴──────┴────────────┘
```

The full schema depends on the observation codes and reader options. The default wide layout includes the following fields; use `lf.collect_schema()` to inspect a particular file:

| Fields | Polars dtype | Meaning |
| --- | --- | --- |
| `time` | `Datetime('ns', 'UTC')` | Nanosecond epochs; `utc=False` returns timezone-naive GPS time at the same precision. |
| `station`, `prn` | `Categorical` | Station and satellite identifiers. |
| Observation codes, e.g. `C2I`, `L2I` | `Float64` | Values in the corresponding RINEX observation units. |
| `<signal>_lli` (with `include_lli=True`) | `UInt8` | Original lock indicators; missing indicators remain null. |
| `epoch_flag` | `UInt8` | Original RINEX epoch flag. |

With `pivot=False`, observations use `code` (`String`) and `value` (`Float64`); `include_lli=True` adds `lli` (`UInt8`). The default `include_lli=False` omits LLI in both layouts, including native buffers and Arrow fields. Enabling it returns companions for all selected codes and preserves raw bits/nulls without changing values, observation keys, epoch flags or header metadata. It does not reduce source-file I/O or upstream inline-indicator parsing. Both layouts contain only decoded observation fields and identifiers.

Receiver coordinates, receiver identity and special event records remain in header metadata. `receiver_history` records each file's first UTC epoch, original ECEF position and receiver identity; saving `header.to_metadata()` preserves this history for multi-file TEC calculation.

The `codes` argument accepts one regular expression or an iterable of patterns. Matching is case-sensitive and uses the complete observation code: literal names such as `"C1C"` still work, `"[CL]1.*"` selects code/phase observations on band 1, and `["C1C", "L[12].*"]` combines patterns. An empty selection or no match returns an empty frame; invalid patterns raise `ValueError`. The filter works with either pivot layout:

```python
header, lf = gt.read_rinex_obs(
    "./data/rinex_obs_v3/CIBG00IDN_R_20240100000_01D_30S_MO.crx.gz",
    codes="[CL]1.*",
    pivot=False,
)
print(lf.collect(engine="in-memory"))
# shape: (353_526, 6)
# ┌─────────────────────────┬─────────┬─────┬──────┬──────────┬────────────┐
# │ time                    ┆ station ┆ prn ┆ code ┆ value    ┆ epoch_flag │
# │ ---                     ┆ ---     ┆ --- ┆ ---  ┆ ---      ┆ ---        │
# │ datetime[ns, UTC]       ┆ cat     ┆ cat ┆ str  ┆ f64      ┆ u8         │
# ╞═════════════════════════╪═════════╪═════╪══════╪══════════╪════════════╡
# │ 2024-01-09 23:59:42 UTC ┆ CIBG    ┆ C20 ┆ C1X  ┆ 2.6626e7 ┆ 0          │
# │ 2024-01-09 23:59:42 UTC ┆ CIBG    ┆ C20 ┆ L1X  ┆ 1.3992e8 ┆ 0          │
# │ 2024-01-09 23:59:42 UTC ┆ CIBG    ┆ C23 ┆ C1X  ┆ 2.6088e7 ┆ 0          │
# │ 2024-01-09 23:59:42 UTC ┆ CIBG    ┆ C23 ┆ L1X  ┆ 1.3710e8 ┆ 0          │
# │ 2024-01-09 23:59:42 UTC ┆ CIBG    ┆ C27 ┆ C1X  ┆ 2.3733e7 ┆ 0          │
# │ …                       ┆ …       ┆ …   ┆ …    ┆ …        ┆ …          │
# │ 2024-01-10 23:59:12 UTC ┆ CIBG    ┆ R22 ┆ L1P  ┆ 1.2722e8 ┆ 0          │
# │ 2024-01-10 23:59:12 UTC ┆ CIBG    ┆ S32 ┆ C1C  ┆ 3.6030e7 ┆ 0          │
# │ 2024-01-10 23:59:12 UTC ┆ CIBG    ┆ S32 ┆ L1C  ┆ 1.8934e8 ┆ 0          │
# │ 2024-01-10 23:59:12 UTC ┆ CIBG    ┆ S37 ┆ C1C  ┆ 3.6282e7 ┆ 0          │
# │ 2024-01-10 23:59:12 UTC ┆ CIBG    ┆ S37 ┆ L1C  ┆ 1.9066e8 ┆ 0          │
# └─────────────────────────┴─────────┴─────┴──────┴──────────┴────────────┘
```

Navigation input belongs to TEC calculation. `read_rinex_obs` no longer accepts `nav_fn`; it does not produce satellite coordinates, azimuth/elevation, half-cycle validity or receiver state columns.

### TEC calculation

#### From RINEX files

Directly calculate from RINEX files using `calc_tec_from_rinex` function:

`stec`, `stec_dcb_corrected`, and `vtec` are in TECU. Receiver and IPP latitude/longitude are in degrees. TEC output times are UTC.

```python
tec_lf = gt.calc_tec_from_rinex(
    "./data/rinex_obs_v3/CIBG00IDN_R_20240100000_01D_30S_MO.crx.gz",
    "./data/rinex_nav_v3/BRDC00IGS_R_20240100000_01D_MN.rnx.gz",
    "./data/bias/CAS0OPSRAP_20240100000_01D_01D_DCB.BIA.gz",  # Optional DCB file, can be omitted if DCB correction is not needed
)

print(tec_lf.collect(engine="in-memory"))
# shape: (50_315, 14)
# ┌─────────────┬─────────┬─────┬───────────┬───┬────────────┬─────────────┬─────────────┬───────────┐
# │ time        ┆ station ┆ prn ┆ rx_lat    ┆ … ┆ ipp_lon    ┆ stec        ┆ stec_dcb_co ┆ vtec      │
# │ ---         ┆ ---     ┆ --- ┆ ---       ┆   ┆ ---        ┆ ---         ┆ rrected     ┆ ---       │
# │ datetime[ns ┆ cat     ┆ cat ┆ f64       ┆   ┆ f64        ┆ f64         ┆ ---         ┆ f64       │
# │ , UTC]      ┆         ┆     ┆           ┆   ┆            ┆             ┆ f64         ┆           │
# ╞═════════════╪═════════╪═════╪═══════════╪═══╪════════════╪═════════════╪═════════════╪═══════════╡
# │ 2024-01-09  ┆ CIBG    ┆ C01 ┆ -6.490368 ┆ … ┆ 110.041392 ┆ -64.909114  ┆ 37.638129   ┆ 28.38914  │
# │ 23:59:42    ┆         ┆     ┆           ┆   ┆            ┆             ┆             ┆           │
# │ UTC         ┆         ┆     ┆           ┆   ┆            ┆             ┆             ┆           │
# │ 2024-01-09  ┆ CIBG    ┆ C02 ┆ -6.490368 ┆ … ┆ 105.125745 ┆ -92.43084   ┆ 30.814723   ┆ 27.533463 │
# │ 23:59:42    ┆         ┆     ┆           ┆   ┆            ┆             ┆             ┆           │
# │ UTC         ┆         ┆     ┆           ┆   ┆            ┆             ┆             ┆           │
# │ 2024-01-09  ┆ CIBG    ┆ C03 ┆ -6.490368 ┆ … ┆ 107.102182 ┆ -100.673684 ┆ 27.121      ┆ 26.795374 │
# │ 23:59:42    ┆         ┆     ┆           ┆   ┆            ┆             ┆             ┆           │
# │ UTC         ┆         ┆     ┆           ┆   ┆            ┆             ┆             ┆           │
# │ 2024-01-09  ┆ CIBG    ┆ C05 ┆ -6.490368 ┆ … ┆ 102.127458 ┆ -80.385586  ┆ 37.75411    ┆ 23.567016 │
# │ 23:59:42    ┆         ┆     ┆           ┆   ┆            ┆             ┆             ┆           │
# │ UTC         ┆         ┆     ┆           ┆   ┆            ┆             ┆             ┆           │
# │ 2024-01-09  ┆ CIBG    ┆ C06 ┆ -6.490368 ┆ … ┆ 105.790572 ┆ -117.679878 ┆ 30.499514   ┆ 20.802595 │
# │ 23:59:42    ┆         ┆     ┆           ┆   ┆            ┆             ┆             ┆           │
# │ UTC         ┆         ┆     ┆           ┆   ┆            ┆             ┆             ┆           │
# │ …           ┆ …       ┆ …   ┆ …         ┆ … ┆ …          ┆ …           ┆ …           ┆ …         │
# │ 2024-01-10  ┆ CIBG    ┆ G18 ┆ -6.490368 ┆ … ┆ 107.007021 ┆ 66.073626   ┆ 24.891081   ┆ 19.597502 │
# │ 23:59:12    ┆         ┆     ┆           ┆   ┆            ┆             ┆             ┆           │
# │ UTC         ┆         ┆     ┆           ┆   ┆            ┆             ┆             ┆           │
# │ 2024-01-10  ┆ CIBG    ┆ G23 ┆ -6.490368 ┆ … ┆ 108.647786 ┆ 68.029699   ┆ 27.375494   ┆ 23.37039  │
# │ 23:59:12    ┆         ┆     ┆           ┆   ┆            ┆             ┆             ┆           │
# │ UTC         ┆         ┆     ┆           ┆   ┆            ┆             ┆             ┆           │
# │ 2024-01-10  ┆ CIBG    ┆ G25 ┆ -6.490368 ┆ … ┆ 109.935171 ┆ 69.761499   ┆ 36.578524   ┆ 27.235158 │
# │ 23:59:12    ┆         ┆     ┆           ┆   ┆            ┆             ┆             ┆           │
# │ UTC         ┆         ┆     ┆           ┆   ┆            ┆             ┆             ┆           │
# │ 2024-01-10  ┆ CIBG    ┆ G28 ┆ -6.490368 ┆ … ┆ 104.292903 ┆ 67.675466   ┆ 25.564254   ┆ 20.288658 │
# │ 23:59:12    ┆         ┆     ┆           ┆   ┆            ┆             ┆             ┆           │
# │ UTC         ┆         ┆     ┆           ┆   ┆            ┆             ┆             ┆           │
# │ 2024-01-10  ┆ CIBG    ┆ G31 ┆ -6.490368 ┆ … ┆ 102.960037 ┆ 73.016374   ┆ 30.592893   ┆ 20.972958 │
# │ 23:59:12    ┆         ┆     ┆           ┆   ┆            ┆             ┆             ┆           │
# │ UTC         ┆         ┆     ┆           ┆   ┆            ┆             ┆             ┆           │
# └─────────────┴─────────┴─────┴───────────┴───┴────────────┴─────────────┴─────────────┴───────────┘
```

The default output includes `time`, `station`, `prn`, `azimuth`, `elevation`, receiver/IPP coordinates, selected `C1_code`/`C2_code` and TEC values, on accepted rows. Geometry is in degrees. `epoch_flag`, `L1_lli`, `L2_lli`, `qc_valid`, `qc_reason` and `calibration_status` are optional diagnostics. Hiding calibration status does not imply absolute or fully calibrated TEC; the available products and calibration policy still determine corrections.

Use `TECConfig(retain_diagnostics=["qc_valid", "qc_reason", "calibration_status"])` for selected diagnostics or `retain_diagnostics="all"` for all available diagnostics and rejected rows with null public TEC. List/tuple selection still returns only accepted rows. `retain_diagnostics=["mw"]` (or `("mw",)`) selects the Melbourne–Wübbena combination in wide-lane cycles; basic QC checks its finiteness but does not detect unflagged slips with it. Internal fields `tx_bias_start`, `tx_bias_end`, `rx_bias_start`, `rx_bias_end`, `level_id`, `offset` and `weight` are unavailable in every mode; unsupported names raise `ValueError`. `weight = sin²(elevation)` remains the internal dimensionless leveling weight. Use `tec_lf.collect_schema()` to inspect available fields. See [Observation quality and scientific conventions](#observation-quality-and-scientific-conventions) for diagnostic and calibration meanings.

#### From DataFrame or LazyFrame

If you wish to calculate TEC from an existing polars DataFrame or LazyFrame (e.g., after some custom preprocessing), you can use the `calc_tec_from_df` function:

```python
header, lf = gt.read_rinex_obs(
    "./data/rinex_obs_v3/CIBG00IDN_R_20240100000_01D_30S_MO.crx.gz",
    include_lli=True,
)

# ...
# Perform any custom preprocessing on lf if needed
# ...

tec_lf = gt.calc_tec_from_df(
    lf,
    header,
    "./data/bias/CAS0OPSRAP_20240100000_01D_01D_DCB.BIA.gz",
    nav_fn="./data/rinex_nav_v3/BRDC00IGS_R_20240100000_01D_MN.rnx.gz",
)
```

#### From parquet file

RINEX parsing often accounts for most of the processing time. When calculating TEC repeatedly from the same observations (e.g., when tuning configuration), save the parsed observations to Parquet and use `calc_tec_from_parquet`. This avoids decoding observations again; navigation and geometry are prepared inside TEC calculation:

```python
header, lf = gt.read_rinex_obs(
    "./data/rinex_obs_v3/CIBG00IDN_R_20240100000_01D_30S_MO.crx.gz",
    include_lli=True,
)

# ...
# Perform any custom preprocessing on lf if needed
# ...

# Note: Make sure to include header information when saving to parquet. Polars also
# preserves whether the time column is timezone-aware UTC or timezone-naive GPS time.
lf.sink_parquet("./data/cibg_obs_2024010.parquet", metadata=header.to_metadata())

tec_lf = gt.calc_tec_from_parquet(
    "./data/cibg_obs_2024010.parquet",
    "./data/bias/CAS0OPSRAP_20240100000_01D_01D_DCB.BIA.gz",
    nav_fn="./data/rinex_nav_v3/BRDC00IGS_R_20240100000_01D_MN.rnx.gz",
)
```

#### Execution engines

For data that fit comfortably in memory, use `in-memory`. Compare both engines for your workload; see the [benchmarks](benchmarks/benchmark.md).

```python
tec_df = tec_lf.collect(engine="in-memory")

# Alternatively, run the same calculation with the streaming engine.
tec_df = tec_lf.collect(engine="streaming")
```

To select the engine for internal queries as well, wrap the calculation call in `pl.Config(engine_affinity="in-memory")`.

Streaming can reduce some intermediate memory use, but RINEX reading and TEC calculation still require observation data in memory. RINEX files are fully loaded before their LazyFrame is returned. Choosing `streaming` cannot make an oversized raw RINEX input fit in memory; prepare a scan-based input or use batches that preserve complete arcs. Compare both engines for large workloads.

If the TEC output is also too large to collect, write it with `tec_lf.sink_parquet("tec.parquet", engine="streaming")`.

#### Configuration

You can customize the TEC calculation process using the `TECConfig` dataclass:

```python
print(gt.TECConfig())

# TECConfig(
#     constellations='CG',
#     ipp_height=400,
#     min_elevation=30.0,
#     min_snr=30.0,
#     c1_codes={
#         '2': {'G': ['C1']}, 
#         '3': {'C': ['C2I', 'C2D', 'C2X', 'C1I', 'C1D', 'C1X', 'C2W', 'C1C'], 'G': ['C1W', 'C1C', 'C1X']}
#     },
#     c2_codes={
#         '2': {'G': ['C2', 'C5']}, 
#         '3': {'C': ['C6I', 'C6D', 'C6X', 'C7I', 'C7D', 'C7X', 'C5I', 'C5D', 'C5X'], 'G': ['C2W', 'C2C', 'C2X', 'C5W', 'C5C', 'C5X']}
#     },
#     rx_bias='external',
#     mapping_function='slm',
#     retain_diagnostics=None,
#     missing_bias='drop'
# )
```

The meaning of each parameter is as follows:

- `constellations`: A string specifying which GNSS constellations to consider for TEC calculation. 'C' for Beidou, 'G' for GPS.
- `ipp_height`: The assumed height of the ionospheric pierce point (IPP) in kilometers.
- `min_elevation`: The minimum satellite elevation angle (in degrees) for observations to be considered in the TEC calculation.
- `min_snr`: The minimum signal-to-noise ratio (in dB-Hz) for observations to be considered in the TEC calculation.
- `c1_codes`: Ordered preferences for the first frequency, by RINEX version and constellation. Selection also considers available code/phase measurements and bias coverage. Partial overrides are supported, e.g., `c1_codes={'3': {'C': [...]}}` changes only the BeiDou RINEX 3 preferences.
- `c2_codes`: A dictionary specifying the preferred observation codes for the second frequency (C2) for each RINEX version and constellation, similar to `c1_codes`.
- `rx_bias`: Specifies how to handle receiver bias. It can be set to 'external' to use an external DCB file for correction, 'mstd' to use the minimum standard deviation method for estimation, 'lsq' to use least squares estimation, or `None` to skip receiver bias correction. Note that the receiver bias estimation is only applicable after the satellite bias has been corrected using an external DCB file (e.g., from IGS). If no external DCB file is provided, this parameter will be ignored. The 'mstd' and 'lsq' methods are for stations that are not included in the external DCB file.
- `mapping_function`: The mapping function to use for converting slant TEC to vertical TEC. It can be set to 'slm' for the Single Layer Model or 'mslm' for the Modified Single Layer Model.
- `retain_diagnostics`: `None` returns base results and geometry; a list/tuple adds supported diagnostics (for example `['mw']`, `['mf', 'stec_p_raw']` or `['calibration_status']`). These modes return only accepted rows. `'all'` also keeps rejected rows with null public TEC and `qc_reason`. Leveling/weight/bias-interval fields are always private. This replaces `retain_intermediate`; the old constructor keyword is no longer accepted.
- `missing_bias`: Specifies how to handle observations whose satellite or receiver bias cannot be matched from the provided DCB file. `'drop'` rejects them, `'warn'` also emits a warning, `'keep_uncorrected'` applies only the available corrections and marks the result `uncorrected_missing_bias`, and `'error'` fails immediately. Rejected rows remain inspectable with `retain_diagnostics='all'`.

When using `calc_tec_from_df` or `calc_tec_from_parquet`, the time scale is expressed by the Polars `time` column type. Use timezone-aware UTC datetimes for UTC time, and timezone-naive datetimes for GPS time. Parquet preserves this timezone information, so saved observation files keep the same UTC/GPS semantics when read back. Other timezones are rejected to avoid ambiguous UTC/GPS conversions.

### Observation quality and scientific conventions

Observation times use nanosecond precision, and sampling intervals are in seconds. Parquet preserves the time scale and RINEX header metadata.

Request `read_rinex_obs(..., include_lli=True)` to retain raw lock indicators as `<signal>_lli` in wide format or `lli` in long format. `epoch_flag` remains available independently of this option. RINEX-to-TEC enables LLI automatically for QC even when the final output hides the diagnostic columns. DataFrame/Parquet inputs without LLI remain accepted, but recorded loss-of-lock/half-cycle information cannot be reconstructed. Preserve version-specific raw bits: RINEX 2 wavelength-factor and RINEX 3 half-cycle meanings differ. Their definitions follow the [RINEX format specification](https://files.igs.org/pub/data/format/rinex305.pdf).

TEC preserves the original carrier phase. Basic quality checks cover observation and geometry validity, SNR, elevation and recorded lock/epoch flags. Data gaps, signal changes and receiver events can start new arcs. Unflagged phase jumps are not automatically detected. Provide a known sampling interval when cadence cannot be inferred consistently.

External correction supports constant code DSB products in nanoseconds and GPS time, as defined by [Bias-SINEX](https://files.igs.org/pub/data/format/sinex_bias_100.pdf). Bias intervals must be valid and non-overlapping.

Bias corrections are applied before code-to-phase leveling. `stec` retains the uncorrected STEC relationship; `stec_dcb_corrected` and `vtec` include the available corrections. `arc_id` identifies an observation arc, while `level_id` also separates bias validity intervals. Failed receiver-bias estimation produces null TEC values.

`calibration_status` records the correction actually available:

| Status | Meaning |
| --- | --- |
| `uncorrected_no_bias_product` | No external bias product was provided. |
| `uncorrected_missing_bias` | Some required external biases were missing; only available corrections were applied. |
| `satellite_code_corrected` | Satellite code bias was corrected; receiver bias was left uncorrected. |
| `external_code_corrected` | Both satellite and receiver code biases were corrected externally. |
| `satellite_code_corrected_receiver_mstd_estimated` / `satellite_code_corrected_receiver_lsq_estimated` | Satellite code bias was corrected and receiver bias was estimated successfully. |
| `receiver_estimation_failed` | Receiver estimation had insufficient usable support or failed; public TEC values are null. |

Results without complete bias corrections are relative or partially corrected products. TEC currently supports GPS and BeiDou; additional constellations and advanced quality checks are tracked in [ROADMAP.md](ROADMAP.md).

## Benchmarks

See [benchmarks/benchmark.md](benchmarks/benchmark.md) for streaming and in-memory benchmark results.

This file is generated by `benchmarks/bench.py`. Regenerate the tables, including the four two-day station cases, with:

```bash
uv run benchmarks/bench.py --multiday
```

`read` measures raw observation decoding, `read-and-TEC` includes navigation and geometry preparation, and `TEC-only` uses observations and geometry already in memory. File sizes refer to on-disk observation files. Detailed environment metadata and individual timing samples can be exported with `--json-output PATH`.
