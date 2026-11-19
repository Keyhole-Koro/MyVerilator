#!/usr/bin/env python3
"""cpu.v の命令ごとの回帰テスト。

小さなプログラムを Python でエンコードして Vcpu に読ませ、
UART (0x24000000) に出た文字列を期待値と比べる。

使い方:
    python3 tests/run_tests.py [./Vcpu] [-k 名前の一部]
"""

import argparse
import os
import struct
import subprocess
import sys
import tempfile

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PROG_BASE = 0x20000000
TIMEOUT_SEC = 10

# --- 命令のエンコード (gen_hello.py と同じ形式) ---
MOV, MOVI, LD, ST, ADD, SUB, CMP = 0x01, 0x02, 0x03, 0x04, 0x05, 0x06, 0x07
AND, OR, XOR, SHL, SHR = 0x08, 0x09, 0x0A, 0x0B, 0x0C
JMP, JZ, JNZ, JG, JL, JA, JB = 0x0D, 0x0E, 0x0F, 0x10, 0x11, 0x12, 0x13
PUSH, POP, IN, OUT, MOVIS, ADDIS = 0x14, 0x15, 0x16, 0x17, 0x18, 0x19
LDB, STB, SWP, CAS, CHK, LUI, HALT = 0x1C, 0x1D, 0x22, 0x23, 0x24, 0x25, 0x3F


def rr(op, r1, r2=0, r3=0):
    """reg, reg (, reg) 形式"""
    return (op << 26) | (r1 << 21) | (r2 << 16) | (r3 << 11)


def ri(op, r1, imm):
    """reg, imm21 形式"""
    return (op << 26) | (r1 << 21) | (imm & 0x1FFFFF)


def jmp(op, offset):
    """imm26 形式 (分岐は命令自身のアドレスからの相対バイト数)"""
    return (op << 26) | (offset & 0x3FFFFFF)


def out(reg, port=0):
    return ri(OUT, reg, port)


def halt():
    return HALT << 26


def load32(reg, value):
    """32 ビット値を 2 命令で入れる (lui + addis)"""
    return [ri(LUI, reg, value >> 11), ri(ADDIS, reg, value & 0x7FF)]


def addr_of(index):
    """プログラム中 index 番目の語のアドレス"""
    return PROG_BASE + 4 * index


def emit_word(reg):
    """reg の 4 バイトを下位から順に出力する (reg は壊れる)"""
    prog = []
    for i in range(4):
        prog.append(out(reg))
        if i != 3:
            prog += [rr(SHR, reg)] * 8
    return prog


def branch(setup, op, taken):
    """setup の後で分岐 op を実行し、分岐したら 'Y'、しなければ 'N' を出す"""
    prog = list(setup)
    prog += [
        jmp(op, 12),          # -> movi r5, 'Y'
        ri(MOVI, 5, ord("N")),
        jmp(JMP, 8),          # -> out r5
        ri(MOVI, 5, ord("Y")),
        out(5),
        halt(),
    ]
    return prog, b"Y" if taken else b"N"


def cmp_setup(a, b):
    prog = []
    for reg, value in ((1, a), (2, b)):
        if value < 0:
            prog.append(ri(MOVIS, reg, value))
        else:
            prog.append(ri(MOVI, reg, value))
    prog.append(rr(CMP, 1, 2))
    return prog


def with_data(make_code, data):
    """make_code(data のアドレス) で作ったコードの直後に data の語を置く"""
    code_len = len(make_code(0))
    code = make_code(addr_of(code_len))
    assert len(code) == code_len
    return code + data


# --- テストケース ---
TESTS = []


def case(name, prog, expected):
    TESTS.append((name, prog, expected))


