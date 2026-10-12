mod glonass;
mod quality;

use rayon::prelude::*;
use rustc_hash::{FxHashMap, FxHashSet};
use std::str::FromStr;
use std::sync::Arc;

use arrow::array::{ArrayRef, Float64Array, Int64Array, LargeStringArray, RecordBatch, UInt8Array};
use arrow::datatypes::{DataType, Field, Schema};
use arrow::pyarrow::PyArrowType;
use pyo3::exceptions::{PyIOError, PyValueError};
use pyo3::prelude::*;
use pyo3::types::PyDict;
use rinex::navigation::{Ephemeris, Perturbations};
use rinex::prelude::{qc::Merge, *};

#[cfg(all(feature = "custom-alloc", target_family = "unix"))]
use tikv_jemallocator::Jemalloc;

#[cfg(all(feature = "custom-alloc", target_family = "unix"))]
#[global_allocator]
static GLOBAL: Jemalloc = Jemalloc;

#[cfg(all(feature = "custom-alloc", target_family = "windows"))]
use mimalloc::MiMalloc;

#[cfg(all(feature = "custom-alloc", target_family = "windows"))]
#[global_allocator]
static GLOBAL: MiMalloc = MiMalloc;

// All supported constellations: G - GPS, C - BeiDou, E - Galileo, R - GLONASS, J - QZSS, I - IRNSS, S - SBAS
const ALL_CONSTELLATIONS: &str = "GCERJIS";

fn read_rinex_file(path: &str) -> PyResult<Rinex> {
    if path.ends_with(".gz") {
        Rinex::from_gzip_file(path).map_err(|e| PyIOError::new_err(e.to_string()))
    } else {
        Rinex::from_file(path).map_err(|e| PyIOError::new_err(e.to_string()))
    }
}

fn read_rinex_files(paths: Vec<String>) -> PyResult<Rinex> {
    let first_path = paths
        .first()
        .ok_or_else(|| PyValueError::new_err("No RINEX file paths provided"))?;
    let mut rinex = read_rinex_file(first_path)?;
    for path in paths.iter().skip(1) {
        let next_rinex = read_rinex_file(path)?;
        rinex
            .merge_mut(&next_rinex)
            .map_err(|e| PyValueError::new_err(format!("RINEX merge failed: {e}")))?;
    }
    Ok(rinex)
}

fn replenish_perturbations(eph: &Ephemeris) -> Ephemeris {
    let crc = eph.get_orbit_f64("crc");
    let crs = eph.get_orbit_f64("crs");

    if crc.is_some() && crs.is_some() {
        return eph.with_perturbations(Perturbations {
            cuc: eph.get_orbit_f64("cuc").unwrap_or(0.0),
            cus: eph.get_orbit_f64("cus").unwrap_or(0.0),
            cic: eph.get_orbit_f64("cic").unwrap_or(0.0),
            cis: eph.get_orbit_f64("cis").unwrap_or(0.0),
            crc: crc.unwrap(),
            crs: crs.unwrap(),
            dn: eph.get_orbit_f64("deltaN").unwrap_or(0.0),
            i_dot: eph.get_orbit_f64("idot").unwrap_or(0.0),
            omega_dot: eph.get_orbit_f64("omegaDot").unwrap_or(0.0),
        });
    } else {
        eph.clone()
    }
}

fn get_sat_pos(
    nav_rnx: &Rinex,
    epochs: Vec<Epoch>,
    svs: Vec<SV>,
) -> (Vec<f64>, Vec<f64>, Vec<f64>) {
    let sv_set: FxHashSet<SV> = svs.iter().copied().collect();
    let mut ephs_by_sv: FxHashMap<SV, Vec<(Epoch, Ephemeris)>> = FxHashMap::default();
    for (key, eph) in nav_rnx.nav_ephemeris_frames_iter() {
        if sv_set.contains(&key.sv) {
            ephs_by_sv
                .entry(key.sv)
                .or_default()
                .push((key.epoch, replenish_perturbations(eph)));
        }
    }

    let (xs, (ys, zs)) = (epochs, svs)
        .into_par_iter()
        .map(|(epoch, sv)| {
            let pos = ephs_by_sv.get(&sv).and_then(|eph_list| {
                eph_list
                    .iter()
                    .min_by_key(|(eph_epoch, _)| (epoch - *eph_epoch).abs())
                    .and_then(|(eph_epoch, eph)| {
                        if sv.constellation == Constellation::Glonass {
                            glonass::position(eph, (epoch - *eph_epoch).to_seconds())
                        } else if sv.constellation.is_sbas() {
                            None // No validated SBAS propagation is available.
                        } else {
                            eph.kepler2position_velocity(sv, epoch)
                                .map(|pv| [pv.0.x * 1e3, pv.0.y * 1e3, pv.0.z * 1e3])
                        }
                    })
            });
            match pos {
                Some(p) => (p[0], (p[1], p[2])),
                None => (f64::NAN, (f64::NAN, f64::NAN)),
            }
        })
        .unzip();

    (xs, ys, zs)
}

