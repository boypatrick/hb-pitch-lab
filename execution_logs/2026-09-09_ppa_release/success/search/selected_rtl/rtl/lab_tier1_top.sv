module lab_tier1_top(
    input wire clk,
    input wire rst,
    input wire [3:0] scratch_req_valid,
    input wire [3:0] scratch_write_enable,
    input wire [19:0] scratch_address,
    input wire [255:0] scratch_write_data,
    output wire [3:0] scratch_read_valid,
    output wire [255:0] scratch_read_data,
    input wire queue_in_valid,
    output wire queue_in_ready,
    input wire [63:0] queue_in_data,
    output wire queue_out_valid,
    input wire queue_out_ready,
    output wire [63:0] queue_out_data,
    input wire [3:0] arbiter_request,
    input wire arbiter_advance,
    output wire [3:0] arbiter_grant,
    output wire arbiter_grant_valid,
    output wire [1:0] arbiter_grant_index
);
    scratch_wrapper u_scratch (.clk(clk), .rst(rst), .req_valid(scratch_req_valid), .write_enable(scratch_write_enable), .address(scratch_address), .write_data(scratch_write_data), .read_valid(scratch_read_valid), .read_data(scratch_read_data));
    queue_wrapper u_queue (.clk(clk), .rst(rst), .in_valid(queue_in_valid), .in_ready(queue_in_ready), .in_data(queue_in_data), .out_valid(queue_out_valid), .out_ready(queue_out_ready), .out_data(queue_out_data));
    arbiter_wrapper u_arbiter (.clk(clk), .rst(rst), .request(arbiter_request), .advance(arbiter_advance), .grant(arbiter_grant), .grant_valid(arbiter_grant_valid), .grant_index(arbiter_grant_index));
endmodule
