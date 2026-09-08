# Frozen RTL candidate

Point: 442ba61c2ed6b5d4c4e7656b0b0f5c29d704d6c1dff542a291ffec4f2e7112fe

Use files.f or check_lab_system_top.ys from this directory. Each parameter is frozen in an instance wrapper.

lab_system_top replicates tile benchmarks; it is not a programmable GPU. lab_tier0/1_top are per-tile partition views.
Only explicitly declared ready/valid edges are connected. All remaining module ports are exposed for a driver/testbench.
HB pitch/tier assignment are physical metadata, not logic parameters. Generated clock.sdc needs I/O and cross-die constraints.
Memories are generic inferred RTL, not mapped SRAM macros. MACs are signed integers with wrapping accumulation.