fn pivot_observations(
    obs_rnx: Rinex,
    const_filter: FxHashSet<Constellation>,
    observables: Option<&FxHashSet<Observable>>,
) -> PyResult<(Vec<i64>, Vec<SV>, Vec<u8>, FxHashMap<String, Vec<f64>>)> {
    // 行索引：(epoch, sv) -> row_idx
    let mut row_index: FxHashMap<(&Epoch, &SV), usize> = FxHashMap::default();

    // 列数据：observable code -> column values
    let mut code_value: FxHashMap<String, Vec<f64>> = FxHashMap::default();

    // 时间和 SV 列
    let mut time: Vec<i64> = Vec::new();
    let mut svs: Vec<SV> = Vec::new();
    let mut flags: Vec<u8> = Vec::new();

    for (key, obs) in obs_rnx.observations_iter() {
        let epoch_ns = quality::unix_ns(key.epoch)?;
        for signal in obs.signals.iter() {
            if !const_filter.contains(&signal.sv.constellation) {
                continue;
            }
            if let Some(obs) = observables {
                if !obs.contains(&signal.observable) {
                    continue;
                }
            }

            // 行索引：确定 row_idx
            let row_key = (&key.epoch, &signal.sv);
            let row_idx = *row_index.entry(row_key).or_insert_with(|| {
                // 记录行的 Time, PRN
                time.push(epoch_ns);
                svs.push(signal.sv);
                flags.push(key.flag as u8);

                // 新行索引
                time.len() - 1
            });

            // 列索引：确定 col_idx，惰性填充
            let code = signal.observable.to_string();
            let col = code_value.entry(code).or_insert_with(Vec::new);
            if col.len() < time.len() {
                col.resize(time.len(), f64::NAN);
            }

            // 写入单元格
            col[row_idx] = signal.value;
            let lli = code_value
                .entry(format!("{}_lli", signal.observable))
                .or_default();
            lli.resize(time.len(), f64::NAN);
            lli[row_idx] = signal.lli.map(|f| f.bits() as f64).unwrap_or(f64::NAN);
        }
    }

    // 对于每一列，补齐长度
    let total_rows = time.len();
    for col in code_value.values_mut() {
        if col.len() < total_rows {
            col.resize(total_rows, f64::NAN);
        }
    }

    Ok((time, svs, flags, code_value))
}

