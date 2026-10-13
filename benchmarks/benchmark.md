# Benchmark Results

| Environment | Value |
| --- | --- |
| Measured (UTC) | 2026-10-13T10:46:25+00:00 |
| Platform | macOS-27.0.1-arm64-arm-64bit-Mach-O; 12 logical cores |
| Python / packages | Python 3.14.8; numpy 2.5.4; polars 2.0.0; pyarrow 26.0.0; pygnss-tec 0.4.2; scipy 1.18.1 |
| Polars threads / warm-up / repeats | 12 / 1 / 7 |
| Native SHA-256 | f443c810a80b43db77e780ef4eb18b1a2280a91436f3bfa02db9f8bd22054de7 |

## streaming

| Task | Rows | Median (s) | Min–max (s) |
| --- | ---: | ---: | ---: |
| read-v2-DGAR (3.65 MiB) | 81810 | 0.1783 | 0.1731–0.1810 |
| read-and-TEC-v2-DGAR (3.65 MiB) | 10933 | 0.2212 | 0.2210–0.2229 |
| TEC-only-v2-DGAR (3.65 MiB) | 10933 | 0.0275 | 0.0266–0.0290 |
| read-v3-CIBG (14.02 MiB) | 180027 | 0.6862 | 0.6644–0.7605 |
| read-and-TEC-v3-CIBG (14.02 MiB) | 50315 | 0.8785 | 0.8705–0.8968 |
| TEC-only-v3-CIBG (14.02 MiB) | 50315 | 0.0930 | 0.0897–0.0977 |
| read-crx-CIBG (6.05 MiB) | 180027 | 1.1244 | 1.1168–1.1412 |
| read-and-TEC-crx-CIBG (6.05 MiB) | 50315 | 1.3389 | 1.3259–1.3505 |
| TEC-only-crx-CIBG (6.05 MiB) | 50315 | 0.0917 | 0.0889–0.0945 |
| read-crx-BELE (2.34 MiB) | 107287 | 0.4313 | 0.4295–0.5241 |
| read-and-TEC-crx-BELE (2.34 MiB) | 19486 | 0.6098 | 0.6017–0.6189 |
| TEC-only-crx-BELE (2.34 MiB) | 19486 | 0.0538 | 0.0532–0.0546 |
| read-two-days-DGAR (7.38 MiB) | 164055 | 0.3471 | 0.3457–0.3522 |
| read-and-TEC-two-days-DGAR (7.38 MiB) | 21870 | 0.4225 | 0.4202–0.4271 |
| TEC-only-two-days-DGAR (7.38 MiB) | 21870 | 0.0391 | 0.0379–0.0394 |
| read-two-days-POAL (14.04 MiB) | 288628 | 0.7969 | 0.7910–0.8069 |
| read-and-TEC-two-days-POAL (14.04 MiB) | 45702 | 0.9086 | 0.9054–0.9226 |
| TEC-only-two-days-POAL (14.04 MiB) | 45702 | 0.0639 | 0.0615–0.0651 |
| read-two-days-CIBG (11.99 MiB) | 352834 | 2.2328 | 2.2083–2.2677 |
| read-and-TEC-two-days-CIBG (11.99 MiB) | 98242 | 2.7093 | 2.6883–2.7857 |
| TEC-only-two-days-CIBG (11.99 MiB) | 98242 | 0.1644 | 0.1607–0.1731 |
| read-two-days-BELE (4.67 MiB) | 213753 | 0.8492 | 0.8445–0.8616 |
| read-and-TEC-two-days-BELE (4.67 MiB) | 33392 | 1.2449 | 1.2316–1.2605 |
| TEC-only-two-days-BELE (4.67 MiB) | 33392 | 0.1171 | 0.1076–0.2677 |

## in-memory

| Task | Rows | Median (s) | Min–max (s) |
| --- | ---: | ---: | ---: |
| read-v2-DGAR (3.65 MiB) | 81810 | 0.1713 | 0.1707–0.1718 |
| read-and-TEC-v2-DGAR (3.65 MiB) | 10933 | 0.2168 | 0.2137–0.2180 |
| TEC-only-v2-DGAR (3.65 MiB) | 10933 | 0.0240 | 0.0231–0.0641 |
| read-v3-CIBG (14.02 MiB) | 180027 | 0.6563 | 0.6501–0.6680 |
| read-and-TEC-v3-CIBG (14.02 MiB) | 50315 | 0.8842 | 0.8776–0.9078 |
| TEC-only-v3-CIBG (14.02 MiB) | 50315 | 0.0786 | 0.0766–0.0793 |
| read-crx-CIBG (6.05 MiB) | 180027 | 1.1115 | 1.1093–1.1217 |
| read-and-TEC-crx-CIBG (6.05 MiB) | 50315 | 1.3650 | 1.3377–1.4853 |
| TEC-only-crx-CIBG (6.05 MiB) | 50315 | 0.0808 | 0.0792–0.0900 |
| read-crx-BELE (2.34 MiB) | 107287 | 0.4212 | 0.4199–0.4497 |
| read-and-TEC-crx-BELE (2.34 MiB) | 19486 | 0.6249 | 0.6107–0.6923 |
| TEC-only-crx-BELE (2.34 MiB) | 19486 | 0.0528 | 0.0515–0.0537 |
| read-two-days-DGAR (7.38 MiB) | 164055 | 0.3467 | 0.3445–0.3510 |
| read-and-TEC-two-days-DGAR (7.38 MiB) | 21870 | 0.4238 | 0.4201–0.4280 |
| TEC-only-two-days-DGAR (7.38 MiB) | 21870 | 0.0383 | 0.0372–0.0401 |
| read-two-days-POAL (14.04 MiB) | 288628 | 0.7991 | 0.7934–0.8123 |
| read-and-TEC-two-days-POAL (14.04 MiB) | 45702 | 0.9140 | 0.9102–0.9209 |
| TEC-only-two-days-POAL (14.04 MiB) | 45702 | 0.0626 | 0.0618–0.0636 |
| read-two-days-CIBG (11.99 MiB) | 352834 | 2.2554 | 2.2132–2.3855 |
| read-and-TEC-two-days-CIBG (11.99 MiB) | 98242 | 2.6887 | 2.6825–2.8352 |
| TEC-only-two-days-CIBG (11.99 MiB) | 98242 | 0.1373 | 0.1357–0.1470 |
| read-two-days-BELE (4.67 MiB) | 213753 | 0.8482 | 0.8403–0.8593 |
| read-and-TEC-two-days-BELE (4.67 MiB) | 33392 | 1.2337 | 1.2240–1.2406 |
| TEC-only-two-days-BELE (4.67 MiB) | 33392 | 0.0823 | 0.0814–0.0838 |
