module lab_tile_top(
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
    input wire [3:0] scratch_req_valid,
    input wire [3:0] scratch_write_enable,
    input wire [19:0] scratch_address,
    input wire [255:0] scratch_write_data,
    output wire [3:0] scratch_read_valid,
    output wire [255:0] scratch_read_data,
    input wire [3:0] rf_write_enable,
    input wire [15:0] rf_write_address,
    input wire [127:0] rf_write_data,
    input wire [15:0] rf_read_address_a,
    input wire [15:0] rf_read_address_b,
    output wire [127:0] rf_read_data_a,
    output wire [127:0] rf_read_data_b,
    input wire queue_in_valid,
    output wire queue_in_ready,
    input wire [127:0] queue_in_data,
    output wire link_out_valid,
    input wire link_out_ready,
    output wire [127:0] link_out_data,
    input wire [3:0] arbiter_request,
    input wire arbiter_advance,
    output wire [3:0] arbiter_grant,
    output wire arbiter_grant_valid,
    output wire [1:0] arbiter_grant_index
);
    wire [127:0] n_queue_to_link_data;
    wire n_queue_to_link_valid;
    wire n_queue_to_link_ready;
    tensor_wrapper u_tensor (.clk(clk), .rst(rst), .in_valid(tensor_in_valid), .in_ready(tensor_in_ready), .clear(tensor_clear), .last(tensor_last), .a_data(tensor_a_data), .b_data(tensor_b_data), .out_valid(tensor_out_valid), .out_ready(tensor_out_ready), .out_data(tensor_out_data));
    scratch_wrapper u_scratch (.clk(clk), .rst(rst), .req_valid(scratch_req_valid), .write_enable(scratch_write_enable), .address(scratch_address), .write_data(scratch_write_data), .read_valid(scratch_read_valid), .read_data(scratch_read_data));
    rf_wrapper u_rf (.clk(clk), .rst(rst), .write_enable(rf_write_enable), .write_address(rf_write_address), .write_data(rf_write_data), .read_address_a(rf_read_address_a), .read_address_b(rf_read_address_b), .read_data_a(rf_read_data_a), .read_data_b(rf_read_data_b));
    queue_wrapper u_queue (.clk(clk), .rst(rst), .in_valid(queue_in_valid), .in_ready(queue_in_ready), .in_data(queue_in_data), .out_valid(n_queue_to_link_valid), .out_ready(n_queue_to_link_ready), .out_data(n_queue_to_link_data));
    link_wrapper u_link (.clk(clk), .rst(rst), .in_valid(n_queue_to_link_valid), .in_ready(n_queue_to_link_ready), .in_data(n_queue_to_link_data), .out_valid(link_out_valid), .out_ready(link_out_ready), .out_data(link_out_data));
    arbiter_wrapper u_arbiter (.clk(clk), .rst(rst), .request(arbiter_request), .advance(arbiter_advance), .grant(arbiter_grant), .grant_valid(arbiter_grant_valid), .grant_index(arbiter_grant_index));
endmodule