/// Decode RINEX observations and their original quality indicators.
/// # Arguments
/// - `obs_fn` - Vector of paths to RINEX observation files.
/// - `constellations` - Optional string of constellation codes to filter (e.g., "CGE").
/// - `codes` - Optional Python regular expressions, matched against complete codes.
/// - `pivot` - Whether to pivot the observation data.
/// # Returns
/// - `PyResult<PyDict>` - Dictionary containing the RINEX header information.
/// - `PyResult<PyArrowType<RecordBatch>>` - Arrow RecordBatch containing the observation data.
#[pyfunction]
fn _read_obs(
    py: Python<'_>,
    obs_fn: Vec<String>,
    constellations: Option<String>,
    codes: Option<Vec<String>>,
    pivot: bool,
) -> PyResult<(Py<PyDict>, PyArrowType<RecordBatch>)> {
    // Read RINEX observation file(s) and process inputs
    let obs_rnx = read_rinex_files(obs_fn.clone())?;
    let const_filter: FxHashSet<Constellation> = constellations
        .unwrap_or(ALL_CONSTELLATIONS.to_string())
        .chars()
        .filter(|&c| ALL_CONSTELLATIONS.contains(c))
        .filter_map(|c| Constellation::from_str(&c.to_string()).ok())
        .collect();
    let observables = if let Some(code_patterns) = codes {
        let re = py.import("re")?;
        let patterns = code_patterns
            .iter()
            .map(|pattern| {
                re.call_method1("compile", (pattern,)).map_err(|error| {
                    PyValueError::new_err(format!(
                        "Invalid observation code pattern {pattern:?}: {error}"
                    ))
                })
            })
            .collect::<PyResult<Vec<_>>>()?;
        let observation_header = obs_rnx
            .header
            .obs
            .as_ref()
            .ok_or_else(|| PyValueError::new_err("Expected a RINEX observation file"))?;
        let mut selected = FxHashSet::default();
        for observable in observation_header.codes.values().flatten() {
            let code = observable.to_string();
            for pattern in &patterns {
                if !pattern.call_method1("fullmatch", (&code,))?.is_none() {
                    selected.insert(observable.clone());
                    break;
                }
            }
        }
        Some(selected)
    } else {
        None
    };

    // construct header dict
    let header = &obs_rnx.header;
    let version = format!("{}.{:02}", header.version.major, header.version.minor);
    let constellation = header.constellation.and_then(|c| Some(c.to_string()));
    let sampling_interval = header
        .sampling_interval
        .map(|duration| duration.to_seconds());
    let leap_seconds = header.leap.and_then(|leap| Some(leap.leap));
    let (x_m, y_m, z_m) = header.rx_position.unwrap_or((f64::NAN, f64::NAN, f64::NAN));
    let marker = header.geodetic_marker.as_ref();
    let marker_name = marker
        .and_then(|m| Some(m.name.clone()))
        .unwrap_or("Unknown".to_string());
    let marker_type = marker.and_then(|m| m.marker_type.and_then(|mt| Some(mt.to_string())));

    let header_dict = PyDict::new(py);
    header_dict.set_item("version", version)?;
    header_dict.set_item("constellation", constellation)?;
    header_dict.set_item("sampling_interval", sampling_interval)?;
    header_dict.set_item("leap_seconds", leap_seconds)?;
    header_dict.set_item("station", marker_name)?;
    header_dict.set_item("marker_type", marker_type)?;
    header_dict.set_item("rx_x", x_m)?;
    header_dict.set_item("rx_y", y_m)?;
    header_dict.set_item("rx_z", z_m)?;
    header_dict.set_item(
        "receiver_id",
        header
            .rcvr
            .as_ref()
            .map(|r| format!("{}|{}|{}", r.sn, r.model, r.firmware)),
    )?;

    let scale = obs_rnx
        .observations_iter()
        .next()
        .map(|(key, _)| key.epoch.time_scale)
        .unwrap_or(TimeScale::GPST);
    let mut events = Vec::new();
    for path in &obs_fn {
        events.extend(quality::events(path, header.version.major, scale)?);
    }
    events.sort_by_key(|e| e.0);
    header_dict.set_item("epoch_events", events)?;
    header_dict.set_item(
        "first_epoch",
        obs_rnx
            .observations_iter()
            .next()
            .map(|(key, _)| quality::unix_ns(key.epoch))
            .transpose()?,
    )?;

    let mut fields: Vec<Field>;
    let mut arrays: Vec<ArrayRef>;
    let epoch_flags: Vec<u8>;
    if pivot {
        let (time, svs, flags, code_value) =
            pivot_observations(obs_rnx, const_filter, observables.as_ref())?;
        epoch_flags = flags;
        let prn: Vec<_> = svs.par_iter().map(|sv| sv.to_string()).collect();
        fields = vec![
            Field::new("time", DataType::Int64, false),
            Field::new("prn", DataType::LargeUtf8, false),
        ];
        arrays = vec![
            Arc::new(Int64Array::from(time)),
            Arc::new(LargeStringArray::from(prn)),
        ];
        for (code, col) in code_value {
            if code.ends_with("_lli") {
                let lli: Vec<Option<u8>> = col
                    .iter()
                    .map(|v| v.is_finite().then_some(*v as u8))
                    .collect();
                fields.push(Field::new(code, DataType::UInt8, true));
                arrays.push(Arc::new(UInt8Array::from(lli)));
            } else {
                fields.push(Field::new(code, DataType::Float64, false));
                arrays.push(Arc::new(Float64Array::from(col)));
            }
        }
    } else {
        let mut time = Vec::new();
        let mut prn = Vec::new();
        let mut code = Vec::new();
        let mut value = Vec::new();
        let mut flags = Vec::new();
        let mut lli = Vec::new();
        for (key, obs) in obs_rnx.observations_iter() {
            let epoch_ns = quality::unix_ns(key.epoch)?;
            for signal in &obs.signals {
                if !const_filter.contains(&signal.sv.constellation) {
                    continue;
                }
                if let Some(observables) = &observables {
                    if !observables.contains(&signal.observable) {
                        continue;
                    }
                }
                time.push(epoch_ns);
                prn.push(signal.sv.to_string());
                code.push(signal.observable.to_string());
                value.push(signal.value);
                flags.push(key.flag as u8);
                lli.push(signal.lli.map(|f| f.bits()));
            }
        }
        epoch_flags = flags;
        fields = vec![
            Field::new("time", DataType::Int64, false),
            Field::new("prn", DataType::LargeUtf8, false),
            Field::new("code", DataType::LargeUtf8, false),
            Field::new("value", DataType::Float64, false),
            Field::new("lli", DataType::UInt8, true),
        ];
        arrays = vec![
            Arc::new(Int64Array::from(time)),
            Arc::new(LargeStringArray::from(prn)),
            Arc::new(LargeStringArray::from(code)),
            Arc::new(Float64Array::from(value)),
            Arc::new(UInt8Array::from(lli)),
        ];
    }
    fields.push(Field::new("epoch_flag", DataType::UInt8, false));
    arrays.push(Arc::new(UInt8Array::from(epoch_flags)));
    let batch = RecordBatch::try_new(Arc::new(Schema::new(fields)), arrays)
        .map_err(|e| PyValueError::new_err(e.to_string()))?;
    Ok((header_dict.into(), PyArrowType(batch)))
}

