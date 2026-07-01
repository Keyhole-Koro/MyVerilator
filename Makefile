# コンパイラとフラグの設定
CXX = g++
VERILATOR = verilator

# ターゲット名
TARGET = Vcpu

all: $(TARGET)

$(TARGET): cpu.v sim_main.cpp
	# VerilogコードをC++に変換 (--cc) し、実行ファイルも生成 (--exe)
	$(VERILATOR) -Wall --cc cpu.v --exe sim_main.cpp
	# 生成されたC++コードをビルド
	make -j -C obj_dir -f Vcpu.mk Vcpu
	# 実行ファイルをカレントディレクトリにコピー
	cp obj_dir/Vcpu .

run: $(TARGET)
	./$(TARGET)

clean:
	rm -rf obj_dir $(TARGET)
