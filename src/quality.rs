//! Frame observation/event records before the upstream observation parser sees them.
use std::{
    io::{self, BufRead, BufReader, Read},
    str::FromStr,
};

use pyo3::{PyResult, exceptions::PyValueError};
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

fn invalid(message: impl ToString) -> io::Error {
    io::Error::new(io::ErrorKind::InvalidData, message.to_string())
}

struct Descriptor {
    flag: u8,
    count: usize,
    epoch: Option<Epoch>,
}

fn descriptor(line: &str, version: u8, scale: TimeScale) -> io::Result<Option<Descriptor>> {
    // COMMENT text may start with an epoch marker. Identify the fixed-column
    // label before interpreting the free-text portion as an epoch descriptor.
    if line
        .get(60..)
        .is_some_and(|label| label.trim() == "COMMENT")
    {
        return Ok(None);
    }
    let offset = if version >= 3 {
        if !line.starts_with('>') {
            return Ok(None);
        }
        29
    } else {
        if !line.starts_with(' ') || line.len() < 32 || line.trim_end().ends_with("COMMENT") {
            return Ok(None);
        }
        26
    };
    // Check extended seconds before fixed-column parsing so unsupported precision
    // cannot shift the flag field and silently hide a timestamped record.
    let date_start = usize::from(version >= 3);
    if let Some(seconds) = line[date_start..].split_whitespace().nth(5)
        && seconds
            .split('.')
            .nth(1)
            .is_some_and(|fraction| fraction.trim_end_matches('0').len() > 9)
    {
        return Err(invalid(
            "RINEX epoch precision finer than nanoseconds is unsupported",
        ));
    }
    let Some(date) = line.get(date_start..offset) else {
        return Err(invalid("Incomplete RINEX epoch record"));
    };
    let flag = line.get(offset..offset + 3).unwrap_or("").trim();
    let count = line.get(offset + 3..offset + 6).unwrap_or("").trim();
    let flag: u8 = flag
        .parse()
        .map_err(|_| invalid("Invalid RINEX epoch flag"))?;
    if flag > 6 {
        return Err(invalid("Invalid RINEX epoch flag"));
    }
    let count = count
        .parse()
        .map_err(|_| invalid("Invalid RINEX record count"))?;
    let parts: Vec<_> = date.split_whitespace().collect();
    let epoch = if parts.is_empty() && flag >= 2 {
        None
    } else {
        if parts.len() != 6 {
            return Err(invalid("Incomplete nonblank RINEX epoch"));
        }
        let mut year: i32 = parts[0]
            .parse()
            .map_err(|_| invalid("Invalid RINEX epoch year"))?;
        if version == 2 {
            year += if year < 80 { 2000 } else { 1900 };
        }
        let timestamp = format!(
            "{year:04}-{:0>2}-{:0>2}T{:0>2}:{:0>2}:{} {scale}",
            parts[1], parts[2], parts[3], parts[4], parts[5]
        );
        Some(
            Epoch::from_str(&timestamp)
                .map_err(|error| invalid(format!("Invalid event epoch: {error}")))?,
        )
    };
    Ok(Some(Descriptor { flag, count, epoch }))
}

/// Decode at most one epoch at a time. Special blocks are consumed by their
/// declared framing, so their payloads cannot be mistaken for new epochs.
pub(crate) struct ObservationReader<R> {
    reader: R,
    decoder: Option<Decompressor>,
    version: u8,
    scale: TimeScale,
    v2_observables: usize,
    raw: String,
    decoded: Vec<u8>,
    decoded_offset: usize,
    pending: Vec<u8>,
    pending_offset: usize,
    pub(crate) error: Option<String>,
}

impl<R: BufRead> ObservationReader<R> {
    pub(crate) fn new(reader: R, header: &Header) -> Self {
        let obs = header.obs.as_ref().expect("observation header");
        Self {
            reader,
            decoder: obs.crinex.as_ref().map(|crinex| {
                Decompressor::new(
                    crinex.version.major >= 3,
                    header.constellation.unwrap_or_default(),
                    obs.codes.clone(),
                )
            }),
            version: header.version.major,
            scale: obs
                .timeof_first_obs
                .or(obs.timeof_last_obs)
                .map(|epoch| epoch.time_scale)
                .unwrap_or(TimeScale::GPST),
            v2_observables: obs.codes.values().next().map_or(0, Vec::len),
            raw: String::new(),
            decoded: Vec::new(),
            decoded_offset: 0,
            pending: Vec::new(),
            pending_offset: 0,
            error: None,
        }
    }

