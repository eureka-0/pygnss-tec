# PyGNSS-TEC

[![PyPI - Version](https://img.shields.io/pypi/v/pygnss-tec)](https://pypi.org/project/pygnss-tec/)
![Supported Python Versions](https://img.shields.io/badge/python-%3E%3D3.12-blue)
[![License](https://img.shields.io/badge/license-MIT-blue)](LICENSE)
[![Tests](https://github.com/Eureka-0/pygnss-tec/actions/workflows/test.yml/badge.svg)](https://github.com/Eureka-0/pygnss-tec/actions/workflows/test.yml)
[![Publish](https://github.com/Eureka-0/pygnss-tec/actions/workflows/publish.yml/badge.svg)](https://github.com/Eureka-0/pygnss-tec/actions/workflows/publish.yml)
[![Documentation](https://github.com/Eureka-0/pygnss-tec/actions/workflows/docs.yml/badge.svg)](https://github.com/Eureka-0/pygnss-tec/actions/workflows/docs.yml)

PyGNSS-TEC is a high-performance Python package leveraging Rust acceleration, designed for calculating and processing Total Electron Content (TEC) data from Global Navigation Satellite System (GNSS) observations.
The package provides tools for RINEX file reading, TEC calculation, and DCB correction to support ionospheric studies.

Read the [documentation](https://eureka-0.github.io/pygnss-tec/) for detailed usage instructions.

> **Warning**: This package is under active development and may undergo significant changes. It is not recommended for production use until it reaches a stable release (v1.0.0).

> **Note**: All code in this repository is tested using standard IGS GNSS data files downloaded from the **Crustal Dynamics Data Information System (CDDIS) database**. If you encounter problems with GNSS data files downloaded from other databases, please open a [bug report issue](https://github.com/Eureka-0/pygnss-tec/issues) and attach the data files to the issue.

## Features

- **High-Performance**: Efficiently read GNSS RINEX files using [rinex crate](https://crates.io/crates/rinex), calculate and calibrate TEC from dual-frequency GNSS observations using Rust and [polars](https://pola.rs/) lazy evaluation (see [benchmarks](https://github.com/eureka-0/pygnss-tec/blob/main/benchmarks/benchmark.md)).
- **Multiple File Formats**: Support for RINEX versions 2.x and 3.x, as well as Hatanaka compressed files (e.g., .rnx, .crx, .crx.gz).
- **Automatic Code Selection**: Select dual-frequency code and carrier-phase pairs based on observation quality, DCB coverage, and configurable priorities, with per-epoch fallback when preferred signals are unavailable.
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

### From source

Building from source requires Python 3.12 or later, Rust 1.88 or later (including Cargo), and uv:

```bash
git clone https://github.com/Eureka-0/pygnss-tec.git
cd pygnss-tec
uv sync
uv run maturin build --release
```

The built wheel is available in `target/wheels/`.

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

# Header contains RINEX header information; lf is a Polars LazyFrame.
header, lf = gt.read_rinex_obs(
    "./data/rinex_obs_v3/CIBG00IDN_R_20240100000_01D_30S_MO.crx.gz"
)

# Collect the LazyFrame into a Polars DataFrame.
df = lf.collect(engine="in-memory")
```

You can read multiple files from the same station by passing a list of file paths.

Read navigation once and reuse it when calculating satellite azimuth and elevation:

```python
header, observations = gt.read_rinex_obs(
    "./data/rinex_obs_v3/CIBG00IDN_R_20240100000_01D_30S_MO.crx.gz",
    include_lli=True,
)
navigation = gt.read_rinex_nav(
    "./data/rinex_nav_v3/BRDC00IGS_R_20240100000_01D_MN.rnx.gz"
)
observations_with_angles = gt.compute_az_el(
    observations, header, navigation
).collect(engine="in-memory")
```

Navigation records remain in Rust memory, and `compute_az_el` appends `azimuth` and `elevation` in degrees without filtering observations.

### TEC calculation

Directly calculate TEC from RINEX observation and navigation files. An optional DCB file supplies satellite and receiver bias corrections:

```python
tec_lf = gt.compute_tec_from_rinex(
    "./data/rinex_obs_v3/CIBG00IDN_R_20240100000_01D_30S_MO.crx.gz",
    "./data/rinex_nav_v3/BRDC00IGS_R_20240100000_01D_MN.rnx.gz",
    "./data/bias/CAS0OPSRAP_20240100000_01D_01D_DCB.BIA.gz",
)
tec_df = tec_lf.collect(engine="in-memory")

# Save the TEC DataFrame to a Parquet file for efficient storage and later use.
tec_df.write_parquet("tec.parquet")
```

STEC and VTEC are in TECU, coordinates are in degrees, and output times are UTC.

### Configuration

You can customize TEC calculation using `TECConfig`:

```python
config = gt.TECConfig(
    constellations="CG",
    min_elevation=30.0,
    min_snr=30.0,
)
tec_lf = gt.compute_tec_from_rinex(
    "observations.crx.gz",
    "navigation.rnx.gz",
    config=config,
)
```

Calculation from existing DataFrames, LazyFrames and saved Parquet observations is also supported.
Use `compute_tec(observations_with_angles, header)` to calculate TEC from observations with precomputed angles.
See the [TEC calculation guide](https://eureka-0.github.io/pygnss-tec/guide/tec-calculation/) for more examples.

## Contributing

Bug reports and reproducible examples are welcome through [GitHub issues](https://github.com/Eureka-0/pygnss-tec/issues).
Bug fixes, new features, and documentation improvements are welcome through [pull requests](https://github.com/Eureka-0/pygnss-tec/pulls).
See [contributing documentation](https://eureka-0.github.io/pygnss-tec/contributing/) for development, testing and documentation builds.

## License

This project is licensed under the [MIT LICENSE](LICENSE), allowing for free use, modification, and distribution of the software.
