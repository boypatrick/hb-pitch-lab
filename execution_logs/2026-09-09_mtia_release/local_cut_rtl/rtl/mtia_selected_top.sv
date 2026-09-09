module mtia_selected_top(
    input wire clk,
    input wire rst,
    input wire [63:0] load_data,
    input wire [5:0] load_addr,
    input wire load_pe,
    input wire load_valid,
    input wire [95:0] cmd_data,
    input wire [1:0] cmd_valid,
    input wire [15:0] me_count,
    input wire [5:0] me_base,
    input wire me_valid,
    input wire [31:0] nic_data,
    input wire nic_valid,
    input wire out_ready,
    output wire load_ready,
    output wire [1:0] cmd_ready,
    output wire me_ready,
    output wire nic_ready,
    output wire [31:0] out_data,
    output wire out_valid,
    output wire [37:0] wb_data,
    output wire wb_valid,
    output wire wb_ready
);
    mtia_cluster #(
        .PES(2), .LANES(8), .ROWS(64), .ENTRIES(64), .CUT(2), .HB_BITS(128), .COARSE_BITS(64), .STAGES(1)
    ) cluster (.*);
endmodule
