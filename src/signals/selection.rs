//! Score signal pairs in place without expanding each epoch into candidate rows.
use std::{cmp::Reverse, sync::Arc};

use super::column;
use arrow::{
    array::{
        Array, ArrayRef, BooleanArray, Float64Array, Int64Array, LargeStringArray,
        LargeStringBuilder, RecordBatch, UInt8Array,
    },
    datatypes::{DataType, Field, Schema},
};
use pyo3::{PyResult, exceptions::PyValueError};
use rayon::prelude::*;
use rustc_hash::FxHashMap;

type Pair = (String, String, String, u32, f64, f64);
type BiasKey<'a> = (Option<&'a str>, &'a str, &'a str, &'a str);

struct Candidate<'a> {
    system: u8,
    first: &'a str,
    second: &'a str,
    priority: u32,
    frequencies: [f64; 2],
    values: [&'a Float64Array; 4],
    snr: [Option<&'a Float64Array>; 2],
    lli: [Option<&'a UInt8Array>; 2],
    usable: &'a BooleanArray,
}

struct Group<'a> {
    station: Option<&'a str>,
    satellite: &'a str,
    rows: Vec<usize>,
}

#[derive(Clone, Copy)]
struct Interval {
    start: i64,
    end: i64,
    value: f64,
}

#[derive(Clone, Copy)]
struct Winner<'a> {
    candidate: usize,
    complete: bool,
    usable: bool,
    available: bool,
    coverage: usize,
    tx: Option<&'a Interval>,
    rx: Option<&'a Interval>,
}

