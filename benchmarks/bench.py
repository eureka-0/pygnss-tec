"""Compare streaming and in-memory RINEX/TEC execution in one benchmark run."""

import argparse
import hashlib
import json
import os
import platform
import statistics
from collections.abc import Callable
from datetime import UTC, datetime
from functools import partial
from importlib.metadata import version
from pathlib import Path
from time import perf_counter
from typing import Literal

import polars as pl
from polars.testing import assert_frame_equal

import gnss_tec as gt
import gnss_tec._core as core
from gnss_tec.rinex import RinexObsHeader

ROOT = Path(__file__).resolve().parents[1]
Engine = Literal["streaming", "in-memory"]
ENGINES: tuple[Engine, ...] = ("streaming", "in-memory")


def read_observations(obs: list[Path], nav: list[Path], engine: Engine) -> pl.DataFrame:
    return gt.read_rinex_obs(obs, nav)[1].collect(engine=engine)


def calculate(
    obs: list[Path], nav: list[Path], bias: list[Path] | None, engine: Engine
) -> pl.DataFrame:
    header, lf = gt.read_rinex_obs(obs, nav)
    return gt.calc_tec_from_df(lf, header, bias).collect(engine=engine)


def calculate_from_df(
    observations: pl.DataFrame,
    header: RinexObsHeader,
    bias: list[Path] | None,
    engine: Engine,
) -> pl.DataFrame:
    return gt.calc_tec_from_df(observations, header, bias).collect(engine=engine)


def logical(df: pl.DataFrame) -> pl.DataFrame:
    # Compare identities rather than categorical dictionary encodings.
    return df.with_columns(pl.col(pl.Categorical).cast(pl.String)).sort(
        "time", "station", "prn"
    )


def measure(
    name: str,
    run: Callable[[], pl.DataFrame],
    repeats: int,
    warmup: int,
    engine: Engine,
) -> tuple[dict[str, object], pl.DataFrame]:
    samples = []
    # Pin nested collect calls as well as the final collection to this engine.
    with pl.Config(engine_affinity=engine):
        for _ in range(warmup):
            run()
        for _ in range(repeats):
            start = perf_counter()
            df = run()
            samples.append(perf_counter() - start)
    if df.height == 0:
        raise ValueError(
            f"{name} produced no observations; empty TEC is not a valid benchmark"
        )
    median = statistics.median(samples)
    print(f"{engine}: {name}: {median:.4f} s, {df.height:,} rows", flush=True)
    return {
        "name": name,
        "rows": df.height,
        "median_s": median,
        "min_s": min(samples),
        "max_s": max(samples),
        "samples_s": samples,
    }, df


