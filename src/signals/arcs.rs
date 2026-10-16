//! Batch GF/MW localization and STEC continuity correction.
use std::{borrow::Cow, sync::Arc};

use arrow::{
    array::{
        Array, ArrayRef, BooleanArray, Float64Array, Int32Array, Int64Array, LargeStringArray,
        LargeStringBuilder, RecordBatch, UInt8Array, UInt32Array,
    },
    datatypes::{DataType, Field, Schema},
};
use pyo3::{PyResult, exceptions::PyValueError};
use rustc_hash::FxHashMap;

use super::{
    column,
    statistics::{level, location_scale, median, phase_noise, spread},
};

const C: f64 = 299_792_458.0;
const WINDOW: usize = 32;

/// Align public STEC after leveling, using the already localized event mask.
pub(crate) fn smooth_stec(input: RecordBatch) -> PyResult<RecordBatch> {
    let times = column::<Int64Array>(&input, "time")?;
    let stations = column::<LargeStringArray>(&input, "station")?;
    let prns = column::<LargeStringArray>(&input, "prn")?;
    let values = column::<Float64Array>(&input, "stec")?;
    let events = column::<BooleanArray>(&input, "event")?;
    let mut groups: FxHashMap<_, Vec<usize>> = FxHashMap::default();
    let mut pending: FxHashMap<_, bool> = FxHashMap::default();
    let mut localized = vec![false; input.num_rows()];
    for (row, localized_event) in localized.iter_mut().enumerate() {
        let key = (
            stations.is_valid(row).then(|| stations.value(row)),
            prns.value(row),
        );
        let event = pending.entry(key).or_default();
        *event |= events.is_valid(row) && events.value(row);
        if values.is_valid(row) && values.value(row).is_finite() {
            groups.entry(key).or_default().push(row);
            *localized_event = *event;
            *event = false;
        }
    }
    let mut adjustment = vec![None; input.num_rows()];
    let mut corrections = vec![None; input.num_rows()];
    for rows in groups.values() {
        let ts: Vec<_> = rows
            .iter()
            .map(|&i| (times.value(i) as i128 - times.value(rows[0]) as i128) as f64 / 1e9)
            .collect();
        let phase: Vec<_> = rows.iter().map(|&i| values.value(i)).collect();
        let mut candidates: Vec<_> = rows.iter().map(|&i| localized[i]).collect();
        candidates[0] = false;
        let mut cumulative = 0.0;
        for (k, &row) in rows.iter().enumerate() {
            if candidates[k] {
                let offset = super::repair::correction(&ts, &phase, &candidates, k).offset;
                cumulative += offset;
                corrections[row] = Some(offset);
            }
            adjustment[row] = Some(cumulative);
        }
    }
    RecordBatch::try_new(
        Arc::new(Schema::new(vec![
            Field::new("_stec_adjustment", DataType::Float64, true),
            Field::new("slip_stec_correction", DataType::Float64, true),
        ])),
        vec![
            Arc::new(Float64Array::from(adjustment)),
            Arc::new(Float64Array::from(corrections)),
        ],
    )
    .map_err(|e| PyValueError::new_err(e.to_string()))
}

