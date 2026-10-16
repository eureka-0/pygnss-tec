"""Small adapters for testing native signal kernels."""

import polars as pl

from gnss_tec._arrow import record_batch
from gnss_tec._core import _slip_arcs


def native(frame, cadence=30, repair=True, integer_cycles=True):
    return pl.from_arrow(
        _slip_arcs(record_batch(frame), cadence, repair, integer_cycles)
    )
