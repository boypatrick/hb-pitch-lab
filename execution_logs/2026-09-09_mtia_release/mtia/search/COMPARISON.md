# MTIA-like architecture comparison

Suite latency/energy are summed; power is energy/time; Tmax is max of per-workload steady cell means. Uncalibrated.

Cost quality: synthetic; selected: 83955264838cf9517b7bd7b068a2368e7b5b9c5db082d4a5f4ff48134287dd80
Raw: 13; geometry feasible: 10; eligible: 10; Pareto: 1

Minimum cycles among geometrically feasible widths. This table is not the PPA policy selection.

| Workload | Partition | Pitch µm | Width bits | Cycles |
|---|---|---:|---:|---:|
| local_supply | 2d | 0 | 128 | 91 |
| local_supply | coarse | 8 | 64 | 254 |
| local_supply | coarse | 4 | 64 | 254 |
| local_supply | coarse | 2 | 64 | 254 |
| local_supply | local_scratch | 8 | 16 | 322 |
| local_supply | local_scratch | 4 | 64 | 226 |
| local_supply | local_scratch | 2 | 128 | 210 |
| hbm_limited | 2d | 0 | 128 | 10036 |
| hbm_limited | coarse | 8 | 64 | 10043 |
| hbm_limited | coarse | 4 | 64 | 10043 |
| hbm_limited | coarse | 2 | 64 | 10043 |
| hbm_limited | local_scratch | 8 | 16 | 10267 |
| hbm_limited | local_scratch | 4 | 64 | 10171 |
| hbm_limited | local_scratch | 2 | 128 | 10155 |
| nic_limited | 2d | 0 | 128 | 8234 |
| nic_limited | coarse | 8 | 64 | 8395 |
| nic_limited | coarse | 4 | 64 | 8395 |
| nic_limited | coarse | 2 | 64 | 8395 |
| nic_limited | local_scratch | 8 | 16 | 8234 |
| nic_limited | local_scratch | 4 | 16 | 8234 |
| nic_limited | local_scratch | 2 | 16 | 8234 |
| embedding | 2d | 0 | 128 | 103 |
| embedding | coarse | 8 | 64 | 237 |
| embedding | coarse | 4 | 64 | 237 |
| embedding | coarse | 2 | 64 | 237 |
| embedding | local_scratch | 8 | 16 | 340 |
| embedding | local_scratch | 4 | 64 | 244 |
| embedding | local_scratch | 2 | 128 | 228 |
| vector | 2d | 0 | 128 | 111 |
| vector | coarse | 8 | 64 | 245 |
| vector | coarse | 4 | 64 | 245 |
| vector | coarse | 2 | 64 | 245 |
| vector | local_scratch | 8 | 16 | 348 |
| vector | local_scratch | 4 | 64 | 252 |
| vector | local_scratch | 2 | 128 | 237 |

2D uses ideal direct same-die wires. No physical routing, FPGA/ASIC frequency or vendor speedup is inferred.
