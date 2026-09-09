// CUT: 0=2D, 1=MI300-like coarse boundary, 2=local scratch boundary.
// This is a research subsystem, not the ISA or floorplan of a vendor chip.
module mtia_cluster #(
    parameter integer PES=2, LANES=8, ROWS=64, ENTRIES=64,
    parameter integer CUT=2, HB_BITS=16, COARSE_BITS=64, STAGES=1,
    parameter integer AW=$clog2(ROWS), SW=$clog2(ENTRIES), PW=(PES>1?$clog2(PES):1),
    parameter integer CW=2+4*AW+16+SW, LW=LANES*8+AW+PW
)(
    input wire clk,rst,
    input wire load_valid,output wire load_ready,
    input wire [PW-1:0] load_pe,input wire [AW-1:0] load_addr,
    input wire [LANES*8-1:0] load_data,
    input wire [PES-1:0] cmd_valid,output wire [PES-1:0] cmd_ready,
    input wire [PES*CW-1:0] cmd_data,
    input wire me_valid,output wire me_ready,input wire [SW-1:0] me_base,input wire [15:0] me_count,
    input wire nic_valid,output wire nic_ready,input wire [31:0] nic_data,
    output wire out_valid,input wire out_ready,output wire [31:0] out_data,
    output wire wb_valid,output wire wb_ready,output wire [32+SW-1:0] wb_data
);
    wire dma_valid;wire [LW-1:0] dma_data;
    mtia_transport #(.WIDTH(LW),.BITS(COARSE_BITS),.STAGES(STAGES),.CUT(CUT==1)) dma_link(
        .clk(clk),.rst(rst),.in_valid(load_valid),.in_ready(load_ready),.in_data({load_pe,load_addr,load_data}),
        .out_valid(dma_valid),.out_ready(1'b1),.out_data(dma_data));
    wire [PES-1:0] completions,completion_ready;
    wire [32+SW-1:0] results[0:PES-1];
    genvar p;
    generate for(p=0;p<PES;p=p+1) begin: pe_tile
        wire qv,qr,sv,sr,mqv,mqr,msv,msr,pwv,pwr;
        wire [2*AW-1:0] qd,mqd;
        wire [LANES*16-1:0] sd,msd;
        wire [32+SW-1:0] pwd;
        mtia_pe #(.LANES(LANES),.AW(AW),.SW(SW)) pe(
            .clk(clk),.rst(rst),.cmd_valid(cmd_valid[p]),.cmd_ready(cmd_ready[p]),.cmd_data(cmd_data[p*CW +: CW]),
            .req_valid(qv),.req_ready(qr),.req_data(qd),.rsp_valid(sv),.rsp_ready(sr),.rsp_data(sd),
            .wb_valid(pwv),.wb_ready(pwr),.wb_data(pwd));
        mtia_transport #(.WIDTH(2*AW),.BITS(8),.STAGES(STAGES),.CUT(CUT==2)) request_link(
            .clk(clk),.rst(rst),.in_valid(qv),.in_ready(qr),.in_data(qd),.out_valid(mqv),.out_ready(mqr),.out_data(mqd));
        mtia_scratch #(.LANES(LANES),.ROWS(ROWS)) scratch(
            .clk(clk),.rst(rst),.wr_valid(dma_valid && dma_data[LANES*8+AW +: PW]==p),
            .wr_addr(dma_data[LANES*8 +: AW]),.wr_data(dma_data[LANES*8-1:0]),
            .req_valid(mqv),.req_ready(mqr),.req_data(mqd),.rsp_valid(msv),.rsp_ready(msr),.rsp_data(msd));
        mtia_transport #(.WIDTH(LANES*16),.BITS(HB_BITS),.STAGES(STAGES),.CUT(CUT==2)) response_link(
            .clk(clk),.rst(rst),.in_valid(msv),.in_ready(msr),.in_data(msd),.out_valid(sv),.out_ready(sr),.out_data(sd));
        mtia_transport #(.WIDTH(32+SW),.BITS(CUT==2?8:COARSE_BITS),.STAGES(STAGES),.CUT(CUT!=0)) result_link(
            .clk(clk),.rst(rst),.in_valid(pwv),.in_ready(pwr),.in_data(pwd),
            .out_valid(completions[p]),.out_ready(completion_ready[p]),.out_data(results[p]));
    end endgenerate
    integer rr,k,idx,pick,locked_pick;
    reg found,locked;reg [32+SW-1:0] chosen;
    always @* begin
        found=0;pick=0;chosen=0;idx=0;
        for(k=0;k<PES;k=k+1) begin
            idx=rr+k;if(idx>=PES) idx=idx-PES;
            if(!found && completions[idx]) begin found=1;pick=idx;chosen=results[idx];end
        end
        // A stalled destination must retain the selected source until handshake.
        if(locked) begin found=completions[locked_pick];pick=locked_pick;chosen=results[locked_pick];end
    end
    assign wb_valid=found;assign wb_data=chosen;
    generate for(p=0;p<PES;p=p+1) begin: ready_route
        assign completion_ready[p]=found && pick==p && wb_ready;
    end endgenerate
    always @(posedge clk) begin
        if(rst) begin rr<=0;locked<=0;locked_pick<=0;end
        else if(wb_valid && wb_ready) begin rr<=(pick==PES-1)?0:pick+1;locked<=0;end
        else if(wb_valid) begin locked<=1;locked_pick<=pick;end
    end
    mtia_me_nmc #(.ENTRIES(ENTRIES)) collective(
        .clk(clk),.rst(rst),.wb_valid(wb_valid),.wb_ready(wb_ready),.wb_data(wb_data),
        .cmd_valid(me_valid),.cmd_ready(me_ready),.cmd_base(me_base),.cmd_count(me_count),
        .nic_valid(nic_valid),.nic_ready(nic_ready),.nic_data(nic_data),
        .out_valid(out_valid),.out_ready(out_ready),.out_data(out_data));
endmodule
