module tb_mtia;
    parameter integer PES=2, LANES=8, ROWS=64, ENTRIES=64, CUT=2, HB_BITS=16, COARSE_BITS=64, STAGES=1;
    parameter integer MAX_CYCLES=100000;
    localparam integer AW=$clog2(ROWS),SW=$clog2(ENTRIES),PW=(PES>1?$clog2(PES):1),CW=2+4*AW+16+SW;
    localparam integer IW=LANES*8+AW+PW+1+PES*CW+PES+16+SW+1+32+1+1;
    localparam integer OW=1+PES+1+1+32+1+32+SW+1+1;
    reg clk=0,rst=1;
    always #5 clk=~clk;
    reg [IW-1:0] inputs=0;
    wire load_valid,load_ready;wire [PW-1:0] load_pe;wire [AW-1:0] load_addr;wire [LANES*8-1:0] load_data;
    wire [PES-1:0] cmd_valid,cmd_ready;wire [PES*CW-1:0] cmd_data;
    wire me_valid,me_ready;wire [SW-1:0] me_base;wire [15:0] me_count;
    wire nic_valid,nic_ready;wire [31:0] nic_data;
    wire out_valid,out_ready;wire [31:0] out_data;
    wire wb_valid,wb_ready;wire [32+SW-1:0] wb_data;
    assign {out_ready,nic_valid,nic_data,me_valid,me_base,me_count,cmd_valid,cmd_data,load_valid,load_pe,load_addr,load_data}=inputs;
    wire [OW-1:0] observed={wb_ready,wb_valid,wb_data,out_valid,out_data,nic_ready,me_ready,cmd_ready,load_ready};
`ifdef MTIA_FROZEN_TOP
    mtia_selected_top dut(.*);
`else
    mtia_cluster #(.PES(PES),.LANES(LANES),.ROWS(ROWS),.ENTRIES(ENTRIES),.CUT(CUT),.HB_BITS(HB_BITS),.COARSE_BITS(COARSE_BITS),.STAGES(STAGES)) dut(.*);
`endif
    reg [IW-1:0] stimulus[0:MAX_CYCLES-1];
    reg [OW-1:0] expected[0:MAX_CYCLES-1],mask[0:MAX_CYCLES-1];
    reg [2047:0] sf,ef,mf;
    integer cycles,j;
    reg held=0;reg [31:0] held_data;
    reg wb_held=0;reg [32+SW-1:0] wb_held_data;
    initial begin
        if(!$value$plusargs("STIM=%s",sf) || !$value$plusargs("EXPECT=%s",ef) || !$value$plusargs("MASK=%s",mf) || !$value$plusargs("CYCLES=%d",cycles)) $fatal(1,"Missing stimulus arguments");
        if(cycles<1 || cycles>MAX_CYCLES) $fatal(1,"Invalid cycles");
        $readmemh(sf,stimulus,0,cycles-1);$readmemh(ef,expected,0,cycles-1);$readmemh(mf,mask,0,cycles-1);
        repeat(2) @(posedge clk);
        @(negedge clk);rst=0;
        for(j=0;j<cycles;j=j+1) begin
            @(negedge clk);inputs=stimulus[j];#1;
            if((observed & mask[j]) !== (expected[j] & mask[j])) begin
                $display("cycle=%0d observed=%h expected=%h mask=%h",j,observed,expected[j],mask[j]);
                $fatal(1,"MTIA cycle/output mismatch");
            end
            if(held && (!out_valid || out_data!==held_data)) $fatal(1,"Output changed under backpressure");
            held=out_valid && !out_ready;held_data=out_data;
            if(wb_held && (!wb_valid || wb_data!==wb_held_data)) $fatal(1,"Writeback changed under backpressure");
            wb_held=wb_valid && !wb_ready;wb_held_data=wb_data;
        end
        @(posedge clk);#1;
        $display("PASS mtia cycles=%0d PES=%0d LANES=%0d CUT=%0d HB_BITS=%0d",cycles,PES,LANES,CUT,HB_BITS);
        $finish;
    end
endmodule
