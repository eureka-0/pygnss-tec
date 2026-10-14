from __future__ import annotations

from typing import Protocol

import numpy as np
import polars as pl

from .constants import Re, TECConfig


class MappingFunctionProtocol(Protocol):
    def __call__(
        self,
        azimuth: pl.Expr,
        elevation: pl.Expr,
        rx_lat_deg: pl.Expr,
        rx_lon_deg: pl.Expr,
        config: TECConfig,
    ) -> tuple[pl.Expr, pl.Expr, pl.Expr]:
        """Construct mapping factor and ionospheric pierce point expressions.

        Parameters
        ----------
        azimuth, elevation : polars.Expr
            Satellite azimuth/elevation in degrees.
        rx_lat_deg, rx_lon_deg : polars.Expr
            Receiver latitude/longitude in degrees.
        config : TECConfig
            Mapping model and shell-height configuration.

        Returns
        -------
        mf : polars.Expr
            Dimensionless slant-to-vertical mapping factor (VTEC=STEC/mf).
        ipp_lat : polars.Expr
            Pierce point latitude in degrees.
        ipp_lon : polars.Expr
            Pierce point longitude in degrees, wrapped to [-180, 180).
        """
        ...


def single_layer_model(
    azimuth: pl.Expr,
    elevation: pl.Expr,
    rx_lat_deg: pl.Expr,
    rx_lon_deg: pl.Expr,
    config: TECConfig,
) -> tuple[pl.Expr, pl.Expr, pl.Expr]:
    """Construct single layer mapping and pierce point expressions.

    Parameters
    ----------
    azimuth, elevation : polars.Expr
        Satellite azimuth/elevation in degrees.
    rx_lat_deg, rx_lon_deg : polars.Expr
        Receiver latitude/longitude in degrees.
    config : TECConfig
        Shell height from ipp_height, in km.

    Returns
    -------
    mf : polars.Expr
        Dimensionless mapping factor for VTEC=STEC/mf.
    ipp_lat : polars.Expr
        Pierce point latitude in degrees.
    ipp_lon : polars.Expr
        Pierce point longitude in degrees, wrapped to [-180, 180).
    """
    az = azimuth.radians()
    el = elevation.radians()
    rx_lat = rx_lat_deg.radians()
    rx_lon = rx_lon_deg.radians()

    # mapping function
    sin_beta = Re * el.cos() / (Re + config.ipp_height_m)
    sin_beta = sin_beta.clip(-1, 1)
    mf = sin_beta.arcsin().cos().pow(-1)

    # IPP latitude and longitude, in radians
    psi = np.pi / 2 - el - sin_beta.arcsin()
    ipp_lat = (
        (rx_lat.sin() * psi.cos() + rx_lat.cos() * psi.sin() * az.cos())
        .clip(-1, 1)
        .arcsin()
    )
    ipp_lon = rx_lon + pl.arctan2(
        psi.sin() * az.sin() * rx_lat.cos(), psi.cos() - rx_lat.sin() * ipp_lat.sin()
    )
    ipp_lon = (ipp_lon + np.pi) % (2 * np.pi) - np.pi

    return mf, ipp_lat.degrees(), ipp_lon.degrees()


def modified_single_layer_model(
    azimuth: pl.Expr,
    elevation: pl.Expr,
    rx_lat_deg: pl.Expr,
    rx_lon_deg: pl.Expr,
    config: TECConfig,
) -> tuple[pl.Expr, pl.Expr, pl.Expr]:
    """Construct modified single layer mapping and pierce point expressions.

    Parameters
    ----------
    azimuth, elevation : polars.Expr
        Satellite azimuth/elevation in degrees.
    rx_lat_deg, rx_lon_deg : polars.Expr
        Receiver latitude/longitude in degrees.
    config : TECConfig
        Fixed MSLM shell height (506.7 km) and dimensionless alpha (0.9782).
        The configured SLM ipp_height does not affect this model.

    Returns
    -------
    mf : polars.Expr
        Dimensionless mapping factor for VTEC=STEC/mf.
    ipp_lat : polars.Expr
        Pierce point latitude in degrees from the modified-model geometry.
    ipp_lon : polars.Expr
        Pierce point longitude in degrees, wrapped to [-180, 180).
    """
    az = azimuth.radians()
    el = elevation.radians()
    rx_lat = rx_lat_deg.radians()
    rx_lon = rx_lon_deg.radians()

    # mapping function
    sin_beta = (
        Re * (np.pi / 2 - el).mul(config.alpha).sin() / (Re + config.mslm_height_m)
    )
    mf = sin_beta.arcsin().cos().pow(-1)

    # IPP latitude and longitude, in radians
    psi = np.pi / 2 - el - sin_beta.arcsin()
    ipp_lat = (
        (rx_lat.sin() * psi.cos() + rx_lat.cos() * psi.sin() * az.cos())
        .clip(-1, 1)
        .arcsin()
    )
    ipp_lon = rx_lon + pl.arctan2(
        psi.sin() * az.sin() * rx_lat.cos(), psi.cos() - rx_lat.sin() * ipp_lat.sin()
    )
    ipp_lon = (ipp_lon + np.pi) % (2 * np.pi) - np.pi

    return mf, ipp_lat.degrees(), ipp_lon.degrees()
