`timescale 1ns/1ps
module tb_arbiter;
    parameter integer PORTS=3;
    localparam integer IW=PORTS<=1 ? 1 : $clog2(PORTS);
    reg clk=0;always #5 clk=~clk;
    reg rst=1,advance=0;reg [PORTS-1:0] request=0;
    wire [PORTS-1:0] grant;wire grant_valid;wire [IW-1:0] grant_index;
    rr_arbiter #(.PORTS(PORTS)) dut(.*);
    integer cycle,pointer=0,offset,index,chosen;reg [PORTS-1:0] expected;
    initial begin
        repeat(2) @(negedge clk);rst=0;
        for(cycle=0;cycle<200;cycle=cycle+1) begin
            request=cycle<20 ? {PORTS{1'b1}} : $random;
            advance=cycle%4!=0;expected=0;chosen=-1;
            for(offset=0;offset<PORTS;offset=offset+1) begin
                index=(pointer+offset)%PORTS;
                if(chosen<0 && request[index]) chosen=index;
            end
            if(chosen>=0) expected[chosen]=1;
            #1;if(grant!==expected || grant_valid!==(chosen>=0)) $fatal(1,"arbiter selection mismatch");
            if(chosen>=0 && grant_index!==IW'(chosen)) $fatal(1,"arbiter index mismatch");
            @(posedge clk);if(advance && chosen>=0) pointer=(chosen+1)%PORTS;
            @(negedge clk);
        end
        $display("PASS arbiter ports=%0d rotation, hold, sparse and empty requests",PORTS);$finish;
    end
endmodule
