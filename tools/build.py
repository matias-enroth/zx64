#!/usr/bin/env python3
"""Build zx64: patch your ZX81 ROM, assemble both sides, make the d64.

    tools/build.py rom/zx81.rom [game.p ...]

Writes, in build/:
  zx81.prg   the boot file: the 6510 loader at $0801, your ROM (patched)
             at $1000 and the Z80 code at $3000 (Z80 $0000 and $2000)
  zx64.d64   the boot file, the monitor (zx64mon, zx64mon2), the test
             programs (progs/*.bas, made into .p files here) and the .p
             files given, as plain PRGs
  zx64mon.prg, zx64mon2.prg  the monitor's two parts (C64 $4000, $F000)
  zx64.lbl, zx64mon.lbl      labels, for VICE's monitor and make test

Each .p file given is looked through by tools/pcheck.py first, and what
may not work on zx64 is printed (a warning only: it still goes on the
d64).

Needs GNU z80asm, acme and c1541 (from VICE). The Makefile runs this.

Every ROM patch checks the bytes it replaces, so a ROM other than the
standard one (8192 bytes, md5 db398d4e4e93a6d4dee3bfe146918219) is refused
unless it has the same code at all eleven places.
"""
import glob
import hashlib
import os
import re
import subprocess
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "tools"))
from zxbasic import CHARS, p_file  # noqa: E402
import pcheck  # noqa: E402
BUILD = os.path.join(ROOT, "build")
ZX81_MD5 = "db398d4e4e93a6d4dee3bfe146918219"   # the standard ("improved") ROM

Z80ASM = os.environ.get("Z80ASM", "z80asm")
ACME = os.environ.get("ACME", "acme")
C1541 = os.environ.get("C1541", "c1541")

# C64 key (column = PA bit, row = PB bit) -> the ZX81 keys it presses,
# as (row select, bit). Positional: the ZX81 layout on the C64 keyboard.
KEYMAP = [
    ((1, 7), [(0xFE, 0)]), ((6, 4), [(0xFE, 0)]),                    # either SHIFT
    ((1, 4), [(0xFE, 1)]), ((2, 7), [(0xFE, 2)]), ((2, 4), [(0xFE, 3)]), ((3, 7), [(0xFE, 4)]),  # Z X C V
    ((1, 2), [(0xFD, 0)]), ((1, 5), [(0xFD, 1)]), ((2, 2), [(0xFD, 2)]), ((2, 5), [(0xFD, 3)]), ((3, 2), [(0xFD, 4)]),  # A S D F G
    ((7, 6), [(0xFB, 0)]), ((1, 1), [(0xFB, 1)]), ((1, 6), [(0xFB, 2)]), ((2, 1), [(0xFB, 3)]), ((2, 6), [(0xFB, 4)]),  # Q W E R T
    ((7, 0), [(0xF7, 0)]), ((7, 3), [(0xF7, 1)]), ((1, 0), [(0xF7, 2)]), ((1, 3), [(0xF7, 3)]), ((2, 0), [(0xF7, 4)]),  # 1 2 3 4 5
    ((4, 3), [(0xEF, 0)]), ((4, 0), [(0xEF, 1)]), ((3, 3), [(0xEF, 2)]), ((3, 0), [(0xEF, 3)]), ((2, 3), [(0xEF, 4)]),  # 0 9 8 7 6
    ((5, 1), [(0xDF, 0)]), ((4, 6), [(0xDF, 1)]), ((4, 1), [(0xDF, 2)]), ((3, 6), [(0xDF, 3)]), ((3, 1), [(0xDF, 4)]),  # P O I U Y
    ((0, 1), [(0xBF, 0)]), ((5, 2), [(0xBF, 1)]), ((4, 5), [(0xBF, 2)]), ((4, 2), [(0xBF, 3)]), ((3, 5), [(0xBF, 4)]),  # NEWLINE L K J H
    ((7, 4), [(0x7F, 0)]), ((7, 7), [(0x7F, 0)]),                    # SPACE, RUN/STOP = BREAK
    ((5, 4), [(0x7F, 1)]), ((4, 4), [(0x7F, 2)]), ((4, 7), [(0x7F, 3)]), ((3, 4), [(0x7F, 4)]),  # . M N B
    ((0, 0), [(0xFE, 0), (0xEF, 0)]),   # INST/DEL   -> RUBOUT (SHIFT 0)
    ((0, 2), [(0xFE, 0), (0xEF, 2)]),   # CRSR RIGHT -> SHIFT 8
    ((0, 7), [(0xFE, 0), (0xEF, 4)]),   # CRSR DOWN  -> SHIFT 6
    ((7, 1), [(0xFE, 0), (0xF7, 4)]),   # <- (arrow) -> SHIFT 5, left
    ((6, 6), [(0xFE, 0), (0xEF, 3)]),   # up arrow   -> SHIFT 7, up
]


