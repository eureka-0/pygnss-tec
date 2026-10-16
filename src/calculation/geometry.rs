//! WGS84 receiver coordinates and batched satellite azimuth/elevation.
use std::{
    f64::consts::{FRAC_PI_2, TAU},
    sync::Arc,
};

use arrow::{
    array::{Array, Float64Array, RecordBatch},
    datatypes::{DataType, Field, Schema},
};
use pyo3::{PyResult, exceptions::PyValueError};
use rayon::prelude::*;
use rustc_hash::FxHashMap;

const SEMIMAJOR: f64 = 6_378_137.0;
const SEMIMINOR: f64 = 6_356_752.314_245_18;
const PARALLEL_ROWS: usize = 16_384;
const OBSERVER_CACHE_LIMIT: usize = 128;

/// Convert ECEF using You (2000), including interior and pole cases.
/// Coordinates and height are metres; latitude and longitude are degrees.
pub(crate) fn ecef_to_geodetic(x: f64, y: f64, z: f64) -> (f64, f64, f64) {
    let a2 = SEMIMAJOR * SEMIMAJOR;
    let b2 = SEMIMINOR * SEMIMINOR;
    let eccentricity = (a2 - b2).sqrt();
    let r = (x * x + y * y + z * z).sqrt();
    let difference = r * r - eccentricity * eccentricity;
    let u = (0.5 * difference + 0.5 * difference.hypot(2.0 * eccentricity * z)).sqrt();
    let horizontal = x.hypot(y);
    let hu_e = u.hypot(eccentricity);
    // Treat distances within 1e-8 metres of zero as singular.
    let beta = if u.abs() <= 1e-8 || horizontal.abs() <= 1e-8 {
        if z.abs() <= 1e-8 {
            0.0
        } else if z > 0.0 {
            FRAC_PI_2
        } else {
            -FRAC_PI_2
        }
    } else {
        let beta = (hu_e / u * z / horizontal).atan();
        beta + ((SEMIMINOR * u - SEMIMAJOR * hu_e + eccentricity * eccentricity) * beta.sin())
            / (SEMIMAJOR * hu_e / beta.cos() - eccentricity * eccentricity * beta.cos())
    };
    let pole_limit = FRAC_PI_2 - f64::EPSILON;
    let (latitude, cos_beta) = if beta >= pole_limit {
        (FRAC_PI_2, 0.0)
    } else if beta <= -pole_limit {
        (-FRAC_PI_2, 0.0)
    } else {
        ((SEMIMAJOR / SEMIMINOR * beta.tan()).atan(), beta.cos())
    };
    let mut altitude = (z - SEMIMINOR * beta.sin()).hypot(horizontal - SEMIMAJOR * cos_beta);
    if x * x / a2 + y * y / a2 + z * z / b2 < 1.0 {
        altitude = -altitude;
    }
    (latitude.to_degrees(), y.atan2(x).to_degrees(), altitude)
}

struct Observer {
    origin: [f64; 3],
    sin_lat: f64,
    cos_lat: f64,
    sin_lon: f64,
    cos_lon: f64,
}

impl Observer {
    fn new(latitude: f64, longitude: f64, altitude: f64) -> Self {
        let (sin_lat, cos_lat) = latitude.to_radians().sin_cos();
        let (sin_lon, cos_lon) = longitude.to_radians().sin_cos();
        let n = SEMIMAJOR * SEMIMAJOR / (SEMIMAJOR * cos_lat).hypot(SEMIMINOR * sin_lat);
        let origin = [
            (n + altitude) * cos_lat * cos_lon,
            (n + altitude) * cos_lat * sin_lon,
            (n * (SEMIMINOR / SEMIMAJOR).powi(2) + altitude) * sin_lat,
        ];
        Self {
            origin,
            sin_lat,
            cos_lat,
            sin_lon,
            cos_lon,
        }
    }

    fn angles(&self, x: f64, y: f64, z: f64) -> (f64, f64) {
        let dx = x - self.origin[0];
        let dy = y - self.origin[1];
        let dz = z - self.origin[2];
        let along_meridian = self.cos_lon * dx + self.sin_lon * dy;
        // Snap sub-millimetre ENU components to positive zero.
        let snap = |value: f64| if value.abs() < 1e-3 { 0.0 } else { value };
        let east = snap(-self.sin_lon * dx + self.cos_lon * dy);
        let north = snap(-self.sin_lat * along_meridian + self.cos_lat * dz);
        let up = snap(self.cos_lat * along_meridian + self.sin_lat * dz);
        (
            east.atan2(north).rem_euclid(TAU).to_degrees(),
            up.atan2(east.hypot(north)).to_degrees(),
        )
    }
}

