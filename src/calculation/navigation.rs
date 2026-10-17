//! Index broadcast records and propagate private satellite geometry.
use std::{str::FromStr, sync::Arc};

use arrow::{
    array::{Array, ArrayRef, Float64Array, Int64Array, LargeStringArray, RecordBatch},
    datatypes::{DataType, Field, Schema},
};
use pyo3::{PyResult, exceptions::PyValueError};
use rayon::prelude::*;
use rinex::{
    navigation::{Ephemeris, Perturbations},
    prelude::*,
};
use rustc_hash::{FxHashMap, FxHashSet};

use super::glonass::BroadcastState;
use crate::io::rinex as rinex_io;

enum Orbit {
    Kepler(Box<Ephemeris>),
    Glonass(Option<BroadcastState>),
    Unsupported,
}

struct NavigationRecord {
    epoch: Epoch,
    utc: Duration,
    source_order: usize,
    orbit: Orbit,
}

impl NavigationRecord {
    fn position(&self, satellite: SV, epoch: Epoch) -> Option<[f64; 3]> {
        match &self.orbit {
            Orbit::Glonass(state) => state.as_ref()?.position((epoch - self.epoch).to_seconds()),
            Orbit::Kepler(ephemeris) => ephemeris
                .kepler2position_velocity(satellite, epoch)
                .map(|(position, _)| [position.x * 1e3, position.y * 1e3, position.z * 1e3]),
            Orbit::Unsupported => None, // No validated SBAS propagation is available.
        }
    }
}

fn replenish_perturbations(ephemeris: &Ephemeris) -> Ephemeris {
    let (Some(crc), Some(crs)) = (
        ephemeris.get_orbit_f64("crc"),
        ephemeris.get_orbit_f64("crs"),
    ) else {
        return ephemeris.clone();
    };
    ephemeris.with_perturbations(Perturbations {
        cuc: ephemeris.get_orbit_f64("cuc").unwrap_or(0.0),
        cus: ephemeris.get_orbit_f64("cus").unwrap_or(0.0),
        cic: ephemeris.get_orbit_f64("cic").unwrap_or(0.0),
        cis: ephemeris.get_orbit_f64("cis").unwrap_or(0.0),
        crc,
        crs,
        dn: ephemeris.get_orbit_f64("deltaN").unwrap_or(0.0),
        i_dot: ephemeris.get_orbit_f64("idot").unwrap_or(0.0),
        omega_dot: ephemeris.get_orbit_f64("omegaDot").unwrap_or(0.0),
    })
}

fn index_records(
    navigation: &Rinex,
    satellites: &FxHashSet<SV>,
) -> FxHashMap<SV, Vec<NavigationRecord>> {
    let mut records: FxHashMap<SV, Vec<NavigationRecord>> = FxHashMap::default();
    for (source_order, (key, ephemeris)) in navigation.nav_ephemeris_frames_iter().enumerate() {
        if !satellites.contains(&key.sv) {
            continue;
        }
        let orbit = if key.sv.constellation == Constellation::Glonass {
            Orbit::Glonass(BroadcastState::from_ephemeris(ephemeris))
        } else if key.sv.constellation.is_sbas() {
            Orbit::Unsupported
        } else {
            Orbit::Kepler(Box::new(replenish_perturbations(ephemeris)))
        };
        records.entry(key.sv).or_default().push(NavigationRecord {
            epoch: key.epoch,
            utc: key.epoch.to_duration_in_time_scale(TimeScale::UTC),
            source_order,
            orbit,
        });
    }
    for satellite_records in records.values_mut() {
        sort_records(satellite_records);
    }
    records
}

fn sort_records(records: &mut Vec<NavigationRecord>) {
    // Stable sorting retains the upstream first record at duplicate timestamps.
    records.sort_by_key(|record| record.utc);
    records.dedup_by_key(|record| record.utc);
}

