module queue_wrapper(
    input wire clk,
    input wire rst,
    input wire in_valid,
    output wire in_ready,
    input wire [63:0] in_data,
    output wire out_valid,
    input wire out_ready,
    output wire [63:0] out_data
);
    stream_fifo #(.WIDTH(64), .DEPTH(4)) u_impl (.clk(clk), .rst(rst), .in_valid(in_valid), .in_ready(in_ready), .in_data(in_data), .out_valid(out_valid), .out_ready(out_ready), .out_data(out_data));
endmodule