/// Cache exact observer triples within a batch, with bounded memory for moving receivers.
enum Observers {
    Uniform(Observer),
    Mixed {
        cached: Vec<Observer>,
        indices: Vec<usize>,
    },
}

impl Observers {
    fn new(coordinates: &[&Float64Array]) -> Self {
        if coordinates.iter().all(|column| {
            column
                .values()
                .iter()
                .all(|value| value.to_bits() == column.value(0).to_bits())
        }) {
            return Self::Uniform(Observer::new(
                coordinates[0].value(0),
                coordinates[1].value(0),
                coordinates[2].value(0),
            ));
        }
        let mut lookup = FxHashMap::default();
        let mut cached = Vec::new();
        let indices = (0..coordinates[0].len())
            .map(|row| {
                let key = std::array::from_fn::<_, 3, _>(|i| coordinates[i].value(row).to_bits());
                if let Some(&index) = lookup.get(&key) {
                    index
                } else if cached.len() < OBSERVER_CACHE_LIMIT {
                    let index = cached.len();
                    cached.push(Observer::new(
                        coordinates[0].value(row),
                        coordinates[1].value(row),
                        coordinates[2].value(row),
                    ));
                    lookup.insert(key, index);
                    index
                } else {
                    usize::MAX
                }
            })
            .collect();
        Self::Mixed { cached, indices }
    }

    fn angles(&self, columns: &[&Float64Array; 6], row: usize) -> (f64, f64) {
        if columns.iter().any(|column| column.is_null(row)) {
            return (f64::NAN, f64::NAN);
        }
        let observer = match self {
            Self::Uniform(observer) => Some(observer),
            Self::Mixed { cached, indices } => cached.get(indices[row]),
        };
        match observer {
            Some(observer) => observer.angles(
                columns[0].value(row),
                columns[1].value(row),
                columns[2].value(row),
            ),
            None => Observer::new(
                columns[3].value(row),
                columns[4].value(row),
                columns[5].value(row),
            )
            .angles(
                columns[0].value(row),
                columns[1].value(row),
                columns[2].value(row),
            ),
        }
    }
}

pub(crate) fn azimuth_elevation(input: RecordBatch) -> PyResult<RecordBatch> {
    let names = ["_sat_x", "_sat_y", "_sat_z", "rx_lat", "rx_lon", "_rx_alt"];
    let columns = names.map(|name| {
        input
            .column_by_name(name)
            .and_then(|array| array.as_any().downcast_ref::<Float64Array>())
            .ok_or_else(|| {
                PyValueError::new_err(format!("Missing or incompatible geometry column: {name}"))
            })
    });
    let [x, y, z, lat, lon, alt] = columns;
    let columns = [x?, y?, z?, lat?, lon?, alt?];
    let mut azimuth = vec![f64::NAN; input.num_rows()];
    let mut elevation = vec![f64::NAN; input.num_rows()];
    if input.num_rows() > 0 {
        let observers = Observers::new(&columns[3..]);
        let calculate = |(row, (azimuth, elevation)): (usize, (&mut f64, &mut f64))| {
            (*azimuth, *elevation) = observers.angles(&columns, row);
        };
        if input.num_rows() >= PARALLEL_ROWS {
            azimuth
                .par_iter_mut()
                .zip(elevation.par_iter_mut())
                .enumerate()
                .for_each(calculate);
        } else {
            azimuth
                .iter_mut()
                .zip(elevation.iter_mut())
                .enumerate()
                .for_each(calculate);
        }
    }
    let schema = Schema::new(vec![
        Field::new("azimuth", DataType::Float64, false),
        Field::new("elevation", DataType::Float64, false),
    ]);
    RecordBatch::try_new(
        Arc::new(schema),
        vec![
            Arc::new(Float64Array::from(azimuth)),
            Arc::new(Float64Array::from(elevation)),
        ],
    )
    .map_err(|error| PyValueError::new_err(error.to_string()))
}
