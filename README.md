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
# shape: (180_027, 140)
# ┌─────────────────────┬─────────┬─────┬──────────┬───┬─────────┬─────────┬─────────┬────────────┐
# │ time                ┆ station ┆ prn ┆ C1C      ┆ … ┆ S7I_lli ┆ S7X_lli ┆ S8X_lli ┆ epoch_flag │
# │ ---                 ┆ ---     ┆ --- ┆ ---      ┆   ┆ ---     ┆ ---     ┆ ---     ┆ ---        │
# │ datetime[ns, UTC]   ┆ cat     ┆ cat ┆ f64      ┆   ┆ u8      ┆ u8      ┆ u8      ┆ u8         │
# ╞═════════════════════╪═════════╪═════╪══════════╪═══╪═════════╪═════════╪═════════╪════════════╡
# │ 2024-01-09 23:59:42 ┆ CIBG    ┆ C01 ┆ null     ┆ … ┆ null    ┆ null    ┆ null    ┆ 0          │
# │ UTC                 ┆         ┆     ┆          ┆   ┆         ┆         ┆         ┆            │
# │ 2024-01-09 23:59:42 ┆ CIBG    ┆ C02 ┆ null     ┆ … ┆ null    ┆ null    ┆ null    ┆ 0          │
# │ UTC                 ┆         ┆     ┆          ┆   ┆         ┆         ┆         ┆            │
# │ 2024-01-09 23:59:42 ┆ CIBG    ┆ C03 ┆ null     ┆ … ┆ null    ┆ null    ┆ null    ┆ 0          │
# │ UTC                 ┆         ┆     ┆          ┆   ┆         ┆         ┆         ┆            │
# │ 2024-01-09 23:59:42 ┆ CIBG    ┆ C04 ┆ null     ┆ … ┆ null    ┆ null    ┆ null    ┆ 0          │
# │ UTC                 ┆         ┆     ┆          ┆   ┆         ┆         ┆         ┆            │
# │ 2024-01-09 23:59:42 ┆ CIBG    ┆ C05 ┆ null     ┆ … ┆ null    ┆ null    ┆ null    ┆ 0          │
# │ UTC                 ┆         ┆     ┆          ┆   ┆         ┆         ┆         ┆            │
# │ …                   ┆ …       ┆ …   ┆ …        ┆ … ┆ …       ┆ …       ┆ …       ┆ …          │
# │ 2024-01-10 23:59:12 ┆ CIBG    ┆ R16 ┆ 2.2936e7 ┆ … ┆ null    ┆ null    ┆ null    ┆ 0          │
# │ UTC                 ┆         ┆     ┆          ┆   ┆         ┆         ┆         ┆            │
# │ 2024-01-10 23:59:12 ┆ CIBG    ┆ R21 ┆ 2.1521e7 ┆ … ┆ null    ┆ null    ┆ null    ┆ 0          │
# │ UTC                 ┆         ┆     ┆          ┆   ┆         ┆         ┆         ┆            │
# │ 2024-01-10 23:59:12 ┆ CIBG    ┆ R22 ┆ 2.3833e7 ┆ … ┆ null    ┆ null    ┆ null    ┆ 0          │
# │ UTC                 ┆         ┆     ┆          ┆   ┆         ┆         ┆         ┆            │
# │ 2024-01-10 23:59:12 ┆ CIBG    ┆ S32 ┆ 3.6030e7 ┆ … ┆ null    ┆ null    ┆ null    ┆ 0          │
# │ UTC                 ┆         ┆     ┆          ┆   ┆         ┆         ┆         ┆            │
# │ 2024-01-10 23:59:12 ┆ CIBG    ┆ S37 ┆ 3.6282e7 ┆ … ┆ null    ┆ null    ┆ null    ┆ 0          │
# │ UTC                 ┆         ┆     ┆          ┆   ┆         ┆         ┆         ┆            │
# └─────────────────────┴─────────┴─────┴──────────┴───┴─────────┴─────────┴─────────┴────────────┘
```

The full schema depends on the observation codes and reader options. The default wide layout includes the following fields; use `lf.collect_schema()` to inspect a particular file:

| Fields | Polars dtype | Meaning |
| --- | --- | --- |
| `time` | `Datetime('ns', 'UTC')` | Nanosecond epochs; `utc=False` returns timezone-naive GPS time at the same precision. |
| `station`, `prn` | `Categorical` | Station and satellite identifiers. |
| Observation codes, e.g. `C2I`, `L2I` | `Float64` | Values in the corresponding RINEX observation units. |
| `<signal>_lli` | `UInt8` | Original loss-of-lock indicators; missing indicators remain null. |
| `epoch_flag` | `UInt8` | Original RINEX epoch flag. |

With `pivot=False`, observation values and indicators use `code` (`String`), `value` (`Float64`) and `lli` (`UInt8`). Both layouts contain only decoded RINEX observation fields and identifiers. Time conversion and an explicit `station` override retain their existing behavior.

Receiver coordinates, receiver identity and special event records remain in header metadata. `receiver_history` records each file's first UTC epoch, original ECEF position and receiver identity; saving `header.to_metadata()` preserves this history for multi-file TEC calculation.

The `codes` argument accepts one regular expression or an iterable of patterns. Matching is case-sensitive and uses the complete observation code: literal names such as `"C1C"` still work, `"[CL]1.*"` selects code/phase observations on band 1, and `["C1C", "L[12].*"]` combines patterns. An empty selection or no match returns an empty frame; invalid patterns raise `ValueError`. The filter works with either pivot layout:

```python
header, lf = gt.read_rinex_obs(
    "./data/rinex_obs_v3/CIBG00IDN_R_20240100000_01D_30S_MO.crx.gz",
    codes="[CL]1.*",
    pivot=False,
)
print(lf.collect(engine="in-memory"))
# shape: (353_526, 7)
# ┌─────────────────────────┬─────────┬─────┬──────┬──────────┬──────┬────────────┐
# │ time                    ┆ station ┆ prn ┆ code ┆ value    ┆ lli  ┆ epoch_flag │
# │ ---                     ┆ ---     ┆ --- ┆ ---  ┆ ---      ┆ ---  ┆ ---        │
# │ datetime[ns, UTC]       ┆ cat     ┆ cat ┆ str  ┆ f64      ┆ u8   ┆ u8         │
# ╞═════════════════════════╪═════════╪═════╪══════╪══════════╪══════╪════════════╡
# │ 2024-01-09 23:59:42 UTC ┆ CIBG    ┆ C20 ┆ C1X  ┆ 2.6626e7 ┆ null ┆ 0          │
# │ 2024-01-09 23:59:42 UTC ┆ CIBG    ┆ C20 ┆ L1X  ┆ 1.3992e8 ┆ 1    ┆ 0          │
# │ 2024-01-09 23:59:42 UTC ┆ CIBG    ┆ C23 ┆ C1X  ┆ 2.6088e7 ┆ null ┆ 0          │
# │ 2024-01-09 23:59:42 UTC ┆ CIBG    ┆ C23 ┆ L1X  ┆ 1.3710e8 ┆ null ┆ 0          │
# │ 2024-01-09 23:59:42 UTC ┆ CIBG    ┆ C27 ┆ C1X  ┆ 2.3733e7 ┆ null ┆ 0          │
# │ …                       ┆ …       ┆ …   ┆ …    ┆ …        ┆ …    ┆ …          │
# │ 2024-01-10 23:59:12 UTC ┆ CIBG    ┆ R22 ┆ L1P  ┆ 1.2722e8 ┆ null ┆ 0          │
# │ 2024-01-10 23:59:12 UTC ┆ CIBG    ┆ S32 ┆ C1C  ┆ 3.6030e7 ┆ null ┆ 0          │
# │ 2024-01-10 23:59:12 UTC ┆ CIBG    ┆ S32 ┆ L1C  ┆ 1.8934e8 ┆ null ┆ 0          │
# │ 2024-01-10 23:59:12 UTC ┆ CIBG    ┆ S37 ┆ C1C  ┆ 3.6282e7 ┆ null ┆ 0          │
# │ 2024-01-10 23:59:12 UTC ┆ CIBG    ┆ S37 ┆ L1C  ┆ 1.9066e8 ┆ null ┆ 0          │
# └─────────────────────────┴─────────┴─────┴──────┴──────────┴──────┴────────────┘
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
# shape: (50_315, 18)
# ┌─────────────┬─────────┬─────┬────────────┬───┬─────────────┬────────────┬────────────┬───────────┐
# │ time        ┆ station ┆ prn ┆ epoch_flag ┆ … ┆ calibration ┆ stec       ┆ stec_dcb_c ┆ vtec      │
# │ ---         ┆ ---     ┆ --- ┆ ---        ┆   ┆ _status     ┆ ---        ┆ orrected   ┆ ---       │
# │ datetime[ns ┆ cat     ┆ cat ┆ u8         ┆   ┆ ---         ┆ f64        ┆ ---        ┆ f64       │
# │ , UTC]      ┆         ┆     ┆            ┆   ┆ str         ┆            ┆ f64        ┆           │
# ╞═════════════╪═════════╪═════╪════════════╪═══╪═════════════╪════════════╪════════════╪═══════════╡
# │ 2024-01-09  ┆ CIBG    ┆ C01 ┆ 0          ┆ … ┆ external_co ┆ -64.909114 ┆ 37.638129  ┆ 28.38914  │
# │ 23:59:42    ┆         ┆     ┆            ┆   ┆ de_correcte ┆            ┆            ┆           │
# │ UTC         ┆         ┆     ┆            ┆   ┆ d           ┆            ┆            ┆           │
# │ 2024-01-09  ┆ CIBG    ┆ C02 ┆ 0          ┆ … ┆ external_co ┆ -92.43084  ┆ 30.814723  ┆ 27.533463 │
# │ 23:59:42    ┆         ┆     ┆            ┆   ┆ de_correcte ┆            ┆            ┆           │
# │ UTC         ┆         ┆     ┆            ┆   ┆ d           ┆            ┆            ┆           │
# │ 2024-01-09  ┆ CIBG    ┆ C03 ┆ 0          ┆ … ┆ external_co ┆ -100.67368 ┆ 27.121     ┆ 26.795374 │
# │ 23:59:42    ┆         ┆     ┆            ┆   ┆ de_correcte ┆ 4          ┆            ┆           │
# │ UTC         ┆         ┆     ┆            ┆   ┆ d           ┆            ┆            ┆           │
# │ 2024-01-09  ┆ CIBG    ┆ C05 ┆ 0          ┆ … ┆ external_co ┆ -80.385586 ┆ 37.75411   ┆ 23.567016 │
# │ 23:59:42    ┆         ┆     ┆            ┆   ┆ de_correcte ┆            ┆            ┆           │
# │ UTC         ┆         ┆     ┆            ┆   ┆ d           ┆            ┆            ┆           │
# │ 2024-01-09  ┆ CIBG    ┆ C06 ┆ 0          ┆ … ┆ external_co ┆ -117.67987 ┆ 30.499514  ┆ 20.802595 │
# │ 23:59:42    ┆         ┆     ┆            ┆   ┆ de_correcte ┆ 8          ┆            ┆           │
# │ UTC         ┆         ┆     ┆            ┆   ┆ d           ┆            ┆            ┆           │
# │ …           ┆ …       ┆ …   ┆ …          ┆ … ┆ …           ┆ …          ┆ …          ┆ …         │
# │ 2024-01-10  ┆ CIBG    ┆ G18 ┆ 0          ┆ … ┆ external_co ┆ 66.073626  ┆ 24.891081  ┆ 19.597502 │
# │ 23:59:12    ┆         ┆     ┆            ┆   ┆ de_correcte ┆            ┆            ┆           │
# │ UTC         ┆         ┆     ┆            ┆   ┆ d           ┆            ┆            ┆           │
# │ 2024-01-10  ┆ CIBG    ┆ G23 ┆ 0          ┆ … ┆ external_co ┆ 68.029699  ┆ 27.375494  ┆ 23.37039  │
# │ 23:59:12    ┆         ┆     ┆            ┆   ┆ de_correcte ┆            ┆            ┆           │
# │ UTC         ┆         ┆     ┆            ┆   ┆ d           ┆            ┆            ┆           │
# │ 2024-01-10  ┆ CIBG    ┆ G25 ┆ 0          ┆ … ┆ external_co ┆ 69.734993  ┆ 36.552019  ┆ 27.215423 │
# │ 23:59:12    ┆         ┆     ┆            ┆   ┆ de_correcte ┆            ┆            ┆           │
# │ UTC         ┆         ┆     ┆            ┆   ┆ d           ┆            ┆            ┆           │
# │ 2024-01-10  ┆ CIBG    ┆ G28 ┆ 0          ┆ … ┆ external_co ┆ 67.675466  ┆ 25.564254  ┆ 20.288658 │
# │ 23:59:12    ┆         ┆     ┆            ┆   ┆ de_correcte ┆            ┆            ┆           │
# │ UTC         ┆         ┆     ┆            ┆   ┆ d           ┆            ┆            ┆           │
# │ 2024-01-10  ┆ CIBG    ┆ G31 ┆ 0          ┆ … ┆ external_co ┆ 73.016374  ┆ 30.592893  ┆ 20.972958 │
# │ 23:59:12    ┆         ┆     ┆            ┆   ┆ de_correcte ┆            ┆            ┆           │
# │ UTC         ┆         ┆     ┆            ┆   ┆ d           ┆            ┆            ┆           │
# └─────────────┴─────────┴─────┴────────────┴───┴─────────────┴────────────┴────────────┴───────────┘
```

The default output includes `time`, `station`, `prn`, `epoch_flag`, receiver/IPP coordinates, selected `C1_code`/`C2_code`, `L1_lli`/`L2_lli`, quality/calibration fields and TEC values. `qc_valid` (`Boolean`) and `qc_reason` (`String`) describe quality decisions; `calibration_status` (`String`) identifies the corrections actually applied. Use `tec_lf.collect_schema()` to inspect all fields. Set `TECConfig(retain_intermediate="all")` to retain intermediate values and rejected diagnostic rows. See [Observation quality and scientific conventions](#observation-quality-and-scientific-conventions) for field semantics and calibration states.

#### From DataFrame or LazyFrame

If you wish to calculate TEC from an existing polars DataFrame or LazyFrame (e.g., after some custom preprocessing), you can use the `calc_tec_from_df` function:

```python
header, lf = gt.read_rinex_obs(
    "./data/rinex_obs_v3/CIBG00IDN_R_20240100000_01D_30S_MO.crx.gz"
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
    "./data/rinex_obs_v3/CIBG00IDN_R_20240100000_01D_30S_MO.crx.gz"
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

For small batches that fit comfortably in memory, use `in-memory`. Our [benchmarks](benchmarks/benchmark.md) show faster TEC calculation from resident observations with this engine. Streaming's batch processing and coordination add overhead to these grouped calculations; end-to-end differences are smaller because RINEX parsing accounts for most of the time.

```python
tec_df = tec_lf.collect(engine="in-memory")

# Alternatively, run the same calculation with the streaming engine.
tec_df = tec_lf.collect(engine="streaming")
```

For large datasets, especially those exceeding available memory, consider `streaming` with a scan-based source such as `calc_tec_from_parquet`. It can reduce intermediate memory use, but TEC still needs complete arcs and grouped calculations; memory use and speed depend on the query, and `collect` must hold the final DataFrame in memory.

If the TEC output is also too large to collect, write it with `tec_lf.sink_parquet("tec.parquet", engine="streaming")`.

RINEX files are fully loaded before their LazyFrame is returned. Choosing `streaming` cannot make an oversized raw RINEX input fit in memory; prepare a scan-based input or use batches that preserve complete arcs. Compare both engines for large workloads.

#### Configuration

You can customize the TEC calculation process using the `TECConfig` dataclass:

```python
# To see the default configuration
print(gt.TECConfig())
# TECConfig(
#     constellations='CG',
#     ipp_height=400,
#     min_elevation=30.0,
#     min_snr=30.0,
#     c1_codes={
#         '2': {
#             'G': ['C1']
#         },
#         '3': {
#             'C': ['C2I', 'C2D', 'C2X', 'C1I', 'C1D', 'C1X', 'C2W', 'C1C'],
#             'G': ['C1W', 'C1C', 'C1X']
#         },
#     },
#     c2_codes={
#         '2': {
#             'G': ['C2', 'C5']
#         },
#         '3': {
#             'C': ['C6I', 'C6D', 'C6X', 'C7I', 'C7D', 'C7X', 'C5I', 'C5D', 'C5X'],
#             'G': ['C2W', 'C2C', 'C2X', 'C5W', 'C5C', 'C5X']
#         },
#     },
#     rx_bias='external',
#     mapping_function='slm',
#     retain_intermediate=None,
#     missing_bias='drop'
# )
```

The meaning of each parameter is as follows:

- `constellations`: A string specifying which GNSS constellations to consider for TEC calculation. 'C' for Beidou, 'G' for GPS.
- `ipp_height`: The assumed height of the ionospheric pierce point (IPP) in kilometers.
- `min_elevation`: The minimum satellite elevation angle (in degrees) for observations to be considered in the TEC calculation.
- `min_snr`: The minimum signal-to-noise ratio (in dB-Hz) for observations to be considered in the TEC calculation.
- `c1_codes`: A dictionary of ordered preferences for the first frequency (C1), by RINEX version and constellation. Together with `c2_codes`, pairs are ranked by complete finite P1/L1/P2/L2 availability at the epoch, required bias coverage, joint daily coverage, then `2 * C1_index + C2_index` (indices start at zero); ties are resolved by code name. A missing phase partner causes fallback to a complete pair. Partial overrides are supported, e.g., `c1_codes={'3': {'C': [...]}}` changes only the BeiDou RINEX 3 preferences.
- `c2_codes`: A dictionary specifying the preferred observation codes for the second frequency (C2) for each RINEX version and constellation, similar to `c1_codes`.
- `rx_bias`: Specifies how to handle receiver bias. It can be set to 'external' to use an external DCB file for correction, 'mstd' to use the minimum standard deviation method for estimation, 'lsq' to use least squares estimation, or `None` to skip receiver bias correction. Note that the receiver bias estimation is only applicable after the satellite bias has been corrected using an external DCB file (e.g., from IGS). If no external DCB file is provided, this parameter will be ignored. The 'mstd' and 'lsq' methods are for stations that are not included in the external DCB file.
- `mapping_function`: The mapping function to use for converting slant TEC to vertical TEC. It can be set to 'slm' for the Single Layer Model or 'mslm' for the Modified Single Layer Model.
- `retain_intermediate`: Names of intermediate columns to retain in the output DataFrame. `None` and a list of column names return only QC-accepted rows. `'all'` also retains rejected diagnostic rows, with null public TEC values and `qc_reason` explaining the rejection. `qc_valid` and `calibration_status` are always included. Explicitly requested TEC intermediates such as `azimuth`, `elevation`, `mf` and `stec_p_raw` remain available. Private preparation columns, satellite ECEF coordinates and receiver/event state helpers are always excluded, including with `'all'`.
- `missing_bias`: Specifies how to handle observations whose satellite or receiver bias cannot be matched from the provided DCB file. `'drop'` rejects them, `'warn'` also emits a warning, `'keep_uncorrected'` applies only the available corrections and marks the result `uncorrected_missing_bias`, and `'error'` fails immediately. Rejected rows remain inspectable with `retain_intermediate='all'`.

When using `calc_tec_from_df` or `calc_tec_from_parquet`, the time scale is expressed by the Polars `time` column type. Use timezone-aware UTC datetimes for UTC time, and timezone-naive datetimes for GPS time. Parquet preserves this timezone information, so saved observation files keep the same UTC/GPS semantics when read back. Other timezones are rejected to avoid ambiguous UTC/GPS conversions.

### Observation quality and scientific conventions

The reader exports `Datetime('ns')` epochs and floating-point sampling intervals in seconds. Header metadata records `epoch_resolution`, receiver identity and epoch events; Parquet round-trips preserve these fields. RINEX precision finer than nanoseconds and epochs outside the signed nanosecond range raise errors. Existing Parquet files with millisecond metadata remain readable.

Both wide and long observation layouts preserve the original LLI: `<signal>_lli` in wide format and `lli` in long format. `epoch_flag` retains the original epoch flag. TEC interprets half-cycle validity from LLI and rebuilds receiver/event state internally from header metadata, including when observation codes are filtered. Special events without observations remain in header metadata. See the [RINEX 3.05 format specification](https://files.igs.org/pub/data/format/rinex305.pdf).

TEC processing preserves the original phase-derived `stec_p_raw` (`stec_p` is the same raw series). LLI, half-cycle state, geometry-free (GF) innovations and robust Melbourne–Wübbena (MW) evidence delimit ambiguity arcs. Uncertain jumps split an arc; phase samples are never flattened. Signal-pair changes, receiver events or identity changes, rejected observations and reacquisition gaps also start new arcs. Continuous unchanged observations can share an arc across midnight. When the header has no sampling interval, cadence is inferred per station/satellite; incompatible sampling regimes require separate processing or a known header interval.

External bias correction currently accepts constant code DSB products in nanoseconds with explicit GPS `TIME_SYSTEM G` metadata. Unsupported kinds, units, time scales, nonzero slopes, invalid intervals and overlaps for the same station/PRN/pair raise errors. Validity intervals are half-open `[bias_start, bias_end)`, and reversing the DSB observation pair reverses its sign. The [Bias-SINEX 1.00 specification](https://files.igs.org/pub/data/format/sinex_bias_100.pdf) defines the retained product metadata.

Known satellite and external receiver code biases are converted to TECU and removed from the code reference before phase leveling. `arc_id` identifies the physical ambiguity segment; `level_id` additionally separates bias validity intervals. Leveling uses finite, accepted samples with positive elevation weights. `stec` preserves the uncorrected STEC relationship, while `stec_dcb_corrected` and `vtec` use the corrected level without subtracting the same bias twice. Estimated receiver bias is subtracted after satellite-corrected leveling. Empty or failed estimation produces null TEC and `receiver_estimation_failed`.

`calibration_status` records the correction actually available:

| Status | Meaning |
| --- | --- |
| `uncorrected_no_bias_product` | No external bias product was provided. |
| `uncorrected_missing_bias` | Some required external biases were missing; only available corrections were applied. |
| `satellite_code_corrected` | Satellite code bias was corrected; receiver bias was left uncorrected. |
| `external_code_corrected` | Both satellite and receiver code biases were corrected externally. |
| `satellite_code_corrected_receiver_mstd_estimated` / `satellite_code_corrected_receiver_lsq_estimated` | Satellite code bias was corrected and receiver bias was estimated successfully. |
| `receiver_estimation_failed` | Receiver estimation had insufficient usable support or failed; public TEC values are null. |

The `mstd` and `lsq` methods retain their estimation assumptions; identifiability and conditioning diagnostics are planned in [T006](docs/tasks/T006.md). See [ROADMAP.md](ROADMAP.md) for the active task index. No-bias results and explicitly retained missing-bias results are relative or partially corrected products.

IPP longitude uses both atan2 quadrants and is normalized to `[-180, 180)` degrees. The private navigation preparation propagates GLONASS broadcast position, velocity and acceleration in the rotating PZ-90 frame with bounded RK4 steps, accepting epochs within ±900 seconds of the broadcast reference. Unsupported or expired geometry produces null angles; satellite coordinates and availability flags remain private. The dynamics follow the [GLONASS coordinate equations](https://gssc.esa.int/navipedia/index.php?title=GLONASS_Satellite_Coordinates_Computation) and [RTKLIB broadcast propagation](https://github.com/tomojitakasu/RTKLIB/blob/master/src/ephemeris.c). GLONASS TEC remains a separate planned capability because FDMA frequencies and bias conventions need per-satellite support.

## Benchmarks

See [benchmarks/benchmark.md](benchmarks/benchmark.md) for streaming and in-memory benchmark results.
