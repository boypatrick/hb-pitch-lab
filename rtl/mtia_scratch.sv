// LANES byte banks, each with 2 synchronous read ports and 1 DMA write port.
// Read-during-write returns the OLD word. No memory reset; load before use.
module mtia_scratch #(
    parameter integer LANES=8, ROWS=64, AW=$clog2(ROWS)
)(
    input wire clk,rst,
    input wire wr_valid, input wire [AW-1:0] wr_addr,
    input wire [LANES*8-1:0] wr_data,
    input wire req_valid, output wire req_ready,
    input wire [2*AW-1:0] req_data,
    output reg rsp_valid, input wire rsp_ready,
    output wire [LANES*16-1:0] rsp_data
);
    assign req_ready=!rsp_valid;
    always @(posedge clk) begin
        if(rst) rsp_valid<=0;
        else begin
            if(rsp_valid && rsp_ready) rsp_valid<=0;
            if(req_valid && req_ready) rsp_valid<=1;
        end
    end
    genvar l;
    generate for(l=0;l<LANES;l=l+1) begin: bank
        reg [7:0] mem[0:ROWS-1];
        reg [7:0] a,b;
        assign rsp_data[l*8 +: 8]=a;
        assign rsp_data[LANES*8+l*8 +: 8]=b;
        always @(posedge clk) begin
            if(wr_valid && !rst) mem[wr_addr]<=wr_data[l*8 +: 8];
            if(req_valid && req_ready && !rst) begin
                a<=mem[req_data[AW-1:0]];
                b<=mem[req_data[2*AW-1:AW]];
            end
        end
    end endgenerate
endmodule
