import numpy as np
import polars as pl
import pytest

from gnss_tec.calculation.mapping_functions import (
    modified_single_layer_model,
    single_layer_model,
)
from gnss_tec.configuration import TECConfig


@pytest.mark.parametrize(
    "mapping,lat,lon,az,el",
    [
        (single_layer_model, 89.0, 10.0, 0.0, 10.0),
        (modified_single_layer_model, -89.0, -10.0, 180.0, 10.0),
        (single_layer_model, 0.0, 179.0, 90.0, 5.0),
        (modified_single_layer_model, 0.0, 179.0, 90.0, 5.0),
        (single_layer_model, 45.0, 200.0, 40.0, 90.0),
        (modified_single_layer_model, 90.0, 0.0, 180.0, 90.0),
    ],
)
def test_ipp_matches_independent_cartesian_great_circle(mapping, lat, lon, az, el):
    config = TECConfig()
    frame = pl.DataFrame({"az": [az], "el": [el], "lat": [lat], "lon": [lon]})
    mf, ilat, ilon = mapping(*[pl.col(n) for n in ("az", "el", "lat", "lon")], config)
    actual = frame.select(mf.alias("mf"), ilat.alias("lat"), ilon.alias("lon")).row(0)
    lat, lon, az, el = np.deg2rad([lat, lon, az, el])
    height = (
        config.ipp_height_m if mapping == single_layer_model else config.mslm_height_m
    )
    beta_sin = (
        6378137.0
        * (
            np.cos(el)
            if mapping == single_layer_model
            else np.sin((np.pi / 2 - el) * config.alpha)
        )
        / (6378137.0 + height)
    )
    psi = np.pi / 2 - el - np.arcsin(beta_sin)
    up = np.array([np.cos(lat) * np.cos(lon), np.cos(lat) * np.sin(lon), np.sin(lat)])
    north = np.array(
        [-np.sin(lat) * np.cos(lon), -np.sin(lat) * np.sin(lon), np.cos(lat)]
    )
    east = np.array([-np.sin(lon), np.cos(lon), 0.0])
    ipp = np.cos(psi) * up + np.sin(psi) * (np.cos(az) * north + np.sin(az) * east)
    expected = [
        1 / np.sqrt(1 - beta_sin**2),
        np.rad2deg(np.arctan2(ipp[2], np.hypot(*ipp[:2]))),
        np.rad2deg(np.arctan2(ipp[1], ipp[0])),
    ]
    # Longitude is undefined exactly at the pole; compare the direction vector there.
    if abs(expected[1]) == 90:
        assert actual[1] == pytest.approx(expected[1], abs=1e-6)
    else:
        np.testing.assert_allclose(actual, expected, rtol=0, atol=1e-10)
