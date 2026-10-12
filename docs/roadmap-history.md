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
