// Per-lane 2 asynchronous reads / 1 synchronous write. Read-during-write
// observes old data before the active edge, new data after it; no bypass mux.
// No zero-register convention and no reset of contents. Unwritten data is undefined.
module register_file #(
    parameter integer LANES=4, DATA_W=32, DEPTH=32,
    parameter integer ADDR_W=(DEPTH<=1 ? 1 : $clog2(DEPTH))
)(
    input wire clk, input wire rst,
    input wire [LANES-1:0] write_enable,
    input wire [LANES*ADDR_W-1:0] write_address,
    input wire [LANES*DATA_W-1:0] write_data,
    input wire [LANES*ADDR_W-1:0] read_address_a,
    input wire [LANES*ADDR_W-1:0] read_address_b,
    output wire [LANES*DATA_W-1:0] read_data_a,
    output wire [LANES*DATA_W-1:0] read_data_b
);
    genvar lane;
    generate for(lane=0;lane<LANES;lane=lane+1) begin:g_lane
        reg [DATA_W-1:0] mem [0:DEPTH-1];
        wire [ADDR_W-1:0] wa=write_address[lane*ADDR_W +: ADDR_W];
        wire [ADDR_W-1:0] ra=read_address_a[lane*ADDR_W +: ADDR_W];
        wire [ADDR_W-1:0] rb=read_address_b[lane*ADDR_W +: ADDR_W];
        assign read_data_a[lane*DATA_W +: DATA_W]=(ra<DEPTH) ? mem[ra] : {DATA_W{1'b0}};
        assign read_data_b[lane*DATA_W +: DATA_W]=(rb<DEPTH) ? mem[rb] : {DATA_W{1'b0}};
        always @(posedge clk)
            if(!rst && write_enable[lane] && wa<DEPTH)
                mem[wa] <= write_data[lane*DATA_W +: DATA_W];
    end endgenerate
endmodule