def build_cases():
    case("movi", [ri(MOVI, 1, ord("A")), out(1), halt()], b"A")
    case("mov", [ri(MOVI, 2, ord("M")), rr(MOV, 1, 2), out(1), halt()], b"M")
    case("movis_negative",
         [ri(MOVIS, 1, -1)] + emit_word(1) + [halt()], b"\xff\xff\xff\xff")
    case("lui_addis", load32(1, 0x44434241) + emit_word(1) + [halt()], b"ABCD")
    case("addis_negative",
         [ri(MOVI, 1, ord("C")), ri(ADDIS, 1, -2), out(1), halt()], b"A")
    case("add", [ri(MOVI, 1, 0x40), ri(MOVI, 2, 1), rr(ADD, 1, 2), out(1), halt()], b"A")
    case("sub", [ri(MOVI, 1, ord("C")), ri(MOVI, 2, 2), rr(SUB, 1, 2), out(1), halt()], b"A")
    case("and", [ri(MOVI, 1, 0x6F), ri(MOVI, 2, 0x43), rr(AND, 1, 2), out(1), halt()], b"C")
    case("or", [ri(MOVI, 1, 0x40), ri(MOVI, 2, 0x02), rr(OR, 1, 2), out(1), halt()], b"B")
    case("xor", [ri(MOVI, 1, 0x61), ri(MOVI, 2, 0x20), rr(XOR, 1, 2), out(1), halt()], b"A")
    case("shl", [ri(MOVI, 1, 0x20), rr(SHL, 1), out(1), halt()], b"@")
    case("shr", [ri(MOVI, 1, 0x82), rr(SHR, 1), out(1), halt()], b"A")

    # 条件分岐 (CMP r1, r2 のフラグで判定)
    for a, b, expect in (
        (5, 5, {JZ: 1, JNZ: 0, JG: 0, JL: 0, JA: 0, JB: 0}),
        (5, 3, {JZ: 0, JNZ: 1, JG: 1, JL: 0, JA: 1, JB: 0}),
        (3, 5, {JZ: 0, JNZ: 1, JG: 0, JL: 1, JA: 0, JB: 1}),
        # -1 と 1: 符号付きでは小さく、符号なしでは大きい
        (-1, 1, {JZ: 0, JNZ: 1, JG: 0, JL: 1, JA: 1, JB: 0}),
    ):
        for op, taken in expect.items():
            name = {JZ: "jz", JNZ: "jnz", JG: "jg", JL: "jl", JA: "ja", JB: "jb"}[op]
            prog, out_expected = branch(cmp_setup(a, b), op, taken)
            case(f"cmp_{a}_{b}_{name}", prog, out_expected)

    # MOVI の結果が 0 なら Z が立つ
    prog, expected = branch([ri(MOVI, 1, 0)], JZ, True)
    case("movi_zero_sets_z", prog, expected)

    # 後ろ向きの分岐でループ: 'a', 'b', 'c' を出す
    case("loop_backward", [
        ri(MOVI, 1, 3),
        ri(MOVI, 4, 1),
        ri(MOVI, 3, ord("a")),
        out(3),               # loop:
        rr(ADD, 3, 4),
        rr(SUB, 1, 4),
        jmp(JNZ, -12),        # -> loop
        halt(),
    ], b"abc")

    # ST: 後ろの命令を書き換えて、実行結果で書き込みを確かめる
    patched = ri(MOVI, 1, ord("S"))
    prog = load32(2, addr_of(5)) + load32(3, patched) + [
        rr(ST, 2, 3),
        ri(MOVI, 1, ord("N")),  # index 5: ここが movi r1, 'S' に変わる
        out(1),
        halt(),
    ]
    case("st_word", prog, b"S")

    # STB: index 5 の命令 movi r2, 'S' の 2 バイト目 (reg1 の下位ビット) だけを
    # 書き換えて movi r1, 'S' にする。他のバイトが壊れると 'S' にならない
    placeholder = ri(MOVI, 2, ord("S"))
    lane2 = (((placeholder >> 16) & 0xFF) & ~0x60) | (1 << 5)
    prog = [ri(MOVI, 1, ord("N"))] + load32(2, addr_of(5) + 2) + [
        ri(MOVI, 3, lane2),
        rr(STB, 2, 3),
        placeholder,           # index 5
        out(1),
        halt(),
    ]
    case("stb_lane2", prog, b"S")

    # SWP: r1 に古い値、メモリに r1 の値
    code = [ri(MOVI, 1, ord("B")), ri(MOVI, 4, ord("C"))]
    code_len = len(code) + 2 + 5
    data_addr = addr_of(code_len)
    code += load32(2, data_addr) + [
        rr(SWP, 1, 2),         # r1 = 'A', mem = 'B'
        rr(SWP, 4, 2),         # r4 = 'B', mem = 'C'
        out(1),
        out(4),
        halt(),
    ]
    assert len(code) == code_len
    case("swp", code + [ord("A")], b"AB")

    # CAS: 一致すれば書き込み、しなければ書き込まない。どちらも古い値を返す
    code = [
        ri(MOVI, 1, ord("A")),
        ri(MOVI, 2, ord("B")),
        ri(MOVI, 4, ord("X")),
        ri(MOVI, 5, ord("Z")),
        ri(MOVI, 6, ord("Q")),
    ]
    code_len = len(code) + 2 + 7
    data_addr = addr_of(code_len)
    code += load32(3, data_addr) + [
        rr(CAS, 1, 2, 3),      # 一致: r1 = 'A', mem = 'B'
        rr(CAS, 4, 5, 3),      # 不一致: r4 = 'B', mem はそのまま
        rr(SWP, 6, 3),         # r6 = 'B' (mem が 'Z' になっていない)
        out(1),
        out(4),
        out(6),
        halt(),
    ]
    assert len(code) == code_len
    case("cas", code + [ord("A")], b"ABB")

    # スタック RAM: リセット直後の SP (0x7FFFFFFF) の直下に PUSH できる。
    # LD を使わず SWP で読み戻す
    case("push_then_swp", [
        ri(MOVI, 1, ord("B")),
        rr(PUSH, 1),
        rr(MOV, 2, 9),         # r2 = SP
        rr(SWP, 3, 2),         # r3 = PUSH した値
        out(3),
        halt(),
    ], b"B")
    # STB でスタック領域の 1 バイトだけを書く
    case("stack_stb_swp", load32(2, 0x7FFFFF01) + [
        ri(MOVI, 3, ord("B")),
        rr(STB, 2, 3),
        rr(SWP, 4, 2),         # r4 = 0x00004200
        rr(SHR, 4), rr(SHR, 4), rr(SHR, 4), rr(SHR, 4),
        rr(SHR, 4), rr(SHR, 4), rr(SHR, 4), rr(SHR, 4),
        out(4),
        halt(),
    ], b"B")
    # 以前から使えた 0x7FFF0000 付近もそのまま使える
    case("stack_low_region", load32(2, 0x7FFF0000) + [
        ri(MOVI, 3, ord("L")),
        rr(ST, 2, 3),
        rr(SWP, 4, 2),
        out(4),
        halt(),
    ], b"L")

    # LD: 読んだデータではなく命令の reg1 に入る
    case("ld_word", with_data(lambda d: load32(2, d) + [
        rr(LD, 4, 2),
    ] + emit_word(4) + [halt()], [0x44434241]), b"ABCD")
    # 上位 6 ビットが LDB (0x1C) と同じデータでも語として読む
    case("ld_word_with_ldb_bits", with_data(lambda d: load32(2, d) + [
        rr(LD, 4, 2),
    ] + emit_word(4) + [halt()], [0x70434241]), b"ABCp")
    # ST したものを LD で読み戻す
    case("st_then_ld", with_data(lambda d: load32(2, d) + [
        ri(MOVI, 3, ord("A")),
        rr(ST, 2, 3),
        rr(LD, 4, 2),
        out(4),
        halt(),
    ], [0]), b"A")
    # LD の結果が 0 なら Z が立つ
    case("ld_zero_sets_z", with_data(lambda d: load32(2, d) + [
        ri(MOVI, 5, 1),        # Z をいったん下ろす
        rr(LD, 4, 2),
        jmp(JZ, 12),
        ri(MOVI, 5, ord("N")),
        jmp(JMP, 8),
        ri(MOVI, 5, ord("Y")),
        out(5),
        halt(),
    ], [0]), b"Y")

    # LDB: 各バイトレーン
    case("ldb_lanes", with_data(lambda d: load32(2, d) + [
        rr(LDB, 4, 2), out(4), ri(ADDIS, 2, 1),
        rr(LDB, 4, 2), out(4), ri(ADDIS, 2, 1),
        rr(LDB, 4, 2), out(4), ri(ADDIS, 2, 1),
        rr(LDB, 4, 2), out(4),
        halt(),
    ], [0x44434241]), b"ABCD")
    # LDB はゼロ拡張する
    case("ldb_zero_extends", with_data(lambda d: load32(2, d + 1) + [
        rr(LDB, 4, 2),
    ] + emit_word(4) + [halt()], [0xFFFFC1FF]), b"\xc1\x00\x00\x00")
    case("stack_stb_ldb", load32(2, 0x7FFFFF02) + [
        ri(MOVI, 3, ord("C")),
        rr(STB, 2, 3),
        rr(LDB, 4, 2),
        out(4),
        halt(),
    ], b"C")

    # PUSH / POP: 後に入れたものから出てくる
    case("push_pop", [
        ri(MOVI, 1, ord("A")),
        ri(MOVI, 2, ord("B")),
        rr(PUSH, 1),
        rr(PUSH, 2),
        rr(POP, 4),
        rr(POP, 5),
        out(4),
        out(5),
        halt(),
    ], b"BA")

    # IN: ハーネスは I/O の読み出しに 0 を返す。結果は命令の reg1 に入る
    case("in", [
        ri(MOVI, 4, ord("X")),
        ri(MOVI, 5, ord("A")),
        ri(IN, 4, 0),          # r4 = 0
        rr(ADD, 4, 5),
        out(4),
        halt(),
    ], b"A")

    # CHK: r1 < imm なら続行、そうでなければ停止
    case("chk_pass", [ri(MOVI, 1, 3), ri(CHK, 1, 4), ri(MOVI, 5, ord("P")), out(5), halt()], b"P")
    case("chk_fail_halts",
         [ri(MOVI, 5, ord("P")), out(5), ri(MOVI, 1, 4), ri(CHK, 1, 4), out(5), halt()], b"P")


