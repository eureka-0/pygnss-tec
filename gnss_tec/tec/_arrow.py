"""Create stable Arrow batches for the private Rust kernels."""

from __future__ import annotations

import polars as pl
import pyarrow as pa


def record_batch(frame: pl.DataFrame) -> pa.RecordBatch:
    table = frame.rechunk().to_arrow(compat_level=pl.CompatLevel.oldest())
    batches = table.to_batches()
    if batches:
        return batches[0]
    return pa.RecordBatch.from_arrays(
        [column.combine_chunks() for column in table.columns], schema=table.schema
    )
