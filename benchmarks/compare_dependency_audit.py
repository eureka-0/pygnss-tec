import json
import sys
from pathlib import Path

import numpy as np
import polars as pl

base, candidate = [Path(x) for x in sys.argv[1:3]]
for path in sorted(base.glob("*.arrow")):
    if not (candidate / path.name).exists():
        continue
    a = pl.read_ipc(path).sort("time", "station", "prn")
    b = pl.read_ipc(candidate / path.name).sort("time", "station", "prn")
    out = {
        "file": path.stem,
        "rows": [a.height, b.height],
        "schema_equal": a.schema == b.schema,
    }
    if a.shape != b.shape:
        out["prns_before"] = a.group_by("prn").len().sort("prn").to_dicts()
        out["prns_after"] = b.group_by("prn").len().sort("prn").to_dicts()
        print(json.dumps(out))
        continue
    nonfloat = [c for c, t in a.schema.items() if not t.is_float()]
    out["nonfloat_equal"] = a.select(nonfloat).equals(b.select(nonfloat))
    out["nulls_equal"] = a.null_count().equals(b.null_count())
    out["null_masks_equal"] = a.select(pl.all().is_null()).equals(
        b.select(pl.all().is_null())
    )
    diffs = {}
    for col, t in a.schema.items():
        if not t.is_float() or a.height == 0:
            continue
        x, y = a[col].to_numpy(), b[col].to_numpy()
        d = np.abs(x - y)
        if not np.array_equal(x, y, equal_nan=True):
            diffs[col] = {
                "max_abs": float(np.nanmax(d)) if np.isfinite(d).any() else None,
                "different_gt_1e-8": int(np.sum(d > 1e-8)),
                "close_at_1e-8": bool(
                    np.allclose(x, y, rtol=0, atol=1e-8, equal_nan=True)
                ),
            }
    out["float_diffs"] = diffs
    print(json.dumps(out))
