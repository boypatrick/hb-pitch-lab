# Target only, not proof of timing closure. Add I/O and cross-tier timing constraints.
create_clock -name core_clk -period 4 [get_ports clk]
