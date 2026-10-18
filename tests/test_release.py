"""Version, installation and scientific failures must stop the artifact gate."""

import importlib.util
import io
import json
import subprocess
import tarfile
import zipfile
from pathlib import Path
from types import SimpleNamespace

import pytest


@pytest.fixture
def release():
    path = (
        Path(__file__).resolve().parents[1]
        / ".github/scripts/validate_publish_artifacts.py"
    )
    spec = importlib.util.spec_from_file_location("release_gate", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.fixture
def project(tmp_path):
    for name, content in {
        "pyproject.toml": '[project]\nversion = "0.5.0"\n',
        "Cargo.toml": '[package]\nversion = "0.5.0"\n',
        "uv.lock": '[[package]]\nname = "pygnss-tec"\nversion = "0.5.0"\n',
        "Cargo.lock": '[[package]]\nname = "gnss_tec_core"\nversion = "0.5.0"\n',
        "CHANGELOG.md": "## [0.5.0]\n",
    }.items():
        (tmp_path / name).write_text(content)
    return tmp_path


@pytest.fixture
def source_archive(project):
    def write(extra_files=None):
        artifact = project / "pygnss_tec-0.5.0.tar.gz"
        files = {
            "Cargo.toml": (project / "Cargo.toml").read_text(),
            "Cargo.lock": (project / "Cargo.lock").read_text(),
            "pyproject.toml": (project / "pyproject.toml").read_text(),
            "src/lib.rs": "// archived source\n",
            "gnss_tec/py.typed": "",
            "gnss_tec/_core.pyi": "",
            "PKG-INFO": "Name: pygnss-tec\nVersion: 0.5.0\n",
        }
        files.update(extra_files or {})
        with tarfile.open(artifact, "w:gz") as archive:
            for name, content in files.items():
                payload = content.encode()
                member = tarfile.TarInfo(f"pygnss_tec-0.5.0/{name}")
                member.size = len(payload)
                archive.addfile(member, io.BytesIO(payload))
        return artifact

    return write


@pytest.mark.parametrize(
    "mismatch", ["Cargo.toml", "uv.lock", "Cargo.lock", "tag", "notes"]
)
def test_release_version_mismatch_blocks_gate(release, project, mismatch):
    assert release.project_version(project, "v0.5.0") == "0.5.0"
    if mismatch in {"tag", "notes"}:
        if mismatch == "notes":
            (project / "CHANGELOG.md").write_text("## [Unreleased]\n")
        tag = "v0.4.2" if mismatch == "tag" else "v0.5.0"
    else:
        path = project / mismatch
        path.write_text(path.read_text().replace("0.5.0", "0.4.2"))
        tag = "v0.5.0"
    with pytest.raises(ValueError):
        release.project_version(project, tag)


def test_artifact_version_and_type_files_are_checked(release, tmp_path):
    wheel = tmp_path / "pygnss_tec-0.5.0-cp312-abi3-win_amd64.whl"
    files = {
        "gnss_tec/__init__.py": "",
        "gnss_tec/py.typed": "",
        "gnss_tec/_core.pyi": "",
        "gnss_tec/_core.pyd": "",
        "pygnss_tec-0.5.0.dist-info/METADATA": "Name: pygnss-tec\nVersion: 0.5.0\n",
    }
    for missing in (None, "gnss_tec/py.typed"):
        with zipfile.ZipFile(wheel, "w") as archive:
            for name, content in files.items():
                if name != missing:
                    archive.writestr(name, content)
        if missing is None:
            assert len(release.inspect_artifact(wheel, "0.5.0")["sha256"]) == 64
            with pytest.raises(ValueError, match="metadata mismatch"):
                release.inspect_artifact(wheel, "0.4.2")
        else:
            with pytest.raises(ValueError, match="missing gnss_tec/py.typed"):
                release.inspect_artifact(wheel, "0.5.0")


def test_sdist_rejects_bundled_sample_data(release, source_archive):
    assert release.inspect_artifact(source_archive(), "0.5.0")["version"] == "0.5.0"
    artifact = source_archive({"data/example.rnx": "sample observations"})
    with pytest.raises(ValueError, match="excluded data directory"):
        release.inspect_artifact(artifact, "0.5.0")


@pytest.mark.parametrize("build_fails", [False, True])
def test_sdist_rebuild_uses_maturin_from_path(
    release, project, source_archive, monkeypatch, capsys, build_fails
):
    artifact = source_archive()
    # Model uv's tool directory, separate from sys.executable's script directory.
    cli = project / "uv-tools" / "maturin"
    monkeypatch.setattr(release.shutil, "which", lambda name: str(cli))
    destination = project / "rebuilt"
    seen = []

    def run(command, *, cwd, check):
        seen.append(command)
        assert command[0] == str(cli)
        assert command[1:4] == ["build", "--release", "--locked"]
        assert command[4:] == ["--out", str(destination), "-i", release.sys.executable]
        assert (cwd / "src/lib.rs").read_text() == "// archived source\n"
        assert not cwd.is_relative_to(project)
        assert check
        if build_fails:
            raise subprocess.CalledProcessError(1, command)

    monkeypatch.setattr(release.subprocess, "run", run)
    monkeypatch.setattr(
        release.sys,
        "argv",
        [
            "gate",
            "--root",
            str(project),
            "rebuild",
            str(artifact),
            "--out",
            str(destination),
        ],
    )
    if build_fails:
        with pytest.raises(subprocess.CalledProcessError):
            release.main()
        assert not capsys.readouterr().out
    else:
        release.main()
        assert json.loads(capsys.readouterr().out)["artifact"] == artifact.name
    assert len(seen) == 1


@pytest.mark.parametrize("failure", ["install", "scientific_tests"])
def test_failed_install_or_scientific_tests_cannot_record_success(
    release, project, monkeypatch, failure
):
    monkeypatch.setattr(release, "inspect_artifact", lambda *args: {"version": "0.5.0"})
    monkeypatch.setattr(release.shutil, "which", lambda _: "uv")
    for path in (project / "tests", project / "data", project / ".github/scripts"):
        path.mkdir(parents=True)
    (project / ".github/scripts/validate_publish_artifacts.py").write_text("")
    seen = []

    def run(command, **kwargs):
        seen.append(command)
        target = "install" if failure == "install" else "pytest"
        if target in command:
            raise subprocess.CalledProcessError(1, command)
        return SimpleNamespace(stdout=json.dumps({}))

    monkeypatch.setattr(release.subprocess, "run", run)
    evidence = project / "provenance.json"
    with pytest.raises(subprocess.CalledProcessError):
        release.validate_wheel(
            project, project / "example.whl", "3.12", "polars==1.40.0", evidence
        )
    assert not evidence.exists()
    assert any(
        ("install" if failure == "install" else "pytest") in command for command in seen
    )


def test_publication_requires_matching_successful_artifact_hashes(
    release, project, monkeypatch
):
    artifacts = project / "dist"
    reports = project / "reports"
    artifacts.mkdir()
    reports.mkdir()
    for i in range(5):
        (artifacts / f"target{i}.whl").touch()
    (artifacts / "source.tar.gz").touch()
    monkeypatch.setattr(
        release, "inspect_artifact", lambda path, version: {"sha256": "tested-hash"}
    )
    entries = []
    for artifact in artifacts.iterdir():
        source = artifact.suffix == ".gz"
        for python, polars in (("3.12.15", "1.40.0"), ("3.14.8", "2.0.0")):
            entries.append(
                {
                    ("source_artifact" if source else "artifact"): artifact.name,
                    ("source_sha256" if source else "sha256"): "tested-hash",
                    "tests_passed": True,
                    "commit": release.os.environ.get("GITHUB_SHA"),
                    "python": python,
                    "dependencies": {"polars": polars},
                }
            )
    for index, entry in enumerate(entries):
        (reports / f"{index}.json").write_text(json.dumps(entry))
    release.verify_publication(project, artifacts, reports)
    source = entries[0].get("source_artifact")
    entries[0]["source_sha256" if source else "sha256"] = "different-artifact"
    (reports / "0.json").write_text(json.dumps(entries[0]))
    with pytest.raises(ValueError, match="Missing matching successful validation"):
        release.verify_publication(project, artifacts, reports)