# --- 実行 ---
HALTED_SUFFIX = b"\n[Simulator] CPU Halted.\n"


def run_program(vcpu, workdir, name, prog):
    """プログラムを実行して UART 出力を返す。失敗時は AssertionError"""
    path = os.path.join(workdir, name + ".bin")
    with open(path, "wb") as f:
        for word in prog:
            f.write(struct.pack("<I", word & 0xFFFFFFFF))
    return run_file(vcpu, path, len(prog) * 4)


def run_file(vcpu, path, size):
    res = subprocess.run([vcpu, path], capture_output=True, timeout=TIMEOUT_SEC)
    if res.returncode != 0:
        raise AssertionError(f"exit code {res.returncode}: {res.stderr!r}")
    header = f"[Simulator] Loaded {size} bytes from {path}\n".encode()
    if not res.stdout.startswith(header):
        raise AssertionError(f"unexpected header: {res.stdout[:200]!r}")
    if not res.stdout.endswith(HALTED_SUFFIX):
        raise AssertionError(f"CPU did not halt: {res.stdout[-200:]!r}")
    return res.stdout[len(header):-len(HALTED_SUFFIX)]


def test_hello(vcpu, workdir):
    path = os.path.join(REPO_ROOT, "hello.bin")
    got = run_file(vcpu, path, os.path.getsize(path))
    if got != b"Hello, World!\n":
        raise AssertionError(f"got {got!r}")