def keymap_inc():
    """Per C64 column 0-7: a count, then (C64 row mask, ZX81 row, ZX81 key
    mask) entries. The Z80 skips a column with no key down in one go."""
    out = []
    for col in range(8):
        entries = [(1 << pb, row, ~(1 << bit) & 0xFF)
                   for (pa, pb), keys in KEYMAP if pa == col for row, bit in keys]
        assert 1 <= len(entries) <= 85, f"column {col}: {len(entries)} entries"
        out.append(f"        db {len(entries)}                    ; column {col}")
        out += [f"        db ${m:02X}, ${r:02X}, ${k:02X}" for m, r, k in entries]
    return "\n".join(out) + "\n"


def zx2pet_inc():
    """ZX81 character codes 0-63 -> PETSCII, for file names."""
    t = [ord('_')] * 64                     # graphics: PETSCII left arrow
    t[0] = ord(' ')
    for i, ch in zip(range(11, 28), '"\\$:?()><=+-*/;,.'):   # PETSCII $5C is the pound sign
        t[i] = ord(ch)
    for i in range(10):
        t[28 + i] = ord('0') + i
    for i in range(26):
        t[38 + i] = ord('A') + i
    return "".join(f"        db ${v:02X}\n" for v in t)


# The C64 keyboard matrix (column = PA bit, row = PB bit), for the
# monitor: each key's name, and what it gives on its own and with SHIFT,
# as PETSCII (0: nothing, as SHIFT, CTRL, C= and the other F-keys).
MATRIX = [
    ["DEL", "RETURN", "CRSRRIGHT", "F7", "F1", "F3", "F5", "CRSRDOWN"],
    ["3", "W", "A", "4", "Z", "S", "E", "LSHIFT"],
    ["5", "R", "D", "6", "C", "F", "T", "X"],
    ["7", "Y", "G", "8", "B", "H", "U", "V"],
    ["9", "I", "J", "0", "M", "K", "O", "N"],
    ["+", "P", "L", "-", ".", ":", "@", ","],
    ["POUND", "*", ";", "HOME", "RSHIFT", "=", "UPARROW", "/"],
    ["1", "LEFTARROW", "CTRL", "2", "SPACE", "C=", "Q", "RUNSTOP"],
]
SPECIAL = {"DEL": (20, 148), "RETURN": (13, 13), "CRSRRIGHT": (29, 157), "CRSRDOWN": (17, 145),
           "F5": (135, 135), "HOME": (19, 147), "SPACE": (32, 32), "RUNSTOP": (3, 3),
           "UPARROW": (0x5E, 0x5E), "LEFTARROW": (0x5F, 0x5F)}
SHIFTED = dict(zip("1234567890:;,./", "!\"#$%&'() []<>?"))


def monkeys_inc():
    """keys, keys_sh: 64 bytes each, PETSCII by column * 8 + row."""
    plain, shifted = [], []
    for col in MATRIX:
        for name in col:
            if name in SPECIAL:
                p, s = SPECIAL[name]
            elif len(name) == 1:
                p = ord(name)
                s = ord(SHIFTED.get(name, name))
            else:
                p = s = 0
            plain.append(p)
            shifted.append(s)
    return "".join(f"{label}:\n" + "".join(f"        db {', '.join(f'${v:02X}' for v in t[i:i + 8])}\n"
                                         for i in range(0, 64, 8))
                   for label, t in (("keys", plain), ("keys_sh", shifted)))


