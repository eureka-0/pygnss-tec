# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/), and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

## [0.5.0](https://github.com/Eureka-0/pygnss-tec/releases/tag/v0.5.0) - 2026-10-18

### Added

- Add reusable navigation with `read_rinex_nav` and `NavigationData`, and standalone satellite angles with `compute_az_el`, including GLONASS geometry.
- Preserve nanosecond timestamps and receiver/quality metadata when reading RINEX and caching observations in Parquet.
- Add online [documentation](https://eureka-0.github.io/pygnss-tec/) with usage guides and an API reference.

### Changed

- Require Python 3.12+, Polars >=1.40.0,<3 and SciPy 1.16+, with support for both Polars 1.x and 2.x. Source builds require Rust 1.88+.
- Rename `calc_tec_from_df`, `calc_tec_from_parquet` and `calc_tec_from_rinex` to `compute_tec`, `compute_tec_from_parquet` and `compute_tec_from_rinex`. The old entry points and `gnss_tec.tec.*`/`gnss_tec.rinex.*` module paths are removed; use package-level imports.
- Make `read_rinex_obs` return raw observations without navigation input or geometry calculation. Use `compute_az_el` separately or pass `nav_fn` to TEC calculation.
- Make LLI output opt-in with `read_rinex_obs(..., include_lli=True)`; direct RINEX-to-TEC calculation enables it automatically.
- Replace `TECConfig.retain_intermediate` with `retain_diagnostics` for selecting diagnostic columns. Default output includes satellite angles; use `'all'` to inspect rejected rows with null TEC and rejection reasons.
- Default `TECConfig.cycle_slip_mode` to `'repair'`, using GF/MW detection and temporal continuity correction while preserving raw observations. Correction can also align physical TEC steps; use `'detect'` or `'basic'` to disable numerical continuity correction.
- Reduce RINEX decoding and repeated satellite-geometry overhead.
- Limit prebuilt wheels to ordinary Python on Linux x86_64/aarch64, Windows x64 and macOS x86_64/arm64; exclude free-threaded and 32-bit builds. Add installed wheel and source-distribution checks before PyPI publication.
- Remove the `custom-alloc` build feature.

### Fixed

- Recover skipped RINEX 2 observations and correct special-event handling in RINEX/Hatanaka files, avoiding overwritten measurements and false arc breaks. Reject unsupported dynamic header changes instead of silently using stale observation or receiver metadata.
- Fix sampling inference and chronological ordering for unordered and fractional-rate observations.
- Preserve per-file receiver positions and station-specific quality control in multi-day/multi-station processing, and correct IPP longitudes.
- Select usable signal pairs before applying preferences, respecting SNR and half-cycle indicators.
- Fix UTF-8 Bias-SINEX decoding and apply time-valid code biases before leveling; reject overlapping or unsupported bias products.
- Reject unidentifiable or failed MSTD/LSQ receiver-bias estimates, returning null calibrated TEC.
- Exclude unhealthy or expired broadcast ephemerides from geometry and TEC calculations.
- Fix UTC timestamp conversion on Windows installations without system timezone data.

## [0.4.2](https://github.com/Eureka-0/pygnss-tec/releases/tag/v0.4.2) - 2026-05-07

### Added

- Support timezone-naive GPS time in `calc_tec_from_df` and `calc_tec_from_parquet`, while continuing to support timezone-aware UTC time
- Add `TECConfig.missing_bias` to control how unmatched satellite or receiver DCB values are handled

### Changed

- Improve `TECConfig` validation for constellations, elevation limits, SNR, IPP height, receiver bias mode, mapping function, and observation code formats
- Preserve independent default observation-code presets when user overrides are supplied
- Update dependencies and release workflows for the 0.4.2 release

### Fixed

- Add clearer validation for missing RINEX header metadata when reading observations from Parquet
- Add required-column checks in `calc_tec_from_df` before TEC calculation starts


## [0.4.1](https://github.com/Eureka-0/pygnss-tec/releases/tag/v0.4.1) - 2026-05-07

### Changed

- Update `rinex` crate to v0.22.0


## [0.4.0](https://github.com/Eureka-0/pygnss-tec/releases/tag/v0.4.0) - 2025-12-15

### Added

- Add modified single layer model (MSLM) as an additional mapping function option
- Support calculating TEC from RINEX v2 files


## [0.3.1](https://github.com/Eureka-0/pygnss-tec/releases/tag/v0.3.1) - 2025-12-10

### Fixed

- Update `rinex` crate to main branch to fix RINEX v3 Hatanaka compressed file reading issue ([#397](https://github.com/nav-solutions/rinex/issues/397))


## [0.3.0](https://github.com/Eureka-0/pygnss-tec/releases/tag/v0.3.0) - 2025-12-09

### Added

- Automatic cycle slip detection and correction in TEC calculation
- Add an extra feature 'custom-alloc' that can improve performance but uses more memory, which is disabled by default.
  Users have to enable it manually when building from source by adding `--features custom-alloc` flag to `maturin build` command.
- Add `station` parameter to `read_rinex_obs` function to allow custom station name assignment in case the RINEX header station name is not desired
- Add two receiver bias estimation methods: 'mstd' (minimum standard deviation) and 'lsq' (least squares)

### Changed

- Change column names to lowercase for convenience
- Symplify function signatures.
  All functions now return LazyFrames, users can call `.collect()` to get DataFrames when needed.
- All configurations are now handled by a single `TECConfig` dataclass
- Remove `pandas` dependency

### Fixed

- Improve performance and memory efficiency in TEC calculation
- Improve performance of RINEX file reading
- Fix observable columns missing when reading RINEX 2 files using `pivot=True`


## [0.2.0](https://github.com/Eureka-0/pygnss-tec/releases/tag/v0.2.0) - 2025-11-28

### Added

- `calc_tec` function to calculate TEC from RINEX observation and navigation files
- Support using single layer model (SLM) to map slant TEC to vertical TEC
- Support DCB bias correction using external bias files

### Changed

- Add `pivot` parameter to `read_rinex_obs` function


## [0.1.0](https://github.com/Eureka-0/pygnss-tec/releases/tag/v0.1.0) - 2025-11-24

### Added

- Initial release of pygnss-tec
- `read_rinex_obs` function that supports reading observation RINEX files and automatically calculating azimuth and elevation angles when navigation RINEX files are provided
