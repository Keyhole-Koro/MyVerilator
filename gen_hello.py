import struct

# 命令のエンコーディング用ヘルパー
def movi(reg, imm):
    return (0x02 << 26) | (reg << 21) | (imm & 0x1FFFFF)

def out(port, reg):
    return (0x17 << 26) | (reg << 21) | (port & 0x1FFFFF)

def halt():
    return (0x3F << 26)

# Hello Worldの各文字を出力するプログラム
text = "Hello, World!\n"
instructions = []

for char in text:
    instructions.append(movi(1, ord(char))) # R1に文字コードを入れる
    instructions.append(out(0, 1))          # R1の値をポート0 (0x24000000) に出力する

instructions.append(halt())

# バイナリファイルとして保存
with open('hello.bin', 'wb') as f:
    for inst in instructions:
        f.write(struct.pack('<I', inst)) # リトルエンディアンで書き込み

print("Generated hello.bin")
