# Frozen RTL candidate

Point: 72226b2baaccf4a9eb49fb125abc936670159da7617b2a642e1cd094d091cdbc

Use files.f or check_lab_system_top.ys from this directory. Each parameter is frozen in an instance wrapper.

lab_system_top replicates tile benchmarks; it is not a programmable GPU. lab_tier0/1_top are per-tile partition views.
Only explicitly declared ready/valid edges are connected. All remaining module ports are exposed for a driver/testbench.
HB pitch/tier assignment are physical metadata, not logic parameters. Generated clock.sdc needs I/O and cross-die constraints.
Memories are generic inferred RTL, not mapped SRAM macros. MACs are signed integers with wrapping accumulation.
