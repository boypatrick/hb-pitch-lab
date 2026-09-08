module rf_wrapper(
    input wire clk,
    input wire rst,
    input wire [3:0] write_enable,
    input wire [15:0] write_address,
    input wire [127:0] write_data,
    input wire [15:0] read_address_a,
    input wire [15:0] read_address_b,
    output wire [127:0] read_data_a,
    output wire [127:0] read_data_b
);
    register_file #(.LANES(4), .DATA_W(32), .DEPTH(16)) u_impl (.clk(clk), .rst(rst), .write_enable(write_enable), .write_address(write_address), .write_data(write_data), .read_address_a(read_address_a), .read_address_b(read_address_b), .read_data_a(read_data_a), .read_data_b(read_data_b));
endmodule
