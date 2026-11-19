#include <iostream>
#include <vector>
#include <iomanip>
#include <fstream>
#include "Vcpu.h"
#include "verilated.h"

int main(int argc, char** argv) {
    Verilated::commandArgs(argc, argv);
    Vcpu* top = new Vcpu;

    // 1MB RAM (プログラムROM領域として使用: 0x20000000〜)
    std::vector<uint32_t> rom(1024 * 1024 / 4, 0);

    // 引数でバイナリファイルが指定された場合は読み込む
    if (argc > 1) {
        std::ifstream file(argv[1], std::ios::binary);
        if (file.is_open()) {
            file.read(reinterpret_cast<char*>(rom.data()), rom.size() * 4);
            const std::streamsize loaded = file.gcount(); // peek() で gcount() が変わるので先に取る
            // ROM に入りきらない分を黙って捨てない
            if (file.peek() != std::ifstream::traits_type::eof()) {
                std::cerr << "Program too large: " << argv[1]
                          << " (max " << rom.size() * 4 << " bytes)" << std::endl;
                return 1;
            }
            std::cout << "[Simulator] Loaded " << loaded << " bytes from " << argv[1] << std::endl;
        } else {
            std::cerr << "Failed to open file: " << argv[1] << std::endl;
            return 1;
        }
    } else {
        // 指定がない場合は、以前のデフォルト・テストプログラムを実行
        rom[0] = (0x02 << 26) | (1 << 21) | 10;
        rom[1] = (0x02 << 26) | (2 << 21) | 20;
        rom[2] = (0x05 << 26) | (1 << 21) | (2 << 16);
        rom[3] = (0x14 << 26) | (1 << 21);
        rom[4] = (0x15 << 26) | (4 << 21);
        rom[5] = (0x3F << 26);
    }

    // スタック等のためのRAM空間 (0x7FFF0000〜0x7FFFFFFF, 64KB)
    // リセット直後の SP (0x7FFFFFFF) の直下から PUSH できるよう 0x80000000 の手前までを含める
    std::vector<uint32_t> stack_ram(64 * 1024 / 4, 0);
    const uint32_t STACK_BASE = 0x7FFF0000;

    // アドレスから読み出す値 (マップされていない領域は 0)
    auto read_mem = [&](uint32_t addr) -> uint32_t {
        if (addr >= 0x20000000 && addr < 0x20000000 + rom.size() * 4) {
            return rom[(addr - 0x20000000) / 4];
        } else if (addr >= STACK_BASE && addr < STACK_BASE + stack_ram.size() * 4) {
            return stack_ram[(addr - STACK_BASE) / 4];
        }
        return 0;
    };

    // CPUのリセット
    top->rst = 1;
    top->clk = 0;
    top->eval();
    
    top->clk = 1;
    top->eval();

    top->rst = 0;

    int tickcount = 0;
    int idle_counter = 0;

    while (!Verilated::gotFinish()) {
        top->clk = 0;
        top->eval();
        
        // --- メモリ Read 処理 ---
        if (top->mem_read) {
            top->mem_rdata = read_mem(top->mem_addr);
        }

        // --- メモリ/IO Write 処理 ---
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
            // UART (シリアル通信) のエミュレーション
            // 仕様書通り、0x24000000 に書き込まれたら標準出力に文字を出す
            else if (top->mem_addr == 0x24000000) {
                char c = top->mem_wdata & 0xFF;
                std::cout << c << std::flush;
            }
        }

        // --- HALT検出 (CPUが完全に停止しているか) ---
        if (!top->mem_read && !top->mem_write) {
            idle_counter++;
            if (idle_counter > 20) { // メモリアクセスが20サイクル連続で無い場合は停止とみなす
                if (argc > 1) std::cout << "\n[Simulator] CPU Halted." << std::endl;
                break;
            }
        } else {
            idle_counter = 0;
        }

        // --- クロックの立ち上がり ---
        top->clk = 1;
        top->eval();
        
        // ファイルを指定せずに実行した場合のみ、以前のような詳細なデバッグ出力を出す
        if (argc == 1) {
            if (top->mem_read && idle_counter == 0) {
                // mem_rdata が渡されるのは次の立ち下がりなので、渡す予定の値を表示する
                std::cout << "Tick: " << std::setw(2) << tickcount 
                          << " | Read  Addr: 0x" << std::hex << top->mem_addr 
                          << " -> Data: 0x" << read_mem(top->mem_addr) << std::dec << std::endl;
            }
            if (top->mem_write && top->mem_addr != 0x24000000) {
                std::cout << "Tick: " << std::setw(2) << tickcount 
                          << " | Write Addr: 0x" << std::hex << top->mem_addr 
                          << " <- Data: 0x" << top->mem_wdata 
                          << " (Mask: 0x" << std::hex << (int)top->mem_wmask << ")" << std::dec << std::endl;
            }
            if (tickcount > 50) break; // 無限ループ防止
        }
                  
        tickcount++;
    }

    delete top;
    return 0;
}
