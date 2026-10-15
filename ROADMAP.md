# PyGNSS-TEC Project Roadmap

## Project Vision

Develop a reliable scientific library for GNSS observations and ionospheric products: preserve raw observations and their quality/state evidence, make calibration and coordinate/time assumptions explicit, and validate scientific results independently of the implementation. Improve scalability, signal/product coverage and workflows without weakening these contracts.

## Current Focus

- **Main goal:** resolve the outstanding R01–R04 findings while preserving the delivered reader/TEC output contract and basic QC/calibration behavior.
- **Underway:** no task is currently in progress.
- **Delivered:** T023 and T027–T029 are recorded in [history](docs/roadmap-history.md#completed-engineering-and-api-tasks).
- **Next implementation run:** execute R01–R04 as the user-selected scope. R01–R03 have defined implementation scopes; begin R04 with event/reset classification and obtain its required review before dependent changes.
- **Reader policy:** `include_lli=False` omits selected LLI columns, while RINEX-to-TEC explicitly enables LLI. Skipping special events with blank epoch fields remains pending under R03.
- **Open decisions:** R04 needs timestamped event/reset classification. R05's independent-truth detection study can be planned now, alongside T005's native-kernel work; production integration/default changes require validation and review. These tasks preserve raw phase and do not schedule numerical ambiguity repair. The default remains basic QC.

## Milestones

Milestones group verifiable outcomes across workstreams; related task lists do not impose dependencies or execution order.

| Milestone | Capability / delivery | Verifiable completion conditions | Related tasks |
|---|---|---|---|
| M1 — Scientific Reliability | Trustworthy observations, ambiguity state and calibration/QC meaning | Existing regressions and R01/R02/R04 counterexamples pass; blank-epoch events are skipped without disrupting timestamped records, and reader/output options preserve QC and calibration behavior; small-slip misses/false positives are quantified; receiver-estimation degeneracies and leveling outliers are handled; documented product/diagnostic meaning cannot turn unsupported or failed calibration into a zero correction. Geometry/navigation assumptions are explicit and independently checked. | R01–R05, T006–T009, T015, T027–T028 |
| M2 — Scalable Processing | Measured, scientifically equivalent processing across input sizes | Repeatable stage and isolated-process RSS baselines cover 1/30 s, single/multiple days and multiple stations. Report throughput, RSS, retention/QC changes and independent scientific residuals together; demonstrate bounded input memory without chunk-boundary TEC steps and measured optimization gains. Set regression budgets from stable measurements; a Polars engine switch alone does not qualify as streaming input. | T001–T005, T010 |
| M3 — Extended GNSS & Product Support | Explicit supported signal modes and reproducible external/derived products | Each released signal pair has frequency/phase/bias tests and independent known-TEC/orbit references, including FDMA channels and BDS GEO/IGSO where advertised. Bias retrieval avoids overlap/datum mixing; IONEX comparisons preserve map semantics; derived indices enforce sampling and arc requirements. | T011–T014, T017 |
| M4 — Reproducible Workflows & Release Readiness | Traceable user workflows and validated distribution artifacts | Exports preserve units/time/coordinates/QC/calibration metadata; CLI/library results agree. Scientific/error branches and supported compatibility jobs are checked; scientific examples document assumptions and reproduce outputs, and Python docstrings follow NumPy conventions. Publishing waits for successful clean installation and minimal RINEX-to-TEC checks of the actual artifacts, with free-threaded artifacts exercised separately. | T018–T022, T024–T026, T029 |

## Active Tasks

These tables are the authority for active task priority, status and dependencies. Task files hold implementation plans, acceptance requirements and handoff notes.

### Scientific Correctness & QC

| ID | Task | Priority | Status | Dependencies | Details |
|---|---|---|---|---|---|
| R01 | Keep cycle-slip event records out of observation values | P1 | ready | — | [Scope & acceptance](#r01-keep-cycle-slip-event-records-out-of-observation-values) |
| R02 | Prefer usable signal pairs before applying priorities | P2 | ready | — | [Scope & acceptance](#r02-prefer-usable-signal-pairs-before-applying-priorities) |
| R03 | Skip special events with blank epoch fields | P2 | ready | — | [Plan](docs/tasks/R03.md) |
| R04 | Distinguish metadata events from ambiguity resets | P2 | backlog | — | [Plan](docs/tasks/R04.md) |
| R05 | Evaluate GF/MW detection and small-slip sensitivity | P1 | backlog | — | [Plan & measured impact](docs/tasks/R05.md) |
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

#### R01: Keep cycle-slip event records out of observation values

**Scope and approach:** `src/observations.rs`, `src/quality.rs`, `tests/test_rinex_quality.py`. Separate flag-6 payloads from normal observations in both layouts and retain timestamped events under R03's policy. Exclusion of event payloads from observations must not depend on LLI output being enabled.

**Acceptance and validation:** a same-epoch flag-6 L1 slip count of 5 never replaces the normal 110355719.242-cycle observation or creates duplicate observation keys. The epoch/SV overwrite mechanism predates this change set.

Reproduce the same-epoch collision, separate event payload ingestion, and verify both table layouts plus preserved event metadata and unique observation keys. The overwrite mechanism predates the reviewed changes.

#### R02: Prefer usable signal pairs before applying priorities

**Scope and approach:** `gnss_tec/signals/selection.py`, `src/selection.rs`, `tests/test_observation_quality.py`. Include phase validity and the existing SNR policy in candidate eligibility; preserve diagnostics when no candidate is usable.

**Acceptance and validation:** invalid-half-cycle C1W/L1W falls back to valid C1C/L1C, retaining all 20 synthetic epochs; loss-of-lock alone remains an arc boundary, not automatic sample rejection.

Reproduce the 20-epoch fallback case, apply the existing validity/SNR policy before preference ranking, and check no-usable-pair diagnostics, loss-of-lock boundaries and existing pair-switch tests. Do not alter the SNR policy as part of this fix. Reader-based QC fixtures must request `include_lli=True` under T027 so the validity checks receive recorded flags.

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
