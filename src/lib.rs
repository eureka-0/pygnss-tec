//! Python entry points; parsing, table construction and geometry live in Rust modules.
mod geometry;
mod glonass;
mod navigation;
mod observations;
mod quality;
mod rinex_io;
mod selection;

use std::str::FromStr;

use arrow::{array::RecordBatch, pyarrow::PyArrowType};
use pyo3::{exceptions::PyValueError, prelude::*, types::PyDict};
use rinex::prelude::*;
use rustc_hash::FxHashSet;

#[cfg(all(feature = "custom-alloc", target_family = "unix"))]
#[global_allocator]
static GLOBAL: tikv_jemallocator::Jemalloc = tikv_jemallocator::Jemalloc;

#[cfg(all(feature = "custom-alloc", target_family = "windows"))]
#[global_allocator]
static GLOBAL: mimalloc::MiMalloc = mimalloc::MiMalloc;

// GPS, BeiDou, Galileo, GLONASS, QZSS, IRNSS, SBAS.
const ALL_CONSTELLATIONS: &str = "GCERJIS";

fn select_observables(
    py: Python<'_>,
    header: &Header,
    codes: Option<Vec<String>>,
) -> PyResult<Option<FxHashSet<Observable>>> {
    let Some(codes) = codes else {
        return Ok(None);
    };
    let re = py.import("re")?;
    let patterns = codes
        .iter()
        .map(|pattern| {
            re.call_method1("compile", (pattern,)).map_err(|error| {
                PyValueError::new_err(format!(
                    "Invalid observation code pattern {pattern:?}: {error}"
                ))
            })
        })
        .collect::<PyResult<Vec<_>>>()?;
    let observation_header = header
        .obs
        .as_ref()
        .ok_or_else(|| PyValueError::new_err("Expected a RINEX observation file"))?;
    let mut selected = FxHashSet::default();
    for observable in observation_header.codes.values().flatten() {
        if selected.contains(observable) {
            continue;
        }
        let code = observable.to_string();
        for pattern in &patterns {
            if !pattern.call_method1("fullmatch", (&code,))?.is_none() {
                selected.insert(observable.clone());
                break;
            }
        }
    }
    Ok(Some(selected))
}

fn header_dict<'py>(py: Python<'py>, header: &Header) -> PyResult<Bound<'py, PyDict>> {
    let (x, y, z) = header.rx_position.unwrap_or((f64::NAN, f64::NAN, f64::NAN));
    let marker = header.geodetic_marker.as_ref();
    let result = PyDict::new(py);
    result.set_item(
        "version",
        format!("{}.{:02}", header.version.major, header.version.minor),
    )?;
    result.set_item("constellation", header.constellation.map(|c| c.to_string()))?;
    result.set_item(
        "sampling_interval",
        header.sampling_interval.map(|d| d.to_seconds()),
    )?;
    result.set_item("leap_seconds", header.leap.map(|leap| leap.leap))?;
    result.set_item(
        "station",
        marker.map(|m| m.name.as_str()).unwrap_or("Unknown"),
    )?;
    result.set_item(
        "marker_type",
        marker.and_then(|m| m.marker_type).map(|m| m.to_string()),
    )?;
    result.set_item("rx_x", x)?;
    result.set_item("rx_y", y)?;
    result.set_item("rx_z", z)?;
    result.set_item(
        "receiver_id",
        header
            .rcvr
            .as_ref()
            .map(|r| format!("{}|{}|{}", r.sn, r.model, r.firmware)),
    )?;
    Ok(result)
}

