"""Isolated dependency audit; production source is never edited by this probe."""

import argparse
import importlib.util
import json
import os
import platform
import statistics
import sys
from collections.abc import Callable
from contextlib import ExitStack
from functools import partial
from pathlib import Path
from time import perf_counter
from typing import Literal
from unittest.mock import patch

import numpy as np
import polars as pl
import pyarrow
import scipy


def measure(
    name: str,
    fn: Callable[[], pl.DataFrame],
    output: Path,
    repeats: int,
    runs: dict[str, dict[str, object]],
) -> None:
    try:
        df = fn()  # warm-up
        samples: list[float] = []
        for _ in range(repeats):
            start = perf_counter()
            df = fn()
            samples.append(perf_counter() - start)
        df.write_ipc(output / (name + ".arrow"))
        runs[name] = {
            "shape": df.shape,
            "median_s": statistics.median(samples),
            "samples_s": samples,
            "schema": {k: str(v) for k, v in df.schema.items()},
            "nulls": df.null_count().row(0, named=True),
        }
        print(name, df.shape, round(statistics.median(samples), 4), flush=True)
    except (
        OSError,
        ValueError,
        TypeError,
        RuntimeError,
        pl.exceptions.PolarsError,
    ) as exc:
        runs[name] = {"error": repr(exc)}
        print(name, repr(exc), flush=True)


def main() -> int:
    root = Path(__file__).resolve().parents[1]
    sys.path.insert(0, str(root))
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path)
    parser.add_argument("--engine", default="auto")
    parser.add_argument("--ordered", action="store_true")
    parser.add_argument("--pytest", action="store_true")
    parser.add_argument("--core", type=Path)
    parser.add_argument("--repeats", type=int, default=5)
    args = parser.parse_args()
    if args.repeats < 1:
        parser.error("--repeats must be at least 1")
    if args.core:
        spec = importlib.util.spec_from_file_location("gnss_tec._core", args.core)
        if spec is None or spec.loader is None:
            parser.error(f"Cannot load a Python extension from {args.core}")
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        sys.modules["gnss_tec._core"] = module

    # Import the package after selecting the Rust extension.
    import gnss_tec as gt
    import gnss_tec._core as core
    import gnss_tec.tec.tec_calculation as tc
    from gnss_tec.rinex import RinexObsHeader

    with ExitStack() as patches:
        pl.Config.set_engine_affinity(args.engine)
        if args.ordered:
            original = tc._coalesce_observations

            def ordered(
                lf: pl.LazyFrame,
                bias_lf: pl.LazyFrame | None,
                config: gt.TECConfig,
                version: Literal["2", "3"],
            ) -> pl.LazyFrame:
                return original(lf, bias_lf, config, version).sort(
                    "time", "station", "prn"
                )

            patches.enter_context(patch.object(tc, "_coalesce_observations", ordered))

        if args.pytest:
            import pytest

            os.chdir(root)
            return pytest.main(["tests", "-q", "--tb=short"])

        if args.output is None:
            parser.error("--output is required unless --pytest is used")
        output = Path(args.output)
        output.mkdir(parents=True, exist_ok=True)
        data = root / "data"
        cases = {
            "v2": (
                data / "rinex_obs_v2/dgar0100.24o.gz",
                data / "rinex_nav_v2/brdc0100.24n.gz",
            ),
            "v3": (
                data / "rinex_obs_v3/CIBG00IDN_R_20240100000_01D_30S_MO.rnx.gz",
                data / "rinex_nav_v3/BRDC00IGS_R_20240100000_01D_MN.rnx.gz",
            ),
            "crx": (
                data / "rinex_obs_v3/CIBG00IDN_R_20240100000_01D_30S_MO.crx.gz",
                data / "rinex_nav_v3/BRDC00IGS_R_20240100000_01D_MN.rnx.gz",
            ),
        }
        runs: dict[str, dict[str, object]] = {}
        summary: dict[str, object] = {
            "polars": pl.__version__,
            "python": platform.python_version(),
            "numpy": np.__version__,
            "scipy": scipy.__version__,
            "pyarrow": pyarrow.__version__,
            "threads": pl.thread_pool_size(),
            "engine": args.engine,
            "ordered": args.ordered,
            "core": str(args.core or core.__file__),
            "runs": runs,
        }

        def read_frame(obs: Path, nav: Path) -> pl.DataFrame:
            return gt.read_rinex_obs(obs, nav)[1].collect()

        def tec_frame(
            observations: pl.DataFrame,
            header: RinexObsHeader,
            bias: Path | None,
            config: gt.TECConfig,
        ) -> pl.DataFrame:
            return gt.calc_tec_from_df(observations, header, bias, config).collect()

        for name, (obs, nav) in cases.items():
            measure(
                "read_" + name,
                partial(read_frame, obs, nav),
                output,
                args.repeats,
                runs,
            )
            header, lf = gt.read_rinex_obs(obs, nav)
            observations = lf.collect()
            methods: list[Literal["external", "mstd", "lsq"] | None] = (
                ["external", "mstd", "lsq", None]
                if name == "v3"
                else ["external", None]
            )
            for bias_method in methods:
                config = gt.TECConfig(rx_bias=bias_method, retain_intermediate="all")
                bias = (
                    data / "bias/CAS0OPSRAP_20240100000_01D_01D_DCB.BIA.gz"
                    if bias_method
                    else None
                )
                measure(
                    f"tec_{name}_{bias_method}",
                    partial(tec_frame, observations, header, bias, config),
                    output,
                    args.repeats,
                    runs,
                )
        if sys.platform == "darwin":
            import resource

            summary["peak_rss_bytes_macos"] = resource.getrusage(
                resource.RUSAGE_SELF
            ).ru_maxrss
        (output / "summary.json").write_text(json.dumps(summary, indent=2))
        print(json.dumps({k: v for k, v in summary.items() if k != "runs"}))
        return 0


if __name__ == "__main__":
    raise SystemExit(main())
