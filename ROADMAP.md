# PyGNSS-TEC Project Roadmap

## Project Vision

Develop a reliable scientific library for GNSS observations and ionospheric products: preserve raw observations and their quality/state evidence, make calibration and coordinate/time assumptions explicit, and validate scientific results independently of the implementation.
Improve scalability, signal/product coverage and workflows without weakening these contracts.

## Current Focus

- **Main goal:** qualify the 0.5.0 release by closing the confirmed silent-error paths and validating the exact distribution artifacts.
- **Underway:** no task is currently in progress.
- **Selected next round:** T031 and T006 address the confirmed observation-decoding and receiver-calibration failures first.
  T009 addresses navigation validity, while T025 prepares version consistency and installed-artifact release gates independently.
  This selection follows the 2026-10-18 release review of `2370e03`; it reuses existing task IDs.
- **First action:** review T031's significant-header rejection policy, T006's identifiability/failure criteria, T009's constellation-specific validity rules and T025's supported artifact matrix.
  The plans remain preliminary and the selected tasks remain `backlog` until those reviews establish executable contracts.
- **Release scope:** deliver the reviewed safeguards and checks below before publishing.
  Full dynamic-header support, estimator optimization and broader navigation analysis retain their task acceptance criteria; partial release safeguards do not mark those tasks or M1 complete.
- **Later work:** T032 still requires the effective-header context from T031; a rejection-only safeguard does not satisfy that dependency.
  T007/T008, stage/RSS baselines and bounded input processing remain outside this release's required fixes unless validation exposes another blocker.
- **Delivered:** navigation reuse, standalone angles, direct TEC API migration and the earlier scientific/API deliveries are recorded in [history](docs/roadmap-history.md).
- **Constraints:** blank-epoch events remain omitted, raw observations remain unchanged, and ordinary reader calls keep `include_lli=False` while RINEX-to-TEC opts in.
  The default `repair` mode provides temporal alignment, not certified carrier-integer recovery or natural-event classification.

## 0.5.0 Release Checks

- [ ] **T031:** scientifically significant header changes are interpreted correctly or explicitly rejected before misleading observations or geometry are returned; harmless COMMENT events retain their behavior.
- [ ] **T006:** unsupported or unidentifiable receiver-bias estimates fail explicitly with null calibrated products, while identifiable controls retain their known bias and TEC.
- [ ] **T009:** queries without eligible broadcast ephemerides cannot produce accepted TEC from expired navigation; valid selection/tie and propagation behavior remains checked.
- [ ] **T025:** Python/Rust manifests, lockfiles, tag, release notes and artifact metadata agree on 0.5.0; publication requires successful validation of the exact artifacts and the scientific safeguards above.

Task design and release-workflow wiring can proceed independently.
Publication requires every release check, rather than administrative completion of each task's broader scope.
The release matrix must be exercised without publication first, including separate validation or reviewed exclusion of free-threaded and 32-bit targets.

## Milestones

Milestones group verifiable outcomes across workstreams; related task lists do not impose dependencies or execution order.

| Milestone | Capability / delivery | Verifiable completion conditions | Related tasks |
|---|---|---|---|
| M1 — Scientific Reliability | Trustworthy observations, ambiguity state and calibration/QC meaning | Existing reader/event regressions remain valid; detection sensitivity and continuity correction have independent validation under their declared contracts, with unresolved detections and physical-interpretation limits explicit. Supported timestamped header changes and targeted slip evidence follow reviewed semantics. Receiver-estimation degeneracies and leveling outliers are handled; product/diagnostic meaning cannot turn unsupported or failed calibration into a zero correction. Geometry/navigation assumptions are explicit and independently checked. | R01–R05, T006–T009, T015, T027–T028, T030–T032 |
| M2 — Scalable Processing | Measured, scientifically equivalent processing across input sizes | Repeatable stage and isolated-process RSS baselines cover 1/30 s, single/multiple days and multiple stations. Report throughput, RSS, retention/QC changes and independent scientific residuals together; demonstrate bounded input memory without chunk-boundary TEC steps and measured optimization gains. Set regression budgets from stable measurements; a Polars engine switch alone does not qualify as streaming input. | T001–T005, T010 |
| M3 — Extended GNSS & Product Support | Explicit supported signal modes and reproducible external/derived products | Each released signal pair has frequency/phase/bias tests and independent known-TEC/orbit references, including FDMA channels and BDS GEO/IGSO where advertised. Bias retrieval avoids overlap/datum mixing; IONEX comparisons preserve map semantics; derived indices enforce sampling and arc requirements. | T011–T014, T017 |
| M4 — Reproducible Workflows & Release Readiness | Traceable user workflows and validated distribution artifacts | Exports preserve units/time/coordinates/QC/calibration metadata; CLI/library results agree. Scientific/error branches and supported compatibility jobs are checked; scientific examples document assumptions and reproduce outputs, and Python docstrings follow NumPy conventions. Publishing waits for successful clean installation and minimal RINEX-to-TEC checks of the actual artifacts, with free-threaded artifacts exercised separately. | T018–T022, T024–T026, T029 |

