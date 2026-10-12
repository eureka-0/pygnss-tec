# Benchmark Results

Python 3.14.8; macOS-27.0.1-arm64-arm-64bit-Mach-O; 12 logical CPU cores.
Dependencies: {"numpy": "2.5.3", "polars": "2.0.0", "pyarrow": "26.0.0", "pygnss-tec": "0.4.2", "scipy": "1.18.1"}.
Polars threads: 12; warm-up runs per engine/task: 1; measured runs per engine/task: 7.
Measured at 2026-10-09T09:38:44+00:00; native extension SHA-256: eea7ecbe79ba393b2362bc3797f5829d15237e02a938c4671f00801cd7d63889.

This historical engine comparison predates the raw-reader API and current quality-control implementation. Its Read stage includes navigation parsing and satellite azimuth/elevation calculation; TEC-only starts with observations and geometry already in memory. In the current `bench.py`, Read decodes raw observations, Read-and-TEC also prepares navigation/geometry, and TEC-only starts with prepared resident geometry. The reader-boundary comparison below uses the current scientific implementation.
RINEX 2 uses no DCB correction: the supplied CAS files do not contain matching C1/C2 biases. RINEX 3 uses external CAS DCBs. Empty outputs fail the benchmark.
Task sizes are the total on-disk observation file sizes, excluding navigation and bias files. For TEC-only, they refer to the source files rather than DataFrame memory usage.
Both engines run serially with alternating measurement order. Each task's final results are compared outside timing: identities, dtypes, null masks and numerical values (rel_tol=0, abs_tol=1e-8).

## streaming

| Task | Rows | Median (s) | Min–max (s) |
| --- | ---: | ---: | ---: |
| read-v2-DGAR (3.65 MiB) | 81810 | 0.1620 | 0.1569–0.1853 |
| read-and-TEC-v2-DGAR (3.65 MiB) | 10933 | 0.1850 | 0.1785–0.2113 |
| TEC-only-v2-DGAR (3.65 MiB) | 10933 | 0.0247 | 0.0238–0.0254 |
| read-v3-CIBG (14.02 MiB) | 180027 | 0.7654 | 0.7440–0.7906 |
| read-and-TEC-v3-CIBG (14.02 MiB) | 50147 | 0.7763 | 0.7687–0.8159 |
| TEC-only-v3-CIBG (14.02 MiB) | 50147 | 0.0602 | 0.0591–0.0830 |
| read-crx-CIBG (6.05 MiB) | 180027 | 1.3070 | 1.2870–1.3497 |
| read-and-TEC-crx-CIBG (6.05 MiB) | 50147 | 1.3802 | 1.3243–1.4106 |
| TEC-only-crx-CIBG (6.05 MiB) | 50147 | 0.0612 | 0.0599–0.0626 |
| read-crx-BELE (2.34 MiB) | 107287 | 0.5710 | 0.5626–0.5882 |
| read-and-TEC-crx-BELE (2.34 MiB) | 18892 | 0.6135 | 0.5999–0.7027 |
| TEC-only-crx-BELE (2.34 MiB) | 18892 | 0.0464 | 0.0456–0.0478 |
| read-two-days-DGAR (7.38 MiB) | 164055 | 0.3297 | 0.3243–0.3445 |
| read-and-TEC-two-days-DGAR (7.38 MiB) | 21870 | 0.3688 | 0.3605–0.3714 |
| TEC-only-two-days-DGAR (7.38 MiB) | 21870 | 0.0323 | 0.0314–0.0356 |
| read-two-days-POAL (14.04 MiB) | 288628 | 0.7071 | 0.7029–0.7340 |
| read-and-TEC-two-days-POAL (14.04 MiB) | 44116 | 0.7370 | 0.7310–0.7434 |
| TEC-only-two-days-POAL (14.04 MiB) | 44116 | 0.0393 | 0.0386–0.0409 |
| read-two-days-CIBG (11.99 MiB) | 352834 | 2.8676 | 2.8364–2.9283 |
| read-and-TEC-two-days-CIBG (11.99 MiB) | 97883 | 2.9899 | 2.9729–3.0673 |
| TEC-only-two-days-CIBG (11.99 MiB) | 97883 | 0.1177 | 0.1165–0.1183 |
| read-two-days-BELE (4.67 MiB) | 213753 | 1.4974 | 1.4655–1.5082 |
| read-and-TEC-two-days-BELE (4.67 MiB) | 32798 | 1.4974 | 1.4873–1.5299 |
| TEC-only-two-days-BELE (4.67 MiB) | 32798 | 0.0687 | 0.0679–0.0988 |

## in-memory