# zx64's version: on the top row as it starts, and in the monitor.
VERSION = "1.0"

# The settings' messages, shown on the top row: the text, then the key.
# msg_1k, msg_16k and msg_32k must follow each other (F3 counts on it), and
# so must msg_col0-5 (F2).
MESSAGES = [
    ("msg_1k", "1K RAM", "F3"),
    ("msg_16k", "16K RAM", "F3"),
    ("msg_32k", "32K RAM", "F3"),
    ("msg_kbon", "TYPE-AHEAD ON", "F1"),
    ("msg_kboff", "TYPE-AHEAD OFF, AS A ZX81", "F1"),
    ("msg_nomon", "NO ZX64MON ON THE DISK", "F5"),
    ("msg_hello", f"ZX64 {VERSION}", ""),
    ("msg_col0", "BLACK ON WHITE", "F2"),
    ("msg_col1", "WHITE ON BLACK", "F2"),
    ("msg_col2", "GREEN SCREEN", "F2"),
    ("msg_col3", "AMBER SCREEN", "F2"),
    ("msg_col4", "BLACK ON GREEN", "F2"),
    ("msg_col5", "C64 COLOURS", "F2"),
]


# Words for the top row while the 6510 loads or saves (lstat): 8 ZX81
# characters each, inverse.
WORDS = [("txt_load", "LOADING "), ("txt_save", "SAVING  "), ("txt_mon", "ZX64MON "), ("txt_rom", "ZX81 ROM")]


def msgs_inc():
    """Each message as 32 ZX81 characters, inverse: " text ... key "."""
    out = []
    for label, text, key in MESSAGES:
        line = f" {text}".ljust(29 - len(key)) + f"  {key} "
        assert len(line) == 32, line
        out.append(f"{label}:")
        out.append("        db " + ",".join(f"${CHARS[c] | 0x80:02X}" for c in line))
    for label, word in WORDS:
        assert len(word) == 8, word
        out.append(f"{label}:")
        out.append("        db " + ",".join(f"${CHARS[c] | 0x80:02X}" for c in word))
    return "\n".join(out) + "\n"


def patches(sym):
    """(ROM address, the bytes it holds now, what goes there, why)."""
    def jp(a): return [0xC3, a & 0xFF, a >> 8]
    def call(a): return [0xCD, a & 0xFF, a >> 8]
    return [
        (0x0000, "D3 FD", [0x00, 0x00], "reset: OUT ($FD),A, NMI off: not needed"),
        (0x0038, "0D C2 45", jp(sym["irqh"]), "INT: the display line counter -> the raster IRQ"),
        (0x0207, "21 3B 40", jp(sym["slowfast"]), "SLOW/FAST: never start the NMI display"),
        (0x0277, "D3 FF 2A 0C 40 CB", call(sym["frame"]) + jp(0x0229), "DISPLAY-1: the picture -> wait a frame"),
        (0x02BB, "21 FF FF", jp(sym["mykbd"]), "KEYBOARD: read the C64 keyboard"),
        (0x02E7, "FD CB 3B 7E", [0xF3, 0xC9], "SET-FAST: DI, RET - no interrupts, as in FAST mode"),
        (0x02F6, "CD A8 03", jp(sym["mysave"]), "SAVE: to disk"),
        (0x0340, "CD A8 03", jp(sym["myload"]), "LOAD: from disk"),
        (0x04CC, "CC 29 02", [0xCC] + jp(sym["keywait"])[1:], "the editor's key wait: FAST again after it"),
        (0x087B, "AF 5F D3 FB", [0xE1] + jp(0x08DE), "printer: skip it, still clear the buffer"),
        (0x0F46, "3E 7F DB FE", call(sym["brk"]) + [0x00], "BREAK-1: LD A,$7F / IN A,($FE)"),
    ]


