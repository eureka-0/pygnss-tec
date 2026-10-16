# API Reference

The public interface is imported from `gnss_tec`.
These pages are generated from the current source docstrings, including NumPy-style parameter, return and exception sections.
Private modules and native bindings are implementation details.

| Page | Public objects |
|---|---|
| [Input and Output](io.md) | `read_rinex_obs`, `RinexObsHeader`, `read_bias`. |
| [TEC Calculation](tec.md) | `calc_tec_from_rinex`, `calc_tec_from_df`, `calc_tec_from_parquet`. |
| [Configuration](configuration.md) | `TECConfig`, `DIAGNOSTIC_COLUMNS`, `SUPPORTED_CONSTELLATIONS`, `SUPPORTED_RINEX_VERSIONS`. |

For runnable workflows, start with [Quick Start](../quick-start.md) or the [guides](../guide/index.md).
Scientific meanings and limitations are described in [Scientific Conventions](../guide/scientific-conventions.md).
