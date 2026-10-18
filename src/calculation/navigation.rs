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
    validity: Option<(Epoch, Duration)>,
}

impl NavigationRecord {
    fn eligible(&self, epoch: Epoch) -> bool {
        self.validity
            .is_some_and(|(reference, limit)| (epoch - reference).abs() <= limit)
    }

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

fn validity(ephemeris: &Ephemeris, satellite: SV, toc: Epoch) -> Option<(Epoch, Duration)> {
    if !matches!(
        satellite.constellation,
        Constellation::GPS
            | Constellation::BeiDou
            | Constellation::Galileo
            | Constellation::Glonass
    ) {
        return None;
    }
    // Galileo is not implemented by upstream sv_healthy. Require all broadcast
    // health/data-validity bits clear because this geometry API has no signal selector.
    let healthy = if satellite.constellation == Constellation::Galileo {
        ephemeris
            .orbits
            .get("health")
            .and_then(|item| item.as_galileo_health_flag())
            .is_some_and(|health| health.is_empty())
    } else {
        ephemeris.sv_healthy()
    };
    if !healthy {
        return None;
    }
    if satellite.constellation == Constellation::Glonass {
        return Some((toc, Duration::from_seconds(900.0)));
    }
    // Check before toe(): upstream converts the floating field to unsigned ns.
    let toe_seconds = ephemeris.get_orbit_f64("toe")?;
    let week = ephemeris.get_orbit_f64("week")?;
    if !toe_seconds.is_finite()
        || !(0.0..604800.0).contains(&toe_seconds)
        || !week.is_finite()
        || week < 0.0
        || week.fract() != 0.0
    {
        return None;
    }
    let reference = ephemeris.toe(satellite)?;
    let mut limit = Ephemeris::validity_duration(satellite.constellation)?;
    if satellite.constellation == Constellation::GPS
        && let Some(fit) = ephemeris.get_orbit_f64("fitInt")
    {
        if !fit.is_finite() || fit < 0.0 {
            return None;
        }
        // RINEX GPS fit interval is hours; zero/omitted retains our age cap.
        // Longer intervals do not relax the two-hour limit.
        if fit > 0.0 {
            limit = limit.min(Duration::from_hours(fit / 2.0));
        }
    }
    Some((reference, limit))
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
            validity: validity(ephemeris, key.sv, key.epoch),
        });
    }
    for satellite_records in records.values_mut() {
        sort_records(satellite_records);
    }
    records
}

fn sort_records(records: &mut [NavigationRecord]) {
    // Stable sorting retains the upstream first record at duplicate timestamps.
    records.sort_by_key(|record| record.utc);
    // Keep duplicates until eligibility is known. An invalid first record must
    // not hide a valid alternative with the same reference epoch.
}

fn nearest_record(records: &[NavigationRecord], epoch: Epoch) -> Option<&NavigationRecord> {
    let utc = epoch.to_duration_in_time_scale(TimeScale::UTC);
    let next = records.partition_point(|record| record.utc < utc);
    let before = first_eligible_epoch(records[..next].iter().rev(), epoch);
    let after = first_eligible_epoch(records[next..].iter(), epoch);
    before
        .into_iter()
        .chain(after)
        .min_by_key(|record| ((utc - record.utc).abs(), record.source_order))
}

fn first_eligible_epoch<'a>(
    records: impl Iterator<Item = &'a NavigationRecord>,
    epoch: Epoch,
) -> Option<&'a NavigationRecord> {
    let mut found: Option<&NavigationRecord> = None;
    for record in records {
        if found.is_some_and(|best| best.utc != record.utc) {
            break;
        }
        if record.eligible(epoch)
            && found.is_none_or(|best| record.source_order < best.source_order)
        {
            found = Some(record);
        }
    }
    found
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
            // Keep the public count of distinct per-SV reference epochs, even
            // though duplicate candidates now remain available for eligibility.
            n_ephemerides += satellite_records.chunk_by(|a, b| a.utc == b.utc).count();
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
                    .and_then(|records| nearest_record(records, epoch))
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
        let mut records: Vec<_> = epochs
            .iter()
            .enumerate()
            .map(|(source_order, &epoch)| NavigationRecord {
                epoch,
                utc: epoch.to_duration_in_time_scale(TimeScale::UTC),
                source_order,
                orbit: Orbit::Unsupported,
                validity: Some((origin, Duration::from_seconds(100.0))),
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
                nearest_record(&records, epoch).unwrap().source_order,
                expected
            );
        }
        assert!(nearest_record(&[], origin).is_none());
    }

    #[test]
    fn eligibility_precedes_nearest_and_duplicate_selection() {
        let origin = Epoch::from_gregorian_utc(2024, 1, 10, 0, 0, 0, 0);
        let mut records: Vec<_> = [(0, None), (0, Some(10.0)), (5, Some(0.0))]
            .into_iter()
            .enumerate()
            .map(|(source_order, (seconds, valid_seconds))| {
                let epoch = origin + Duration::from_seconds(seconds as f64);
                NavigationRecord {
                    epoch,
                    utc: epoch.to_duration_in_time_scale(TimeScale::UTC),
                    source_order,
                    orbit: Orbit::Unsupported,
                    validity: valid_seconds
                        .map(|seconds| (origin, Duration::from_seconds(seconds))),
                }
            })
            .collect();
        sort_records(&mut records);
        // Unhealthy duplicate and expired nearest cannot hide the valid record.
        assert_eq!(nearest_record(&records, origin).unwrap().source_order, 1);
        assert_eq!(
            nearest_record(&records, origin + Duration::from_seconds(5.0))
                .unwrap()
                .source_order,
            1
        );
        for seconds in [-10.0, 10.0] {
            assert!(nearest_record(&records, origin + Duration::from_seconds(seconds)).is_some());
            assert!(
                nearest_record(&records, origin + Duration::from_seconds(seconds * 1.001))
                    .is_none()
            );
        }
    }
}