    fn line(&mut self, mut at_epoch: bool) -> io::Result<Option<String>> {
        loop {
            if self.decoded_offset < self.decoded.len() {
                let tail = &self.decoded[self.decoded_offset..];
                let len = tail
                    .iter()
                    .position(|&c| c == b'\n')
                    .map_or(tail.len(), |i| i + 1);
                let line = std::str::from_utf8(&tail[..len])
                    .map_err(invalid)?
                    .to_string();
                self.decoded_offset += len;
                return Ok(Some(line));
            }
            self.raw.clear();
            if self.reader.read_line(&mut self.raw)? == 0 {
                return Ok(None);
            }
            let Some(decoder) = &mut self.decoder else {
                // Event metadata stores logical records with normalized LF,
                // including an unterminated final record.
                if self.raw.ends_with('\n') {
                    self.raw.pop();
                    if self.raw.ends_with('\r') {
                        self.raw.pop();
                    }
                }
                self.raw.push('\n');
                return Ok(Some(self.raw.clone()));
            };
            // Preserve a terminator for the shortest epoch text differences;
            // clock/observation kernels strip their own trailing whitespace.
            if !self.raw.ends_with('\n') {
                self.raw.push('\n');
            }
            let raw = self.raw.as_str();
            // A trailing blank record is legal. Blank clock records inside an
            // epoch are significant and must still reach the decompressor.
            if at_epoch && raw.trim().is_empty() {
                continue;
            }
            at_epoch = false;
            self.decoded.resize(128 * 1024, 0);
            let capacity = self.decoded.len();
            let size = decoder
                .decompress(raw, raw.len(), &mut self.decoded, capacity)
                .map_err(|error| {
                    invalid(format!(
                        "Event decompression failed: {error}; input {raw:?}"
                    ))
                })?;
            self.decoded.truncate(size);
            if size > 0 && !self.decoded.ends_with(b"\n") {
                self.decoded.push(b'\n');
            }
            self.decoded_offset = 0;
        }
    }

    fn next_record(&mut self) -> io::Result<Option<(Option<Epoch>, u8)>> {
        self.pending.clear();
        self.pending_offset = 0;
        let Some(line) = self.line(true)? else {
            return Ok(None);
        };
        let Some(record) = descriptor(&line, self.version, self.scale)? else {
            // RINEX permits standalone comments between records.
            self.pending.extend_from_slice(line.as_bytes());
            return Ok(Some((None, 0)));
        };
        self.pending.extend_from_slice(line.as_bytes());
        let following = if (2..=5).contains(&record.flag) {
            record.count
        } else if self.version == 2 {
            record.count.saturating_sub(1) / 12 + record.count * self.v2_observables.div_ceil(5)
        } else {
            record.count
        };
        for _ in 0..following {
            let line = self
                .line(false)?
                .ok_or_else(|| invalid("Truncated RINEX epoch payload"))?;
            self.pending.extend_from_slice(line.as_bytes());
        }
        Ok(Some((record.epoch, record.flag)))
    }
}

impl<R: BufRead> ObservationReader<R> {
    fn read_observations(&mut self, output: &mut [u8]) -> io::Result<usize> {
        if output.is_empty() {
            return Ok(0);
        }
        while self.pending_offset == self.pending.len() {
            let Some((_, flag)) = self.next_record()? else {
                return Ok(0);
            };
            if flag >= 2 {
                self.pending.clear();
            }
        }
        let count = output.len().min(self.pending.len() - self.pending_offset);
        output[..count]
            .copy_from_slice(&self.pending[self.pending_offset..self.pending_offset + count]);
        self.pending_offset += count;
        Ok(count)
    }
}

impl<R: BufRead> Read for ObservationReader<R> {
    fn read(&mut self, output: &mut [u8]) -> io::Result<usize> {
        let result = self.read_observations(output);
        if let Err(error) = &result {
            self.error = Some(error.to_string());
        }
        result
    }
}

pub(crate) fn events(path: &str) -> PyResult<Vec<EpochEvent>> {
    let mut reader = BufReader::new(rinex_io::open(path)?);
    let header =
        Header::parse(&mut reader).map_err(|error| PyValueError::new_err(error.to_string()))?;
    let mut reader = ObservationReader::new(reader, &header);
    let mut result = Vec::new();
    while let Some((epoch, flag)) = reader
        .next_record()
        .map_err(|error| PyValueError::new_err(error.to_string()))?
    {
        if flag != 0
            && let Some(epoch) = epoch
        {
            result.push((
                unix_ns(epoch)?,
                flag,
                String::from_utf8(reader.pending.clone())
                    .map_err(|error| PyValueError::new_err(error.to_string()))?,
            ));
        }
    }
    result.sort_by_key(|event| event.0);
    Ok(result)
}
