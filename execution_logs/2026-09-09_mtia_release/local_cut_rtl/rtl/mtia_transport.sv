// One outstanding packet, actual chunk serialization and reassembly.
// CUT=0 is a combinational same-die connection. STAGES is added wire latency.
module mtia_transport #(
    parameter integer WIDTH=32, BITS=8, STAGES=1, CUT=1,
    parameter integer CHUNKS=(WIDTH+BITS-1)/BITS
)(
    input wire clk, rst,
    input wire in_valid, output wire in_ready, input wire [WIDTH-1:0] in_data,
    output wire out_valid, input wire out_ready, output wire [WIDTH-1:0] out_data
);
    generate if (!CUT) begin: direct
        assign in_ready=out_ready;
        assign out_valid=in_valid;
        assign out_data=in_data;
    end else begin: serial
        reg [1:0] state;
        reg [CHUNKS*BITS-1:0] tx, rx;
        integer index, delay_left;
        assign in_ready=(state==0);
        assign out_valid=(state==3);
        assign out_data=rx[WIDTH-1:0];
        always @(posedge clk) begin
            if(rst) begin state<=0;tx<=0;rx<=0;index<=0;delay_left<=0;end
            else case(state)
                0: if(in_valid) begin tx<=in_data;rx<=0;index<=0;state<=1;end
                1: begin
                    rx[index*BITS +: BITS]<=tx[BITS-1:0];
                    tx<=tx>>BITS;
                    if(index==CHUNKS-1) begin
                        delay_left<=STAGES;
                        state<=(STAGES==0)?3:2;
                    end else index<=index+1;
                end
                2: if(delay_left==1) state<=3; else delay_left<=delay_left-1;
                3: if(out_ready) state<=0;
            endcase
        end
    end endgenerate
endmodule