fn optional<'a, T: 'static>(batch: &'a RecordBatch, name: &str) -> PyResult<Option<&'a T>> {
    batch
        .column_by_name(name)
        .map(|_| column(batch, name))
        .transpose()
}

fn value(array: &Float64Array, row: usize) -> Option<f64> {
    array.is_valid(row).then(|| array.value(row))
}

fn interval(records: Option<&Vec<Interval>>, time: i64) -> Option<&Interval> {
    let records = records?;
    let index = records
        .partition_point(|record| record.start <= time)
        .checked_sub(1)?;
    records.get(index).filter(|record| time < record.end)
}

pub(crate) fn record_batch(
    input: RecordBatch,
    pairs: Vec<Pair>,
    bias: Option<RecordBatch>,
    receiver: bool,
) -> PyResult<RecordBatch> {
    let times = column::<Int64Array>(&input, "time")?;
    let stations = column::<LargeStringArray>(&input, "station")?;
    let satellites = column::<LargeStringArray>(&input, "prn")?;
    if times.null_count() != 0 || satellites.null_count() != 0 {
        return Err(PyValueError::new_err(
            "Time and PRN must not contain null values.",
        ));
    }
    let candidates = pairs
        .iter()
        .map(
            |(system, first, second, priority, first_frequency, second_frequency)| {
                if system.len() != 1
                    || !system.is_ascii()
                    || first.len() < 2
                    || !first.is_ascii()
                    || second.len() < 2
                    || !second.is_ascii()
                {
                    return Err(PyValueError::new_err(
                        "Signal pairs require ASCII system and observation codes.",
                    ));
                }
                Ok(Candidate {
                    system: system.as_bytes().first().copied().unwrap_or(0),
                    first,
                    second,
                    priority: *priority,
                    frequencies: [*first_frequency, *second_frequency],
                    values: [
                        column(&input, first)?,
                        column(&input, second)?,
                        column(&input, &format!("L{}", &first[1..]))?,
                        column(&input, &format!("L{}", &second[1..]))?,
                    ],
                    snr: [
                        optional(&input, &format!("S{}", &first[1..]))?,
                        optional(&input, &format!("S{}", &second[1..]))?,
                    ],
                    lli: [
                        optional(&input, &format!("L{}_lli", &first[1..]))?,
                        optional(&input, &format!("L{}_lli", &second[1..]))?,
                    ],
                    usable: column(&input, &format!("_usable_{system}_{first}_{second}"))?,
                })
            },
        )
        .collect::<PyResult<Vec<_>>>()?;
    let mut products: FxHashMap<BiasKey<'_>, Vec<Interval>> = FxHashMap::default();
    if let Some(bias) = &bias {
        let prns = column::<LargeStringArray>(bias, "prn")?;
        let station = column::<LargeStringArray>(bias, "station")?;
        let first = column::<LargeStringArray>(bias, "obs1")?;
        let second = column::<LargeStringArray>(bias, "obs2")?;
        let starts = column::<Int64Array>(bias, "bias_start")?;
        let ends = column::<Int64Array>(bias, "bias_end")?;
        let values = column::<Float64Array>(bias, "estimated_value")?;
        for row in 0..bias.num_rows() {
            let station = station.is_valid(row).then(|| station.value(row));
            products
                .entry((
                    station,
                    prns.value(row),
                    first.value(row),
                    second.value(row),
                ))
                .or_default()
                .push(Interval {
                    start: starts.value(row),
                    end: ends.value(row),
                    value: values.value(row),
                });
        }
        for intervals in products.values_mut() {
            intervals.sort_by_key(|record| record.start);
        }
    }
    let mut group_ids = FxHashMap::default();
    let mut groups: Vec<Group<'_>> = Vec::new();
    for row in 0..input.num_rows() {
        let station = stations.is_valid(row).then(|| stations.value(row));
        let satellite = satellites.value(row);
        let day = times.value(row).div_euclid(86_400_000_000_000);
        let index = *group_ids
            .entry((day, station, satellite))
            .or_insert_with(|| {
                groups.push(Group {
                    station,
                    satellite,
                    rows: Vec::new(),
                });
                groups.len() - 1
            });
        groups[index].rows.push(row);
    }
    let winners: Vec<_> = groups
        .par_iter()
        .map(|group| {
            let mut winners: Vec<Option<Winner<'_>>> = vec![None; group.rows.len()];
            for (index, candidate) in candidates.iter().enumerate() {
                if group.satellite.as_bytes().first().copied() != Some(candidate.system) {
                    continue;
                }
                let complete = |row| {
                    candidate
                        .values
                        .iter()
                        .all(|array| value(array, row).is_some_and(f64::is_finite))
                };
                let coverage = group.rows.iter().filter(|&&row| complete(row)).count();
                let (first, second) = if candidate.first < candidate.second {
                    (candidate.first, candidate.second)
                } else {
                    (candidate.second, candidate.first)
                };
                let tx = products.get(&(None, group.satellite, first, second));
                let rx = group.station.and_then(|station| {
                    group
                        .satellite
                        .get(..1)
                        .and_then(|system| products.get(&(Some(station), system, first, second)))
                });
                for (&row, winner) in group.rows.iter().zip(&mut winners) {
                    let time = times.value(row);
                    let tx = interval(tx, time);
                    let rx = interval(rx, time);
                    let available = bias.is_none() || (tx.is_some() && (!receiver || rx.is_some()));
                    let complete = complete(row);
                    let usable = complete && candidate.usable.value(row);
                    let score = (
                        usable,
                        complete,
                        available,
                        coverage,
                        Reverse(candidate.priority),
                        Reverse(candidate.first),
                        Reverse(candidate.second),
                    );
                    let better = winner.is_none_or(|old| {
                        let previous = &candidates[old.candidate];
                        score
                            > (
                                old.usable,
                                old.complete,
                                old.available,
                                old.coverage,
                                Reverse(previous.priority),
                                Reverse(previous.first),
                                Reverse(previous.second),
                            )
                    });
                    if better {
                        *winner = Some(Winner {
                            candidate: index,
                            complete,
                            usable,
                            available,
                            coverage,
                            tx,
                            rx,
                        });
                    }
                }
            }
            group.rows.iter().copied().zip(winners).collect::<Vec<_>>()
        })
        .collect();
    let mut selected = vec![None; input.num_rows()];
    for group in winners {
        for (row, winner) in group {
            selected[row] = winner;
        }
    }
    let mut first = LargeStringBuilder::new();
    let mut second = LargeStringBuilder::new();
    let mut values: [Vec<Option<f64>>; 6] =
        std::array::from_fn(|_| Vec::with_capacity(selected.len()));
    let mut lli: [Vec<Option<u8>>; 2] = std::array::from_fn(|_| Vec::with_capacity(selected.len()));
    let mut tx_values = Vec::new();
    let mut rx_values = Vec::new();
    let mut tx_start = Vec::new();
    let mut tx_end = Vec::new();
    let mut rx_start = Vec::new();
    let mut rx_end = Vec::new();
    let mut available = Vec::with_capacity(selected.len());
    let mut frequencies: [Vec<Option<f64>>; 2] =
        std::array::from_fn(|_| Vec::with_capacity(selected.len()));
    for (row, winner) in selected.into_iter().enumerate() {
        let candidate = winner.map(|winner| &candidates[winner.candidate]);
        first.append_option(candidate.map(|candidate| candidate.first));
        second.append_option(candidate.map(|candidate| candidate.second));
        for (i, buffer) in frequencies.iter_mut().enumerate() {
            buffer.push(candidate.map(|candidate| candidate.frequencies[i]));
        }
        for (i, buffer) in values.iter_mut().enumerate() {
            buffer.push(candidate.and_then(|candidate| {
                if i < 4 {
                    value(candidate.values[i], row)
                } else {
                    candidate.snr[i - 4].and_then(|array| value(array, row))
                }
            }));
        }
        for (i, buffer) in lli.iter_mut().enumerate() {
            buffer.push(
                candidate
                    .and_then(|candidate| candidate.lli[i])
                    .and_then(|array| array.is_valid(row).then(|| array.value(row))),
            );
        }
        let sign = if candidate.is_some_and(|candidate| candidate.first < candidate.second) {
            -1.0
        } else {
            1.0
        };
        let tx = winner.and_then(|winner| winner.tx);
        let rx = winner.and_then(|winner| winner.rx);
        tx_values.push(tx.map(|record| sign * record.value));
        rx_values.push(rx.map(|record| sign * record.value));
        tx_start.push(tx.map(|record| record.start));
        tx_end.push(tx.map(|record| record.end));
        rx_start.push(rx.map(|record| record.start));
        rx_end.push(rx.map(|record| record.end));
        available.push(winner.map_or(bias.is_none(), |winner| winner.available));
    }
    let mut fields = vec![
        Field::new("C1_code", DataType::LargeUtf8, true),
        Field::new("C2_code", DataType::LargeUtf8, true),
    ];
    let mut arrays: Vec<ArrayRef> = vec![Arc::new(first.finish()), Arc::new(second.finish())];
    for (name, values) in ["C1_val", "C2_val", "L1_val", "L2_val", "S1", "S2"]
        .into_iter()
        .zip(values)
    {
        fields.push(Field::new(name, DataType::Float64, true));
        arrays.push(Arc::new(Float64Array::from(values)));
    }
    for (name, values) in ["L1_lli", "L2_lli"].into_iter().zip(lli) {
        fields.push(Field::new(name, DataType::UInt8, true));
        arrays.push(Arc::new(UInt8Array::from(values)));
    }
    if bias.is_some() {
        for (name, values) in [("tx_bias_start", tx_start), ("tx_bias_end", tx_end)] {
            fields.push(Field::new(name, DataType::Int64, true));
            arrays.push(Arc::new(Int64Array::from(values)));
        }
        fields.push(Field::new("tx_bias", DataType::Float64, true));
        arrays.push(Arc::new(Float64Array::from(tx_values)));
        if receiver {
            for (name, values) in [("rx_bias_start", rx_start), ("rx_bias_end", rx_end)] {
                fields.push(Field::new(name, DataType::Int64, true));
                arrays.push(Arc::new(Int64Array::from(values)));
            }
            fields.push(Field::new("rx_bias", DataType::Float64, true));
            arrays.push(Arc::new(Float64Array::from(rx_values)));
        }
    }
    for (name, values) in ["_C1_freq", "_C2_freq"].into_iter().zip(frequencies) {
        fields.push(Field::new(name, DataType::Float64, true));
        arrays.push(Arc::new(Float64Array::from(values)));
    }
    fields.push(Field::new("_bias_available", DataType::Boolean, false));
    arrays.push(Arc::new(BooleanArray::from(available)));
    RecordBatch::try_new(Arc::new(Schema::new(fields)), arrays)
        .map_err(|error| PyValueError::new_err(error.to_string()))
}
