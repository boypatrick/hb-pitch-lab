module scratch_wrapper(
    input wire clk,
    input wire rst,
    input wire [3:0] req_valid,
    input wire [3:0] write_enable,
    input wire [19:0] address,
    input wire [255:0] write_data,
    output wire [3:0] read_valid,
    output wire [255:0] read_data
);
    banked_sram #(.BANKS(4), .DATA_W(64), .DEPTH(32)) u_impl (.clk(clk), .rst(rst), .req_valid(req_valid), .write_enable(write_enable), .address(address), .write_data(write_data), .read_valid(read_valid), .read_data(read_data));
endmodule
