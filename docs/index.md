# PyGNSS-TEC

[![PyPI - Version](https://img.shields.io/pypi/v/pygnss-tec)](https://pypi.org/project/pygnss-tec/)
![Supported Python Versions](https://img.shields.io/badge/python-%3E%3D3.12-blue)
[![License](https://img.shields.io/badge/license-MIT-blue)](LICENSE)
[![Tests](https://github.com/Eureka-0/pygnss-tec/actions/workflows/test.yml/badge.svg)](https://github.com/Eureka-0/pygnss-tec/actions/workflows/test.yml)
[![Publish](https://github.com/Eureka-0/pygnss-tec/actions/workflows/publish.yml/badge.svg)](https://github.com/Eureka-0/pygnss-tec/actions/workflows/publish.yml)
[![Documentation](https://github.com/Eureka-0/pygnss-tec/actions/workflows/docs.yml/badge.svg)](https://github.com/Eureka-0/pygnss-tec/actions/workflows/docs.yml)

PyGNSS-TEC is a high-performance Python package leveraging Rust acceleration, designed for calculating and processing Total Electron Content (TEC) data from Global Navigation Satellite System (GNSS) observations.
The package provides tools for RINEX file reading, TEC calculation, and DCB correction to support ionospheric studies.`

## Features

- **High-Performance**: Efficiently read GNSS RINEX files using [rinex crate](https://crates.io/crates/rinex), calculate and calibrate TEC from dual-frequency GNSS observations using Rust and [polars](https://pola.rs/) lazy evaluation (see [benchmarks](https://github.com/eureka-0/pygnss-tec/blob/main/benchmarks/benchmark.md)).
- **Multiple File Formats**: Support for RINEX versions 2.x and 3.x, as well as Hatanaka compressed files (e.g., .rnx, .crx, .crx.gz).
- **Multi-GNSS Support**: Process observations from multiple GNSS constellations.

    | Constellation  | RINEX Reading  | TEC Calculation |
    | -------------- | -------------- | --------------- |
    | GPS (G)        | Yes            | Yes             |
    | Beidou (C)     | Yes            | Yes             |
    | Galileo (E)    | Yes            | No              |
    | GLONASS (R)    | Yes            | No              |
    | QZSS (J)       | Yes            | No              |
    | IRNSS (I)      | Yes            | No              |
    | SBAS (S)       | Yes            | No              |

- **Open-Source**: Fully open-source under the MIT License, encouraging community contributions and collaboration.

## Start here

- [Quick Start](quick-start.md): get up and running with the package.
- [Documentation](guide/index.md): comprehensive guides and examples for using the package.
- [API Reference](api/index.md): detailed reference for all public classes, functions, and modules.
- [Contributing](contributing.md): guidelines for contributing to the project, including development setup and testing.
