`timescale 1ns/1ps
// KIND=0: banked SRAM; KIND=1: register file. Tests actual selected parameters.
module tb_memory;
    parameter integer KIND=0, N=4, WIDTH=32, DEPTH=16;
    localparam integer AW=DEPTH<=1 ? 1 : $clog2(DEPTH);
    reg clk=0;always #5 clk=~clk;
    reg rst=1;reg [N-1:0] req_valid=0,write_enable=0;
    reg [N*AW-1:0] address=0,read_address_a=0,read_address_b=0;
    reg [N*WIDTH-1:0] write_data=0;
    wire [N-1:0] read_valid;wire [N*WIDTH-1:0] read_data,read_data_a,read_data_b;
    generate if(KIND==0) begin
        banked_sram #(.BANKS(N),.DATA_W(WIDTH),.DEPTH(DEPTH)) dut(
            .clk(clk),.rst(rst),.req_valid(req_valid),.write_enable(write_enable),.address(address),
            .write_data(write_data),.read_valid(read_valid),.read_data(read_data));
    end else begin
        register_file #(.LANES(N),.DATA_W(WIDTH),.DEPTH(DEPTH)) dut(
            .clk(clk),.rst(rst),.write_enable(write_enable),.write_address(address),.write_data(write_data),
            .read_address_a(read_address_a),.read_address_b(read_address_b),.read_data_a(read_data_a),.read_data_b(read_data_b));
    end endgenerate
    integer samples[0:2];integer s,b,addr;
    reg [WIDTH-1:0] expected,expected_b;
    initial begin
        samples[0]=0;samples[1]=DEPTH/2;samples[2]=DEPTH-1;
        repeat(2) @(negedge clk);rst=0;
        for(s=0;s<3;s=s+1) begin
            addr=samples[s];
            for(b=0;b<N;b=b+1) begin
                address[b*AW +: AW]=addr;write_data[b*WIDTH +: WIDTH]=addr*17+b*31+3;
            end
            req_valid={N{1'b1}};write_enable={N{1'b1}};
            @(posedge clk);#1;if(KIND==0 && read_valid!==0) $fatal(1,"write produced read response");
            @(negedge clk);
        end
        write_enable=0;
        for(s=0;s<3;s=s+1) begin
            addr=samples[s];
            for(b=0;b<N;b=b+1) begin
                address[b*AW +: AW]=addr;read_address_a[b*AW +: AW]=addr;
                read_address_b[b*AW +: AW]=DEPTH-1;
            end
            #1;
            if(KIND==1) for(b=0;b<N;b=b+1) begin
                expected=addr*17+b*31+3;expected_b=(DEPTH-1)*17+b*31+3;
                if(read_data_a[b*WIDTH +: WIDTH]!==expected || read_data_b[b*WIDTH +: WIDTH]!==expected_b)
                    $fatal(1,"RF asynchronous independent read mismatch");
            end
            @(posedge clk);#1;
            if(KIND==0) begin
                if(read_valid!=={N{1'b1}}) $fatal(1,"SRAM read valid mismatch");
                for(b=0;b<N;b=b+1) begin
                    expected=addr*17+b*31+3;
                    if(read_data[b*WIDTH +: WIDTH]!==expected) $fatal(1,"SRAM synchronous read mismatch");
                end
            end
            @(negedge clk);
        end
        address=0;write_enable=1;req_valid=1;write_data=2;
        @(posedge clk);@(negedge clk);write_enable=0;req_valid={N{1'b1}};read_address_a=0;
        @(posedge clk);#1;
        for(b=0;b<N;b=b+1) begin
            expected=b==0 ? 2 : b*31+3;
            if(KIND==0 && read_data[b*WIDTH +: WIDTH]!==expected) $fatal(1,"SRAM bank isolation");
            if(KIND==1 && read_data_a[b*WIDTH +: WIDTH]!==expected) $fatal(1,"RF lane isolation");
        end
        @(negedge clk);
        if((1<<AW)>DEPTH) begin
            address={N*AW{1'b1}};read_address_a=address;read_address_b=address;
            @(posedge clk);#1;
            if(KIND==0 && read_valid!==0) $fatal(1,"SRAM invalid address responded");
            if(KIND==1 && (read_data_a!==0 || read_data_b!==0)) $fatal(1,"RF invalid address response");
        end
        $display("PASS selected memory kind=%0d banks/lanes=%0d width=%0d depth=%0d",KIND,N,WIDTH,DEPTH);$finish;
    end
endmodule
