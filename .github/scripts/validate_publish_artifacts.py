"""Validate PyPI distribution metadata and artifacts outside the checkout."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import platform
import re
import shutil
import subprocess
import sys
import tarfile
import tempfile
import tomllib
import zipfile
from email.parser import BytesParser
from pathlib import Path


def project_version(root: Path, tag: str | None = None) -> str:
    def read(name):
        return tomllib.loads((root / name).read_text(encoding="utf-8"))

    python = read("pyproject.toml")["project"]["version"]
    versions = {
        "pyproject.toml": python,
        "Cargo.toml": read("Cargo.toml")["package"]["version"],
        "uv.lock": next(
            p["version"]
            for p in read("uv.lock")["package"]
            if p["name"] == "pygnss-tec"
        ),
        "Cargo.lock": next(
            p["version"]
            for p in read("Cargo.lock")["package"]
            if p["name"] == "gnss_tec_core"
        ),
    }
    if any(version != python for version in versions.values()):
        raise ValueError(f"Release version mismatch: {versions}")
    if tag is not None and tag != f"v{python}":
        raise ValueError(f"Tag {tag!r} does not match v{python}")
    if not re.search(
        rf"^## \[{re.escape(python)}\]",
        (root / "CHANGELOG.md").read_text(encoding="utf-8"),
        re.MULTILINE,
    ):
        raise ValueError(f"Missing release notes for {python}")
    return python


def inspect_artifact(artifact: Path, expected: str) -> dict:
    if artifact.suffix == ".whl":
        # This release advertises only ordinary CPython ABI3 and 64-bit wheels.
        if not re.search(
            r"-cp312-abi3-(?:manylinux[^/]*_(?:x86_64|aarch64)|macosx_[^/]*_(?:x86_64|arm64)|win_amd64)\.whl$",
            artifact.name,
        ):
            raise ValueError(f"Unsupported release wheel: {artifact.name}")
        with zipfile.ZipFile(artifact) as archive:
            names = archive.namelist()
            metadata = BytesParser().parsebytes(
                archive.read(
                    next(n for n in names if n.endswith(".dist-info/METADATA"))
                )
            )
            for required in (
                "gnss_tec/__init__.py",
                "gnss_tec/py.typed",
                "gnss_tec/_core.pyi",
            ):
                if required not in names:
                    raise ValueError(f"Wheel missing {required}")
            if not any(
                n.startswith("gnss_tec/_core") and n.endswith((".so", ".pyd"))
                for n in names
            ):
                raise ValueError("Wheel missing native extension")
    elif artifact.name.endswith(".tar.gz"):
        with tarfile.open(artifact) as archive:
            names = archive.getnames()
            prefix = names[0].split("/")[0] + "/"
            if any(name.startswith(prefix + "data/") for name in names):
                raise ValueError("Source distribution contains excluded data directory")
            for required in (
                "Cargo.toml",
                "Cargo.lock",
                "pyproject.toml",
                "src/lib.rs",
                "gnss_tec/py.typed",
                "gnss_tec/_core.pyi",
            ):
                if prefix + required not in names:
                    raise ValueError(f"Source distribution missing {required}")
            member = archive.extractfile(prefix + "PKG-INFO")
            if member is None:
                raise ValueError("Source distribution missing PKG-INFO")
            metadata = BytesParser().parsebytes(member.read())
            for name, section in (
                ("pyproject.toml", "project"),
                ("Cargo.toml", "package"),
            ):
                member = archive.extractfile(prefix + name)
                if (
                    member is None
                    or tomllib.loads(member.read().decode())[section]["version"]
                    != expected
                ):
                    raise ValueError(f"Source distribution version mismatch in {name}")
            if any(
                "/docs/agents/" in name or "/.venv/" in name or "/__pycache__/" in name
                for name in names
            ):
                raise ValueError("Source distribution contains local generated files")
    else:
        raise ValueError(f"Unsupported artifact: {artifact}")
    if metadata["Version"] != expected or metadata["Name"] != "pygnss-tec":
        raise ValueError(
            f"Artifact metadata mismatch: {metadata['Name']} {metadata['Version']}, expected {expected}"
        )
    return {
        "artifact": artifact.name,
        "sha256": hashlib.sha256(artifact.read_bytes()).hexdigest(),
        "version": expected,
    }


def validate_wheel(
    root: Path,
    artifact: Path,
    python: str,
    polars: str,
    output: Path,
    source: Path | None = None,
) -> None:
    evidence = inspect_artifact(artifact, project_version(root))
    if source is not None:
        source_evidence = inspect_artifact(source, evidence["version"])
        evidence.update(
            source_artifact=source_evidence["artifact"],
            source_sha256=source_evidence["sha256"],
        )
    uv = shutil.which("uv")
    if uv is None:
        raise RuntimeError("uv is required to validate artifacts")
    env = {
        k: v
        for k, v in os.environ.items()
        if k not in {"PYTHONPATH", "PYTHONHOME", "VIRTUAL_ENV"}
    }
    with tempfile.TemporaryDirectory(prefix="pygnss-artifact-") as directory:
        temporary = Path(directory)
        venv = temporary / "venv"
        subprocess.run([uv, "venv", "--python", python, str(venv)], env=env, check=True)
        interpreter = venv / (
            "Scripts/python.exe" if sys.platform == "win32" else "bin/python"
        )
        subprocess.run(
            [
                uv,
                "pip",
                "install",
                "--python",
                str(interpreter),
                str(artifact),
                "pytest>=8.4.2",
                polars,
            ],
            env=env,
            check=True,
        )
        consumer = temporary / "consumer"
        consumer.mkdir()
        shutil.copytree(
            root / "tests",
            consumer / "tests",
            ignore=shutil.ignore_patterns("__pycache__", ".pytest_cache"),
        )
        shutil.copytree(root / "data", consumer / "data")
        # Gate tests themselves use this helper; no package source is copied.
        helper = consumer / ".github/scripts"
        helper.mkdir(parents=True)
        shutil.copy2(
            root / ".github/scripts/validate_publish_artifacts.py",
            helper / "validate_publish_artifacts.py",
        )
        probe = (
            "import importlib, importlib.metadata, json, pathlib, sys, sysconfig; "
            "import gnss_tec as gt; import gnss_tec._core as core; "
            "assert pathlib.Path(gt.__file__).resolve().is_relative_to(pathlib.Path(sys.prefix).resolve()); "
            "assert pathlib.Path(core.__file__).resolve().is_relative_to(pathlib.Path(sys.prefix).resolve()); "
            f"assert importlib.metadata.version('pygnss-tec') == {evidence['version']!r}; "
            "assert not sysconfig.get_config_var('Py_GIL_DISABLED'); "
            "assert all(not hasattr(gt, n) for n in ['calc_tec_from_df','calc_tec_from_rinex','calc_tec_from_parquet']); "
            "print(json.dumps({'python':sys.version,'package':gt.__file__,'extension':core.__file__,"
            "'dependencies':{n:importlib.metadata.version(n) for n in ['numpy','polars','pyarrow','scipy']}}))"
        )
        result = subprocess.run(
            [str(interpreter), "-I", "-c", probe],
            cwd=consumer,
            env=env,
            check=True,
            capture_output=True,
            text=True,
        )
        evidence.update(json.loads(result.stdout))
        subprocess.run(
            [
                str(interpreter),
                "-I",
                "-m",
                "pytest",
                "tests",
                "-q",
                "--junitxml=results.xml",
            ],
            cwd=consumer,
            env=env,
            check=True,
        )
        # Keep the exact test results alongside the artifact hash/provenance.
        output.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(consumer / "results.xml", output.with_suffix(".xml"))
    evidence.update(
        {
            "tests_passed": True,
            "commit": os.environ.get("GITHUB_SHA"),
            "runner": platform.platform(),
            "machine": platform.machine(),
            "polars_requirement": polars,
        }
    )
    output.write_text(json.dumps(evidence, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(evidence, indent=2))


def verify_publication(root: Path, directory: Path, reports: Path) -> None:
    expected = project_version(root)
    artifacts = list(directory.iterdir())
    if (
        len(list(directory.glob("*.whl"))) != 5
        or len(list(directory.glob("*.tar.gz"))) != 1
        or len(artifacts) != 6
    ):
        raise ValueError(
            "Publication requires five 64-bit wheels and one source archive"
        )
    evidence = [
        json.loads(path.read_text(encoding="utf-8")) for path in reports.rglob("*.json")
    ]
    for artifact in artifacts:
        metadata = inspect_artifact(artifact, expected)
        source = artifact.name.endswith(".tar.gz")
        name_key, hash_key = (
            ("source_artifact", "source_sha256") if source else ("artifact", "sha256")
        )
        matched = [
            entry
            for entry in evidence
            if entry.get(name_key) == artifact.name
            and entry.get(hash_key) == metadata["sha256"]
            and entry.get("tests_passed") is True
            and entry.get("commit") == os.environ.get("GITHUB_SHA")
        ]
        for python, polars in (("3.12", "1.40.0"), ("3.14", "2.0.0")):
            if not any(
                entry.get("python", "").startswith(python + ".")
                and entry.get("dependencies", {}).get("polars") == polars
                for entry in matched
            ):
                raise ValueError(
                    f"Missing matching successful validation: {artifact.name}, Python {python}, Polars {polars}"
                )
        print(f"Verified tested artifact: {artifact.name} {metadata['sha256']}")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--root", type=Path, default=Path(__file__).resolve().parents[2]
    )
    commands = parser.add_subparsers(dest="command", required=True)
    versions = commands.add_parser("versions")
    versions.add_argument("--tag")
    inspect = commands.add_parser("inspect")
    inspect.add_argument("artifacts", type=Path, nargs="+")
    validate = commands.add_parser("validate")
    validate.add_argument("artifact", type=Path)
    validate.add_argument("--python", required=True)
    validate.add_argument("--polars", required=True)
    validate.add_argument("--output", type=Path, required=True)
    validate.add_argument("--source", type=Path)
    verify = commands.add_parser("verify")
    verify.add_argument("directory", type=Path)
    verify.add_argument("--reports", type=Path, required=True)
    rebuild = commands.add_parser("rebuild")
    rebuild.add_argument("artifact", type=Path)
    rebuild.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()
    root = args.root.resolve()
    if args.command == "versions":
        print(project_version(root, args.tag or None))
    elif args.command == "inspect":
        expected = project_version(root)
        for artifact in args.artifacts:
            print(json.dumps(inspect_artifact(artifact, expected)))
    elif args.command == "verify":
        verify_publication(root, args.directory.resolve(), args.reports.resolve())
    elif args.command == "rebuild":
        artifact = args.artifact.resolve()
        evidence = inspect_artifact(artifact, project_version(root))
        # uv --with can put the CLI outside the interpreter's script directories.
        maturin = shutil.which("maturin")
        if maturin is None:
            raise RuntimeError("maturin is required to rebuild source distributions")
        destination = args.out.resolve()
        destination.mkdir(parents=True, exist_ok=True)
        with tempfile.TemporaryDirectory(prefix="pygnss-sdist-") as directory:
            with tarfile.open(artifact) as archive:
                archive.extractall(directory, filter="data")
            (source,) = Path(directory).iterdir()
            subprocess.run(
                [
                    maturin,
                    "build",
                    "--release",
                    "--locked",
                    "--out",
                    str(destination),
                    "-i",
                    sys.executable,
                ],
                cwd=source,
                check=True,
            )
        print(json.dumps(evidence))
    else:
        validate_wheel(
            root,
            args.artifact.resolve(),
            args.python,
            args.polars,
            args.output.resolve(),
            args.source.resolve() if args.source else None,
        )


if __name__ == "__main__":
    main()
