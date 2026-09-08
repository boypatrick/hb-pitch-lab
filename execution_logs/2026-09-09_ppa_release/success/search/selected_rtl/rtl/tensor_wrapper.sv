module tensor_wrapper(
    input wire clk,
    input wire rst,
    input wire in_valid,
    output wire in_ready,
    input wire clear,
    input wire last,
    input wire [63:0] a_data,
    input wire [31:0] b_data,
    output wire out_valid,
    input wire out_ready,
    output wire [1023:0] out_data
);
    int_mac_array #(.ROWS(8), .COLS(4), .DATA_W(8), .ACC_W(32)) u_impl (.clk(clk), .rst(rst), .in_valid(in_valid), .in_ready(in_ready), .clear(clear), .last(last), .a_data(a_data), .b_data(b_data), .out_valid(out_valid), .out_ready(out_ready), .out_data(out_data));
endmodule
