# コンパイラとフラグの設定
CXX = g++
VERILATOR = verilator

# ターゲット名
TARGET = Vcpu

all: $(TARGET)

.PHONY: all run test clean

$(TARGET): cpu.v sim_main.cpp
	# VerilogコードをC++に変換 (--cc) し、実行ファイルも生成 (--exe)
	$(VERILATOR) -Wall --cc cpu.v --exe sim_main.cpp
	# 生成されたC++コードをビルド
	$(MAKE) -j -C obj_dir -f Vcpu.mk Vcpu
	# 実行ファイルをカレントディレクトリにコピー
	cp obj_dir/Vcpu .

run: $(TARGET)
	./$(TARGET)

# 命令ごとの回帰テスト (tests/run_tests.py)
test: $(TARGET)
	python3 tests/run_tests.py ./$(TARGET)

clean:
	rm -rf obj_dir $(TARGET)