def cases(
    multiday: bool,
) -> list[tuple[str, list[Path], list[Path], list[Path] | None]]:
    nav2 = ROOT / "data/rinex_nav_v2/brdc0100.24n.gz"
    nav3 = ROOT / "data/rinex_nav_v3/BRDC00IGS_R_20240100000_01D_MN.rnx.gz"
    bias = [ROOT / "data/bias/CAS0OPSRAP_20240100000_01D_01D_DCB.BIA.gz"]
    result = [
        ("v2-DGAR", [ROOT / "data/rinex_obs_v2/dgar0100.24o.gz"], [nav2], None),
        (
            "v3-CIBG",
            [ROOT / "data/rinex_obs_v3/CIBG00IDN_R_20240100000_01D_30S_MO.rnx.gz"],
            [nav3],
            bias,
        ),
        (
            "crx-CIBG",
            [ROOT / "data/rinex_obs_v3/CIBG00IDN_R_20240100000_01D_30S_MO.crx.gz"],
            [nav3],
            bias,
        ),
        (
            "crx-BELE",
            [ROOT / "data/rinex_obs_v3/BELE00BRA_R_20240100000_01D_30S_MO.crx.gz"],
            [nav3],
            bias,
        ),
    ]
    if multiday:
        for station in ("DGAR", "POAL", "CIBG", "BELE"):
            v2 = station in {"DGAR", "POAL"}
            country = "IDN" if station == "CIBG" else "BRA"
            obs = [
                ROOT / f"data/rinex_obs_v2/{station.lower()}{day:03d}0.24o.gz"
                if v2
                else ROOT
                / f"data/rinex_obs_v3/{station}00{country}_R_2024{day:03d}0000_01D_30S_MO.crx.gz"
                for day in (10, 11)
            ]
            nav = [
                ROOT / f"data/rinex_nav_v2/brdc{day:03d}0.24n.gz"
                if v2
                else ROOT
                / f"data/rinex_nav_v3/BRDC00IGS_R_2024{day:03d}0000_01D_MN.rnx.gz"
                for day in (10, 11)
            ]
            biases = (
                None
                if v2
                else [
                    ROOT / f"data/bias/CAS0OPSRAP_2024{day:03d}0000_01D_01D_DCB.BIA.gz"
                    for day in (10, 11)
                ]
            )
            result.append((f"two-days-{station}", obs, nav, biases))
    return result


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repeats", type=int, default=7)
    parser.add_argument("--warmup", type=int, default=1)
    parser.add_argument(
        "--stages",
        nargs="+",
        choices=["read", "read-and-TEC", "TEC-only"],
        default=["read", "read-and-TEC", "TEC-only"],
    )
    parser.add_argument(
        "--multiday",
        action="store_true",
        help="Include four real receivers over two GPS days",
    )
    parser.add_argument("--output", type=Path, default=ROOT / "benchmarks/benchmark.md")
    parser.add_argument("--json-output", type=Path)
    args = parser.parse_args()
    if args.repeats < 1 or args.warmup < 0:
        parser.error("--repeats must be positive and --warmup must be nonnegative")
    metadata = {
        "timestamp_utc": datetime.now(UTC).isoformat(timespec="seconds"),
        "platform": platform.platform(),
        "python": platform.python_version(),
        "packages": {
            p: version(p) for p in ("polars", "numpy", "scipy", "pyarrow", "pygnss-tec")
        },
        "cpu_cores": os.cpu_count(),
        "polars_threads": pl.thread_pool_size(),
        "engines": ENGINES,
        "native_core_sha256": hashlib.sha256(
            Path(core.__file__).read_bytes()
        ).hexdigest(),
        "repeats": args.repeats,
        "warmup": args.warmup,
        "stages": args.stages,
    }
    print(json.dumps(metadata, indent=2), flush=True)
    runs: dict[Engine, list[dict[str, object]]] = {engine: [] for engine in ENGINES}
    for case_index, (name, obs, nav, bias) in enumerate(cases(args.multiday)):
        size_mib = sum(p.stat().st_size for p in obs) / 1024**2
        for stage_index, stage in enumerate(args.stages):
            if stage == "read":
                operation = partial(read_observations, obs, nav)
            elif stage == "read-and-TEC":
                operation = partial(calculate, obs, nav, bias)
            else:
                # Both engines calculate TEC from exactly the same resident data.
                header, lf = gt.read_rinex_obs(obs, nav)
                cached_df = lf.collect(engine="in-memory")
                operation = partial(calculate_from_df, cached_df, header, bias)
            # Alternate measurement order to avoid consistently favouring one engine.
            engine_order = (
                ENGINES if (case_index + stage_index) % 2 == 0 else ENGINES[::-1]
            )
            reference = None
            for engine in engine_order:
                result, df = measure(
                    f"{stage}-{name}",
                    partial(operation, engine),
                    args.repeats,
                    args.warmup,
                    engine,
                )
                result["size_mib"] = size_mib
                runs[engine].append(result)
                # Identity/null/value comparison is outside the measured interval.
                if reference is None:
                    reference = logical(df)
                else:
                    assert_frame_equal(
                        reference,
                        logical(df),
                        check_exact=False,
                        rel_tol=0,
                        abs_tol=1e-8,
                    )
                del df
            del reference, operation
            if stage == "TEC-only":
                del cached_df, header, lf
    packages = metadata["packages"]
    lines = [
        "# Benchmark Results",
        "",
        f"Python {metadata['python']}; {metadata['platform']}; {metadata['cpu_cores']} logical CPU cores.",
        f"Dependencies: {json.dumps(packages, sort_keys=True)}.",
        f"Polars threads: {metadata['polars_threads']}; warm-up runs per engine/task: {args.warmup}; measured runs per engine/task: {args.repeats}.",
        f"Measured at {metadata['timestamp_utc']}; native extension SHA-256: {metadata['native_core_sha256']}.",
        "",
        "Read includes navigation parsing and satellite azimuth/elevation calculation. Read-and-TEC uses the same reader scope; TEC-only starts with observations already in memory.",
        "RINEX 2 uses no DCB correction: the supplied CAS files do not contain matching C1/C2 biases. RINEX 3 uses external CAS DCBs. Empty outputs fail the benchmark.",
        "Task sizes are the total on-disk observation file sizes, excluding navigation and bias files. For TEC-only, they refer to the source files rather than DataFrame memory usage.",
        "Both engines run serially with alternating measurement order. Each task's final results are compared outside timing: identities, dtypes, null masks and numerical values (rel_tol=0, abs_tol=1e-8).",
        "",
    ]
    for engine in ENGINES:
        lines.extend(
            [
                f"## {engine}",
                "",
                "| Task | Rows | Median (s) | Min–max (s) |",
                "| --- | ---: | ---: | ---: |",
            ]
        )
        for run in runs[engine]:
            lines.append(
                f"| {run['name']} ({run['size_mib']:.2f} MiB) | {run['rows']} | {run['median_s']:.4f} | {run['min_s']:.4f}–{run['max_s']:.4f} |"
            )
        lines.append("")
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text("\n".join(lines) + "\n")
    if args.json_output is not None:
        args.json_output.parent.mkdir(parents=True, exist_ok=True)
        args.json_output.write_text(
            json.dumps({"environment": metadata, "runs": runs}, indent=2) + "\n"
        )
    print(f"Benchmark results written to {args.output}")


if __name__ == "__main__":
    main()
