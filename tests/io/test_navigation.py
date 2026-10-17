"""Public navigation ownership, filtering and recoverable input errors."""

import gzip
import shutil
from concurrent.futures import ThreadPoolExecutor
from dataclasses import FrozenInstanceError

import pytest
from polars.testing import assert_frame_equal

import gnss_tec as gt


@pytest.mark.parametrize(
    "fixture", ["rinex_nav_v2", "rinex_nav_v2_glo", "rinex_nav_v3"]
)
def test_navigation_metadata_and_readonly(fixture, request):
    path = request.getfixturevalue(fixture)
    nav = gt.read_rinex_nav(path)
    assert nav.sources == (str(path.resolve()),)
    assert nav.satellites == tuple(sorted(nav.satellites))
    assert set(nav.constellations) <= set("GCERJIS")
    assert all(s[0] in "GCERJIS" and s[1:].isdigit() for s in nav.satellites)
    assert nav.n_ephemerides > len(nav.satellites) > 0
    epoch_range = nav.epoch_range
    assert epoch_range is not None
    assert epoch_range[0] <= epoch_range[1]
    assert "n_ephemerides=" in repr(nav)
    with pytest.raises(FrozenInstanceError):
        nav.__setattr__("_handle", None)


def test_navigation_filter_plain_gzip_and_multiday(
    rinex_nav_v3, test_data_dir, tmp_path
):
    plain = tmp_path / "navigation.rnx"
    plain.write_bytes(gzip.decompress(rinex_nav_v3.read_bytes()))
    filtered = gt.read_rinex_nav(plain, constellations="GC")
    assert filtered.constellations == "CG"
    assert all(s[0] in "GC" for s in filtered.satellites)
    assert (
        filtered.n_ephemerides
        == gt.read_rinex_nav(rinex_nav_v3, constellations="CG").n_ephemerides
    )
    paths = sorted((test_data_dir / "rinex_nav_v3").glob("*.gz"))
    combined = gt.read_rinex_nav(reversed(paths))
    assert combined.sources == tuple(str(p.resolve()) for p in paths)
    assert combined.n_ephemerides > gt.read_rinex_nav(paths[0]).n_ephemerides
    empty = gt.read_rinex_nav(plain, constellations="S")
    assert empty.n_ephemerides > 0
    assert empty.constellations == "S"
    assert all(s.startswith("S") for s in empty.satellites)


@pytest.mark.parametrize("codes", ["", "g", "GX", "GPS"])
def test_navigation_rejects_invalid_filter(rinex_nav_v3, codes):
    with pytest.raises(ValueError, match="one-letter GNSS"):
        gt.read_rinex_nav(rinex_nav_v3, constellations=codes)


def test_navigation_rejects_wrong_files(tmp_path, rinex_obs_v3, rinex_nav_v3):
    with pytest.raises(FileNotFoundError):
        gt.read_rinex_nav(tmp_path / "missing.nav")
    with pytest.raises(ValueError, match="No RINEX"):
        gt.read_rinex_nav([])
    with pytest.raises(ValueError, match="navigation"):
        gt.read_rinex_nav(rinex_obs_v3)
    with pytest.raises(ValueError, match="merge"):
        gt.read_rinex_nav([rinex_nav_v3, rinex_obs_v3])
    broken = tmp_path / "broken.nav"
    broken.write_text("not a RINEX file\n")
    with pytest.raises((OSError, ValueError)):
        gt.read_rinex_nav(broken)


def test_loaded_navigation_survives_source_removal_and_parallel_calls(
    tmp_path, rinex_nav_v3, small_observations
):
    source = tmp_path / "navigation.rnx.gz"
    shutil.copyfile(rinex_nav_v3, source)
    nav = gt.read_rinex_nav(source)
    source.unlink()
    header, frame = small_observations
    frame = frame.head(128)
    lazy = gt.compute_az_el(frame, header, nav)
    expected = lazy.collect()
    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(
            pool.map(
                lambda _, loaded=nav: gt.compute_az_el(frame, header, loaded).collect(),
                range(2),
            )
        )
    for result in results:
        assert_frame_equal(result, expected, check_exact=True)
    del nav
    assert_frame_equal(lazy.collect(), expected, check_exact=True)


def test_public_old_tec_names_are_removed():
    for name in ("calc_tec_from_df", "calc_tec_from_parquet", "calc_tec_from_rinex"):
        assert not hasattr(gt, name)
        assert name not in gt.__all__
    assert {
        "compute_tec",
        "compute_tec_from_parquet",
        "compute_tec_from_rinex",
        "compute_az_el",
        "read_rinex_nav",
        "NavigationData",
    } <= set(gt.__all__)
