# Benchmark Results

| Environment | Value |
| --- | --- |
| Measured (UTC) | 2026-10-15T09:25:39+00:00 |
| Platform | macOS-27.0.1-arm64-arm-64bit-Mach-O; 12 logical cores |
| Python / packages | Python 3.14.8; numpy 2.5.4; polars 2.0.0; pyarrow 26.0.0; pygnss-tec 0.4.2; scipy 1.18.1 |
| Polars threads / warm-up / repeats | 12 / 1 / 3 |
| Native SHA-256 | 4df5a4804f6cde7cb93d51bb04f237bd9ebf5a2581fc3e84d386174b987e2a9e |
| TEC cycle-slip policy | repair; batch GF/MW, configured observation projection, LLI enabled |

## streaming

| Task | Rows | Median (s) | Min–max (s) |
| --- | ---: | ---: | ---: |
| read-v2-DGAR (3.65 MiB) | 81810 | 0.1937 | 0.1910–0.1958 |
| read-and-TEC-v2-DGAR (3.65 MiB) | 10933 | 0.2486 | 0.2466–0.2500 |
| TEC-only-v2-DGAR (3.65 MiB) | 10933 | 0.0543 | 0.0483–0.0581 |
| read-v3-CIBG (14.02 MiB) | 180027 | 0.6728 | 0.6604–0.6754 |
| read-and-TEC-v3-CIBG (14.02 MiB) | 50315 | 0.9966 | 0.9888–1.0064 |
| TEC-only-v3-CIBG (14.02 MiB) | 50315 | 0.2904 | 0.2863–0.2949 |
| read-crx-CIBG (6.05 MiB) | 180027 | 2.4644 | 2.2607–2.4654 |
| read-and-TEC-crx-CIBG (6.05 MiB) | 50315 | 2.4603 | 2.4521–2.6476 |
| TEC-only-crx-CIBG (6.05 MiB) | 50315 | 0.3925 | 0.3134–0.7732 |
| read-crx-BELE (2.34 MiB) | 107287 | 0.9768 | 0.9454–0.9876 |
| read-and-TEC-crx-BELE (2.34 MiB) | 19486 | 1.1906 | 1.1821–1.1976 |
| TEC-only-crx-BELE (2.34 MiB) | 19486 | 0.1262 | 0.1258–0.1385 |
| read-two-days-DGAR (7.38 MiB) | 164055 | 0.3888 | 0.3847–0.3893 |
| read-and-TEC-two-days-DGAR (7.38 MiB) | 21870 | 0.4634 | 0.4584–0.4646 |
| TEC-only-two-days-DGAR (7.38 MiB) | 21870 | 0.0720 | 0.0718–0.0725 |
| read-two-days-POAL (14.04 MiB) | 288628 | 0.8515 | 0.8490–0.8524 |
| read-and-TEC-two-days-POAL (14.04 MiB) | 45743 | 1.0203 | 1.0152–1.0245 |
| TEC-only-two-days-POAL (14.04 MiB) | 45743 | 0.1660 | 0.1615–0.1667 |
| read-two-days-CIBG (11.99 MiB) | 352834 | 4.4197 | 4.4025–4.4692 |
| read-and-TEC-two-days-CIBG (11.99 MiB) | 98250 | 5.2569 | 5.1201–5.3808 |
| TEC-only-two-days-CIBG (11.99 MiB) | 98250 | 0.5803 | 0.5556–0.5835 |
| read-two-days-BELE (4.67 MiB) | 213753 | 1.8767 | 1.8585–1.9622 |
| read-and-TEC-two-days-BELE (4.67 MiB) | 33392 | 2.3313 | 2.3225–2.3945 |
| TEC-only-two-days-BELE (4.67 MiB) | 33392 | 0.2607 | 0.2599–0.2690 |

## in-memory

| Task | Rows | Median (s) | Min–max (s) |
| --- | ---: | ---: | ---: |
| read-v2-DGAR (3.65 MiB) | 81810 | 0.1910 | 0.1890–0.1910 |
| read-and-TEC-v2-DGAR (3.65 MiB) | 10933 | 0.2394 | 0.2383–0.2440 |
| TEC-only-v2-DGAR (3.65 MiB) | 10933 | 0.0408 | 0.0405–0.0415 |
| read-v3-CIBG (14.02 MiB) | 180027 | 0.6791 | 0.6587–0.6904 |
| read-and-TEC-v3-CIBG (14.02 MiB) | 50315 | 0.9897 | 0.9851–0.9989 |
| TEC-only-v3-CIBG (14.02 MiB) | 50315 | 0.2434 | 0.2345–0.2481 |
| read-crx-CIBG (6.05 MiB) | 180027 | 2.2827 | 2.2213–2.3108 |
| read-and-TEC-crx-CIBG (6.05 MiB) | 50315 | 2.4664 | 2.4635–2.4718 |
| TEC-only-crx-CIBG (6.05 MiB) | 50315 | 0.2397 | 0.2328–0.2526 |
| read-crx-BELE (2.34 MiB) | 107287 | 0.9208 | 0.8892–1.0116 |
| read-and-TEC-crx-BELE (2.34 MiB) | 19486 | 1.1507 | 1.1381–1.2663 |
| TEC-only-crx-BELE (2.34 MiB) | 19486 | 0.1247 | 0.1211–0.1260 |
| read-two-days-DGAR (7.38 MiB) | 164055 | 0.3864 | 0.3743–0.3975 |
| read-and-TEC-two-days-DGAR (7.38 MiB) | 21870 | 0.4557 | 0.4546–0.4655 |
| TEC-only-two-days-DGAR (7.38 MiB) | 21870 | 0.0691 | 0.0684–0.0700 |
| read-two-days-POAL (14.04 MiB) | 288628 | 0.8382 | 0.8375–0.8470 |
| read-and-TEC-two-days-POAL (14.04 MiB) | 45743 | 1.0531 | 1.0155–1.1855 |
| TEC-only-two-days-POAL (14.04 MiB) | 45743 | 0.1579 | 0.1549–0.1583 |
| read-two-days-CIBG (11.99 MiB) | 352834 | 4.2505 | 4.2209–4.2714 |
| read-and-TEC-two-days-CIBG (11.99 MiB) | 98250 | 4.8988 | 4.8584–4.9024 |
| TEC-only-two-days-CIBG (11.99 MiB) | 98250 | 0.4335 | 0.4335–0.4558 |
| read-two-days-BELE (4.67 MiB) | 213753 | 1.8132 | 1.8041–1.9202 |
| read-and-TEC-two-days-BELE (4.67 MiB) | 33392 | 2.3500 | 2.3453–2.4044 |
| TEC-only-two-days-BELE (4.67 MiB) | 33392 | 0.1997 | 0.1979–0.2004 |
