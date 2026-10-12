//! Supplement event records that the upstream observation parser discards.
use pyo3::{
    PyResult,
    exceptions::{PyIOError, PyValueError},
};
use rinex::{hatanaka::Decompressor, prelude::*};
use std::{
    fs::File,
    io::{BufRead, BufReader, Read},
    str::FromStr,
};

pub fn unix_ns(epoch: Epoch) -> PyResult<i64> {
    let reference = Epoch::from_gregorian_utc(1970, 1, 1, 0, 0, 0, 0);
    let duration = epoch.to_duration_in_time_scale(TimeScale::UTC)
        - reference.to_duration_in_time_scale(TimeScale::UTC);
    i64::try_from(duration.total_nanoseconds())
        .map_err(|_| PyValueError::new_err("Epoch is outside the signed nanosecond range"))
}

pub fn events(path: &str, version: u8, scale: TimeScale) -> PyResult<Vec<(i64, u8, String)>> {
    let file = File::open(path).map_err(|e| PyIOError::new_err(e.to_string()))?;
    let reader: Box<dyn Read> = if path.ends_with(".gz") {
        Box::new(flate2::read::GzDecoder::new(file))
    } else {
        Box::new(file)
    };
    let mut compact = false;
    let mut header = true;
    let mut decomp = Decompressor::default();
    let mut buffer = vec![0u8; 128 * 1024];
    let mut result: Vec<(i64, u8, String)> = Vec::new();
    let mut records_remaining = 0usize;
    for raw in BufReader::new(reader).lines() {
        let raw = raw.map_err(|e| PyIOError::new_err(e.to_string()))?;
        if raw.contains("CRINEX VERS / TYPE") {
            compact = true;
        }
        let decoded;
        let line = if compact {
            let size = decomp
                .decompress(&raw, raw.len(), &mut buffer, 128 * 1024)
                .map_err(|e| PyValueError::new_err(format!("Event decompression failed: {e:?}")))?;
            decoded = String::from_utf8_lossy(&buffer[..size]).into_owned();
            decoded.as_str()
        } else {
            raw.as_str()
        };
        // A decompression call may produce multiple logical records.
        for line in line.lines() {
            if header {
                if line.contains("END OF HEADER") {
                    header = false;
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
            let epoch_line = if version >= 3 {
                line.strip_prefix('>')
            } else if line.len() >= 32 && line.starts_with(' ') {
                line.get(..32)
            } else {
                None
            };
            let Some(epoch_line) = epoch_line else {
                continue;
            };
            let parts: Vec<_> = epoch_line.split_whitespace().collect();
            if parts.len() < 8 {
                continue;
            }
            let Ok(flag) = parts[6].parse::<u8>() else {
                continue;
            };
            if flag > 6 {
                continue;
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
                continue;
            }
            let Ok(mut year) = parts[0].parse::<i32>() else {
                continue;
            };
            if version == 2 {
                year += if year < 80 { 2000 } else { 1900 };
            }
            let timestamp = format!(
                "{year:04}-{:0>2}-{:0>2}T{:0>2}:{:0>2}:{} {scale}",
                parts[1], parts[2], parts[3], parts[4], parts[5]
            );
            let epoch = Epoch::from_str(&timestamp)
                .map_err(|e| PyValueError::new_err(format!("Invalid event epoch: {e}")))?;
            result.push((unix_ns(epoch)?, flag, line.to_string() + "\n"));
            if (2..=5).contains(&flag) {
                records_remaining = parts[7].parse().unwrap_or(0);
            }
        }
    }
    result.sort_by_key(|e| e.0);
    Ok(result)
}
