# MyVerilator

`cpu.v` の CPU モデルを Verilator で動かすためのリポジトリです。

## ビルドと実行

Verilator と g++ が必要です。

```bash
make                 # ./Vcpu をビルド
./Vcpu               # 組み込みのテストプログラムを実行し、メモリアクセスを表示
./Vcpu hello.bin     # バイナリ (リトルエンディアン, 0x20000000 から配置) を実行
```

`hello.bin` は `python3 gen_hello.py` で作り直せます。

## テスト

```bash
make test                                # ビルドしてから全テストを実行
python3 tests/run_tests.py ./Vcpu        # ビルド済みの Vcpu でテスト
python3 tests/run_tests.py ./Vcpu -k cmp # 名前に cmp を含むテストだけ
```

`tests/run_tests.py` は命令ごとに小さなプログラムを作って `./Vcpu` で実行し、
UART (`0x24000000`) に出た文字列を期待値と比べます。
