//! Signal selection, ambiguity boundaries and scientific phase continuity.
pub(crate) mod arcs;
pub(crate) mod repair;
pub(crate) mod selection;
mod statistics;

use arrow::array::RecordBatch;
use pyo3::{PyResult, exceptions::PyValueError};

pub(crate) fn column<'a, T: 'static>(batch: &'a RecordBatch, name: &str) -> PyResult<&'a T> {
    batch
        .column_by_name(name)
        .and_then(|array| array.as_any().downcast_ref())
        .ok_or_else(|| {
            PyValueError::new_err(format!("Missing or incompatible selection column: {name}"))
        })
}
