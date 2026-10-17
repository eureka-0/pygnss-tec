# API Reference

The public interface is imported from `gnss_tec`.
These pages are generated from the current source docstrings, including NumPy-style parameter, return and exception sections.
Private modules and native bindings are implementation details.

| Page | Public objects |
|---|---|
| [Input and Output](io.md) | `read_rinex_obs`, `RinexObsHeader`, `read_rinex_nav`, `NavigationData`, `read_bias`. |
| [Observation Geometry](geometry.md) | `compute_az_el`. |
| [TEC Calculation](tec.md) | `compute_tec_from_rinex`, `compute_tec`, `compute_tec_from_parquet`. |
| [Configuration](configuration.md) | `TECConfig`, `DIAGNOSTIC_COLUMNS`, `SUPPORTED_CONSTELLATIONS`, `SUPPORTED_RINEX_VERSIONS`. |

For runnable workflows, start with [Quick Start](../quick-start.md) or the [guides](../guide/index.md).
Scientific meanings and limitations are described in [Scientific Conventions](../guide/scientific-conventions.md).
