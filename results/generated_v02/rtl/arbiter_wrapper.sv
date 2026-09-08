module arbiter_wrapper(
    input wire clk,
    input wire rst,
    input wire [3:0] request,
    input wire advance,
    output wire [3:0] grant,
    output wire grant_valid,
    output wire [1:0] grant_index
);
    rr_arbiter #(.PORTS(4)) u_impl (.clk(clk), .rst(rst), .request(request), .advance(advance), .grant(grant), .grant_valid(grant_valid), .grant_index(grant_index));
endmodule
