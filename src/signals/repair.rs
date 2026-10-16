//! Repair offsets minimize the local discontinuity in STEC rate.
//! Code, MW, integer feasibility and noise scales never veto this objective.

use super::statistics::spread;

const WINDOW: usize = 32;
const RATES: usize = 3;

pub(crate) struct Correction {
    pub offset: f64,
    pub sigma: f64,
}

/// Nearest normal increments on one side; skip all localized jump edges.
fn rates(
    times: &[f64],
    phase: &[f64],
    candidates: &[bool],
    event: usize,
    before: bool,
) -> Option<(f64, f64, f64)> {
    let mut values = [(0.0, 0.0); RATES];
    let mut count = 0;
    for distance in 1..=WINDOW {
        let edge = if before {
            let Some(edge) = event.checked_sub(distance) else {
                break;
            };
            edge
        } else {
            event + distance
        };
        if edge == 0 || edge >= phase.len() {
            break;
        }
        if candidates[edge] {
            continue;
        }
        values[count] = (
            (phase[edge] - phase[edge - 1]) / (times[edge] - times[edge - 1]),
            (times[edge] + times[edge - 1]) / 2.0,
        );
        count += 1;
        if count == RATES {
            break;
        }
    }
    if count == 0 {
        return None;
    }
    values[..count].sort_unstable_by(|a, b| a.0.total_cmp(&b.0));
    let rate = if count == 2 {
        (values[0].0 + values[1].0) / 2.0
    } else {
        values[count / 2].0
    };
    let center = values[..count].iter().map(|v| v.1).sum::<f64>() / count as f64;
    let mut slopes = [0.0; RATES];
    for (out, value) in slopes.iter_mut().zip(&values[..count]) {
        *out = value.0;
    }
    Some((rate, center, spread(&slopes[..count])))
}

pub(crate) fn correction(
    times: &[f64],
    phase: &[f64],
    candidates: &[bool],
    event: usize,
) -> Correction {
    let left = rates(times, phase, candidates, event, true);
    let right = rates(times, phase, candidates, event, false);
    let midpoint = (times[event - 1] + times[event]) / 2.0;
    let dt = times[event] - times[event - 1];
    let (rate, sigma) = match (left, right) {
        (Some((a, ta, sa)), Some((b, tb, sb))) => {
            let weight = ((midpoint - ta) / (tb - ta)).clamp(0.0, 1.0);
            (a * (1.0 - weight) + b * weight, sa.hypot(sb))
        }
        (Some((a, _, s)), None) | (None, Some((a, _, s))) => (a, s),
        (None, None) => (0.0, 0.0),
    };
    Correction {
        offset: phase[event] - phase[event - 1] - rate * dt,
        sigma: sigma * dt,
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn adjacent_offsets_restore_an_affine_stec_curve() {
        let times: Vec<_> = (0..20).map(|i| i as f64 * 15.0).collect();
        let baseline: Vec<_> = times.iter().map(|t| 30.0 + t * 0.02).collect();
        let phase: Vec<_> = baseline
            .iter()
            .enumerate()
            .map(|(i, value)| {
                value + if i >= 5 { 13.123 } else { 0.0 } + if i >= 6 { -8.75 } else { 0.0 }
            })
            .collect();
        let candidates: Vec<_> = (0..20).map(|i| i == 5 || i == 6).collect();
        let mut cumulative = 0.0;
        for i in 0..phase.len() {
            if candidates[i] {
                cumulative += correction(&times, &phase, &candidates, i).offset;
            }
            assert!((phase[i] - cumulative - baseline[i]).abs() < 1e-12);
        }
    }
}
