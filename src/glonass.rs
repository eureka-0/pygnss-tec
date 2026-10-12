//! Broadcast GLONASS propagation in the rotating PZ-90 frame, in SI units.
//! Equations follow the GLONASS ICD/RTKLIB, with bounded RK4 steps.
use rinex::navigation::Ephemeris;

fn derivative(s: &[f64; 6], acc: &[f64; 3]) -> [f64; 6] {
    const MU: f64 = 3.9860044e14;
    const J2: f64 = 1.0826257e-3;
    const R: f64 = 6378136.0;
    const OMEGA: f64 = 7.292115e-5;
    let r2 = s[0] * s[0] + s[1] * s[1] + s[2] * s[2];
    let r3 = r2 * r2.sqrt();
    let a = 1.5 * J2 * MU * R * R / (r2 * r3);
    let b = 5.0 * s[2] * s[2] / r2;
    let g = -MU / r3 - a * (1.0 - b);
    [
        s[3],
        s[4],
        s[5],
        (g + OMEGA * OMEGA) * s[0] + 2.0 * OMEGA * s[4] + acc[0],
        (g + OMEGA * OMEGA) * s[1] - 2.0 * OMEGA * s[3] + acc[1],
        (g - 2.0 * a) * s[2] + acc[2],
    ]
}

pub fn position(eph: &Ephemeris, dt: f64) -> Option<[f64; 3]> {
    // Broadcast ephemerides are valid near their reference epoch only.
    if !dt.is_finite() || dt.abs() > 900.0 {
        return None;
    }
    let mut s = [0.0; 6];
    let mut acc = [0.0; 3];
    for (i, axis) in ["X", "Y", "Z"].iter().enumerate() {
        s[i] = eph.get_orbit_f64(&format!("satPos{axis}"))? * 1e3;
        s[i + 3] = eph.get_orbit_f64(&format!("vel{axis}"))? * 1e3;
        acc[i] = eph.get_orbit_f64(&format!("accel{axis}"))? * 1e3;
    }
    if !s.iter().chain(acc.iter()).all(|v| v.is_finite())
        || s[..3].iter().map(|v| v * v).sum::<f64>() < 1e12
    {
        return None;
    }
    let steps = (dt.abs() / 30.0).ceil().max(1.0) as usize;
    let h = dt / steps as f64;
    for _ in 0..steps {
        let k1 = derivative(&s, &acc);
        let k2 = derivative(&std::array::from_fn(|i| s[i] + h * k1[i] / 2.0), &acc);
        let k3 = derivative(&std::array::from_fn(|i| s[i] + h * k2[i] / 2.0), &acc);
        let k4 = derivative(&std::array::from_fn(|i| s[i] + h * k3[i]), &acc);
        for i in 0..6 {
            s[i] += h * (k1[i] + 2.0 * k2[i] + 2.0 * k3[i] + k4[i]) / 6.0;
        }
    }
    s.iter()
        .all(|v| v.is_finite())
        .then_some([s[0], s[1], s[2]])
}