fn nearest_record(records: &[NavigationRecord], utc: Duration) -> Option<&NavigationRecord> {
    let next = records.partition_point(|record| record.utc < utc);
    let before = next.checked_sub(1).map(|index| &records[index]);
    let after = records.get(next);
    match (before, after) {
        (Some(before), Some(after)) => {
            // Preserve min_by_key's first-in-source-order choice for equal distance.
            // UTC durations match the original subtraction for the UTC input epochs.
            let before_key = ((utc - before.utc).abs(), before.source_order);
            let after_key = ((after.utc - utc).abs(), after.source_order);
            Some(if before_key <= after_key {
                before
            } else {
                after
            })
        }
        (before, after) => before.or(after),
    }
}

pub(crate) fn record_batch(paths: Vec<String>, input: RecordBatch) -> PyResult<RecordBatch> {
    let satellites = query_satellites(&input)?;
    let selected = satellites.iter().copied().collect();
    let store = NavigationStore::load(paths, None, Some(&selected))?;
    store.positions(input, &satellites)
}

/// Owned, immutable propagation records. The decoded RINEX is dropped after indexing.
pub(crate) struct NavigationStore {
    records: FxHashMap<SV, Vec<NavigationRecord>>,
    pub(crate) sources: Vec<String>,
    pub(crate) satellites: Vec<String>,
    pub(crate) constellations: String,
    pub(crate) n_ephemerides: usize,
    pub(crate) epoch_range: Option<(i64, i64)>,
}

impl NavigationStore {
    pub(crate) fn load(
        mut paths: Vec<String>,
        constellations: Option<&str>,
        selected: Option<&FxHashSet<SV>>,
    ) -> PyResult<Self> {
        paths.sort();
        let navigation = rinex_io::read_files(&paths)?;
        if navigation.header.nav.is_none() {
            return Err(PyValueError::new_err("Expected a RINEX navigation file"));
        }
        if !(2..=3).contains(&navigation.header.version.major) {
            return Err(PyValueError::new_err(
                "Navigation reading supports RINEX 2/3",
            ));
        }
        let mut satellites = selected.cloned().unwrap_or_else(|| {
            navigation
                .nav_ephemeris_frames_iter()
                .map(|(key, _)| key.sv)
                .collect()
        });
        if let Some(codes) = constellations {
            satellites.retain(|sv| codes.contains(&format!("{:x}", sv.constellation)));
        }
        let records = index_records(&navigation, &satellites);
        drop(navigation);
        let mut satellites: Vec<_> = records.keys().map(|sv| format!("{sv:x}")).collect();
        satellites.sort();
        let mut codes: Vec<_> = satellites
            .iter()
            .map(|name| name.as_bytes()[0] as char)
            .collect();
        codes.sort();
        codes.dedup();
        let mut epoch_range: Option<(i64, i64)> = None;
        let mut n_ephemerides = 0;
        for satellite_records in records.values() {
            n_ephemerides += satellite_records.len();
            // The per-SV index is sorted: only its endpoints can extend the range.
            for record in [satellite_records.first(), satellite_records.last()]
                .into_iter()
                .flatten()
            {
                let time = crate::io::quality::unix_ns(record.epoch)?;
                epoch_range = Some(match epoch_range {
                    Some((start, end)) => (start.min(time), end.max(time)),
                    None => (time, time),
                });
            }
        }
        Ok(Self {
            records,
            sources: paths,
            satellites,
            constellations: codes.into_iter().collect(),
            n_ephemerides,
            epoch_range,
        })
    }

    pub(crate) fn record_batch(&self, input: RecordBatch) -> PyResult<RecordBatch> {
        let satellites = query_satellites(&input)?;
        self.positions(input, &satellites)
    }

