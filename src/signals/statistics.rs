//! Bounded robust statistics shared by detection and phase-trend estimation.
const WINDOW: usize = 32;

pub(crate) fn phase_noise(values: &[f64]) -> f64 {
    let mut differences = [0.0; 2 * WINDOW];
    let size = values.len().saturating_sub(2);
    for (out, v) in differences.iter_mut().zip(values.windows(3)) {
        *out = v[2] - 2.0 * v[1] + v[0];
    }
    spread(&differences[..size]) / 6.0_f64.sqrt()
}

pub(crate) fn median(values: &[f64]) -> f64 {
    if values.is_empty() {
        return 0.0;
    }
    // Two-sided fits use at most 2 * WINDOW samples; no epoch-loop allocation.
    let mut scratch = [0.0; 2 * WINDOW];
    scratch[..values.len()].copy_from_slice(values);
    let values = &mut scratch[..values.len()];
    let mid = values.len() / 2;
    let even = values.len() % 2 == 0;
    let (lower, middle, _) = values.select_nth_unstable_by(mid, f64::total_cmp);
    if even {
        let before = lower.iter().max_by(|a, b| a.total_cmp(b)).unwrap();
        (*before + *middle) / 2.0
    } else {
        *middle
    }
}

pub(crate) fn location_scale(values: &[f64]) -> (f64, f64) {
    let center = median(values);
    let mut residual = [0.0; 2 * WINDOW];
    for (out, value) in residual.iter_mut().zip(values) {
        *out = (value - center).abs();
    }
    (center, 1.4826 * median(&residual[..values.len()]))
}

pub(crate) fn spread(values: &[f64]) -> f64 {
    location_scale(values).1
}

pub(crate) fn level(values: &[f64]) -> (f64, f64) {
    let (center, scale) = location_scale(values);
    if scale == 0.0 {
        return (center, 0.0);
    }
    let mut residual = [0.0; 2 * WINDOW];
    let residual = &mut residual[..values.len()];
    for (out, value) in residual.iter_mut().zip(values) {
        *out = (value - center).clamp(-3.0 * scale, 3.0 * scale);
    }
    let variance: f64 = residual.iter().map(|v| v * v).sum();
    let mut inflation = 1.0;
    if variance > 0.0 {
        for lag in 1..=8.min(values.len() / 4) {
            let correlation = residual[lag..]
                .iter()
                .zip(residual.iter())
                .map(|(a, b)| a * b)
                .sum::<f64>()
                / variance;
            if correlation <= 0.0 {
                break;
            }
            inflation += 2.0 * correlation;
        }
    }
    (
        center,
        1.2533 * scale / (values.len() as f64 / inflation).max(1.0).sqrt(),
    )
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn selection_median_matches_sorted_reference() {
        let mut state = 17u64;
        for size in 0..=64 {
            for _ in 0..32 {
                let mut values = [0.0; 64];
                for (i, value) in values[..size].iter_mut().enumerate() {
                    state = state.wrapping_mul(6364136223846793005).wrapping_add(1);
                    *value = if i % 7 == 0 {
                        -0.0
                    } else {
                        ((state >> 32) as i32 % 31) as f64
                    };
                }
                let actual = median(&values[..size]);
                values[..size].sort_unstable_by(f64::total_cmp);
                let expected = if size == 0 {
                    0.0
                } else if size % 2 == 0 {
                    (values[size / 2 - 1] + values[size / 2]) / 2.0
                } else {
                    values[size / 2]
                };
                assert_eq!(actual.to_bits(), expected.to_bits());
            }
        }
    }
}
