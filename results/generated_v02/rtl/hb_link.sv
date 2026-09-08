// Digital elastic pipeline only: WIDTH payload wires, valid forward, ready back.
// STAGES>=1, same clock on both ends; no PHY/CDC/pad parasitics in synthesizable RTL.
// At no stalls, latency=STAGES cycles and throughput=one word/cycle.
module hb_link #(
    parameter integer WIDTH=64, STAGES=2
)(
    input wire clk, input wire rst,
    input wire in_valid, output wire in_ready,
    input wire [WIDTH-1:0] in_data,
    output wire out_valid, input wire out_ready,
    output wire [WIDTH-1:0] out_data
);
    reg [STAGES-1:0] valid;
    reg [WIDTH-1:0] payload [0:STAGES-1];
    wire [STAGES:0] ready;
    assign ready[STAGES]=out_ready;
    assign in_ready=ready[0];
    assign out_valid=valid[STAGES-1];
    assign out_data=payload[STAGES-1];
    genvar s;
    generate for(s=0;s<STAGES;s=s+1) begin:g_stage
        assign ready[s]=!valid[s] || ready[s+1];
        if(s==0) begin:g_first
            always @(posedge clk) begin
                if(rst) begin valid[s]<=0; payload[s]<=0; end
                else if(ready[s]) begin
                    valid[s]<=in_valid;
                    if(in_valid) payload[s]<=in_data;
                end
            end
        end else begin:g_other
            always @(posedge clk) begin
                if(rst) begin valid[s]<=0; payload[s]<=0; end
                else if(ready[s]) begin
                    valid[s]<=valid[s-1];
                    if(valid[s-1]) payload[s]<=payload[s-1];
                end
            end
        end
    end endgenerate
endmodule
