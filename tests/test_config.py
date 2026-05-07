import pytest

from gnss_tec.rinex import RinexObsHeader
from gnss_tec.tec.constants import TECConfig, get_sampling_config


def test_rinex_header_metadata_roundtrip():
    header = RinexObsHeader(
        version="3.04",
        constellation="MIXED",
        marker_name="CIBG",
        marker_type="GEODETIC",
        rx_ecef=(-1837003.1909, 6065631.1631, -716184.055),
        rx_geodetic=(-6.490367937958374, 106.84916836419953, 173.0000212144293),
        sampling_interval=30,
        leap_seconds=18,
    )

    assert RinexObsHeader.from_metadata(header.to_metadata()) == header


def test_tec_config_rejects_unsupported_constellation():
    with pytest.raises(ValueError, match="allowed letters"):
        TECConfig(constellations="E")


def test_tec_config_merges_partial_custom_code_priorities():
    config = TECConfig(c1_codes={"3": {"G": ["C1X", "C1C"]}})

    assert config.c1_codes["3"]["G"] == ["C1X", "C1C"]
    assert config.c1_codes["3"]["C"][0] == "C2I"
    assert config.c1_priority("3")["G_C1X"] == 0
    assert config.c1_priority("3")["G_C1C"] == 1


@pytest.mark.parametrize(
    "kwargs", [{"c1_codes": {"4": {"G": ["C1C"]}}}, {"c2_codes": {"3": {"E": ["C5Q"]}}}]
)
def test_tec_config_rejects_invalid_code_maps(kwargs):
    with pytest.raises(ValueError):
        TECConfig(**kwargs)


def test_sampling_config_thresholds():
    high_rate = get_sampling_config(5)
    low_rate = get_sampling_config(30)

    assert high_rate.slip_tec_threshold == 0.5
    assert high_rate.slip_correction_window == 20
    assert low_rate.slip_tec_threshold == 2.0
    assert low_rate.slip_correction_window == 10
