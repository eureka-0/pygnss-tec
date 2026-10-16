//! Broadcast GLONASS propagation in the rotating PZ-90 frame, in SI units.
//! Equations follow the GLONASS ICD/RTKLIB, with bounded RK4 steps.
use rinex::navigation::Ephemeris;

#[derive(Clone, Copy)]
pub(crate) struct BroadcastState {
    state: [f64; 6],
    acceleration: [f64; 3],
}

impl BroadcastState {
    pub(crate) fn from_ephemeris(ephemeris: &Ephemeris) -> Option<Self> {
        let mut state = [0.0; 6];
        let mut acceleration = [0.0; 3];
        // Convert the broadcast kilometres once per ephemeris, before propagation.
        for (i, (position, velocity, accel)) in [
            ("satPosX", "velX", "accelX"),
            ("satPosY", "velY", "accelY"),
            ("satPosZ", "velZ", "accelZ"),
        ]
        .into_iter()
        .enumerate()
        {
            state[i] = ephemeris.get_orbit_f64(position)? * 1e3;
            state[i + 3] = ephemeris.get_orbit_f64(velocity)? * 1e3;
            acceleration[i] = ephemeris.get_orbit_f64(accel)? * 1e3;
        }
        if !state
            .iter()
            .chain(acceleration.iter())
            .all(|v| v.is_finite())
            || state[..3].iter().map(|v| v * v).sum::<f64>() < 1e12
        {
            return None;
        }
        Some(Self {
            state,
            acceleration,
        })
    }

    pub(crate) fn position(&self, dt: f64) -> Option<[f64; 3]> {
        // Broadcast ephemerides are valid near their reference epoch only.
        if !dt.is_finite() || dt.abs() > 900.0 {
            return None;
        }
        let mut state = self.state;
        let steps = (dt.abs() / 30.0).ceil().max(1.0) as usize;
        let step = dt / steps as f64;
        for _ in 0..steps {
            let k1 = derivative(&state, &self.acceleration);
            let k2 = derivative(
                &std::array::from_fn(|i| state[i] + step * k1[i] / 2.0),
                &self.acceleration,
            );
            let k3 = derivative(
                &std::array::from_fn(|i| state[i] + step * k2[i] / 2.0),
                &self.acceleration,
            );
            let k4 = derivative(
                &std::array::from_fn(|i| state[i] + step * k3[i]),
                &self.acceleration,
            );
            for i in 0..6 {
                state[i] += step * (k1[i] + 2.0 * k2[i] + 2.0 * k3[i] + k4[i]) / 6.0;
            }
        }
        state
            .iter()
            .all(|v| v.is_finite())
            .then_some([state[0], state[1], state[2]])
    }
}

fn derivative(state: &[f64; 6], acceleration: &[f64; 3]) -> [f64; 6] {
    const MU: f64 = 3.9860044e14;
    const J2: f64 = 1.0826257e-3;
    const R: f64 = 6378136.0;
    const OMEGA: f64 = 7.292115e-5;
    let r2 = state[0] * state[0] + state[1] * state[1] + state[2] * state[2];
    let r3 = r2 * r2.sqrt();
    let a = 1.5 * J2 * MU * R * R / (r2 * r3);
    let b = 5.0 * state[2] * state[2] / r2;
    let g = -MU / r3 - a * (1.0 - b);
    [
        state[3],
        state[4],
        state[5],
        (g + OMEGA * OMEGA) * state[0] + 2.0 * OMEGA * state[4] + acceleration[0],
        (g + OMEGA * OMEGA) * state[1] - 2.0 * OMEGA * state[3] + acceleration[1],
        (g - 2.0 * a) * state[2] + acceleration[2],
    ]
}
