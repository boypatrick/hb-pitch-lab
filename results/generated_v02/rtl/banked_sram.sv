// Independent single read-or-write ports. Synchronous read, one-cycle response.
// No array reset: unread/unwritten locations are undefined. A write has no
// read response. Out-of-range addresses are ignored. Technology macro binding
// is a later integration step; this file infers generic memories.
module banked_sram #(
    parameter integer BANKS=4, DATA_W=64, DEPTH=32,
    parameter integer ADDR_W=(DEPTH<=1 ? 1 : $clog2(DEPTH))
)(
    input wire clk, input wire rst,
    input wire [BANKS-1:0] req_valid,
    input wire [BANKS-1:0] write_enable,
    input wire [BANKS*ADDR_W-1:0] address,
    input wire [BANKS*DATA_W-1:0] write_data,
    output reg [BANKS-1:0] read_valid,
    output reg [BANKS*DATA_W-1:0] read_data
);
    genvar b;
    generate for(b=0;b<BANKS;b=b+1) begin:g_bank
        reg [DATA_W-1:0] mem [0:DEPTH-1];
        wire [ADDR_W-1:0] addr=address[b*ADDR_W +: ADDR_W];
        always @(posedge clk) begin
            if(rst) begin
                read_valid[b] <= 1'b0;
                read_data[b*DATA_W +: DATA_W] <= 0;
            end else begin
                read_valid[b] <= req_valid[b] && !write_enable[b] && (addr<DEPTH);
                if(req_valid[b] && (addr<DEPTH)) begin
                    if(write_enable[b]) mem[addr] <= write_data[b*DATA_W +: DATA_W];
                    else read_data[b*DATA_W +: DATA_W] <= mem[addr];
                end
            end
        end
    end endgenerate
endmodule
