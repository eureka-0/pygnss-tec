# RINEX Observations

PyGNSS-TEC supports reading RINEX v2.x and v3.x observation files, including Hatanaka-compressed and gzip files.
Use `read_rinex_obs` to read observations and return a `RinexObsHeader` object and a Polars LazyFrame.
To calculate navigation geometry and TEC, use the functions described in [TEC Calculation](tec-calculation.md).
Use `read_rinex_nav` to load broadcast navigation separately and reuse it across geometry calculations.

## Read observations

Read an observation file and inspect its header, available columns and first rows:

```python
import gnss_tec as gt

obs = "data/rinex_obs_v3/CIBG00IDN_R_20240100000_01D_30S_MO.crx.gz"
header, observations = gt.read_rinex_obs(obs)

print(header)
print(observations.collect_schema())
print(observations.collect(engine="in-memory").head())
```

The reader decodes the RINEX files before returning the LazyFrame.
Collecting the LazyFrame evaluates the remaining Polars operations; it does not defer file decoding or limit the memory used to read the source files.

You can pass a list of file paths to combine observations from the same station and RINEX major version.
Use `station` to override the station identifier and `constellations` to select the constellation letters to read.
Observation reading supports more constellations than the GPS/BeiDou TEC calculation workflow.

## Layout and types

By default, `pivot=True` returns a wide table with one column per observation code.
Use `collect_schema()` to check which codes are available in your input:

| Fields | Polars dtype | Meaning |
|---|---|---|
| `time` | `Datetime('ns', 'UTC')` | UTC epochs; `utc=False` returns timezone-naive GPS epochs. |
| `station`, `prn` | `Categorical` | Station and satellite identifiers. |
| Codes such as `C2I`, `L2I` | `Float64` | Values in the original RINEX observation units. |
| `<code>_lli`, when requested | `UInt8` | Original lock indicators, preserving nulls and version-specific bits. |
| `epoch_flag` | `UInt8` | Original RINEX epoch flag, independent of LLI retention. |

Set `pivot=False` to return a long table, with individual observations stored in `code` (`String`) and `value` (`Float64`).
If LLI is requested, this layout also includes an `lli` (`UInt8`) column.
Use the wide layout for TEC calculation.

## Select observation codes

Use `codes` to select observation codes by name or regular expression.
It accepts a single expression or an iterable of expressions, with case-sensitive matching against the complete observation code.
When multiple expressions are supplied, observations matching any expression are included.
Invalid expressions raise `ValueError`; an empty selection or no matches returns an empty frame.

For example, read `C1C` and the matching L1/L2 phase observations in long format:

```python
header, selected = gt.read_rinex_obs(
    obs,
    codes=["C1C", "L[12].*"],
    pivot=False,
    include_lli=True,
)
print(selected.collect(engine="in-memory").head())
```

You can use `codes="[CL]1.*"` to select code and phase observations on band 1.
For TEC calculation, keep complete code and phase pairs on both selected frequencies.

## Retain lock indicators

By default, `include_lli=False` omits LLI buffers and columns in both layouts.
Set `include_lli=True` to retain the raw lock indicator for each selected observation.
This option leaves observation values, row keys, epoch flags and header metadata unchanged.
It controls the returned LLI data; the reader still reads the full source file and parses its inline indicators.

Include LLI when preparing a DataFrame or Parquet file if TEC calculation needs the recorded lock and half-cycle information for QC.
The direct RINEX-to-TEC function enables this option automatically.
LLI omitted from a saved table cannot be reconstructed later.
See [quality and continuity](scientific-conventions.md#quality-and-continuity) for how these indicators are used.

## Header and event metadata

The header stores receiver coordinates, receiver identity and timestamped special events.
`receiver_history` records each file's first UTC epoch, original ECEF coordinates and receiver identity.
Use `header.to_metadata()` to preserve this information when [saving observations to Parquet](tec-calculation.md#cache-observations-in-parquet).

Observation values come from records with epoch flags 0 or 1.
Timestamped flag-6 payloads are stored as event metadata and cannot overwrite observations.
Special records with blank epoch fields are read and omitted, without inheriting timestamps or changing receiver state.
Header-update events are retained, but their new values are not applied to later observations.
Dynamic header updates and satellite/phase-specific flag-6 interpretation remain planned work.

## Read navigation

Read RINEX 2/3 broadcast navigation, including gzip files:

```python
navigation = gt.read_rinex_nav(
    "data/rinex_nav_v3/BRDC00IGS_R_20240100000_01D_MN.rnx.gz",
    constellations="CG",
)
print(navigation)
print(navigation.satellites)
```

The result is a read-only `NavigationData` object containing native ephemerides and per-satellite indexes.
Reading and indexing finish before return, and later calculations do not need the source files to remain available.
Multiple files are merged in sorted path order; `constellations=None` retains all parsed constellations.
The object exposes source paths, constellation/satellite identifiers, the retained ephemeris count and the reference-epoch range in UTC Unix nanoseconds.
This range describes reference epochs, not a guarantee of valid navigation coverage.
SBAS records can be read, but SBAS propagation is not implemented and produces unavailable geometry.
The object supports reuse within one process; it is not a DataFrame or a lossless navigation-file editing format.

See the [I/O API](../api/io.md) for function parameters, header fields and serialization methods.
