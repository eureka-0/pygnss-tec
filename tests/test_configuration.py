import pytest

from gnss_tec.configuration import TECConfig, get_sampling_config


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


@pytest.mark.parametrize(
    "kwargs",
    [
        {"mapping_function": "bad"},
        {"rx_bias": "bad"},
        {"missing_bias": "bad"},
        {"min_elevation": 91},
        {"ipp_height": 0},
        {"c1_codes": {"3": {"G": ["L1C"]}}},
    ],
)
def test_tec_config_rejects_invalid_values(kwargs):
    with pytest.raises(ValueError):
        TECConfig(**kwargs)


def test_sampling_config_thresholds():
    high_rate = get_sampling_config(5)
    low_rate = get_sampling_config(30)

    assert high_rate.slip_tec_threshold == 0.5
    assert high_rate.slip_correction_window == 20
    assert low_rate.slip_tec_threshold == 2.0
    assert low_rate.slip_correction_window == 10


@pytest.mark.parametrize(
    "name,value",
    [
        ("ipp_height", float("nan")),
        ("min_snr", float("inf")),
        ("min_elevation", float("nan")),
    ],
)
def test_nonfinite_configuration_is_rejected(name, value):
    with pytest.raises(ValueError):
        TECConfig(**{name: value})


def test_frequency_and_sampling_validation():
    with pytest.raises(ValueError, match="distinct frequencies"):
        TECConfig(c2_codes={"3": {"G": ["C1W"]}})
    for value in (0, -1, float("nan"), float("inf")):
        with pytest.raises(ValueError, match="finite and positive"):
            get_sampling_config(value)
