# Benchmark Results

| Environment | Value |
| --- | --- |
| Measured (UTC) | 2026-10-14T03:42:07+00:00 |
| Platform | macOS-27.0.1-arm64-arm-64bit-Mach-O; 12 logical cores |
| Python / packages | Python 3.14.8; numpy 2.5.4; polars 2.0.0; pyarrow 26.0.0; pygnss-tec 0.4.2; scipy 1.18.1 |
| Polars threads / warm-up / repeats | 12 / 1 / 7 |
| Native SHA-256 | f4935ba9f10aaa300d8b6f43b4cb8d28f014ba15c7f94c7b73c42ac922ffe447 |

## streaming

| Task | Rows | Median (s) | Min–max (s) |
| --- | ---: | ---: | ---: |
| read-v2-DGAR (3.65 MiB) | 81810 | 0.1736 | 0.1696–0.1795 |
| read-and-TEC-v2-DGAR (3.65 MiB) | 10933 | 0.2302 | 0.2254–0.2376 |
| TEC-only-v2-DGAR (3.65 MiB) | 10933 | 0.0289 | 0.0279–0.0308 |
| read-v3-CIBG (14.02 MiB) | 180027 | 0.6370 | 0.6289–0.6537 |
| read-and-TEC-v3-CIBG (14.02 MiB) | 50315 | 0.8772 | 0.8589–0.8974 |
| TEC-only-v3-CIBG (14.02 MiB) | 50315 | 0.0888 | 0.0878–0.0946 |
| read-crx-CIBG (6.05 MiB) | 180027 | 1.1162 | 1.0858–1.1471 |
| read-and-TEC-crx-CIBG (6.05 MiB) | 50315 | 1.3564 | 1.3541–1.4043 |
| TEC-only-crx-CIBG (6.05 MiB) | 50315 | 0.0935 | 0.0872–0.1016 |
| read-crx-BELE (2.34 MiB) | 107287 | 0.4310 | 0.4283–0.4424 |
| read-and-TEC-crx-BELE (2.34 MiB) | 19486 | 0.6223 | 0.6161–0.6364 |
| TEC-only-crx-BELE (2.34 MiB) | 19486 | 0.0570 | 0.0540–0.0645 |
| read-two-days-DGAR (7.38 MiB) | 164055 | 0.3483 | 0.3443–0.3583 |
| read-and-TEC-two-days-DGAR (7.38 MiB) | 21870 | 0.4242 | 0.4210–0.4375 |
| TEC-only-two-days-DGAR (7.38 MiB) | 21870 | 0.0406 | 0.0399–0.0428 |
| read-two-days-POAL (14.04 MiB) | 288628 | 0.8012 | 0.7767–0.8861 |
| read-and-TEC-two-days-POAL (14.04 MiB) | 45702 | 0.9175 | 0.9044–0.9388 |
| TEC-only-two-days-POAL (14.04 MiB) | 45702 | 0.0676 | 0.0625–0.0761 |
| read-two-days-CIBG (11.99 MiB) | 352834 | 2.2084 | 2.1596–2.3561 |
| read-and-TEC-two-days-CIBG (11.99 MiB) | 98242 | 2.7599 | 2.6487–3.3254 |
| TEC-only-two-days-CIBG (11.99 MiB) | 98242 | 0.1759 | 0.1626–0.2888 |
| read-two-days-BELE (4.67 MiB) | 213753 | 0.8467 | 0.8416–0.8525 |
| read-and-TEC-two-days-BELE (4.67 MiB) | 33392 | 1.2582 | 1.2500–1.4500 |
| TEC-only-two-days-BELE (4.67 MiB) | 33392 | 0.1076 | 0.1021–0.1232 |

## in-memory

| Task | Rows | Median (s) | Min–max (s) |
| --- | ---: | ---: | ---: |
| read-v2-DGAR (3.65 MiB) | 81810 | 0.1733 | 0.1719–0.2245 |
| read-and-TEC-v2-DGAR (3.65 MiB) | 10933 | 0.2187 | 0.2148–0.2415 |
| TEC-only-v2-DGAR (3.65 MiB) | 10933 | 0.0225 | 0.0223–0.0233 |
| read-v3-CIBG (14.02 MiB) | 180027 | 0.6292 | 0.6255–0.6695 |
| read-and-TEC-v3-CIBG (14.02 MiB) | 50315 | 0.8744 | 0.8693–0.9079 |
| TEC-only-v3-CIBG (14.02 MiB) | 50315 | 0.0762 | 0.0747–0.0779 |
| read-crx-CIBG (6.05 MiB) | 180027 | 1.1103 | 1.0784–1.1196 |
| read-and-TEC-crx-CIBG (6.05 MiB) | 50315 | 1.3639 | 1.3189–1.4118 |
| TEC-only-crx-CIBG (6.05 MiB) | 50315 | 0.0782 | 0.0761–0.1118 |
| read-crx-BELE (2.34 MiB) | 107287 | 0.4368 | 0.4280–0.4622 |
| read-and-TEC-crx-BELE (2.34 MiB) | 19486 | 0.6219 | 0.6155–0.7144 |
| TEC-only-crx-BELE (2.34 MiB) | 19486 | 0.0519 | 0.0513–0.0540 |
| read-two-days-DGAR (7.38 MiB) | 164055 | 0.3401 | 0.3353–0.3484 |
| read-and-TEC-two-days-DGAR (7.38 MiB) | 21870 | 0.4228 | 0.4164–0.4279 |
| TEC-only-two-days-DGAR (7.38 MiB) | 21870 | 0.0374 | 0.0370–0.0388 |
| read-two-days-POAL (14.04 MiB) | 288628 | 0.8012 | 0.7959–0.8547 |
| read-and-TEC-two-days-POAL (14.04 MiB) | 45702 | 0.9202 | 0.9060–1.0560 |
| TEC-only-two-days-POAL (14.04 MiB) | 45702 | 0.0609 | 0.0598–0.0637 |
| read-two-days-CIBG (11.99 MiB) | 352834 | 2.1764 | 2.1598–2.2248 |
| read-and-TEC-two-days-CIBG (11.99 MiB) | 98242 | 2.7361 | 2.6819–3.0480 |
| TEC-only-two-days-CIBG (11.99 MiB) | 98242 | 0.1345 | 0.1308–0.1566 |
| read-two-days-BELE (4.67 MiB) | 213753 | 0.8468 | 0.8273–0.8843 |
| read-and-TEC-two-days-BELE (4.67 MiB) | 33392 | 1.2959 | 1.2157–1.4160 |
| TEC-only-two-days-BELE (4.67 MiB) | 33392 | 0.0843 | 0.0824–0.0918 |