pub(crate) fn basic_arcs(input: RecordBatch, cadence: Option<f64>) -> PyResult<RecordBatch> {
    let times = column::<Int64Array>(&input, "time")?;
    let stations = column::<LargeStringArray>(&input, "station")?;
    let satellites = column::<LargeStringArray>(&input, "prn")?;
    let first = column::<LargeStringArray>(&input, "C1_code")?;
    let second = column::<LargeStringArray>(&input, "C2_code")?;
    let state = column::<LargeStringArray>(&input, "_receiver_state")?;
    let valid = column::<BooleanArray>(&input, "_numeric_valid")?;
    let lli1 = column::<UInt8Array>(&input, "L1_lli")?;
    let lli2 = column::<UInt8Array>(&input, "L2_lli")?;
    let flags = column::<Int64Array>(&input, "epoch_flag")?;
    if times.null_count() != 0 || satellites.null_count() != 0 {
        return Err(PyValueError::new_err(
            "Time and PRN must not contain null values.",
        ));
    }
    if cadence.is_some_and(|value| !value.is_finite() || value <= 0.0) {
        return Err(PyValueError::new_err(
            "Cadence must be finite and positive.",
        ));
    }
    fn string(array: &LargeStringArray, row: usize) -> Option<&str> {
        array.is_valid(row).then(|| array.value(row))
    }
    let lli = |row| {
        (if lli1.is_valid(row) {
            lli1.value(row)
        } else {
            0
        }) | (if lli2.is_valid(row) {
            lli2.value(row)
        } else {
            0
        })
    };
    let is_valid = |row| valid.is_valid(row) && valid.value(row);
    let mut previous: FxHashMap<_, (usize, u32)> = FxHashMap::default();
    let mut inferred: FxHashMap<_, f64> = FxHashMap::default();
    if cadence.is_none() {
        for row in 0..input.num_rows() {
            let key = (string(stations, row), satellites.value(row));
            if let Some(&(before, _)) = previous.get(&key) {
                let dt = (times.value(row) as i128 - times.value(before) as i128) as f64 / 1e9;
                if dt <= 0.0 {
                    return Err(PyValueError::new_err(
                        "Observation times must be finite and unique within each station/PRN.",
                    ));
                }
                inferred
                    .entry(key)
                    .and_modify(|value| *value = value.min(dt))
                    .or_insert(dt);
            }
            previous.insert(key, (row, 0));
        }
        previous.clear();
    }
    const REASONS: [&str; 8] = [
        "invalid_observation_or_geometry",
        "half_cycle_invalid",
        "loss_of_lock",
        "epoch_event",
        "reacquisition_gap",
        "signal_pair_change",
        "receiver_state_change",
        "reacquisition_after_rejection",
    ];
    let names: Vec<_> = (0..256)
        .map(|code| {
            let names = REASONS
                .iter()
                .enumerate()
                .filter_map(|(bit, name)| ((code & (1 << bit)) != 0).then_some(*name))
                .collect::<Vec<_>>();
            if names.is_empty() {
                "ok".to_string()
            } else {
                names.join("|")
            }
        })
        .collect();
    let mut arcs = Vec::with_capacity(input.num_rows());
    let mut reasons = LargeStringBuilder::new();
    for row in 0..input.num_rows() {
        let key = (string(stations, row), satellites.value(row));
        let bits = lli(row);
        let mut reason = usize::from(!is_valid(row))
            | (usize::from(bits & 2 != 0) << 1)
            | (usize::from(bits & 1 != 0) << 2)
            | (usize::from(flags.is_valid(row) && flags.value(row) != 0) << 3);
        let mut arc = 0;
        if let Some(&(before, previous_arc)) = previous.get(&key) {
            let dt = (times.value(row) as i128 - times.value(before) as i128) as f64 / 1e9;
            if dt <= 0.0 {
                return Err(PyValueError::new_err(
                    "Observation times must be finite and unique within each station/PRN.",
                ));
            }
            let interval = cadence.unwrap_or_else(|| inferred.get(&key).copied().unwrap_or(1.0));
            reason |= usize::from(dt > interval * 1.5) << 4;
            reason |= usize::from(
                string(first, row) != string(first, before)
                    || string(second, row) != string(second, before),
            ) << 5;
            reason |= usize::from(string(state, row) != string(state, before)) << 6;
            reason |= usize::from(!is_valid(before) || lli(before) & 2 != 0) << 7;
            arc = previous_arc + u32::from(reason != 0);
        }
        previous.insert(key, (row, arc));
        arcs.push(arc);
        reasons.append_value(&names[reason]);
    }
    let fields = vec![
        Field::new("arc_id", DataType::UInt32, false),
        Field::new("qc_reason", DataType::LargeUtf8, false),
    ];
    let arrays: Vec<ArrayRef> = vec![
        Arc::new(arrow::array::UInt32Array::from(arcs)),
        Arc::new(reasons.finish()),
    ];
    RecordBatch::try_new(Arc::new(Schema::new(fields)), arrays)
        .map_err(|error| PyValueError::new_err(error.to_string()))
}