/// Decode observations and quality indicators, with Python fullmatch code filters.
/// `pivot` selects a wide table; otherwise each row contains one observation signal.
#[pyfunction]
fn _read_obs(
    py: Python<'_>,
    obs_fn: Vec<String>,
    constellations: Option<String>,
    codes: Option<Vec<String>>,
    pivot: bool,
) -> PyResult<(Py<PyDict>, PyArrowType<RecordBatch>)> {
    let observations = py.detach(|| rinex_io::read_files(&obs_fn))?;
    let constellations: FxHashSet<_> = constellations
        .as_deref()
        .unwrap_or(ALL_CONSTELLATIONS)
        .chars()
        .filter(|&code| ALL_CONSTELLATIONS.contains(code))
        .filter_map(|code| Constellation::from_str(&code.to_string()).ok())
        .collect();
    let observables = select_observables(py, &observations.header, codes)?;
    let header = header_dict(py, &observations.header)?;
    let first = observations
        .observations_iter()
        .next()
        .map(|(key, _)| key.epoch);
    let scale = first
        .map(|epoch| epoch.time_scale)
        .unwrap_or(TimeScale::GPST);
    let version = observations.header.version.major;
    let events = py.detach(|| {
        let mut events = Vec::new();
        for path in &obs_fn {
            events.extend(quality::events(path, version, scale)?);
        }
        events.sort_by_key(|event| event.0);
        Ok::<_, PyErr>(events)
    })?;
    header.set_item("epoch_events", events)?;
    header.set_item("first_epoch", first.map(quality::unix_ns).transpose()?)?;
    let batch = py.detach(|| {
        observations::record_batch(observations, &constellations, observables.as_ref(), pivot)
    })?;
    Ok((header.into(), PyArrowType(batch)))
}

/// Propagate navigation records for UTC nanosecond epoch/satellite pairs.
/// Geometry is private to TEC preparation and is never part of reader output.
#[pyfunction]
fn _satellite_positions(
    py: Python<'_>,
    mut nav_fn: Vec<String>,
    times: Vec<i64>,
    prns: Vec<String>,
) -> PyResult<PyArrowType<RecordBatch>> {
    if times.len() != prns.len() {
        return Err(PyValueError::new_err("Epoch and PRN lengths must match"));
    }
    nav_fn.sort();
    py.detach(|| navigation::record_batch(&nav_fn, times, prns))
        .map(PyArrowType)
}

#[pymodule]
fn _core(m: &Bound<'_, PyModule>) -> PyResult<()> {
    m.add_function(wrap_pyfunction!(_read_obs, m)?)?;
    m.add_function(wrap_pyfunction!(_satellite_positions, m)?)?;
    m.add_function(wrap_pyfunction!(_select_observations, m)?)?;
    m.add_function(wrap_pyfunction!(_basic_arcs, m)?)?;
    m.add_function(wrap_pyfunction!(_azimuth_elevation, m)?)?;
    m.add_function(wrap_pyfunction!(_ecef_to_geodetic, m)?)?;
    Ok(())
}

#[pyfunction]
fn _azimuth_elevation(
    py: Python<'_>,
    input: PyArrowType<RecordBatch>,
) -> PyResult<PyArrowType<RecordBatch>> {
    py.detach(|| geometry::azimuth_elevation(input.0))
        .map(PyArrowType)
}

#[pyfunction]
fn _ecef_to_geodetic(x: f64, y: f64, z: f64) -> (f64, f64, f64) {
    geometry::ecef_to_geodetic(x, y, z)
}

#[pyfunction]
fn _basic_arcs(
    py: Python<'_>,
    input: PyArrowType<RecordBatch>,
    cadence: Option<f64>,
) -> PyResult<PyArrowType<RecordBatch>> {
    py.detach(|| selection::basic_arcs(input.0, cadence))
        .map(PyArrowType)
}

#[pyfunction]
fn _select_observations(
    py: Python<'_>,
    input: PyArrowType<RecordBatch>,
    pairs: Vec<(String, String, String, u32, f64, f64)>,
    bias: Option<PyArrowType<RecordBatch>>,
    receiver: bool,
) -> PyResult<PyArrowType<RecordBatch>> {
    py.detach(|| selection::record_batch(input.0, pairs, bias.map(|batch| batch.0), receiver))
        .map(PyArrowType)
}