def run(*cmd, cwd=None):
    try:
        r = subprocess.run(cmd, cwd=cwd, capture_output=True, text=True, errors="replace")
    except FileNotFoundError:
        sys.exit(f"{cmd[0]} not found. zx64 needs GNU z80asm, acme and c1541 (VICE):\n"
                 "  brew install z80asm acme vice   /   apt install z80asm acme vice")
    if r.returncode:
        sys.exit(f"{' '.join(cmd)} failed:\n{r.stdout}{r.stderr}")
    return r.stdout


def labels(path):
    return {m.group(1).lower(): int(m.group(2), 16)
            for m in re.finditer(r"^(\w+):\s+equ\s+\$([0-9A-Fa-f]+)", open(path).read(), re.M)}


def main():
    if len(sys.argv) < 2:
        sys.exit(__doc__)
    rom_path = sys.argv[1]
    if not os.path.exists(rom_path):
        sys.exit(f"{rom_path}: no such file. zx64 needs your own ZX81 ROM image (8192 bytes);\n"
                 "it is not included. Put it at rom/zx81.rom (see rom/README.md) or run\n"
                 "make ROM=path/to/rom")
    rom = bytearray(open(rom_path, "rb").read())
    if len(rom) != 8192:
        sys.exit(f"{rom_path}: {len(rom)} bytes; a ZX81 ROM is 8192")
    if hashlib.md5(rom).hexdigest() != ZX81_MD5:
        print(f"note: {rom_path} is not the standard ZX81 ROM; checking the patch places")

    os.makedirs(BUILD, exist_ok=True)
    open(os.path.join(BUILD, "keymap.inc"), "w").write(keymap_inc())
    open(os.path.join(BUILD, "zx2pet.inc"), "w").write(zx2pet_inc())
    open(os.path.join(BUILD, "msgs.inc"), "w").write(msgs_inc())
    open(os.path.join(BUILD, "rom.inc"), "w").write(   # the K-GRAPH byte zx64 borrows
        f"KALL_ROM: equ ${rom[0x00FE]:02X}\n")
    z80bin = os.path.join(BUILD, "zx64.bin")
    lbl = os.path.join(BUILD, "zx64.lbl")
    run(Z80ASM, "-I", BUILD, "-o", z80bin, f"--label={lbl}", os.path.join(ROOT, "z80", "zx64.asm"))
    sym = labels(lbl)
    blob = bytearray(open(z80bin, "rb").read())

    # the monitor, zx64mon: two PRGs, for C64 $4000 and $F000 (Z80 $3000
    # and $E000), which zx64 loads the first time F5 is pressed
    open(os.path.join(BUILD, "core.inc"), "w").write(
        f"MON_RET: equ ${sym['mon_ret']:04X}\nMONIFF: equ ${sym['moniff']:04X}\n"
        f"NOTBAD: equ ${sym['notbad']:04X}\nCREAD: equ ${sym['cread']:04X}\n"
        + "".join(f"{n.upper()}: equ ${sym[n]:04X}\n" for n in ("bp_off", "bpcnt", "bptab", "monwhy",
                                                                  "call6510", "mbox", "setcol", "ghosty")))
    open(os.path.join(BUILD, "version.inc"), "w").write(f'verstr: db "{VERSION}",0\n')
    open(os.path.join(BUILD, "monkeys.inc"), "w").write(monkeys_inc())
    monbin, monlbl = os.path.join(BUILD, "zx64mon.bin"), os.path.join(BUILD, "zx64mon.lbl")
    run(Z80ASM, "-I", BUILD, "-o", monbin, f"--label={monlbl}", os.path.join(ROOT, "z80", "mon.asm"))
    monall = open(monbin, "rb").read()                # both parts, packed
    msym = labels(monlbl)
    n1 = msym["part1end"] - 0x3000
    mon, mon2 = monall[:n1], monall[n1:]
    if msym["part1end"] > 0x4000:
        sys.exit(f"the monitor's part 1 ends at ${msym['part1end']:04X}: past $3000-$3FFF")
    if msym["monend"] > 0xEFFA:
        sys.exit(f"the monitor's part 2 ends at ${msym['monend']:04X}: into the vectors at $EFFA")
    o = sym["monsz"] - 0x2000                     # their sizes into zx64, for the bar
    blob[o:o + 4] = len(mon).to_bytes(2, "little") + len(mon2).to_bytes(2, "little")
    monprg = os.path.join(BUILD, "zx64mon.prg")
    open(monprg, "wb").write(bytes([0x00, 0x40]) + mon)       # C64 $4000
    monprg2 = os.path.join(BUILD, "zx64mon2.prg")
    open(monprg2, "wb").write(bytes([0x00, 0xF0]) + mon2)     # C64 $F000
    if 0x2000 + len(blob) > 0x2E00:
        sys.exit(f"Z80 code is {len(blob)} bytes: it runs into the keyboard page at $2E00")

    bad = []
    for addr, was, new, why in patches(sym):
        want = bytes.fromhex(was)
        if rom[addr:addr + len(want)] != want:
            bad.append(f"  ${addr:04X} {why}: expected {was}, found "
                       f"{rom[addr:addr + len(want)].hex(' ').upper()}")
        rom[addr:addr + len(new)] = bytes(new)
    if bad:
        sys.exit("this ROM doesn't have the code zx64 patches:\n" + "\n".join(bad))
    o = sym["romsum_v"] - 0x2000                  # the patched ROM's sum, for F7's and F3's check
    blob[o:o + 2] = (sum(rom[5:0x2000]) & 0xFFFF).to_bytes(2, "little")

    bootbin = os.path.join(BUILD, "boot.bin")
    run(ACME, "-f", "plain", "-o", bootbin, os.path.join(ROOT, "c64", "boot.asm"))
    boot = open(bootbin, "rb").read()

    mem = bytearray(0x4000)                       # C64 $0000-$3FFF
    mem[0x0801:0x0801 + len(boot)] = boot
    mem[0x1000:0x3000] = rom                      # Z80 $0000
    mem[0x3000:0x3000 + len(blob)] = blob         # Z80 $2000
    end = 0x3000 + len(blob)                      # the keyboard page and the
    prg = bytes([0x01, 0x08]) + bytes(mem[0x0801:end])   # mailbox needn't load
    prgpath = os.path.join(BUILD, "zx81.prg")
    open(prgpath, "wb").write(prg)

    blobs, psym = {}, dict(sym)                   # machine code for the test programs' REMs
    for asm in sorted(glob.glob(os.path.join(ROOT, "progs", "*.asm"))):
        name = os.path.splitext(os.path.basename(asm))[0]
        out, lb = os.path.join(BUILD, name + ".bin"), os.path.join(BUILD, name + ".lbl")
        run(Z80ASM, "-o", out, f"--label={lb}", asm)
        blobs[name] = open(out, "rb").read()
        psym.update(labels(lb))
    progs = []                                    # the test programs, with zx64's addresses
    for bas in sorted(glob.glob(os.path.join(ROOT, "progs", "*.bas"))):
        p = os.path.join(BUILD, os.path.splitext(os.path.basename(bas))[0] + ".p")
        open(p, "wb").write(p_file(open(bas).read(), psym, blobs))
        progs.append(p)

    for p in sys.argv[2:]:                        # the games: what may not work on zx64
        lines = pcheck.summary(p)[0]
        print("\n".join(["pcheck: " + lines[0]] + ["      " + x for x in lines[1:]]))

    d64 = os.path.join(BUILD, "zx64.d64")
    args = [C1541, "-format", "zx64,81", "d64", d64, "-write", prgpath, "zx81",
            "-write", monprg, "zx64mon", "-write", monprg2, "zx64mon2"]
    for p in progs + sys.argv[2:]:
        name = os.path.splitext(os.path.basename(p))[0].lower()[:16]
        args += ["-write", p, name]
    run(*args)
    print(f"build/zx81.prg: {len(prg)} bytes (6510 loader {len(boot)}, ROM 8192, Z80 code {len(blob)})")
    print(f"build/zx64mon.prg, zx64mon2.prg: the monitor, {len(mon)} + {len(mon2)} bytes")
    print(f"build/zx64.d64: the boot file, {len(progs)} test program(s) and {len(sys.argv) - 2} more")


if __name__ == "__main__":
    main()
