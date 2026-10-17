# Quick Start

## Install

Use Python 3.12 or later.
Create a project with [uv](https://docs.astral.sh/uv/) and install the latest published package:

```bash
uv init --python 3.14 tec-example
cd tec-example
uv add pygnss-tec
```

Alternatively, install the package with pip:

```bash
pip install pygnss-tec
```

Building from source requires Python 3.12 or later, Rust 1.88 or later (including Cargo), and uv:

```bash
git clone https://github.com/Eureka-0/pygnss-tec.git
cd pygnss-tec
uv sync
uv run maturin build --release
```

The built wheel is available in `target/wheels/`.

## Read RINEX and bias files

Read a RINEX observation file (supports RINEX v2.x, v3.x, and Hatanaka compressed files):

```python
import gnss_tec as gt

# Header contains RINEX header information; lf is a Polars LazyFrame.
header, lf = gt.read_rinex_obs(
    "data/rinex_obs_v3/CIBG00IDN_R_20240100000_01D_30S_MO.crx.gz"
)

# Collect the LazyFrame into a Polars DataFrame if needed.
df = lf.collect(engine="in-memory")
```

To calculate angles separately, load navigation with `read_rinex_nav` and call `compute_az_el(observations, header, navigation)`.
See [the separate-angle workflow](guide/tec-calculation.md#calculate-angles-separately) for preparing observations with LLI and passing them to `compute_tec`.

You can save the DataFrame to a Parquet file for later use:

```python
# Save the LazyFrame to a Parquet file.
lf.sink_parquet("rinex_obs.parquet")

# Save the collected DataFrame to a Parquet file.
df.write_parquet("rinex_obs.parquet")
```

Read a bias file (supports IGS and CAS DCB products):

```python
import gnss_tec as gt

lf = gt.read_bias(
    "data/bias/CAS0OPSRAP_20240100000_01D_01D_DCB.BIA.gz"
)

# Collect the LazyFrame into a Polars DataFrame if needed.
df = lf.collect(engine="in-memory")
```

## Calculate and calibrate TEC

Obtain calibrated TEC from RINEX observation, navigation and optional bias files:

```python
import gnss_tec as gt

tec_lf = gt.compute_tec_from_rinex(
    "data/rinex_obs_v3/CIBG00IDN_R_20240100000_01D_30S_MO.crx.gz",
    "data/rinex_nav_v3/BRDC00IGS_R_20240100000_01D_MN.rnx.gz",
    "data/bias/CAS0OPSRAP_20240100000_01D_01D_DCB.BIA.gz",
)

# Collect the LazyFrame into a Polars DataFrame if needed.
tec_df = tec_lf.collect(engine="in-memory")

# Save the LazyFrame to a Parquet file.
tec_lf.sink_parquet("tec.parquet")

# Save the collected DataFrame to a Parquet file.
tec_df.write_parquet("tec.parquet")
```

The output columns include UTC epochs, station/satellite identities, selected signals, receiver/IPP coordinates, azimuth/elevation and TEC values.
The supplied product determines which bias corrections are available.
Inspect [calibration status](guide/scientific-conventions.md#bias-correction-and-calibration) before treating a result as fully calibrated.

## Continue

- [RINEX Observations](guide/rinex.md): read raw data, select codes and retain LLI.
- [TEC Calculation](guide/tec-calculation.md): use existing tables, cache Parquet and select diagnostics.
- [Configuration](guide/configuration.md): choose signal priorities, calibration and processing modes.
