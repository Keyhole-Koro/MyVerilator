/* verilator lint_off UNUSEDSIGNAL */
/* verilator lint_off WIDTHTRUNC */
/* verilator lint_off LATCH */

module cpu(
    input wire clk,
    input wire rst,
    
    // Memory interface
    output reg [31:0] mem_addr,
    output reg mem_read,
    output reg mem_write,
    output reg [3:0]  mem_wmask,
    output reg [31:0] mem_wdata,
    input wire [31:0] mem_rdata
);

    // Register Mapping
    // 0-7: R0-R7
    // 8: PC
    // 9: SP
    // 10: BP
    // 11: SR
    // 12: LR
    reg [31:0] r [0:12]; 

    // Flags mapping inside r[11] (SR)
    wire z_flag = r[11][0];
    wire n_flag = r[11][1];
    wire c_flag = r[11][2];
    wire v_flag = r[11][3];

    localparam FETCH = 0, 
               EXECUTE = 1, 
               MEM_READ_WAIT = 2, 
               MEM_WRITE_WAIT = 3, 
               HALTED = 4;
    reg [2:0] state;

    wire [31:0] ir = mem_rdata;
    wire [5:0] opcode = ir[31:26];
    wire [4:0] reg1   = ir[25:21];
    wire [4:0] reg2   = ir[20:16];
    
    wire [31:0] imm21_sext = {{11{ir[20]}}, ir[20:0]};
    wire [31:0] imm26_sext = {{6{ir[25]}}, ir[25:0]};
    
    wire [31:0] val1 = (reg1 <= 12) ? r[reg1] : 32'h0;
    wire [31:0] val2 = (reg2 <= 12) ? r[reg2] : 32'h0;

    // ALU results
    wire [31:0] add_res = val1 + val2;
    wire [31:0] addis_res = val1 + imm21_sext;
    wire [31:0] sub_res = val1 - val2;
    
    wire alu_c = (val1 < val2);
    wire alu_z = (sub_res == 0);
    wire alu_n = sub_res[31];
    wire alu_v = ((val1[31] != val2[31]) && (sub_res[31] != val1[31]));

    wire [7:0] byte_val = (mem_addr[1:0] == 2'b00) ? mem_rdata[7:0] :
                          (mem_addr[1:0] == 2'b01) ? mem_rdata[15:8] :
                          (mem_addr[1:0] == 2'b10) ? mem_rdata[23:16] :
                                                     mem_rdata[31:24];

    integer i;

    always @(posedge clk) begin
        if (rst) begin
            for (i=0; i<=12; i=i+1) r[i] <= 32'h0;
            r[8] <= 32'h2000_0000; // PC
            r[9] <= 32'h7FFF_FFFF; // SP
            state <= FETCH;
            mem_read <= 0;
            mem_write <= 0;
            mem_wmask <= 4'b0000;
            mem_addr <= 32'h0;
            mem_wdata <= 32'h0;
        end else begin
            case (state)
                FETCH: begin
                    mem_addr <= r[8]; // PC
                    mem_read <= 1;
                    mem_write <= 0;
                    mem_wmask <= 4'b0000;
                    state <= EXECUTE;
                end
                
                EXECUTE: begin
                    mem_read <= 0;
                    
                    case (opcode)
                        6'h01: begin // MOV r1, r2
                            if (reg1 <= 12) r[reg1] <= val2;
                            r[11][0] <= (val2 == 0); 
                            r[8] <= r[8] + 4;
                            state <= FETCH;
                        end
                        6'h02: begin // MOVI r1, imm21
                            if (reg1 <= 12) r[reg1] <= {11'b0, ir[20:0]};
                            r[11][0] <= (ir[20:0] == 0);
                            r[8] <= r[8] + 4;
                            state <= FETCH;
                        end
                        6'h18: begin // MOVIS r1, imm21
                            if (reg1 <= 12) r[reg1] <= imm21_sext;
                            r[11][0] <= (imm21_sext == 0);
                            r[8] <= r[8] + 4;
                            state <= FETCH;
                        end
                        6'h03, 6'h1C: begin // LD, LDB
                            mem_addr <= val2;
                            mem_read <= 1;
                            state <= MEM_READ_WAIT;
                        end
                        6'h04: begin // ST
                            mem_addr <= val1;
                            mem_wdata <= val2;
                            mem_wmask <= 4'b1111;
                            mem_write <= 1;
                            state <= MEM_WRITE_WAIT;
                        end
                        6'h1D: begin // STB
                            mem_addr <= val1;
                            mem_wdata <= {val2[7:0], val2[7:0], val2[7:0], val2[7:0]};
                            mem_wmask <= (4'b0001 << val1[1:0]);
                            mem_write <= 1;
                            state <= MEM_WRITE_WAIT;
                        end
                        6'h05: begin // ADD
                            if (reg1 <= 12) r[reg1] <= add_res;
                            r[11][0] <= (add_res == 0);
                            r[8] <= r[8] + 4;
                            state <= FETCH;
                        end
                        6'h19: begin // ADDIS
                            if (reg1 <= 12) r[reg1] <= addis_res;
                            r[11][0] <= (addis_res == 0);
                            r[8] <= r[8] + 4;
                            state <= FETCH;
                        end
                        6'h06: begin // SUB
                            if (reg1 <= 12) r[reg1] <= sub_res;
                            r[11][0] <= alu_z;
                            r[11][1] <= alu_n;
                            r[11][2] <= alu_c;
                            r[11][3] <= alu_v;
                            r[8] <= r[8] + 4;
                            state <= FETCH;
                        end
                        6'h07: begin // CMP
                            r[11][0] <= alu_z;
                            r[11][1] <= alu_n;
                            r[11][2] <= alu_c;
                            r[11][3] <= alu_v;
                            r[8] <= r[8] + 4;
                            state <= FETCH;
                        end
                        6'h08: begin // AND
                            if (reg1 <= 12) r[reg1] <= val1 & val2;
                            r[11][0] <= ((val1 & val2) == 0);
                            r[8] <= r[8] + 4;
                            state <= FETCH;
                        end
                        6'h09: begin // OR
                            if (reg1 <= 12) r[reg1] <= val1 | val2;
                            r[11][0] <= ((val1 | val2) == 0);
                            r[8] <= r[8] + 4;
                            state <= FETCH;
                        end
                        6'h0A: begin // XOR
                            if (reg1 <= 12) r[reg1] <= val1 ^ val2;
                            r[11][0] <= ((val1 ^ val2) == 0);
                            r[8] <= r[8] + 4;
                            state <= FETCH;
                        end
                        6'h0B: begin // SHL
                            if (reg1 <= 12) r[reg1] <= val1 << 1;
                            r[11][0] <= ((val1 << 1) == 0);
                            r[8] <= r[8] + 4;
                            state <= FETCH;
                        end
                        6'h0C: begin // SHR
                            if (reg1 <= 12) r[reg1] <= val1 >> 1;
                            r[11][0] <= ((val1 >> 1) == 0);
                            r[8] <= r[8] + 4;
                            state <= FETCH;
                        end
                        6'h0D: begin // JMP
                            r[8] <= r[8] + imm26_sext;
                            state <= FETCH;
                        end
                        6'h0E: begin // JZ
                            r[8] <= r[8] + (z_flag ? imm26_sext : 32'd4);
                            state <= FETCH;
                        end
                        6'h0F: begin // JNZ
                            r[8] <= r[8] + (!z_flag ? imm26_sext : 32'd4);
                            state <= FETCH;
                        end
                        6'h10: begin // JG
                            r[8] <= r[8] + ((!z_flag && (n_flag == v_flag)) ? imm26_sext : 32'd4);
                            state <= FETCH;
                        end
                        6'h11: begin // JL
                            r[8] <= r[8] + ((n_flag != v_flag) ? imm26_sext : 32'd4);
                            state <= FETCH;
                        end
                        6'h12: begin // JA
                            r[8] <= r[8] + ((!c_flag && !z_flag) ? imm26_sext : 32'd4);
                            state <= FETCH;
                        end
                        6'h13: begin // JB
                            r[8] <= r[8] + (c_flag ? imm26_sext : 32'd4);
                            state <= FETCH;
                        end
                        6'h1B: begin // CALL
                            r[12] <= r[8]; // LR = PC
                            r[8] <= r[8] + imm26_sext;
                            state <= FETCH;
                        end
                        6'h14: begin // PUSH r1
                            mem_addr <= r[9] - 4;
                            mem_wdata <= val1;
                            mem_wmask <= 4'b1111;
                            mem_write <= 1;
                            r[9] <= r[9] - 4;
                            state <= MEM_WRITE_WAIT;
                        end
                        6'h15: begin // POP r1
                            mem_addr <= r[9];
                            mem_read <= 1;
                            r[9] <= r[9] + 4;
                            state <= MEM_READ_WAIT;
                        end
                        6'h16: begin // IN
                            mem_addr <= 32'h24000000 + {11'b0, ir[20:0]};
                            mem_read <= 1;
                            state <= MEM_READ_WAIT;
                        end
                        6'h17: begin // OUT
                            mem_addr <= 32'h24000000 + {11'b0, ir[20:0]};
                            mem_wdata <= val1;
                            mem_wmask <= 4'b1111;
                            mem_write <= 1;
                            state <= MEM_WRITE_WAIT;
                        end
                        6'h1E: begin // EI
                            r[11][4] <= 1'b1;
                            r[8] <= r[8] + 4;
                            state <= FETCH;
                        end
                        6'h1F: begin // DI
                            r[11][4] <= 1'b0;
                            r[8] <= r[8] + 4;
                            state <= FETCH;
                        end
                        6'h1A: begin // DEBUG
                            r[8] <= r[8] + 4;
                            state <= FETCH;
                        end
                        6'h3F: begin // HALT
                            state <= HALTED;
                        end
                        default: begin
                            r[8] <= r[8] + 4;
                            state <= FETCH;
                        end
                    endcase
                end
                
                MEM_READ_WAIT: begin
                    mem_read <= 0;
                    if (opcode == 6'h1C) begin // LDB
                        if (reg1 <= 12) r[reg1] <= {24'b0, byte_val};
                        r[11][0] <= (byte_val == 0);
                    end else begin
                        if (reg1 <= 12) r[reg1] <= mem_rdata;
                        r[11][0] <= (mem_rdata == 0);
                    end
                    r[8] <= r[8] + 4;
                    state <= FETCH;
                end
                
                MEM_WRITE_WAIT: begin
                    mem_write <= 0;
                    mem_wmask <= 4'b0000;
                    r[8] <= r[8] + 4;
                    state <= FETCH;
                end
                
                HALTED: begin
                    // Stay halted
                end
            endcase
        end
    end
endmodule
