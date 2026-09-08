module lab_tier0_top(
    input wire clk,
    input wire rst,
    input wire tensor_in_valid,
    output wire tensor_in_ready,
    input wire tensor_clear,
    input wire tensor_last,
    input wire [63:0] tensor_a_data,
    input wire [31:0] tensor_b_data,
    output wire tensor_out_valid,
    input wire tensor_out_ready,
    output wire [1023:0] tensor_out_data,
    input wire [3:0] rf_write_enable,
    input wire [15:0] rf_write_address,
    input wire [127:0] rf_write_data,
    input wire [15:0] rf_read_address_a,
    input wire [15:0] rf_read_address_b,
    output wire [127:0] rf_read_data_a,
    output wire [127:0] rf_read_data_b,
    input wire link_in_valid,
    output wire link_in_ready,
    input wire [63:0] link_in_data,
    output wire link_out_valid,
    input wire link_out_ready,
    output wire [63:0] link_out_data
);
    tensor_wrapper u_tensor (.clk(clk), .rst(rst), .in_valid(tensor_in_valid), .in_ready(tensor_in_ready), .clear(tensor_clear), .last(tensor_last), .a_data(tensor_a_data), .b_data(tensor_b_data), .out_valid(tensor_out_valid), .out_ready(tensor_out_ready), .out_data(tensor_out_data));
    rf_wrapper u_rf (.clk(clk), .rst(rst), .write_enable(rf_write_enable), .write_address(rf_write_address), .write_data(rf_write_data), .read_address_a(rf_read_address_a), .read_address_b(rf_read_address_b), .read_data_a(rf_read_data_a), .read_data_b(rf_read_data_b));
    link_wrapper u_link (.clk(clk), .rst(rst), .in_valid(link_in_valid), .in_ready(link_in_ready), .in_data(link_in_data), .out_valid(link_out_valid), .out_ready(link_out_ready), .out_data(link_out_data));
endmodule
