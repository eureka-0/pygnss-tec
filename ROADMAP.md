# PyGNSS-TEC Project Roadmap

## Project Vision

Develop a reliable scientific library for GNSS observations and ionospheric products: preserve raw observations and their quality/state evidence, make calibration and coordinate/time assumptions explicit, and validate scientific results independently of the implementation.
Improve scalability, signal/product coverage and workflows without weakening these contracts.

## Current Focus

- **Main goal:** deliver default batch GF/MW localization and final STEC temporal continuity while preserving raw observations, and continue the remaining M1 reliability work.
- **Current acceptance:** the user's latest instruction makes final STEC smoothness at localized edges the sole repair criterion.
  Code/MW/integer/noise vetoes are removed.
  The [consolidated validation record](docs/agents/cycle-slip-validation.md) preserves the current evaluation and earlier continuity checkpoint.
  The [completed R05/T005 evaluation](docs/agents/cycle-slip-validation.md#r05-and-t005-completion-validation) quantifies detection sensitivity, physical-structure responses and equivalent optimization separately.
- **Delivered:** R01–R04 are recorded in [history](docs/roadmap-history.md#completed-reader-and-observation-qc-tasks), alongside the earlier deliveries.
  M1 still has open scientific/reliability requirements.
- **Current delivery:** T030 aligns working phase and then raw/calibrated final STEC independently, so signal-specific code references cannot reintroduce jumps.
  R05's finite detector evaluation and T005's equivalent optimization are complete, with measured complete CIBG runtime <=1.4 s and peak process RSS <=10^9 bytes.
  CIBG is a workload and regression case, not a source of station/date/pair-specific rules.
  Rust is organized into `io`, `calculation` and `signals`, with `src/lib.rs` retained.
- **Validation checkpoint:** analytic, noise, partition and real multi-station/day controls check temporal residuals on actual final products.
  All detected injections in the fixed real cohort receive correction; the completed R05 report retains the missed events, paired-control distinctions and sensitivity limits.
  Expanded offline controls and frozen-build comparisons qualify detector state and output equivalence across the declared input matrix.
  Routine regressions use representative coverage instead of exhaustive seed Cartesian products.
  Detailed counts, timings and source/input hashes belong in the validation report.
- **Reader policy:** `include_lli=False` omits selected LLI columns, while RINEX-to-TEC explicitly enables LLI.
  Blank-epoch special events are consumed and omitted without inherited timestamps/state; timestamped flag-6 payloads remain metadata rather than observations.
- **Production default:** `TECConfig.cycle_slip_mode='repair'` applies continuity offsets to every localized edge, using up to 32 future intervals and available short-support rates.
  `detect` and frozen `basic` remain selectable.
  Raw observations are immutable; invalid/half-cycle rows retain null public TEC.
  Per-event phase/raw-STEC/calibrated-STEC adjustments are opt-in; carrier integer fields stay null.
- **Known limits and open work:** the completed R05 study does not establish perfect small/equal-slip detection or natural-event cause labels; T020 retains broader independent fixture coverage.
  T005's declared long/high-rate matrix and frozen-build equivalence are measured, while T004/T003 retain bounded input streaming/navigation reuse.
  The historical resident-TEC <0.1 s goal remains unmet and separate from the satisfied complete-call budget.
  T031 needs a supported-header matrix and T032 version-aware event targeting/recorded-slip semantics.
  No station/date/pair tuning is authorized by these open questions.
- **Later candidates:** T006's estimator support/degeneracy contract and T007's robust SNR/leveling policy are the next reliability candidates; they do not have hard dependencies on the proposed research round.

## Milestones

Milestones group verifiable outcomes across workstreams; related task lists do not impose dependencies or execution order.

| Milestone | Capability / delivery | Verifiable completion conditions | Related tasks |
|---|---|---|---|
| M1 — Scientific Reliability | Trustworthy observations, ambiguity state and calibration/QC meaning | Existing reader/event regressions remain valid; detection and scientific-repair accuracy, false repairs and unresolved events are independently validated against the final acceptance criterion. Supported timestamped header changes and targeted slip evidence follow reviewed semantics. Receiver-estimation degeneracies and leveling outliers are handled; product/diagnostic meaning cannot turn unsupported or failed calibration into a zero correction. Geometry/navigation assumptions are explicit and independently checked. | R01–R05, T006–T009, T015, T027–T028, T030–T032 |
| M2 — Scalable Processing | Measured, scientifically equivalent processing across input sizes | Repeatable stage and isolated-process RSS baselines cover 1/30 s, single/multiple days and multiple stations. Report throughput, RSS, retention/QC changes and independent scientific residuals together; demonstrate bounded input memory without chunk-boundary TEC steps and measured optimization gains. Set regression budgets from stable measurements; a Polars engine switch alone does not qualify as streaming input. | T001–T005, T010 |
| M3 — Extended GNSS & Product Support | Explicit supported signal modes and reproducible external/derived products | Each released signal pair has frequency/phase/bias tests and independent known-TEC/orbit references, including FDMA channels and BDS GEO/IGSO where advertised. Bias retrieval avoids overlap/datum mixing; IONEX comparisons preserve map semantics; derived indices enforce sampling and arc requirements. | T011–T014, T017 |
| M4 — Reproducible Workflows & Release Readiness | Traceable user workflows and validated distribution artifacts | Exports preserve units/time/coordinates/QC/calibration metadata; CLI/library results agree. Scientific/error branches and supported compatibility jobs are checked; scientific examples document assumptions and reproduce outputs, and Python docstrings follow NumPy conventions. Publishing waits for successful clean installation and minimal RINEX-to-TEC checks of the actual artifacts, with free-threaded artifacts exercised separately. | T018–T022, T024–T026, T029 |

## Active Tasks

These tables are the authority for active task priority, status and dependencies.
Task files hold implementation plans, acceptance requirements and handoff notes.

### Scientific Correctness & QC

| ID | Task | Priority | Status | Dependencies | Details |
|---|---|---|---|---|---|
| T006 | Stabilize and accelerate receiver-bias estimation | P1 | backlog | — | [Plan](docs/tasks/T006.md) |
| T007 | Make SNR filtering and leveling robust | P1 | backlog | — | [Plan](docs/tasks/T007.md) |
| T008 | Separate geometric IPPs from mapping models | P1 | backlog | — | [Plan](docs/tasks/T008.md) |
| T009 | Validate navigation selection and merge failures | P1 | backlog | — | [Plan](docs/tasks/T009.md) |
| T016 | Offer an optional causal Hatch mode | P2 | backlog | — | [Plan](docs/tasks/T016.md) |

### Architecture & Performance

| ID | Task | Priority | Status | Dependencies | Details |
|---|---|---|---|---|---|
| T001 | Establish stage and memory baselines | P1 | backlog | — | [Plan](docs/tasks/T001.md) |
| T002 | Push required observation columns into the reader | P1 | backlog | — | [Plan](docs/tasks/T002.md) |
| T003 | Reuse navigation and unique epoch/SV geometry | P1 | backlog | — | [Plan](docs/tasks/T003.md) |
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

| ID | Task | Priority | Status | Dependencies | Completed | Outcome |
| --- | --- | --- | --- | --- | --- | --- |
| R05 | Evaluate GF/MW detection and small-slip sensitivity | P1 | done | — | 2026-10-15 | Finite independent detector-arm evaluation, real paired controls and candidate tradeoffs are documented with retained misses/alarms; [record](docs/tasks/R05.md). |
| T005 | Explore high-performance arc and GF/MW kernels | P1 | done | — | 2026-10-15 | Equivalent native/selector optimization passes scientific/state comparisons, long/high-rate measurements and complete CIBG time/RSS budgets; historical resident target remains unmet; [record](docs/tasks/T005.md). |
| T030 | Correct cycle slips for scientific TEC continuity | P1 | done | — | 2026-10-15 | Default working-phase and independent final-product alignment pass the user-defined temporal criterion and complete CIBG time/RSS budgets; [record](docs/tasks/T030.md). |

R05 completion records the finite evaluation, including its measured limits; it does not certify every natural discontinuity as a cycle slip.
Earlier deliveries are in [history](docs/roadmap-history.md).

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
