//! Python entry points; parsing, table construction and geometry live in Rust modules.
mod calculation;
mod io;
mod signals;

use calculation::{geometry, navigation};
use io::{observations, quality, rinex as rinex_io};
use signals::{arcs as slips, selection};

use std::{str::FromStr, sync::Arc};

use arrow::{array::RecordBatch, pyarrow::PyArrowType};
use pyo3::{exceptions::PyValueError, prelude::*, types::PyDict};
use rinex::prelude::*;
use rustc_hash::FxHashSet;

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
#[pyo3(signature = (obs_fn, constellations, codes, pivot, include_lli=false))]
fn _read_obs(
    py: Python<'_>,
    obs_fn: Vec<String>,
    constellations: Option<String>,
    codes: Option<Vec<String>>,
    pivot: bool,
    include_lli: bool,
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
    let events = py.detach(|| {
        let mut events = Vec::new();
        for path in &obs_fn {
            events.extend(quality::events(path)?);
        }
        events.sort_by_key(|event| event.0);
        Ok::<_, PyErr>(events)
    })?;
    let integer_cycles = rinex_io::integer_cycles(&obs_fn)?
        && !events.iter().any(|(_, _, text)| {
            text.contains("WAVELENGTH FACT L1/2") || text.contains("SYS / SCALE FACTOR")
        });
    header.set_item("phase_integer_cycles", integer_cycles)?;
    header.set_item("epoch_events", events)?;
    header.set_item("first_epoch", first.map(quality::unix_ns).transpose()?)?;
    let batch = py.detach(|| {
        observations::record_batch(
            observations,
            &constellations,
            observables.as_ref(),
            pivot,
            include_lli,
        )
    })?;
    Ok((header.into(), PyArrowType(batch)))
}

#[pyclass(frozen)]
struct _NavigationData {
    store: Arc<navigation::NavigationStore>,
}

#[pymethods]
impl _NavigationData {
    #[getter]
    fn sources(&self) -> Vec<String> {
        self.store.sources.clone()
    }
    #[getter]
    fn satellites(&self) -> Vec<String> {
        self.store.satellites.clone()
    }
    #[getter]
    fn constellations(&self) -> &str {
        &self.store.constellations
    }
    #[getter]
    fn n_ephemerides(&self) -> usize {
        self.store.n_ephemerides
    }
    #[getter]
    fn epoch_range(&self) -> Option<(i64, i64)> {
        self.store.epoch_range
    }
}

#[pyfunction]
fn _read_nav(
    py: Python<'_>,
    nav_fn: Vec<String>,
    constellations: Option<String>,
) -> PyResult<_NavigationData> {
    let store =
        py.detach(|| navigation::NavigationStore::load(nav_fn, constellations.as_deref(), None))?;
    Ok(_NavigationData {
        store: Arc::new(store),
    })
}

/// Borrow a loaded store; the Arrow query buffers remain in their original allocation.
#[pyfunction]
fn _satellite_positions(
    py: Python<'_>,
    navigation: &_NavigationData,
    input: PyArrowType<RecordBatch>,
) -> PyResult<PyArrowType<RecordBatch>> {
    let store = Arc::clone(&navigation.store);
    py.detach(|| store.record_batch(input.0)).map(PyArrowType)
}

#[pyfunction]
fn _satellite_positions_from_files(
    py: Python<'_>,
    nav_fn: Vec<String>,
    input: PyArrowType<RecordBatch>,
) -> PyResult<PyArrowType<RecordBatch>> {
    py.detach(|| navigation::record_batch(nav_fn, input.0))
        .map(PyArrowType)
}

#[pymodule]
fn _core(m: &Bound<'_, PyModule>) -> PyResult<()> {
    m.add_function(wrap_pyfunction!(_read_obs, m)?)?;
    m.add_class::<_NavigationData>()?;
    m.add_function(wrap_pyfunction!(_read_nav, m)?)?;
    m.add_function(wrap_pyfunction!(_satellite_positions, m)?)?;
    m.add_function(wrap_pyfunction!(_satellite_positions_from_files, m)?)?;
    m.add_function(wrap_pyfunction!(_select_observations, m)?)?;
    m.add_function(wrap_pyfunction!(_basic_arcs, m)?)?;
    m.add_function(wrap_pyfunction!(_slip_arcs, m)?)?;
    m.add_function(wrap_pyfunction!(_smooth_stec, m)?)?;
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
    py.detach(|| slips::basic_arcs(input.0, cadence))
        .map(PyArrowType)
}

#[pyfunction]
fn _slip_arcs(
    py: Python<'_>,
    input: PyArrowType<RecordBatch>,
    cadence: Option<f64>,
    repair: bool,
    integer_cycles: bool,
) -> PyResult<PyArrowType<RecordBatch>> {
    py.detach(|| slips::arcs(input.0, cadence, repair, integer_cycles))
        .map(PyArrowType)
}

#[pyfunction]
fn _smooth_stec(
    py: Python<'_>,
    input: PyArrowType<RecordBatch>,
) -> PyResult<PyArrowType<RecordBatch>> {
    py.detach(|| slips::smooth_stec(input.0)).map(PyArrowType)
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
