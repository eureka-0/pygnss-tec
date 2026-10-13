//! Construct observation tables without allocating a string for every signal.
use std::sync::Arc;

use arrow::{
    array::{
        ArrayRef, Float64Array, Int64Array, LargeStringBuilder, RecordBatch, UInt8Array,
        UInt8Builder,
    },
    datatypes::{DataType, Field, Schema},
};
use pyo3::{PyResult, exceptions::PyValueError};
use rinex::prelude::*;
use rustc_hash::{FxHashMap, FxHashSet};

use crate::quality;

#[derive(Default)]
struct ObservationColumn {
    values: Vec<f64>,
    lli: Vec<Option<u8>>,
}

pub(crate) fn record_batch(
    observations: Rinex,
    constellations: &FxHashSet<Constellation>,
    observables: Option<&FxHashSet<Observable>>,
    pivot: bool,
) -> PyResult<RecordBatch> {
    let (fields, arrays) = if pivot {
        wide(observations, constellations, observables)?
    } else {
        long(observations, constellations, observables)?
    };
    RecordBatch::try_new(Arc::new(Schema::new(fields)), arrays)
        .map_err(|error| PyValueError::new_err(error.to_string()))
}

fn wide(
    observations: Rinex,
    constellations: &FxHashSet<Constellation>,
    observables: Option<&FxHashSet<Observable>>,
) -> PyResult<(Vec<Field>, Vec<ArrayRef>)> {
    let mut row_by_satellite: FxHashMap<SV, usize> = FxHashMap::default();
    let mut previous_epoch = None;
    let mut columns: FxHashMap<&Observable, ObservationColumn> = FxHashMap::default();
    let mut times = Vec::new();
    let mut satellites = Vec::new();
    let mut flags = Vec::new();

    // The upstream BTreeMap orders epochs; only the current epoch needs an index.
    // Keep that index across flags at the same epoch to preserve existing output.
    for (key, epoch) in observations.observations_iter() {
        if previous_epoch != Some(key.epoch) {
            row_by_satellite.clear();
            previous_epoch = Some(key.epoch);
        }
        let time = quality::unix_ns(key.epoch)?;
        let mut previous_satellite = None;
        let mut previous_row = 0;
        for signal in &epoch.signals {
            if !constellations.contains(&signal.sv.constellation)
                || observables.is_some_and(|codes| !codes.contains(&signal.observable))
            {
                continue;
            }
            let row = if previous_satellite == Some(signal.sv) {
                previous_row
            } else {
                let row = *row_by_satellite.entry(signal.sv).or_insert_with(|| {
                    times.push(time);
                    satellites.push(signal.sv);
                    flags.push(key.flag as u8);
                    times.len() - 1
                });
                previous_satellite = Some(signal.sv);
                previous_row = row;
                row
            };
            let column = columns.entry(&signal.observable).or_default();
            column.values.resize(times.len(), f64::NAN);
            column.lli.resize(times.len(), None);
            column.values[row] = signal.value;
            column.lli[row] = signal.lli.map(|lli| lli.bits());
        }
    }

    let columns: Vec<_> = columns
        .into_iter()
        .map(|(code, column)| (code.to_string(), column))
        .collect();
    // All column names are owned now; release parsed records before Arrow conversion.
    drop(observations);
    let len = times.len();
    let mut satellite_names = FxHashMap::default();
    let mut prns = LargeStringBuilder::with_capacity(len, len * 3);
    for satellite in satellites {
        prns.append_value(
            satellite_names
                .entry(satellite)
                .or_insert_with(|| satellite.to_string()),
        );
    }
    let field_count = 3 + 2 * columns.len();
    let mut fields = Vec::with_capacity(field_count);
    fields.push(Field::new("time", DataType::Int64, false));
    fields.push(Field::new("prn", DataType::LargeUtf8, false));
    let mut arrays: Vec<ArrayRef> = Vec::with_capacity(field_count);
    arrays.push(Arc::new(Int64Array::from(times)));
    arrays.push(Arc::new(prns.finish()));
    for (code, mut column) in columns {
        column.values.resize(len, f64::NAN);
        column.lli.resize(len, None);
        fields.push(Field::new(&code, DataType::Float64, false));
        arrays.push(Arc::new(Float64Array::from(column.values)));
        fields.push(Field::new(format!("{code}_lli"), DataType::UInt8, true));
        arrays.push(Arc::new(UInt8Array::from(column.lli)));
    }
    fields.push(Field::new("epoch_flag", DataType::UInt8, false));
    arrays.push(Arc::new(UInt8Array::from(flags)));
    Ok((fields, arrays))
}

fn long(
    observations: Rinex,
    constellations: &FxHashSet<Constellation>,
    observables: Option<&FxHashSet<Observable>>,
) -> PyResult<(Vec<Field>, Vec<ArrayRef>)> {
    // Full reads can reserve from epoch lengths. Filtered reads grow only selected
    // buffers, avoiding a second scan of every signal just to count output rows.
    let len: usize =
        if observables.is_none() && constellations.len() == crate::ALL_CONSTELLATIONS.len() {
            observations
                .observations_iter()
                .map(|(_, epoch)| epoch.signals.len())
                .sum()
        } else {
            0
        };
    let mut satellite_names: FxHashMap<SV, String> = FxHashMap::default();
    let mut observable_names: FxHashMap<&Observable, String> = FxHashMap::default();
    let mut times = Vec::with_capacity(len);
    let mut values = Vec::with_capacity(len);
    let mut flags = Vec::with_capacity(len);
    let mut prns = LargeStringBuilder::with_capacity(len, len * 3);
    let mut codes = LargeStringBuilder::with_capacity(len, len * 3);
    let mut lli = UInt8Builder::with_capacity(len);
    for (key, epoch) in observations.observations_iter() {
        let time = quality::unix_ns(key.epoch)?;
        for signal in &epoch.signals {
            if !constellations.contains(&signal.sv.constellation)
                || observables.is_some_and(|codes| !codes.contains(&signal.observable))
            {
                continue;
            }
            let code = observable_names
                .entry(&signal.observable)
                .or_insert_with(|| signal.observable.to_string());
            let prn = satellite_names
                .entry(signal.sv)
                .or_insert_with(|| signal.sv.to_string());
            times.push(time);
            values.push(signal.value);
            flags.push(key.flag as u8);
            prns.append_value(prn);
            codes.append_value(code);
            lli.append_option(signal.lli.map(|lli| lli.bits()));
        }
    }
    drop(observable_names);
    drop(observations);
    let fields = vec![
        Field::new("time", DataType::Int64, false),
        Field::new("prn", DataType::LargeUtf8, false),
        Field::new("code", DataType::LargeUtf8, false),
        Field::new("value", DataType::Float64, false),
        Field::new("lli", DataType::UInt8, true),
        Field::new("epoch_flag", DataType::UInt8, false),
    ];
    let arrays: Vec<ArrayRef> = vec![
        Arc::new(Int64Array::from(times)),
        Arc::new(prns.finish()),
        Arc::new(codes.finish()),
        Arc::new(Float64Array::from(values)),
        Arc::new(lli.finish()),
        Arc::new(UInt8Array::from(flags)),
    ];
    Ok((fields, arrays))
}