def test_default_program(vcpu, workdir):
    res = subprocess.run([vcpu], capture_output=True, timeout=TIMEOUT_SEC)
    if res.returncode != 0:
        raise AssertionError(f"exit code {res.returncode}")
    lines = res.stdout.decode().splitlines()
    # PUSH (10 + 20 = 0x1e) と、その値を読む POP
    for want in ("Tick:  7 | Write Addr: 0x7ffffffb <- Data: 0x1e (Mask: 0xf)",
                 "Tick: 10 | Read  Addr: 0x7ffffffb -> Data: 0x1e"):
        if want not in lines:
            raise AssertionError(f"missing {want!r} in {lines!r}")


ROM_SIZE = 1024 * 1024


def test_rom_exactly_full(vcpu, workdir):
    path = os.path.join(workdir, "full.bin")
    with open(path, "wb") as f:
        f.write(struct.pack("<II", ri(MOVI, 1, ord("F")), out(1)))
        f.write(struct.pack("<I", halt()))
        f.write(b"\0" * (ROM_SIZE - 12))
    got = run_file(vcpu, path, ROM_SIZE)
    if got != b"F":
        raise AssertionError(f"got {got!r}")


def test_rom_too_large(vcpu, workdir):
    path = os.path.join(workdir, "too_large.bin")
    with open(path, "wb") as f:
        f.write(struct.pack("<I", halt()))
        f.write(b"\0" * (ROM_SIZE - 4 + 4))
    res = subprocess.run([vcpu, path], capture_output=True, timeout=TIMEOUT_SEC)
    if res.returncode == 0:
        raise AssertionError("expected a non-zero exit code")
    if b"too large" not in res.stderr:
        raise AssertionError(f"unexpected stderr: {res.stderr!r}")


SPECIAL_TESTS = [
    ("hello_bin", test_hello),
    ("rom_exactly_full", test_rom_exactly_full),
    ("rom_too_large", test_rom_too_large),
    ("default_program", test_default_program),
]


def main():
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("vcpu", nargs="?", default=os.path.join(REPO_ROOT, "Vcpu"))
    parser.add_argument("-k", dest="pattern", default="", help="名前にこの文字列を含むテストだけ実行")
    args = parser.parse_args()
    vcpu = os.path.abspath(args.vcpu)
    if not os.access(vcpu, os.X_OK):
        print(f"Vcpu が見つかりません: {vcpu} (先に make でビルドしてください)", file=sys.stderr)
        return 2

    build_cases()
    passed = failed = 0
    with tempfile.TemporaryDirectory(prefix="cpu-tests-") as workdir:
        jobs = [(name, lambda n=name, p=prog, e=expected: check(vcpu, workdir, n, p, e))
                for name, prog, expected in TESTS]
        jobs += [(name, lambda f=fn: f(vcpu, workdir)) for name, fn in SPECIAL_TESTS]
        for name, job in jobs:
            if args.pattern not in name:
                continue
            try:
                job()
            except (AssertionError, subprocess.TimeoutExpired) as e:
                failed += 1
                print(f"FAIL {name}: {e}")
            else:
                passed += 1
                print(f"ok   {name}")
    print(f"\n{passed} passed, {failed} failed")
    return 1 if failed else 0


def check(vcpu, workdir, name, prog, expected):
    got = run_program(vcpu, workdir, name, prog)
    if got != expected:
        raise AssertionError(f"expected {expected!r}, got {got!r}")


if __name__ == "__main__":
    sys.exit(main())
