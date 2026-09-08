`timescale 1ns/1ps
module tb_storage;
    parameter integer DEPTH=3;
    localparam integer AW=DEPTH<=1 ? 1 : $clog2(DEPTH);
    reg clk=0;always #5 clk=~clk;
    reg rst=1;reg [1:0] req_valid=0,write_enable=0;
    reg [2*AW-1:0] address=0;reg [15:0] write_data=0;
    wire [1:0] read_valid;wire [15:0] read_data;
    banked_sram #(.BANKS(2),.DATA_W(8),.DEPTH(DEPTH)) ram(.*);
    reg [2*AW-1:0] read_address_a=0,read_address_b=0;
    wire [15:0] read_data_a,read_data_b;
    register_file #(.LANES(2),.DATA_W(8),.DEPTH(DEPTH)) rf(
        .clk(clk),.rst(rst),.write_enable(write_enable),.write_address(address),.write_data(write_data),
        .read_address_a(read_address_a),.read_address_b(read_address_b),.read_data_a(read_data_a),.read_data_b(read_data_b));
    integer i;reg [15:0] expected;
    initial begin
        repeat(2) @(negedge clk);rst=0;
        for(i=0;i<DEPTH;i=i+1) begin
            address={AW'(i),AW'(i)};write_data={8'(100+i),8'(10+i)};
            req_valid=3;write_enable=3;
            @(posedge clk);#1;
            if(read_valid!==0) $fatal(1,"write must not issue read response");
            @(negedge clk);
        end
        write_enable=0;
        for(i=0;i<DEPTH;i=i+1) begin
            address={AW'(i),AW'(i)};read_address_a=address;
            read_address_b={AW'(DEPTH-1-i),AW'(DEPTH-1-i)};
            expected={8'(100+i),8'(10+i)};
            #1;if(read_data_a!==expected || read_data_b!=={8'(100+DEPTH-1-i),8'(10+DEPTH-1-i)}) $fatal(1,"RF independent reads mismatch");
            @(posedge clk);#1;
            if(read_valid!==3 || read_data!==expected) $fatal(1,"SRAM synchronous read mismatch");
            @(negedge clk);
        end
        // Per-bank enables: overwrite only bank/lane 0, preserve bank/lane 1.
        address=0;write_enable=1;req_valid=1;write_data=16'hffff;
        @(posedge clk);@(negedge clk);write_enable=0;req_valid=3;read_address_a=0;
        @(posedge clk);#1;
        if(read_data!==16'h64ff || read_data_a!==16'h64ff) $fatal(1,"bank isolation mismatch");
        @(negedge clk);
        if((1<<AW)>DEPTH) begin
            address={2*AW{1'b1}};read_address_a=address;read_address_b=address;
            @(posedge clk);#1;
            if(read_valid!==0 || read_data_a!==0 || read_data_b!==0) $fatal(1,"out-of-range access mismatch");
        end
        $display("PASS SRAM/RF depth=%0d independent banks, sync/async reads, invalid addresses",DEPTH);$finish;
    end
endmodule
