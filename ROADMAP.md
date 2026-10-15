# PyGNSS-TEC Project Roadmap

## Project Vision

Develop a reliable scientific library for GNSS observations and ionospheric products: preserve raw observations and their quality/state evidence, make calibration and coordinate/time assumptions explicit, and validate scientific results independently of the implementation. Improve scalability, signal/product coverage and workflows without weakening these contracts.

## Current Focus

- **Main goal:** develop independently validated cycle-slip detection and integer repair while preserving raw observations and completing the remaining M1 reliability work.
- **Underway:** no task is currently in progress.
- **Delivered:** R01–R04 are recorded in [history](docs/roadmap-history.md#completed-reader-and-observation-qc-tasks), alongside the earlier deliveries. M1 still has open scientific/reliability requirements.
- **Proposed next round:** R05 supplies the reviewed detector/reference study and T030 supplies integer ambiguity estimation, derived-phase correction and fallback. Begin with their validation/state/API contracts; T005 optimizes the frozen reference and measures the complete pipeline. T031/T032 separately address time-varying header values and satellite/signal-specific flag-6 evidence.
- **Reader policy:** `include_lli=False` omits selected LLI columns, while RINEX-to-TEC explicitly enables LLI. Blank-epoch special events are consumed and omitted without inherited timestamps/state; timestamped flag-6 payloads remain metadata rather than observations.
- **Repair target:** the user selected validated integer repair as the eventual default, with uncertain cases falling back to arc splits. Until T030's reviewed acceptance gates pass, the current default remains basic QC. Raw phases stay unchanged; half-cycle repair is outside the initial scope.
- **Open decisions:** review the scientific noise/TEC envelope, false-repair criteria, effective continuity/leveling model and API before implementation. T031 needs a supported-header matrix; T032 needs version-aware event targeting and recorded-slip semantics. These tasks remain backlog while the design decisions are unresolved.
- **Later candidates:** T006's estimator support/degeneracy contract and T007's robust SNR/leveling policy are the next reliability candidates; they do not have hard dependencies on the proposed research round.

## Milestones

Milestones group verifiable outcomes across workstreams; related task lists do not impose dependencies or execution order.

| Milestone | Capability / delivery | Verifiable completion conditions | Related tasks |
|---|---|---|---|
| M1 — Scientific Reliability | Trustworthy observations, ambiguity state and calibration/QC meaning | Existing reader/event regressions remain valid; detection and integer-repair accuracy, false repairs and fallback are independently validated before the approved default transition. Supported timestamped header changes and targeted slip evidence follow reviewed semantics. Receiver-estimation degeneracies and leveling outliers are handled; product/diagnostic meaning cannot turn unsupported or failed calibration into a zero correction. Geometry/navigation assumptions are explicit and independently checked. | R01–R05, T006–T009, T015, T027–T028, T030–T032 |
| M2 — Scalable Processing | Measured, scientifically equivalent processing across input sizes | Repeatable stage and isolated-process RSS baselines cover 1/30 s, single/multiple days and multiple stations. Report throughput, RSS, retention/QC changes and independent scientific residuals together; demonstrate bounded input memory without chunk-boundary TEC steps and measured optimization gains. Set regression budgets from stable measurements; a Polars engine switch alone does not qualify as streaming input. | T001–T005, T010 |
| M3 — Extended GNSS & Product Support | Explicit supported signal modes and reproducible external/derived products | Each released signal pair has frequency/phase/bias tests and independent known-TEC/orbit references, including FDMA channels and BDS GEO/IGSO where advertised. Bias retrieval avoids overlap/datum mixing; IONEX comparisons preserve map semantics; derived indices enforce sampling and arc requirements. | T011–T014, T017 |
| M4 — Reproducible Workflows & Release Readiness | Traceable user workflows and validated distribution artifacts | Exports preserve units/time/coordinates/QC/calibration metadata; CLI/library results agree. Scientific/error branches and supported compatibility jobs are checked; scientific examples document assumptions and reproduce outputs, and Python docstrings follow NumPy conventions. Publishing waits for successful clean installation and minimal RINEX-to-TEC checks of the actual artifacts, with free-threaded artifacts exercised separately. | T018–T022, T024–T026, T029 |

## Active Tasks

These tables are the authority for active task priority, status and dependencies. Task files hold implementation plans, acceptance requirements and handoff notes.

### Scientific Correctness & QC

| ID | Task | Priority | Status | Dependencies | Details |
|---|---|---|---|---|---|
| R05 | Evaluate GF/MW detection and small-slip sensitivity | P1 | backlog | — | [Study plan](docs/tasks/R05.md) |
| T006 | Stabilize and accelerate receiver-bias estimation | P1 | backlog | — | [Plan](docs/tasks/T006.md) |
| T007 | Make SNR filtering and leveling robust | P1 | backlog | — | [Plan](docs/tasks/T007.md) |
| T008 | Separate geometric IPPs from mapping models | P1 | backlog | — | [Plan](docs/tasks/T008.md) |
| T009 | Validate navigation selection and merge failures | P1 | backlog | — | [Plan](docs/tasks/T009.md) |
| T016 | Offer an optional causal Hatch mode | P2 | backlog | — | [Plan](docs/tasks/T016.md) |
| T030 | Estimate and repair integer cycle slips with fallback | P1 | backlog | R05 | [Plan](docs/tasks/T030.md) |

### Architecture & Performance

| ID | Task | Priority | Status | Dependencies | Details |
|---|---|---|---|---|---|
| T001 | Establish stage and memory baselines | P1 | backlog | — | [Plan](docs/tasks/T001.md) |
| T002 | Push required observation columns into the reader | P1 | backlog | — | [Plan](docs/tasks/T002.md) |
| T003 | Reuse navigation and unique epoch/SV geometry | P1 | backlog | — | [Plan](docs/tasks/T003.md) |
| T004 | Introduce genuinely bounded input batches | P1 | backlog | — | [Plan](docs/tasks/T004.md) |
| T005 | Explore high-performance arc and GF/MW kernels | P1 | backlog | — | [Plan](docs/tasks/T005.md) |
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
| T031 | Apply timestamped RINEX header updates | P1 | backlog | — | [Plan](docs/tasks/T031.md) |
| T032 | Interpret flag-6 events by satellite and phase signal | P2 | backlog | T031 | [Plan](docs/tasks/T032.md) |

### Engineering & Release

| ID | Task | Priority | Status | Dependencies | Details |
|---|---|---|---|---|---|
| T020 | Expand independent scientific regression assets | P3 | backlog | — | [Plan](docs/tasks/T020.md) |
| T021 | Add Rust failure-path tests and parser fuzzing | P3 | backlog | — | [Plan](docs/tasks/T021.md) |
| T022 | Tighten typing and schema contracts | P3 | backlog | — | [Scope & acceptance](#t022-tighten-typing-and-schema-contracts) |
| T024 | Measure coverage and maintain compatibility matrices | P3 | backlog | — | [Scope & acceptance](#t024-measure-coverage-and-maintain-compatibility-matrices) |
| T025 | Gate publishing on installed-artifact validation | P3 | backlog | — | [Plan](docs/tasks/T025.md) |
| T026 | Document scientific assumptions and operating limits | P3 | backlog | — | [Scope & acceptance](#t026-document-scientific-assumptions-and-operating-limits) |

### Inline task specifications

#### T022: Tighten typing and schema contracts

**Scope and approach:** `gnss_tec/py.typed`, `gnss_tec/_core.pyi`, headers/configuration modules, `pyproject.toml`. Fill annotation gaps; validate units/time/columns at boundaries; use PEP 695 only where useful and preserve Python 3.12 compatibility when considering PEP 696.

**Acceptance and validation:** ty plus installed-wheel consumer checks pass on the supported floor.

Before starting, inventory remaining annotation/schema gaps and identify the installed-wheel consumer cases. Use the existing ty configuration and the supported Python floor; do not silence diagnostics or change scientific units/time semantics to pass checks.

#### T024: Measure coverage and maintain compatibility matrices

**Scope and approach:** `.github/workflows/test.yml`, `pyproject.toml`, `tests/`. Retain existing OS/Python/Polars/minimum-dependency jobs and explicit in-memory testing; qualify other engines separately; add coverage and Rust checks; separate core test tools from notebook/plot dependencies.

**Acceptance and validation:** scientific and error branches are tracked, with no invented coverage targets.

Before starting, inspect current CI/dependency groups, select coverage reporting and confirm hosted execution access.

#### T026: Document scientific assumptions and operating limits

**Scope and approach:** `README.md`, `docs/`, `CHANGELOG.md`. Publish signal/product support, DCB signs, coordinate/time conventions, leveling assumptions, QC meanings, memory budgets and reproducibility commands.

**Acceptance and validation:** examples produce traceable products without relying on hidden defaults.

Before starting, inventory undocumented contracts against the current implementation and completed task evidence. Re-run the exact affected examples and preserve native output; cite dated memory/performance measurements with their input and environment limits. Follow the NumPy-style convention delivered by T029; this task owns the broader scientific guidance.

## Recently Completed

No recent entries. Completed deliveries are in [history](docs/roadmap-history.md).

## Conventions

- **IDs and authority:** retain R01–R05 for existing review findings and H001–H010 for archived tasks; assign unused T-series IDs to other work. Never renumber or reuse IDs. Metadata has one authority: Active Tasks, Recently Completed or history, according to the record's location; task files do not duplicate it.
- **Classification:** each task has one owning workstream. Priority, status and milestone association are independent; a task may contribute to multiple milestones or none. Workstreams and milestones do not impose scheduling gates.
- **Priority:** P0 = scientific correctness or supported-input blockers; P1 = core reliability, architecture, performance and scalability; P2 = scientific capabilities and user workflows; P3 = long-term engineering quality and release readiness. Preserve established priorities unless evidence justifies a change.
- **Status:** `backlog` = planned, executability unconfirmed; `ready` = scope, acceptance and dependencies clear; `in_progress` = implementation underway; `blocked` = a named obstacle; `done` = implementation and all acceptance verified. Unchecked or uncertain legacy work defaults to backlog.
- **Dependencies:** record only actual task prerequisites by ID, or `—` for none. General relationships and recommended order are not hard dependencies; confirm uncertain prerequisites before promoting a task to ready.
- **Plans and recovery:** use `docs/tasks/<ID>.md` only for complex work. Implementation Plans are proposals until required review is complete. Record facts, design choices and hypotheses distinctly. Progress & Handoff holds implemented changes, acceptance progress, open issues, next action and constraints.
- **Completion:** verify every acceptance criterion before `done` and retain a concise completion summary. Keep scientific validation evidence in tests, benchmarks or technical reports, outside task records. Necessary tests and documentation accompany the affected change.
- **Lifecycle:** move completed tasks to Recently Completed with ID/title, known completion date and a brief outcome; archive older entries in [history](docs/roadmap-history.md), retaining priority, dependencies, `done`, known limits and commit references there. Remove archived task files and update incoming links; recover detailed plans from Git history. Track follow-up problems separately from completed work.
