# PyGNSS-TEC Roadmap History

This is the authoritative record for archived tasks. Active work is indexed in [ROADMAP.md](../ROADMAP.md).

## Completed Scientific Correctness Tasks

| ID | Task | Priority | Status | Dependencies | Outcome |
|---|---|---|---|---|---|
| H001 | Preserve observation quality and epoch state | P0 | done | — | Preserved observation flags and receiver/event metadata. |
| H002 | Replace unconditional cycle-slip flattening | P0 | done | — | Replaced unconditional phase flattening with conservative QC and arc splits. |
| H003 | Make arc boundaries respect signal and receiver state | P0 | done | — | Added signal and receiver state to physical arc boundaries. |
| H004 | Correct external code biases before phase leveling | P0 | done | — | Applied external code biases before leveling; separated physical arcs from bias/level intervals. |
| H005 | Enforce bias kind, units, time scale and validity | P0 | done | — | Enforced supported bias semantics and validity rules. |
| H006 | Reject invalid numerics and frequency pairs before aggregation | P0 | done | — | Added numeric/configuration validation and rejection reasons. |
| H007 | Select complete code-and-phase pairs with explicit fallback | P0 | done | — | Added complete signal-pair selection and deterministic fallback. |
| H008 | Fix IPP longitude quadrants and wrapping | P0 | done | — | Corrected IPP longitude quadrants and normalization. |
| H009 | Preserve fractional sampling intervals and epoch precision | P0 | done | — | Retained fractional sampling intervals and explicit epoch resolution. |
| H010 | Repair advertised GLONASS geometry propagation | P0 | done | — | Added epoch-dependent GLONASS propagation and unavailable-geometry handling. |

## Completed Engineering and API Tasks

Commit IDs identify the delivered changes; regression details and former task files remain recoverable from Git history.

| ID | Task | Priority | Status | Dependencies | Completed | Outcome |
|---|---|---|---|---|---|---|
| T027 | Make LLI output optional in RINEX observation reads | P2 | done | — | 2026-10-14 | Native/Python wide and long output defaults omit LLI; RINEX-to-TEC explicitly opts in. Commit `992a7e9`. |
| T028 | Simplify TEC output and diagnostic columns | P2 | done | — | 2026-10-14 | `retain_diagnostics` replaces the old option; geometry is always public, diagnostics are selectable and leveling/bias state remains private. Commit `992a7e9`. |
| T029 | Migrate Python docstrings to NumPy style | P3 | done | — | 2026-10-14 | Package/TECConfig docstrings and AGENTS.md convention updated. Class/field hover exposes descriptions; constructor-keyword hover remains limited to type/default. Commit `992a7e9`. |
| T023 | Extract focused modules behind compatible entry points | P3 | done | — | 2026-10-15 | Approved `io`/`signals`/`calibration`/`calculation` layout implemented; six common exports retained and old deep-import paths removed without aliases. Commit `98c849c`. |
| T003 | Reuse navigation and unique epoch/SV geometry | P1 | done | — | 2026-10-17 | Native navigation ownership, indexed Arrow queries, standalone angles and direct TEC API migration delivered without old aliases; matched geometry/TEC, clean-wheel, docs and local performance checks passed. Commit `9bc9671`. |

T003 preserves the existing navigation selection rules; health/validity/age safeguards remain T009.
Wider default reads retain separate timing/memory costs, and the complete stage/high-rate matrix remains T001.
The completed task plan and detailed acceptance record are recoverable from commit `9bc9671`.

## Completed Reader and Observation-QC Tasks

Delivered in commit `d7dbbcb`. Permanent regressions remain in the reader/event, signal-selection and physical-arc tests; detailed plans are recoverable from that commit.

| ID | Task | Priority | Status | Dependencies | Completed | Outcome |
|---|---|---|---|---|---|---|
| R01 | Keep cycle-slip event records out of observation values | P1 | done | — | 2026-10-15 | Flag-6 payloads remain metadata; normal values and unique keys survive in both layouts and LLI modes. |
| R02 | Prefer usable signal pairs before applying priorities | P2 | done | — | 2026-10-15 | Half-cycle/SNR eligibility precedes ranking; changed groups can restore null-SNR candidates, with cycle protection and no-usable-pair diagnostics. |
| R03 | Skip special events with blank epoch fields | P2 | done | — | 2026-10-15 | Untimed blocks are consumed without timestamps/state across supported inputs; standalone COMMENT records remain readable, including text beginning with `>`. |
| R04 | Distinguish metadata events from ambiguity resets | P2 | done | — | 2026-10-15 | Reviewed classification preserves metadata-event continuity and true-reset boundaries without rewriting phase; explicit receiver state remains authoritative. |

The [reader/event policy](guide/rinex.md#header-and-event-metadata) documents conservative resets and retained metadata.
Applying new event-header values to observations/geometry and per-satellite flag-6 interpretation remain outside this delivery.
The existing grouped missing-SNR policy is preserved; broader policy changes belong to T007.
GF/MW detection and numerical phase repair were not implemented by these fixes.

## Completed Cycle-Slip Evaluation and Continuity Tasks

Delivered in commit `1b9130f`; completion dates below retain the task records' dates.
Detailed plans are recoverable from that commit.
Permanent regressions remain in `tests/`, with published measurements in [benchmark results](../benchmarks/benchmark.md).

| ID | Task | Priority | Status | Dependencies | Completed | Outcome |
|---|---|---|---|---|---|---|
| R05 | Evaluate GF/MW detection and small-slip sensitivity | P1 | done | — | 2026-10-15 | Completed the finite independent GF/MW evaluation, paired controls and candidate tradeoff analysis. Small/equal-slip misses remain documented; natural-event causes remain unlabeled. |
| T005 | Explore high-performance arc and GF/MW kernels | P1 | done | — | 2026-10-15 | Delivered equivalent native/selector optimization with measured long/high-rate improvements and accepted complete-call time/RSS results. The historical resident detection-only <0.1 s target remains unmet; this is not bounded input streaming. |
| T030 | Correct cycle slips for scientific TEC continuity | P1 | done | — | 2026-10-15 | Delivered default working-phase and independent final-STEC alignment under the approved temporal-continuity criterion, retaining raw observations, basic/detect modes and diagnostic offsets. It does not resolve carrier integers or identify physical causes and can align genuine physical steps. |

These records close the evaluated scope without completing M1.
T031/T032 retain effective header state and targeted flag-6 semantics; T006/T007 retain estimator and leveling robustness, T009 retains navigation validity, T004 retains bounded input processing, and T020 retains broader independent reference assets.