| Task | Rows | Median (s) | Min–max (s) |
| --- | ---: | ---: | ---: |
| read-v2-DGAR (3.65 MiB) | 81810 | 0.1610 | 0.1537–0.1637 |
| read-and-TEC-v2-DGAR (3.65 MiB) | 10933 | 0.1803 | 0.1753–0.1854 |
| TEC-only-v2-DGAR (3.65 MiB) | 10933 | 0.0179 | 0.0172–0.0182 |
| read-v3-CIBG (14.02 MiB) | 180027 | 0.7488 | 0.7404–0.7798 |
| read-and-TEC-v3-CIBG (14.02 MiB) | 50147 | 0.7939 | 0.7773–0.8404 |
| TEC-only-v3-CIBG (14.02 MiB) | 50147 | 0.0516 | 0.0499–0.0526 |
| read-crx-CIBG (6.05 MiB) | 180027 | 1.2899 | 1.2673–1.3169 |
| read-and-TEC-crx-CIBG (6.05 MiB) | 50147 | 1.3561 | 1.3421–1.3627 |
| TEC-only-crx-CIBG (6.05 MiB) | 50147 | 0.0509 | 0.0498–0.0531 |
| read-crx-BELE (2.34 MiB) | 107287 | 0.5596 | 0.5571–0.5769 |
| read-and-TEC-crx-BELE (2.34 MiB) | 18892 | 0.5964 | 0.5886–0.6252 |
| TEC-only-crx-BELE (2.34 MiB) | 18892 | 0.0364 | 0.0353–0.0378 |
| read-two-days-DGAR (7.38 MiB) | 164055 | 0.3333 | 0.3315–0.3457 |
| read-and-TEC-two-days-DGAR (7.38 MiB) | 21870 | 0.3592 | 0.3503–0.3795 |
| TEC-only-two-days-DGAR (7.38 MiB) | 21870 | 0.0248 | 0.0245–0.0279 |
| read-two-days-POAL (14.04 MiB) | 288628 | 0.7216 | 0.7033–0.7397 |
| read-and-TEC-two-days-POAL (14.04 MiB) | 44116 | 0.7276 | 0.7261–0.7692 |
| TEC-only-two-days-POAL (14.04 MiB) | 44116 | 0.0325 | 0.0320–0.0334 |
| read-two-days-CIBG (11.99 MiB) | 352834 | 2.9015 | 2.8142–2.9716 |
| read-and-TEC-two-days-CIBG (11.99 MiB) | 97883 | 2.9996 | 2.9497–3.0514 |
| TEC-only-two-days-CIBG (11.99 MiB) | 97883 | 0.1023 | 0.1010–0.1032 |
| read-two-days-BELE (4.67 MiB) | 213753 | 1.4145 | 1.4030–1.5327 |
| read-and-TEC-two-days-BELE (4.67 MiB) | 32798 | 1.4589 | 1.4533–1.4872 |
| TEC-only-two-days-BELE (4.67 MiB) | 32798 | 0.0501 | 0.0463–0.0536 |

## Raw reader and internal geometry comparison (2026-10-12)

This comparison isolates the reader/TEC boundary change from the [completed scientific correctness tasks](../docs/roadmap-history.md#completed-scientific-correctness-tasks). The reference uses the pre-change reader and TEC source snapshot, rebuilt as a separate release extension with the same Cargo.lock. The new path reads raw observations and supplies nav_fn to TEC. Both use Python 3.14.8, Polars 2.0.0, PyArrow 26.0.0, 12 threads and the in-memory engine, with one warmup and seven serial repetitions in separate processes.

Input: CIBG00IDN_R_20240100000_01D_30S_MO.rnx.gz, GPS/BeiDou, all observation codes (101,663 epoch/satellite rows), BRDC00IGS_R_20240100000_01D_MN.rnx.gz navigation and CAS0OPSRAP_20240100000_01D_01D_DCB.BIA.gz biases. Median elapsed times include final collection; the geometry stage decodes observations, propagates satellite positions and calculates angles. Raw-only and geometry stages are measured separately rather than subtracted.

| Work | Previous path (s) | Current path (s) | Change |
| --- | ---: | ---: | ---: |
| Raw observation decoding | 0.7668 | 0.7699 | +0.4% |
| Observation decoding and geometry | 0.8844 | 0.9482 | +7.2% |
| Observation decoding and complete TEC | 1.7504 | 1.8909 | +8.0% |

Satellite ECEF propagation remains Rust; azimuth/elevation remain Python pymap3d.ecef2aer. An additional resident-data comparison measured the angle conversion calls at approximately 4.36/8.92 ms for the previous/current paths. The new call supports per-row receiver positions and returns a Polars struct; its roughly 5 ms increment accounts for only a small part of the end-to-end difference. The new preparation also extracts unique epoch/satellite keys and joins geometry and receiver history. These measurements do not attribute the full difference to any single operation, and they are not a general speedup claim.

All satellite ECEF values are exactly equal. Angles and the 50,315 TEC rows match in identity, dtype, null masks and all 18 shared public columns (rel_tol=0, abs_tol=1e-8). Removed diagnostic/helper columns are excluded from the public-schema comparison.
