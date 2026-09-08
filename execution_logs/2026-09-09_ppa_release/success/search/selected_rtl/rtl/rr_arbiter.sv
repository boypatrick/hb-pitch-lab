// Round-robin selection. advance commits the current grant; callers must keep
// a request asserted until accepted. This is an arbiter, not a full NoC router.
module rr_arbiter #(
    parameter integer PORTS=4,
    parameter integer INDEX_W=(PORTS<=1 ? 1 : $clog2(PORTS))
)(
    input wire clk, input wire rst,
    input wire [PORTS-1:0] request,
    input wire advance,
    output reg [PORTS-1:0] grant,
    output reg grant_valid,
    output reg [INDEX_W-1:0] grant_index
);
    reg [INDEX_W-1:0] next_port;
    integer offset,index;
    always @* begin
        grant=0; grant_valid=0; grant_index=0; index=0;
        for(offset=0;offset<PORTS;offset=offset+1) begin
            index=next_port+offset;
            if(index>=PORTS) index=index-PORTS;
            if(!grant_valid && request[index]) begin
                grant[index]=1'b1; grant_valid=1'b1; grant_index=index;
            end
        end
    end
    always @(posedge clk) begin
        if(rst) next_port<=0;
        else if(advance && grant_valid)
            next_port<=(grant_index==PORTS-1) ? 0 : grant_index+1'b1;
    end
endmodule
