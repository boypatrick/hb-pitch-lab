`timescale 1ns/1ps
module tb_mac;
    parameter integer ROWS=2,COLS=3,DATA_W=4,ACC_W=8;
    reg clk=0;always #5 clk=~clk;
    reg rst=1,in_valid=0,clear=0,last=0,out_ready=0;
    reg [ROWS*DATA_W-1:0] a_data;
    reg [COLS*DATA_W-1:0] b_data;
    wire in_ready,out_valid;wire [ROWS*COLS*ACC_W-1:0] out_data;
    int_mac_array #(.ROWS(ROWS),.COLS(COLS),.DATA_W(DATA_W),.ACC_W(ACC_W)) dut(.*);
    reg [ACC_W-1:0] acc[0:ROWS*COLS-1],result[0:ROWS*COLS-1];
    reg expected_valid=0,blocked=0;
    integer cycle,r,c,j,av,bv,accepted=0,published=0;
    initial begin
        for(j=0;j<ROWS*COLS;j=j+1) begin acc[j]=0;result[j]=0;end
        repeat(2) @(negedge clk);rst=0;
        for(cycle=0;cycle<400;cycle=cycle+1) begin
            if(!blocked) begin
                in_valid=(($random & 3)!=0); clear=(cycle%7==0);last=(cycle%3!=0);
                for(r=0;r<ROWS;r=r+1) a_data[r*DATA_W +: DATA_W]=$random;
                for(c=0;c<COLS;c=c+1) b_data[c*DATA_W +: DATA_W]=$random;
            end
            out_ready=(cycle%5!=0 && cycle%5!=1);
            @(posedge clk);
            if(out_valid!==expected_valid || in_ready!==(!expected_valid || out_ready)) $fatal(1,"MAC handshake mismatch");
            if(out_valid) for(j=0;j<ROWS*COLS;j=j+1)
                if(out_data[j*ACC_W +: ACC_W]!==result[j]) $fatal(1,"signed MAC/result/stall mismatch %0d",j);
            if(out_valid && out_ready) begin expected_valid=0;published=published+1;end
            if(in_valid && in_ready) begin
                accepted=accepted+1;
                for(r=0;r<ROWS;r=r+1) for(c=0;c<COLS;c=c+1) begin
                    av=$signed(a_data[r*DATA_W +: DATA_W]);bv=$signed(b_data[c*DATA_W +: DATA_W]);j=r*COLS+c;
                    acc[j]=(clear ? 0 : acc[j])+av*bv;
                    if(last) result[j]=acc[j];
                end
                if(last) expected_valid=1;
            end
            blocked=in_valid && !in_ready;
            @(negedge clk);
        end
        if(accepted<100 || published<60) $fatal(1,"insufficient MAC transactions");
        $display("PASS MAC %0dx%0d data=%0d acc=%0d accepted=%0d results=%0d",ROWS,COLS,DATA_W,ACC_W,accepted,published);$finish;
    end
endmodule
