# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/), and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

### Added

- Add `read_rinex_nav` and read-only `NavigationData` for reusing native broadcast ephemerides and satellite indexes.
- Add `compute_az_el` for independent azimuth/elevation calculation on wide or long observations, preserving row order and input times.

### Changed

- Rename `calc_tec_from_df`, `calc_tec_from_parquet` and `calc_tec_from_rinex` to `compute_tec`, `compute_tec_from_parquet` and `compute_tec_from_rinex`, without compatibility aliases.
- Pass navigation query columns through Arrow rather than Python time/PRN lists, retaining the existing propagation and angle kernels.
- Keep receiver coordinates before azimuth/elevation in TEC output for both precomputed-angle and RINEX navigation workflows.
- Remove the `custom-alloc` feature; the default allocator is now used for all builds, and the `custom-alloc` feature is no longer available.
- Default `TECConfig.cycle_slip_mode` to `'repair'`: batch GF/MW detection with continuous offsets accepted solely by final STEC temporal continuity.
  Every localized edge is aligned without code/noise/integer vetoes.
  `'detect'` and historical `'basic'` remain available.
  Up to 32 future epochs may be used; separate calls do not share state.
  Detection misses remain a separate metric.
- Preserve raw carrier phase and `stec_p`/`stec_p_raw`; expose opt-in `stec_p_corrected`, repair status, per-event TECU offsets and phase/GF/MW scales.
  Carrier integer fields remain null.
  Align final raw and DCB-corrected STEC independently after leveling; expose `slip_stec_correction` and `slip_dcb_correction`, and derive VTEC from the aligned source.
  Physical `arc_id`, raw measurements and input bias estimates remain traceable.
- Project RINEX-to-TEC export columns to every configured observation fallback and its phase/SNR/LLI companions, retaining existing signal-selection rules.
- Persist `RinexObsHeader.phase_integer_cycles` through Parquet metadata.
  The metadata does not veto temporal continuity correction.
  Recorded half-cycle/invalid rows keep null public TEC; neighboring valid segments may be aligned without synthesizing missing observations.
- Organize native Rust code into `io`, `calculation` and `signals` modules; retain the PyO3 entry point at `src/lib.rs` and preserve Python names.
- Keep README introductory; move configuration, scientific conventions, algorithm/acceptance details and development guidance into `docs/`.
- Reorganize Python modules into `io`, `signals`, `calibration` and `calculation`, with shared `configuration.py`, physical constants and Arrow adaptation at package level.
  Remove `gnss_tec.tec.*` and `gnss_tec.rinex.*` import paths without compatibility aliases.
- Add keyword-only `read_rinex_obs(..., include_lli=False)`: default wide/long outputs omit LLI and native LLI buffers.
  Opt in for raw UInt8/null indicators; observations, epoch flags and retained event metadata are unchanged.
  `compute_tec_from_rinex` explicitly opts in for QC.
  DataFrame/Parquet callers should retain LLI when recorded lock/half-cycle information is required.
- Rename `TECConfig.retain_intermediate` to `retain_diagnostics` without an alias.
  Use None, a list/tuple of supported diagnostic names, or 'all'.
  Default output includes azimuth/elevation and hides epoch/LLI/QC/calibration fields.
  'all' retains rejected rows with null public TEC and reasons.
  All modes omit private leveling/weight/bias-interval fields; unsupported selections raise.
  `mw` remains selectable in wide-lane cycles; diagnostic retention choices do not change QC or calibration computation.
- Convert structured package docstrings to NumPy style and document TECConfig defaults, units, validation and output behavior at class and field level.

### Fixed

- Declare timezone data as a Windows runtime dependency so UTC timestamps can be converted to Python objects without a system IANA timezone database.
- Keep flag-6 cycle-slip counts out of wide/long observation values and preserve timestamped slip payloads in event metadata, independently of LLI output.
- Consume and omit blank-epoch special events without inheriting timestamps or receiver state, including RINEX 2 satellite/observation continuations and supported gzip/Hatanaka and multi-file input paths.
- Recognize fixed-column COMMENT records before epoch parsing, including RINEX 3 comments whose free text starts with `>`.
- Prefer usable signal pairs before preference ranking, with half-cycle/SNR eligibility and retained rejection diagnostics when no usable pair exists.
  Reconsider null-SNR candidates when selected groups change and resolve cyclic group assignments conservatively.
  Loss-of-lock boundaries and final grouped SNR acceptance remain unchanged.
- Preserve continuous phase across COMMENT-only/empty flag-4 and external flag-5 events; conservatively split on power/site/slip and other flag-4 events.
  Keep timestamped event metadata and deduplicate reset epochs.

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
