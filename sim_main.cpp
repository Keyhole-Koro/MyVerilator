#include <iostream>
#include <vector>
#include <iomanip>
#include "Vcpu.h"
#include "verilated.h"

int main(int argc, char** argv) {
    Verilated::commandArgs(argc, argv);
    Vcpu* top = new Vcpu;

    // 1MB RAM
    std::vector<uint32_t> rom(1024 * 1024 / 4, 0);

    // テスト用の簡単なプログラムを構築
    // 0x20000000: MOVI R1, 10    -> 0x02 << 26 | 1 << 21 | 10
    // 0x20000004: MOVI R2, 20    -> 0x02 << 26 | 2 << 21 | 20
    // 0x20000008: ADD R3, R1, R2 -> 0x05 << 26 | 3 << 21 | 1 << 16 | 2 (R3 = R1 + R2) wait, architecture doesn't have 3-reg ADD.
    // Spec: add r1, r2 -> r1 = r1 + r2. 
    // 0x20000008: ADD R1, R2     -> 0x05 << 26 | 1 << 21 | 2 << 16
    // 0x2000000C: PUSH R1        -> 0x14 << 26 | 1 << 21
    // 0x20000010: POP R4         -> 0x15 << 26 | 4 << 21
    // 0x20000014: HALT           -> 0x3F << 26

    rom[0] = (0x02 << 26) | (1 << 21) | 10;
    rom[1] = (0x02 << 26) | (2 << 21) | 20;
    rom[2] = (0x05 << 26) | (1 << 21) | (2 << 16);
    rom[3] = (0x14 << 26) | (1 << 21);
    rom[4] = (0x15 << 26) | (4 << 21);
    rom[5] = (0x3F << 26);

    // RAM領域のシミュレーション（PUSH先のスタックなど）
    // RAM_START = 0x00000000, SIZE = 512MB. 
    // ここではテスト用に0x7FF00000〜0x7FFFFFFF付近の少量のスタック領域を確保
    std::vector<uint32_t> stack_ram(1024, 0); 
    const uint32_t STACK_BASE = 0x7FFF0000;

    top->rst = 1;
    top->clk = 0;
    top->eval();
    
    top->clk = 1;
    top->eval();

    top->rst = 0;

    int tickcount = 0;
    while (!Verilated::gotFinish() && tickcount < 50) {
        top->clk = 0;
        top->eval();
        
        // メモリ Read
        if (top->mem_read) {
            if (top->mem_addr >= 0x20000000 && top->mem_addr < 0x20000000 + rom.size() * 4) {
                uint32_t word_addr = (top->mem_addr - 0x20000000) / 4;
                top->mem_rdata = rom[word_addr];
            } else if (top->mem_addr >= STACK_BASE && top->mem_addr < STACK_BASE + stack_ram.size() * 4) {
                uint32_t word_addr = (top->mem_addr - STACK_BASE) / 4;
                top->mem_rdata = stack_ram[word_addr];
            } else {
                top->mem_rdata = 0; 
            }
        }

        // メモリ Write
        if (top->mem_write) {
            uint32_t mask = 0;
            if (top->mem_wmask & 1) mask |= 0x000000FF;
            if (top->mem_wmask & 2) mask |= 0x0000FF00;
            if (top->mem_wmask & 4) mask |= 0x00FF0000;
            if (top->mem_wmask & 8) mask |= 0xFF000000;

            if (top->mem_addr >= 0x20000000 && top->mem_addr < 0x20000000 + rom.size() * 4) {
                uint32_t word_addr = (top->mem_addr - 0x20000000) / 4;
                rom[word_addr] = (rom[word_addr] & ~mask) | (top->mem_wdata & mask);
            } else if (top->mem_addr >= STACK_BASE && top->mem_addr < STACK_BASE + stack_ram.size() * 4) {
                uint32_t word_addr = (top->mem_addr - STACK_BASE) / 4;
                stack_ram[word_addr] = (stack_ram[word_addr] & ~mask) | (top->mem_wdata & mask);
            }
        }

        top->clk = 1;
        top->eval();
        
        if (top->mem_read) {
            std::cout << "Tick: " << std::setw(2) << tickcount 
                      << " | Read  Addr: 0x" << std::hex << top->mem_addr 
                      << " -> Data: 0x" << top->mem_rdata << std::dec << std::endl;
        }
        if (top->mem_write) {
            std::cout << "Tick: " << std::setw(2) << tickcount 
                      << " | Write Addr: 0x" << std::hex << top->mem_addr 
                      << " <- Data: 0x" << top->mem_wdata 
                      << " (Mask: 0x" << std::hex << (int)top->mem_wmask << ")" << std::dec << std::endl;
        }
                  
        tickcount++;
        
        // HALT検出 (簡易的)
        if (top->mem_addr == 0x20000014 && top->mem_read) {
            // halt命令をフェッチしたら数サイクル後に終了
            if (tickcount > 40) break;
        }
    }

    delete top;
    return 0;
}