/// Propagate navigation records for UTC nanosecond epoch/satellite pairs.
/// Geometry is private to TEC preparation and is never part of reader output.
#[pyfunction]
fn _satellite_positions(
    mut nav_fn: Vec<String>,
    times: Vec<i64>,
    prns: Vec<String>,
) -> PyResult<PyArrowType<RecordBatch>> {
    if times.len() != prns.len() {
        return Err(PyValueError::new_err("Epoch and PRN lengths must match"));
    }
    nav_fn.sort();
    let navigation = read_rinex_files(nav_fn)?;
    let epochs = times
        .iter()
        .map(|time| Epoch::from_unix_duration(Duration::from_total_nanoseconds(*time as i128)))
        .collect();
    let svs = prns
        .iter()
        .map(|prn| SV::from_str(prn).map_err(|e| PyValueError::new_err(e.to_string())))
        .collect::<PyResult<Vec<_>>>()?;
    let (x, y, z) = get_sat_pos(&navigation, epochs, svs);
    let fields = vec![
        Field::new("_utc_ns", DataType::Int64, false),
        Field::new("prn", DataType::LargeUtf8, false),
        Field::new("_sat_x", DataType::Float64, false),
        Field::new("_sat_y", DataType::Float64, false),
        Field::new("_sat_z", DataType::Float64, false),
    ];
    let arrays: Vec<ArrayRef> = vec![
        Arc::new(Int64Array::from(times)),
        Arc::new(LargeStringArray::from(prns)),
        Arc::new(Float64Array::from(x)),
        Arc::new(Float64Array::from(y)),
        Arc::new(Float64Array::from(z)),
    ];
    let batch = RecordBatch::try_new(Arc::new(Schema::new(fields)), arrays)
        .map_err(|e| PyValueError::new_err(e.to_string()))?;
    Ok(PyArrowType(batch))
}

#[pymodule]
fn _core(m: &Bound<'_, PyModule>) -> PyResult<()> {
    m.add_function(wrap_pyfunction!(_read_obs, m)?)?;
    m.add_function(wrap_pyfunction!(_satellite_positions, m)?)?;
    Ok(())
}