    fn positions(&self, input: RecordBatch, satellites: &[SV]) -> PyResult<RecordBatch> {
        let (times, _) = query_arrays(&input)?;
        let (xs, (ys, zs)): (Vec<_>, (Vec<_>, Vec<_>)) = times
            .values()
            .par_iter()
            .zip(satellites.par_iter())
            .map(|(&time, &satellite)| {
                let epoch =
                    Epoch::from_unix_duration(Duration::from_total_nanoseconds(time as i128));
                let position = self
                    .records
                    .get(&satellite)
                    .and_then(|records| nearest_record(records, epoch.duration))
                    .and_then(|record| record.position(satellite, epoch));
                let [x, y, z] = position.unwrap_or([f64::NAN; 3]);
                (x, (y, z))
            })
            .unzip();
        let fields = vec![
            Field::new("_utc_ns", DataType::Int64, false),
            Field::new("prn", DataType::LargeUtf8, false),
            Field::new("_sat_x", DataType::Float64, false),
            Field::new("_sat_y", DataType::Float64, false),
            Field::new("_sat_z", DataType::Float64, false),
        ];
        let arrays: Vec<ArrayRef> = vec![
            input.column_by_name("_utc_ns").unwrap().clone(),
            input.column_by_name("prn").unwrap().clone(),
            Arc::new(Float64Array::from(xs)),
            Arc::new(Float64Array::from(ys)),
            Arc::new(Float64Array::from(zs)),
        ];
        RecordBatch::try_new(Arc::new(Schema::new(fields)), arrays)
            .map_err(|error| PyValueError::new_err(error.to_string()))
    }
}

fn query_arrays(input: &RecordBatch) -> PyResult<(&Int64Array, &LargeStringArray)> {
    let times = input
        .column_by_name("_utc_ns")
        .and_then(|column| column.as_any().downcast_ref::<Int64Array>())
        .ok_or_else(|| PyValueError::new_err("Navigation queries require Int64 _utc_ns"))?;
    let prns = input
        .column_by_name("prn")
        .and_then(|column| column.as_any().downcast_ref::<LargeStringArray>())
        .ok_or_else(|| PyValueError::new_err("Navigation queries require LargeUtf8 prn"))?;
    if times.null_count() != 0 || prns.null_count() != 0 {
        return Err(PyValueError::new_err(
            "Navigation query times and PRNs must not be null",
        ));
    }
    Ok((times, prns))
}

fn query_satellites(input: &RecordBatch) -> PyResult<Vec<SV>> {
    let (_, prns) = query_arrays(input)?;
    let mut satellite_names = FxHashMap::default();
    prns.iter()
        .map(|prn| {
            let prn = prn.expect("validated non-null PRN");
            if let Some(satellite) = satellite_names.get(prn) {
                return Ok(*satellite);
            }
            let satellite =
                SV::from_str(prn).map_err(|error| PyValueError::new_err(error.to_string()))?;
            satellite_names.insert(prn, satellite);
            Ok(satellite)
        })
        .collect()
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn indexed_selection_matches_linear_selection_at_boundaries_and_ties() {
        let origin = Epoch::from_gregorian_utc(2024, 1, 10, 0, 0, 0, 0);
        // Unsorted source order, duplicate epochs and mixed broadcast time scales.
        let epochs: Vec<_> = [30, 10, 10, 20]
            .into_iter()
            .map(|seconds| origin + Duration::from_seconds(seconds as f64))
            .enumerate()
            .map(|(i, epoch)| {
                epoch.to_time_scale(if i % 2 == 0 {
                    TimeScale::GPST
                } else {
                    TimeScale::UTC
                })
            })
            .collect();
        let mut records = epochs
            .iter()
            .enumerate()
            .map(|(source_order, &epoch)| NavigationRecord {
                epoch,
                utc: epoch.to_duration_in_time_scale(TimeScale::UTC),
                source_order,
                orbit: Orbit::Unsupported,
            })
            .collect();
        sort_records(&mut records);
        for nanoseconds in [
            -1,
            0,
            10_000_000_000,
            14_999_999_999,
            15_000_000_000,
            15_000_000_001,
            20_000_000_000,
            25_000_000_000,
            30_000_000_000,
            40_000_000_000,
        ] {
            let epoch = origin + Duration::from_total_nanoseconds(nanoseconds);
            let expected = epochs
                .iter()
                .enumerate()
                .min_by_key(|(_, reference)| (epoch - **reference).abs())
                .unwrap()
                .0;
            assert_eq!(
                nearest_record(&records, epoch.duration)
                    .unwrap()
                    .source_order,
                expected
            );
        }
        assert!(nearest_record(&[], origin.duration).is_none());
    }
}
