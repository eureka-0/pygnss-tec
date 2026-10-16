"""Check continuity on the final calibrated products of the complete workload."""

import numpy as np
import polars as pl
from slip_reference import offsets

import gnss_tec as gt


def test_complete_cibg_final_products(
    rinex_obs_v3_hatanaka, rinex_nav_v3, bias, record_property
):
    result = gt.calc_tec_from_rinex(
        rinex_obs_v3_hatanaka,
        rinex_nav_v3,
        bias,
        gt.TECConfig(retain_diagnostics="all"),
    ).collect(engine="in-memory")
    maxima = {name: 0.0 for name in ("stec", "stec_dcb_corrected", "stec_p_corrected")}
    event_count = 0
    for group in result.filter(pl.col("qc_valid")).partition_by("station", "prn"):
        times = group["time"].cast(pl.Int64).to_numpy().astype(float) / 1e9
        events = group["slip_stec_correction"].is_not_null().to_numpy()
        event_count += int(events.sum())
        for name, previous_max in maxima.items():
            mask = events
            if name == "stec_p_corrected":
                mask = (
                    group["slip_status"]
                    .is_in(["phase_repaired", "phase_continuous"])
                    .to_numpy()
                )
            residual = offsets(times, group[name].to_numpy(), mask)
            error = float(np.max(np.abs(residual[mask]), initial=0))
            maxima[name] = max(previous_max, error)
            assert error < 1e-6, (group["prn"][0], name, error)
    np.testing.assert_allclose(
        result["vtec"] * result["mf"], result["stec_dcb_corrected"], rtol=0, atol=1e-12
    )
    c38 = result.filter(pl.col("qc_valid") & (pl.col("prn") == "C38"))
    assert c38["C1_code"].n_unique() > 1
    record_property("final_product_event_count", event_count)
    record_property("final_product_max_discontinuity_tecu", maxima)
