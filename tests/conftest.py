import gzip
from pathlib import Path

import polars as pl
from pytest import fixture
from real_observations import OBSERVATION_CODES, collect_short_windows

import gnss_tec as gt


@fixture(scope="session")
def test_data_dir():
    return Path(__file__).parent.parent / "data"


@fixture(scope="session", autouse=True)
def in_memory_engine():
    """Keep internal library collections on the same engine as the tests."""
    with pl.Config(engine_affinity="in-memory"):
        yield


@fixture(scope="session")
def rinex_obs_v2(test_data_dir):
    return test_data_dir / "rinex_obs_v2/dgar0100.24o.gz"


@fixture(scope="session")
def rinex_nav_v2(test_data_dir):
    return test_data_dir / "rinex_nav_v2/brdc0100.24n.gz"


@fixture(scope="session")
def rinex_nav_v2_glo(test_data_dir):
    return test_data_dir / "rinex_nav_v2/brdc0100.24g.gz"


@fixture(scope="session")
def rinex_obs_v3_hatanaka(test_data_dir):
    return test_data_dir / "rinex_obs_v3/CIBG00IDN_R_20240100000_01D_30S_MO.crx.gz"


@fixture(scope="session")
def rinex_obs_v3_bele_hatanaka(test_data_dir):
    return test_data_dir / "rinex_obs_v3/BELE00BRA_R_20240100000_01D_30S_MO.crx.gz"


@fixture(scope="session")
def rinex_obs_v3(test_data_dir):
    return test_data_dir / "rinex_obs_v3/CIBG00IDN_R_20240100000_01D_30S_MO.rnx.gz"


@fixture(scope="session")
def rinex_nav_v3(test_data_dir):
    return test_data_dir / "rinex_nav_v3/BRDC00IGS_R_20240100000_01D_MN.rnx.gz"


@fixture(scope="session")
def bias(test_data_dir):
    return test_data_dir / "bias/CAS0OPSRAP_20240100000_01D_01D_DCB.BIA.gz"


@fixture(scope="session")
def bias_gfz(test_data_dir):
    return test_data_dir / "bias/GFZ0OPSRAP_20240100000_01D_01D_DCB.BIA.gz"


@fixture(scope="module")
def small_observations(short_rinex_v3, rinex_nav_v3):
    header, lf = gt.read_rinex_obs(
        short_rinex_v3,
        constellations="CG",
        codes=OBSERVATION_CODES["3"],
        include_lli=True,
    )
    return header, collect_short_windows(lf)


@fixture(scope="session")
def short_rinex_v3(tmp_path_factory, rinex_obs_v3):
    """Copy complete real epochs in two five-minute windows, keeping the header."""
    path = tmp_path_factory.mktemp("rinex") / "CIBG_short.rnx"
    in_header = True
    selected = False
    with gzip.open(rinex_obs_v3, "rt") as source, path.open("w") as target:
        for line in source:
            if in_header:
                target.write(line)
                in_header = "END OF HEADER" not in line
                continue
            if line.startswith(">"):
                hour, minute = map(int, line.split()[4:6])
                selected = (hour == 18 and minute < 5) or (hour == 23 and minute >= 55)
            if selected:
                target.write(line)
    return path
