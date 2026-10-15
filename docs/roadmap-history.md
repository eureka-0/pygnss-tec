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