## Active Tasks

These tables are the authority for active task priority, status and dependencies.
Task files hold implementation plans, acceptance requirements and handoff notes.

### Scientific Correctness & QC

| ID | Task | Priority | Status | Dependencies | Details |
|---|---|---|---|---|---|
| T031 | Apply timestamped RINEX header updates | P0 | backlog | — | [Plan](docs/tasks/T031.md) |
| T006 | Stabilize and accelerate receiver-bias estimation | P0 | backlog | — | [Plan](docs/tasks/T006.md) |
| T009 | Validate navigation selection and merge failures | P1 | backlog | — | [Plan](docs/tasks/T009.md) |
| T007 | Make SNR filtering and leveling robust | P1 | backlog | — | [Plan](docs/tasks/T007.md) |
| T008 | Separate geometric IPPs from mapping models | P1 | backlog | — | [Plan](docs/tasks/T008.md) |
| T016 | Offer an optional causal Hatch mode | P2 | backlog | — | [Plan](docs/tasks/T016.md) |
| T032 | Interpret flag-6 events by satellite and phase signal | P2 | backlog | T031 | [Plan](docs/tasks/T032.md) |

### Architecture & Performance

| ID | Task | Priority | Status | Dependencies | Details |
|---|---|---|---|---|---|
| T001 | Establish stage and memory baselines | P1 | backlog | — | [Plan](docs/tasks/T001.md) |
| T002 | Push required observation columns into the reader | P1 | backlog | — | [Plan](docs/tasks/T002.md) |
| T004 | Introduce genuinely bounded input batches | P1 | backlog | — | [Plan](docs/tasks/T004.md) |
| T010 | Bound parallelism and eliminate demonstrated rescans | P1 | backlog | — | [Plan](docs/tasks/T010.md) |

### Signals & Data Products

| ID | Task | Priority | Status | Dependencies | Details |
|---|---|---|---|---|---|
| T011 | Add a versioned signal registry and RINEX 2 adapters | P2 | backlog | — | [Plan](docs/tasks/T011.md) |
| T012 | Extend Galileo, GPS/BDS multi-frequency and GLONASS TEC | P2 | backlog | T011 | [Plan](docs/tasks/T012.md) |
| T013 | Normalize DSB/OSB products and add product retrieval | P2 | backlog | — | [Plan](docs/tasks/T013.md) |
| T014 | Add IONEX ingestion and comparison utilities | P2 | backlog | — | [Plan](docs/tasks/T014.md) |
| T015 | Expose calibrated, leveled and relative TEC products | P2 | backlog | — | [Plan](docs/tasks/T015.md) |
| T017 | Add ROT/ROTI and qualified scintillation products | P2 | backlog | — | [Plan](docs/tasks/T017.md) |

### APIs & Workflows

| ID | Task | Priority | Status | Dependencies | Details |
|---|---|---|---|---|---|
| T018 | Standardize export metadata and add Xarray/NetCDF | P2 | backlog | — | [Plan](docs/tasks/T018.md) |
| T019 | Add a CLI that delegates to the library | P2 | backlog | — | [Plan](docs/tasks/T019.md) |

### Engineering & Release

