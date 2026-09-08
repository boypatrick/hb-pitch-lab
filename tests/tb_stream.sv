`timescale 1ns/1ps
module tb_stream;
    parameter integer KIND=0, DEPTH=3, WIDTH=8;
    reg clk=0; always #5 clk=~clk;
    reg rst=1,in_valid=0,out_ready=0;
    reg [WIDTH-1:0] in_data=0;
    wire in_ready,out_valid;wire [WIDTH-1:0] out_data;
    generate if(KIND==0) begin
        stream_fifo #(.WIDTH(WIDTH),.DEPTH(DEPTH)) dut(.*);
    end else begin
        hb_link #(.WIDTH(WIDTH),.STAGES(DEPTH)) dut(.*);
    end endgenerate
    reg [WIDTH-1:0] expected[0:2047];
    integer rd=0,wr=0,cycle,stalls=0,full_replace=0;
    reg blocked=0,hold_output=0;reg [WIDTH-1:0] held;
    initial begin
        repeat(2) @(negedge clk);rst=0;
        for(cycle=0;cycle<600;cycle=cycle+1) begin
            in_valid=cycle<500 ? (blocked || (($random & 3)!=0)) : blocked;
            in_data=wr;out_ready=cycle>=500 || (($random & 3)!=0);
            @(posedge clk);
            if(hold_output && (!out_valid || out_data!==held)) $fatal(1,"unstable stalled output");
            hold_output=out_valid && !out_ready;held=out_data;
            if(out_valid && !out_ready) stalls=stalls+1;
            if(wr-rd==DEPTH && in_valid && in_ready && out_valid && out_ready) full_replace=full_replace+1;
            if(out_valid && out_ready) begin
                if(rd>=wr || out_data!==expected[rd]) $fatal(1,"stream ordering/data mismatch at %0d",rd);
                rd=rd+1;
            end
            if(in_valid && in_ready) begin expected[wr]=in_data;wr=wr+1;end
            if(wr-rd>DEPTH) $fatal(1,"capacity exceeded");
            blocked=in_valid && !in_ready;
            @(negedge clk);
        end
        if(rd!=wr || rd<100 || stalls<10 || full_replace<1) $fatal(1,"insufficient exercise or failed drain %0d %0d",rd,wr);
        $display("PASS stream kind=%0d depth=%0d width=%0d transfers=%0d stalls=%0d full_replace=%0d",KIND,DEPTH,WIDTH,rd,stalls,full_replace);
        $finish;
    end
endmodule
