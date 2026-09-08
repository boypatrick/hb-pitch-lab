// Ready/valid synchronous FIFO, arbitrary positive DEPTH. Supports simultaneous
// pop/push at full occupancy. No fall-through when empty; synchronous reset.
module stream_fifo #(
    parameter integer WIDTH=64, DEPTH=4,
    parameter integer PTR_W=(DEPTH<=1 ? 1 : $clog2(DEPTH)),
    parameter integer COUNT_W=$clog2(DEPTH+1)
)(
    input wire clk, input wire rst,
    input wire in_valid, output wire in_ready,
    input wire [WIDTH-1:0] in_data,
    output wire out_valid, input wire out_ready,
    output wire [WIDTH-1:0] out_data
);
    reg [WIDTH-1:0] mem [0:DEPTH-1];
    reg [PTR_W-1:0] rd_ptr,wr_ptr;
    reg [COUNT_W-1:0] count;
    wire push=in_valid && in_ready;
    wire pop=out_valid && out_ready;
    assign out_valid=(count!=0);
    assign in_ready=(count<DEPTH) || pop;
    assign out_data=mem[rd_ptr];
    always @(posedge clk) begin
        if(rst) begin rd_ptr<=0; wr_ptr<=0; count<=0; end
        else begin
            if(push) begin
                mem[wr_ptr]<=in_data;
                wr_ptr<=(wr_ptr==DEPTH-1) ? 0 : wr_ptr+1'b1;
            end
            if(pop) rd_ptr<=(rd_ptr==DEPTH-1) ? 0 : rd_ptr+1'b1;
            case({push,pop})
                2'b10: count<=count+1'b1;
                2'b01: count<=count-1'b1;
                default: count<=count;
            endcase
        end
    end
endmodule