| ID | Task | Priority | Status | Dependencies | Details |
|---|---|---|---|---|---|
| T025 | Gate publishing on installed-artifact validation | P1 | backlog | — | [Plan](docs/tasks/T025.md) |
| T020 | Expand independent scientific regression assets | P3 | backlog | — | [Plan](docs/tasks/T020.md) |
| T021 | Add Rust failure-path tests and parser fuzzing | P3 | backlog | — | [Plan](docs/tasks/T021.md) |
| T022 | Tighten typing and schema contracts | P3 | backlog | — | [Scope & acceptance](#t022-tighten-typing-and-schema-contracts) |
| T024 | Measure coverage and maintain compatibility matrices | P3 | backlog | — | [Scope & acceptance](#t024-measure-coverage-and-maintain-compatibility-matrices) |
| T026 | Document scientific assumptions and operating limits | P3 | backlog | — | [Scope & acceptance](#t026-document-scientific-assumptions-and-operating-limits) |

### Inline task specifications

#### T022: Tighten typing and schema contracts

**Scope and approach:** `gnss_tec/py.typed`, `gnss_tec/_core.pyi`, headers/configuration modules, `pyproject.toml`.
Fill annotation gaps; validate units/time/columns at boundaries; use PEP 695 only where useful and preserve Python 3.12 compatibility when considering PEP 696.

**Acceptance and validation:** ty plus installed-wheel consumer checks pass on the supported floor.

Before starting, inventory remaining annotation/schema gaps and identify the installed-wheel consumer cases.
Use the existing ty configuration and the supported Python floor; do not silence diagnostics or change scientific units/time semantics to pass checks.

#### T024: Measure coverage and maintain compatibility matrices

**Scope and approach:** `.github/workflows/test.yml`, `pyproject.toml`, `tests/`.
Retain existing OS/Python/Polars/minimum-dependency jobs and explicit in-memory testing; qualify other engines separately; add coverage and Rust checks; separate core test tools from notebook/plot dependencies.

**Acceptance and validation:** scientific and error branches are tracked, with no invented coverage targets.

Before starting, inspect current CI/dependency groups, select coverage reporting and confirm hosted execution access.

#### T026: Document scientific assumptions and operating limits

**Scope and approach:** `README.md`, `docs/`, `CHANGELOG.md`.
Publish signal/product support, DCB signs, coordinate/time conventions, leveling assumptions, QC meanings, memory budgets and reproducibility commands.

**Acceptance and validation:** examples produce traceable products without relying on hidden defaults.

Before starting, inventory undocumented contracts against the current implementation and completed task evidence.
Re-run the exact affected examples and preserve native output; cite dated memory/performance measurements with their input and environment limits.
Follow the NumPy-style convention delivered by T029; this task owns the broader scientific guidance.

## Recently Completed

No completed tasks are awaiting archival.
Completed deliveries are recorded in [history](docs/roadmap-history.md).

## Conventions

- **IDs and authority:** retain R01–R05 for existing review findings and H001–H010 for archived tasks; assign unused T-series IDs to other work.
  Never renumber or reuse IDs.
  Metadata has one authority: Active Tasks, Recently Completed or history, according to the record's location; task files do not duplicate it.
- **Classification:** each task has one owning workstream.
  Priority, status and milestone association are independent; a task may contribute to multiple milestones or none.
  Workstreams and milestones do not impose scheduling gates.
- **Priority:** P0 = scientific correctness or supported-input blockers; P1 = core reliability, architecture, performance and scalability; P2 = scientific capabilities and user workflows; P3 = long-term engineering quality and release readiness.
  Preserve established priorities unless evidence justifies a change.
- **Status:** `backlog` = planned, executability unconfirmed; `ready` = scope, acceptance and dependencies clear; `in_progress` = implementation underway; `blocked` = a named obstacle; `done` = implementation and all acceptance verified.
  Unchecked or uncertain legacy work defaults to backlog.
- **Dependencies:** record only actual task prerequisites by ID, or `—` for none.
  General relationships and recommended order are not hard dependencies; confirm uncertain prerequisites before promoting a task to ready.
- **Plans and recovery:** use `docs/tasks/<ID>.md` only for complex work.
  Implementation Plans are proposals until required review is complete.
  Record facts, design choices and hypotheses distinctly.
  Progress & Handoff holds implemented changes, acceptance progress, open issues, next action and constraints.
- **Completion:** verify every acceptance criterion before `done` and retain a concise completion summary.
  Keep scientific validation evidence in tests, benchmarks or technical reports, outside task records.
  Necessary tests and documentation accompany the affected change.
- **Lifecycle:** move completed tasks to Recently Completed with ID/title, known completion date and a brief outcome; archive older entries in [history](docs/roadmap-history.md), retaining priority, dependencies, `done`, known limits and commit references there.
  Remove archived task files and update incoming links; recover detailed plans from Git history.
  Track follow-up problems separately from completed work.
