// Signed integer outer-product accumulator; no floating-point interpretation.
// Accept one A[ROWS], B[COLS] vector pair per cycle. clear starts a new sum;
// last publishes the updated matrix. Arithmetic wraps modulo 2**ACC_W.
module int_mac_array #(
    parameter integer ROWS=4, COLS=4, DATA_W=8, ACC_W=32
)(
    input wire clk, input wire rst,
    input wire in_valid, output wire in_ready,
    input wire clear, input wire last,
    input wire [ROWS*DATA_W-1:0] a_data,
    input wire [COLS*DATA_W-1:0] b_data,
    output reg out_valid, input wire out_ready,
    output wire [ROWS*COLS*ACC_W-1:0] out_data
);
    reg signed [ACC_W-1:0] accum [0:ROWS*COLS-1];
    reg [ROWS*COLS*ACC_W-1:0] result;
    assign out_data = result;
    assign in_ready = !out_valid || out_ready;
    always @(posedge clk) begin
        if (rst) out_valid <= 1'b0;
        else if (in_ready) out_valid <= in_valid && last;
    end
    genvar r,c;
    generate for (r=0; r<ROWS; r=r+1) begin: g_row
        for(c=0; c<COLS; c=c+1) begin: g_col
            localparam integer IDX=r*COLS+c;
            wire signed [DATA_W-1:0] a = a_data[r*DATA_W +: DATA_W];
            wire signed [DATA_W-1:0] b = b_data[c*DATA_W +: DATA_W];
            wire signed [2*DATA_W-1:0] product = a*b;
            wire signed [ACC_W-1:0] extended_product = {{(ACC_W-2*DATA_W){product[2*DATA_W-1]}},product};
            wire signed [ACC_W-1:0] next_value = (clear ? {ACC_W{1'b0}} : accum[IDX]) + extended_product;
            always @(posedge clk) begin
                if (rst) begin
                    accum[IDX] <= 0;
                    result[IDX*ACC_W +: ACC_W] <= 0;
                end else if (in_valid && in_ready) begin
                    accum[IDX] <= next_value;
                    if (last) result[IDX*ACC_W +: ACC_W] <= next_value;
                end
            end
        end
    end endgenerate
endmodule
