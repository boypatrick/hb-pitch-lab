// Memory-side collective engine: wait for local writeback, then accept one
// NIC INT32 word and accumulate local+remote. Valid bits implement a barrier
// and prevent overwrite of unconsumed local results. NIC is an external port.
module mtia_me_nmc #(
    parameter integer ENTRIES=64, SW=$clog2(ENTRIES)
)(
    input wire clk,rst,
    input wire wb_valid,output wire wb_ready,input wire [32+SW-1:0] wb_data,
    input wire cmd_valid,output wire cmd_ready,
    input wire [SW-1:0] cmd_base,input wire [15:0] cmd_count,
    input wire nic_valid,output wire nic_ready,input wire [31:0] nic_data,
    output wire out_valid,input wire out_ready,output wire [31:0] out_data
);
    reg [31:0] mem[0:ENTRIES-1];
    reg [ENTRIES-1:0] occupied;
    reg [1:0] state;
    reg [SW-1:0] addr;
    reg [15:0] left;
    reg [31:0] local_value,accum;
    wire [SW-1:0] wa=wb_data[32 +: SW];
    assign wb_ready=!occupied[wa];
    assign cmd_ready=(state==0);
    assign nic_ready=(state==2);
    assign out_valid=(state==3);
    assign out_data=accum;
    always @(posedge clk) begin
        if(rst) begin occupied<=0;state<=0;addr<=0;left<=0;local_value<=0;accum<=0;end
        else begin
            if(wb_valid && wb_ready) begin mem[wa]<=wb_data[31:0];occupied[wa]<=1;end
            case(state)
                0: if(cmd_valid) begin addr<=cmd_base;left<=cmd_count;accum<=0;state<=1;end
                1: if(occupied[addr]) begin local_value<=mem[addr];occupied[addr]<=0;state<=2;end
                2: if(nic_valid) begin
                    accum<=accum+local_value+nic_data;
                    if(left==1) state<=3;
                    else begin left<=left-1;addr<=addr+1;state<=1;end
                end
                3: if(out_ready) state<=0;
            endcase
        end
    end
endmodule
