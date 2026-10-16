from __future__ import annotations

import gzip
import io
import re
from collections.abc import Iterable
from pathlib import Path

import polars as pl


def _read_bias_file(fn: str | Path) -> pl.LazyFrame:
    if str(fn).endswith(".gz"):
        with gzip.open(fn, "rt", encoding="utf-8") as f:
            lines = f.readlines()
    else:
        with open(fn, "r", encoding="utf-8") as f:
            lines = f.readlines()

    if not lines:
        raise ValueError(f"Bias file {fn} is empty.")

    try:
        header_marker_idx = next(
            i for i, line in enumerate(lines) if "+BIAS/SOLUTION" in line
        )
    except StopIteration:
        raise ValueError("Header '+BIAS/SOLUTION' not found in the file.")

    header_line_idx = header_marker_idx + 1
    if header_line_idx >= len(lines):
        raise ValueError("No header line found after '+BIAS/SOLUTION' marker.")

    header_str = lines[header_line_idx].rstrip("\n")

    footer_line_idx = None
    for i in range(len(lines) - 1, header_line_idx, -1):
        if "-BIAS/SOLUTION" in lines[i]:
            footer_line_idx = i
            break

    if footer_line_idx is None:
        footer_line_idx = len(lines)

    if footer_line_idx <= header_line_idx + 1:
        buf = io.StringIO("")
    else:
        buf = io.StringIO("".join(lines[header_line_idx + 1 : footer_line_idx]))

    colspecs = [(m.start(), m.end()) for m in re.finditer(r"\S+", header_str)]
    cols = [col.strip("*_").lower() for col in header_str.split()]
    schema = {
        "prn": pl.Categorical,
        "station": pl.Categorical,
        "obs1": pl.Categorical,
        "obs2": pl.Categorical,
        "unit": pl.Categorical,
        "estimated_value": pl.Float64,
        "std_dev": pl.Float64,
    }
    lf = (
        pl.scan_csv(buf, has_header=False, new_columns=["full_str"])
        .with_columns(
            [
                pl.col("full_str")
                .str.slice(colspec[0], colspec[1] - colspec[0])
                .str.strip_chars()
                .replace("", None)
                .cast(schema.get(col, pl.String))
                .alias(col)
                for colspec, col in zip(colspecs, cols)
            ]
        )
        .drop("full_str")
    )

    for col in ["bias_start", "bias_end"]:
        lf = (
            lf.with_columns(pl.col(col).str.split(":").alias("parts"))
            .with_columns(
                pl.col("parts").list.get(0).alias("year"),
                pl.col("parts").list.get(1).alias("doy"),
                pl.col("parts").list.get(2).cast(pl.Int64).alias("sod"),
            )
            .with_columns(
                pl.concat_str(pl.col("year"), pl.lit("-"), pl.col("doy"))
                .str.strptime(pl.Date, "%Y-%j")
                .cast(pl.Datetime)
                .add(pl.col("sod") * pl.duration(seconds=1))
                .alias(col)
            )
            .drop("parts", "year", "doy", "sod")
        )

    descriptors = {}
    for line in lines[:header_marker_idx]:
        parts = line.split()
        if parts and parts[0] in {"TIME_SYSTEM", "BIAS_MODE", "DETERMINATION_METHOD"}:
            descriptors[parts[0]] = " ".join(parts[1:])
    if descriptors.get("TIME_SYSTEM") != "G":
        raise ValueError(
            "Only Bias-SINEX TIME_SYSTEM G (GPS) is supported; metadata is required."
        )
    return lf.with_columns(
        pl.lit(descriptors["TIME_SYSTEM"]).alias("time_system"),
        pl.lit(descriptors.get("BIAS_MODE")).alias("bias_mode"),
        pl.lit(descriptors.get("DETERMINATION_METHOD")).alias("determination_method"),
    )


def read_bias(fn: str | Path | Iterable[str | Path]) -> pl.LazyFrame:
    """Read GNSS bias products into a lazy table.

    Parameters
    ----------
    fn : str, Path, or iterable of str or Path
        Bias product files, including supported compressed inputs.

    Returns
    -------
    polars.LazyFrame
        Decoded bias records and product metadata. TEC code-bias
        preparation separately validates DSB/ns/GPS semantics and
        half-open validity intervals before applying corrections.

    Raises
    ------
    FileNotFoundError
        If a bias file does not exist.
    TypeError
        If fn is not a path or iterable of paths.
    """
    if isinstance(fn, (str, Path)):
        fn_list = [str(fn)]
    elif isinstance(fn, Iterable):
        fn_list = [str(f) for f in fn]
    else:
        raise TypeError("fn must be a str, Path, or Iterable of str/Path.")

    for f in fn_list:
        if not Path(f).exists():
            raise FileNotFoundError(f"Bias file not found: {f}")

    return pl.concat([_read_bias_file(f) for f in fn_list])
