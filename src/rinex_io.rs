//! Shared file decoding and ordered merging for observations and navigation.
use std::{
    fs::File,
    io::{BufReader, Read},
    path::Path,
    str::FromStr,
};

use pyo3::{
    PyResult,
    exceptions::{PyIOError, PyValueError},
};
use rinex::prelude::{ProductionAttributes, Rinex, qc::Merge};

pub(crate) fn open(path: &str) -> PyResult<Box<dyn Read>> {
    let file = File::open(path).map_err(|error| PyIOError::new_err(error.to_string()))?;
    Ok(if path.ends_with(".gz") {
        Box::new(flate2::read::GzDecoder::new(file))
    } else {
        Box::new(file)
    })
}

fn read(path: &str) -> PyResult<Rinex> {
    // The upstream file helpers panic on open errors. Open here so Python receives
    // an OSError, while retaining the same parsing and filename metadata.
    let mut reader = BufReader::new(open(path)?);
    let mut rinex =
        Rinex::parse(&mut reader).map_err(|error| PyIOError::new_err(error.to_string()))?;
    rinex.production = Path::new(path)
        .file_name()
        .and_then(|name| ProductionAttributes::from_str(&name.to_string_lossy()).ok())
        .unwrap_or_default();
    Ok(rinex)
}

pub(crate) fn read_files(paths: &[String]) -> PyResult<Rinex> {
    let (first, remaining) = paths
        .split_first()
        .ok_or_else(|| PyValueError::new_err("No RINEX file paths provided"))?;
    let mut rinex = read(first)?;
    for path in remaining {
        let next = read(path)?;
        rinex
            .merge_mut(&next)
            .map_err(|error| PyValueError::new_err(format!("RINEX merge failed: {error}")))?;
    }
    Ok(rinex)
}