pub(crate) fn arcs(
    input: RecordBatch,
    cadence: Option<f64>,
    repair: bool,
    _integer_cycles: bool,
) -> PyResult<RecordBatch> {
    let basic = basic_arcs(input.clone(), cadence)?;
    let reasons = column::<LargeStringArray>(&basic, "qc_reason")?;
    let stations = column::<LargeStringArray>(&input, "station")?;
    let prns = column::<LargeStringArray>(&input, "prn")?;
    let times = column::<Int64Array>(&input, "time")?;
    let raw = column::<Float64Array>(&input, "stec_p_raw")?;
    let code = column::<Float64Array>(&input, "stec_g")?;
    let mw = column::<Float64Array>(&input, "mw")?;
    let f1 = column::<Float64Array>(&input, "C1_freq")?;
    let f2 = column::<Float64Array>(&input, "C2_freq")?;
    let valid = column::<BooleanArray>(&input, "_numeric_valid")?;
    let lli1 = column::<UInt8Array>(&input, "L1_lli")?;
    let lli2 = column::<UInt8Array>(&input, "L2_lli")?;
    let mut groups: FxHashMap<_, Vec<usize>> = FxHashMap::default();
    for row in 0..input.num_rows() {
        groups
            .entry((
                stations.is_valid(row).then(|| stations.value(row)),
                prns.value(row),
            ))
            .or_default()
            .push(row);
    }
    let size = input.num_rows();
    let mut arcs = vec![0u32; size];
    let mut continuity = vec![0u32; size];
    let mut working = raw.values().to_vec();
    let mut status = vec!["none"; size];
    // Continuity offsets do not assert per-carrier integers.
    let mut sg = vec![None; size];
    let mut sm = vec![None; size];
    let mut correction = vec![None; size];
    let mut phase_sigma = vec![None; size];
    let mut output_reasons: Vec<_> = (0..size).map(|i| Cow::Borrowed(reasons.value(i))).collect();
    for rows in groups.values() {
        let mut boundary = Vec::with_capacity(rows.len());
        let mut selected = Vec::with_capacity(rows.len());
        for (j, &i) in rows.iter().enumerate() {
            let changed = j > 0
                && (f1.value(i) != f1.value(rows[j - 1]) || f2.value(i) != f2.value(rows[j - 1]));
            if changed {
                output_reasons[i].to_mut().push_str("|frequency_change");
            }
            boundary.push(j == 0 || reasons.value(i) != "ok" || changed);
            if boundary[j] {
                status[i] = "boundary";
            }
            let bits = if lli1.is_valid(i) { lli1.value(i) } else { 0 }
                | if lli2.is_valid(i) { lli2.value(i) } else { 0 };
            if valid.is_valid(i)
                && valid.value(i)
                && bits & 2 == 0
                && raw.is_valid(i)
                && raw.value(i).is_finite()
                && f1.is_valid(i)
                && f2.is_valid(i)
                && f1.value(i).is_finite()
                && f2.value(i).is_finite()
                && f1.value(i) > 0.0
                && f2.value(i) > 0.0
                && f1.value(i) != f2.value(i)
            {
                selected.push(j);
            }
        }
        if selected.is_empty() {
            for &i in rows {
                status[i] = "boundary";
            }
        } else {
            let ids: Vec<_> = selected.iter().map(|&j| rows[j]).collect();
            let ts: Vec<_> = ids
                .iter()
                .map(|&i| (times.value(i) as i128 - times.value(ids[0]) as i128) as f64 / 1e9)
                .collect();
            let phase: Vec<_> = ids.iter().map(|&i| raw.value(i)).collect();
            let melbourne: Vec<_> = ids.iter().map(|&i| mw.value(i)).collect();
            let mut candidate = vec![false; ids.len()];
            let mut start = 0;
            // First localize every edge. Correction is a separate pass so that
            // adjacent jumps and single-epoch spikes cannot pollute each other.
            for k in 1..ids.len() {
                let j = selected[k];
                if boundary[j] || selected[k - 1] + 1 != j {
                    candidate[k] = true;
                    start = k;
                    continue;
                }
                let lo = start.max(k.saturating_sub(WINDOW));
                let mut slopes = [0.0; WINDOW];
                let mut deltas = [0.0; WINDOW];
                let mut len = 0;
                for q in lo + 1..k {
                    if !candidate[q] {
                        slopes[len] = (phase[q] - phase[q - 1]) / (ts[q] - ts[q - 1]);
                        deltas[len] = melbourne[q] - melbourne[q - 1];
                        len += 1;
                    }
                }
                let dt = ts[k] - ts[k - 1];
                let slope = if len > 0 {
                    median(&slopes[len.saturating_sub(3)..len])
                } else {
                    let mut future = [0.0; 3];
                    let mut count = 0;
                    for q in k + 1..(k + 4).min(ids.len()) {
                        if boundary[selected[q]] {
                            break;
                        }
                        future[count] = (phase[q] - phase[q - 1]) / (ts[q] - ts[q - 1]);
                        count += 1;
                    }
                    median(&future[..count])
                };
                let i = ids[k];
                let a = f1.value(i).powi(2);
                let b = f2.value(i).powi(2);
                let coeff = a * b / (a - b) / 40.3e16;
                let separation = (C / f1.value(i) - C / f2.value(i)).abs();
                let limit = (coeff.abs() * separation / 4.0)
                    .max(6.0 * spread(&slopes[..len]) * dt)
                    .max(6.0 * phase_noise(&phase[lo..k]));
                let gf_cue = (phase[k] - phase[k - 1] - slope * dt).abs() > limit;
                let mw_cue = len >= 3 && {
                    let (center, scale) = location_scale(&deltas[..len]);
                    (melbourne[k] - melbourne[k - 1] - center).abs() > 0.5_f64.max(6.0 * scale)
                };
                candidate[k] = gf_cue || mw_cue;
            }
            let mut cumulative = 0.0;
            for (k, &i) in ids.iter().enumerate() {
                if k == 0 {
                    status[i] = "boundary";
                } else if candidate[k] {
                    let fit = super::repair::correction(&ts, &phase, &candidate, k);
                    phase_sigma[i] = Some(fit.sigma);
                    let lo = k.saturating_sub(WINDOW);
                    let end = (k + WINDOW).min(ids.len());
                    let mut residual = [0.0; 2 * WINDOW];
                    for (out, &row) in residual.iter_mut().zip(&ids[lo..end]) {
                        let a = f1.value(row).powi(2);
                        let b = f2.value(row).powi(2);
                        let coeff = a * b / (a - b) / 40.3e16;
                        *out = (raw.value(row) - code.value(row)) / coeff;
                    }
                    let (_, before_g) = level(&residual[..k - lo]);
                    let (_, after_g) = level(&residual[k - lo..end - lo]);
                    let (_, before_m) = level(&melbourne[lo..k]);
                    let (_, after_m) = level(&melbourne[k..end]);
                    sg[i] = Some(before_g.hypot(after_g));
                    sm[i] = Some(before_m.hypot(after_m));
                    if repair {
                        cumulative += fit.offset;
                        correction[i] = Some(fit.offset);
                        status[i] = if fit.offset == 0.0 {
                            "phase_continuous"
                        } else {
                            "phase_repaired"
                        };
                    } else {
                        status[i] = "phase_detected";
                    }
                    if reasons.value(i) == "ok" {
                        output_reasons[i] = Cow::Owned(format!("gf_mw_{}", status[i]));
                    }
                }
                working[i] = raw.value(i) - cumulative;
            }
        }
        let mut physical = 0;
        for (j, &i) in rows.iter().enumerate() {
            if j > 0
                && (boundary[j]
                    || matches!(
                        status[i],
                        "phase_repaired" | "phase_detected" | "phase_continuous"
                    ))
            {
                physical += 1;
            }
            arcs[i] = physical;
            continuity[i] = if repair { 0 } else { physical };
        }
    }
    let mut strings = LargeStringBuilder::new();
    for value in output_reasons {
        strings.append_value(value.as_ref());
    }
    let mut statuses = LargeStringBuilder::new();
    for value in status {
        statuses.append_value(value);
    }
    let fields = vec![
        Field::new("arc_id", DataType::UInt32, false),
        Field::new("qc_reason", DataType::LargeUtf8, false),
        Field::new("_continuity_id", DataType::UInt32, false),
        Field::new("stec_p_corrected", DataType::Float64, true),
        Field::new("slip_status", DataType::LargeUtf8, false),
        Field::new("slip_n1", DataType::Int32, true),
        Field::new("slip_n2", DataType::Int32, true),
        Field::new("slip_sigma_gf", DataType::Float64, true),
        Field::new("slip_sigma_mw", DataType::Float64, true),
        Field::new("slip_correction", DataType::Float64, true),
        Field::new("slip_sigma_phase", DataType::Float64, true),
    ];
    let arrays: Vec<ArrayRef> = vec![
        Arc::new(UInt32Array::from(arcs)),
        Arc::new(strings.finish()),
        Arc::new(UInt32Array::from(continuity)),
        Arc::new(Float64Array::new(working.into(), raw.nulls().cloned())),
        Arc::new(statuses.finish()),
        Arc::new(Int32Array::new_null(size)),
        Arc::new(Int32Array::new_null(size)),
        Arc::new(Float64Array::from(sg)),
        Arc::new(Float64Array::from(sm)),
        Arc::new(Float64Array::from(correction)),
        Arc::new(Float64Array::from(phase_sigma)),
    ];
    RecordBatch::try_new(Arc::new(Schema::new(fields)), arrays)
        .map_err(|e| PyValueError::new_err(e.to_string()))
}
