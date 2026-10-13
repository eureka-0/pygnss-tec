//! Supplement event records that the upstream observation parser discards.
use std::{
    borrow::Cow,
    io::{BufRead, BufReader},
    str::FromStr,
};

use pyo3::{
    PyResult,
    exceptions::{PyIOError, PyValueError},
};
use rinex::{hatanaka::Decompressor, prelude::*};

use crate::rinex_io;

/// UTC nanoseconds, epoch flag, and original logical records including newlines.
pub(crate) type EpochEvent = (i64, u8, String);

pub(crate) fn unix_ns(epoch: Epoch) -> PyResult<i64> {
    let reference = Epoch::from_gregorian_utc(1970, 1, 1, 0, 0, 0, 0);
    let duration = epoch.to_duration_in_time_scale(TimeScale::UTC)
        - reference.to_duration_in_time_scale(TimeScale::UTC);
    i64::try_from(duration.total_nanoseconds())
        .map_err(|_| PyValueError::new_err("Epoch is outside the signed nanosecond range"))
}

/// Return an event and its following payload length, or skip a non-event line.
fn parse_event(line: &str, version: u8, scale: TimeScale) -> PyResult<Option<(EpochEvent, usize)>> {
    let epoch_line = if version >= 3 {
        line.strip_prefix('>')
    } else if line.len() >= 32 && line.starts_with(' ') {
        line.get(..32)
    } else {
        None
    };
    let Some(epoch_line) = epoch_line else {
        return Ok(None);
    };
    let mut fields = epoch_line.split_whitespace();
    let mut parts = [""; 8];
    for part in &mut parts {
        let Some(field) = fields.next() else {
            return Ok(None);
        };
        *part = field;
    }
    let Ok(flag) = parts[6].parse::<u8>() else {
        return Ok(None);
    };
    if flag > 6 {
        return Ok(None);
    }
    if parts[5]
        .split('.')
        .nth(1)
        .is_some_and(|fraction| fraction.trim_end_matches('0').len() > 9)
    {
        return Err(PyValueError::new_err(
            "RINEX epoch precision finer than nanoseconds is unsupported",
        ));
    }
    if flag == 0 {
        return Ok(None);
    }
    let Ok(mut year) = parts[0].parse::<i32>() else {
        return Ok(None);
    };
    if version == 2 {
        year += if year < 80 { 2000 } else { 1900 };
    }
    let timestamp = format!(
        "{year:04}-{:0>2}-{:0>2}T{:0>2}:{:0>2}:{} {scale}",
        parts[1], parts[2], parts[3], parts[4], parts[5]
    );
    let epoch = Epoch::from_str(&timestamp)
        .map_err(|error| PyValueError::new_err(format!("Invalid event epoch: {error}")))?;
    let payload_count = if (2..=5).contains(&flag) {
        parts[7].parse().unwrap_or(0)
    } else {
        0
    };
    Ok(Some((
        (unix_ns(epoch)?, flag, line.to_string() + "\n"),
        payload_count,
    )))
}

pub(crate) fn events(path: &str, version: u8, scale: TimeScale) -> PyResult<Vec<EpochEvent>> {
    const DECODE_CAPACITY: usize = 128 * 1024;
    let mut reader = BufReader::with_capacity(64 * 1024, rinex_io::open(path)?);
    let mut raw = String::new();
    let mut compact = false;
    let mut in_header = true;
    let mut decompressor = Decompressor::default();
    let mut buffer = vec![0u8; DECODE_CAPACITY];
    let mut result: Vec<EpochEvent> = Vec::new();
    let mut records_remaining = 0usize;
    loop {
        raw.clear();
        if reader
            .read_line(&mut raw)
            .map_err(|error| PyIOError::new_err(error.to_string()))?
            == 0
        {
            break;
        }
        // Match BufRead::lines: strip CR only when it precedes a terminating LF.
        if raw.ends_with('\n') {
            raw.pop();
            if raw.ends_with('\r') {
                raw.pop();
            }
        }
        if raw.contains("CRINEX VERS / TYPE") {
            compact = true;
        }
        let decoded = if compact {
            let size = decompressor
                .decompress(&raw, raw.len(), &mut buffer, DECODE_CAPACITY)
                .map_err(|error| {
                    PyValueError::new_err(format!("Event decompression failed: {error:?}"))
                })?;
            String::from_utf8_lossy(&buffer[..size])
        } else {
            Cow::Borrowed(raw.as_str())
        };
        // A decompression call may produce multiple logical records.
        for line in decoded.lines() {
            if in_header {
                if line.contains("END OF HEADER") {
                    in_header = false;
                }
                continue;
            }
            if records_remaining > 0 {
                if let Some((_, _, text)) = result.last_mut() {
                    text.push_str(line);
                    text.push('\n');
                }
                records_remaining -= 1;
                continue;
            }
            if let Some((event, payload_count)) = parse_event(line, version, scale)? {
                result.push(event);
                records_remaining = payload_count;
            }
        }
    }
    result.sort_by_key(|event| event.0);
    Ok(result)
}
