// Descriptor PE: DOT, ADD_SUM and RELU_SUM with signed INT8 / wrapping INT32.
// Descriptor low-to-high: op(2), a(AW), b(AW), stride_a(AW), stride_b(AW),
// vectors(16), destination(SW). No RISC-V ISA or floating point is implied.
module mtia_pe #(
    parameter integer LANES=8, AW=6, SW=6, CW=2+4*AW+16+SW
)(
    input wire clk,rst,
    input wire cmd_valid,output wire cmd_ready,input wire [CW-1:0] cmd_data,
    output wire req_valid,input wire req_ready,output wire [2*AW-1:0] req_data,
    input wire rsp_valid,output wire rsp_ready,input wire [LANES*16-1:0] rsp_data,
    output wire wb_valid,input wire wb_ready,output wire [32+SW-1:0] wb_data
);
    reg [1:0] state,op;
    reg [AW-1:0] a,b,sa,sb;
    reg [15:0] left;
    reg [SW-1:0] dst;
    reg signed [31:0] accum;
    wire signed [31:0] terms[0:LANES-1];
    genvar l;
    generate for(l=0;l<LANES;l=l+1) begin: lane
        wire signed [7:0] x=rsp_data[l*8 +: 8];
        wire signed [7:0] y=rsp_data[LANES*8+l*8 +: 8];
        wire signed [15:0] product=x*y;
        wire signed [31:0] ex={{24{x[7]}},x}, ey={{24{y[7]}},y};
        assign terms[l]=(op==0)?{{16{product[15]}},product}:
                        (op==1)?(ex+ey):(x[7]?32'sd0:ex);
    end endgenerate
    integer k;
    reg signed [31:0] delta;
    always @* begin
        delta=0;
        for(k=0;k<LANES;k=k+1) delta=delta+terms[k];
    end
    assign cmd_ready=(state==0);
    assign req_valid=(state==1);
    assign req_data={b,a};
    assign rsp_ready=(state==2);
    assign wb_valid=(state==3);
    assign wb_data={dst,accum};
    always @(posedge clk) begin
        if(rst) begin state<=0;op<=0;a<=0;b<=0;sa<=0;sb<=0;left<=0;dst<=0;accum<=0;end
        else case(state)
            0: if(cmd_valid) begin
                op<=cmd_data[1:0];a<=cmd_data[2 +: AW];b<=cmd_data[2+AW +: AW];
                sa<=cmd_data[2+2*AW +: AW];sb<=cmd_data[2+3*AW +: AW];
                left<=cmd_data[2+4*AW +: 16];dst<=cmd_data[2+4*AW+16 +: SW];
                accum<=0;state<=1;
            end
            1: if(req_ready) state<=2;
            2: if(rsp_valid) begin
                accum<=accum+delta;
                if(left==1) state<=3;
                else begin left<=left-1;a<=a+sa;b<=b+sb;state<=1;end
            end
            3: if(wb_ready) state<=0;
        endcase
    end
endmodule
