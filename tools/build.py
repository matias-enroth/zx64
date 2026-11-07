#!/usr/bin/env python3
"""Build zx64, zx128 and zx128vic: patch your ZX81 ROM, assemble both sides, make the d64s.

    tools/build.py [--target zx64|zx128|zx128vic|all] rom/zx81.rom [game.p ...]

all (the default) builds all three. zx64 writes build/zx64.d64, and the rest in build/obj/:
  zx81.prg   the boot file: a stub (c64/stub.asm) that loads zx64.prg,
             and on a JiffyDOS drive the monitor too, and starts it
  zx64.prg   the 6510 loader at $0801, your ROM (patched) at $1000, the
             Z80 code at $3000 (Z80 $0000 and $2000), the JiffyDOS
             reader at $3E00 and zx64's second area behind it (start puts
             both in place: the area at $E500, Z80 ZX64HI)
  zx64.d64   the boot file and zx64, the monitor (zx64mon, zx64mon2), the test
             programs (progs/*.bas, made into .p files here) and the .p
             files given, as plain PRGs
  zx64mon.prg, zx64mon2.prg  the monitor's two parts (C64 $4000, $F000)
  zx64.lbl, zx64mon.lbl      labels, for VICE's monitor and make test

zx128 writes build/zx128.d64 (with a C128 boot sector: it starts by
itself), and in build/obj/:
  zx128.prg  the 8502's side (c128/boot128.asm) at $1300, the payload
             behind it: the patched ROM, the Z80 code (z80/zx128.asm),
             the VDC's fonts (made from the ROM's)
  zx128.lbl  its labels; build/obj/zx128/ the test programs built for it
and the function ROM (the C128 starts zx128 from it, no disk):
  build/zx128.rom  32K for $8000-$FFFF: c128/from.asm, an unpacker,
             and zx128.prg's bytes packed (extras/zx0/zx0.py: ZX0) up against
             it (an EPROM for U36, the internal function ROM, or the
             Ultimate)
  build/zx128.crt  the same as a C128 cartridge, one 32K CHIP at $8000
             (the Ultimate's); zx128-vice.crt in build/obj, two 16K
             CHIPs at $8000 and $C000 (VICE's x128 -cartcrt)

zx128vic writes build/zx128vic.d64 (a C128 boot sector too): zx128 with
zx64's picture on the VIC's 40 columns (z80/zx128vic.asm, boot128 with
VDC=0), and build/obj/zx128vic.prg, zx128vic.lbl, and its pieces and
test programs in build/obj/zx128vic/; and its function ROM as zx128's:
build/zx128vic.rom, build/zx128vic.crt (one 32K CHIP) and build/obj/
zx128vic-vice.crt (two 16K), from.asm's from.bin in build/obj/zx128vic/
(FAST, the unpack at 2 MHz, off).

Each .p file given is looked through by tools/pcheck.py first, and what
may not work on zx64 is printed (a warning only: it still goes on the
d64).

Needs GNU z80asm, acme and c1541 (from VICE). The Makefile runs this.

Every ROM patch checks the bytes it replaces, so a ROM other than the
standard one (8192 bytes, md5 db398d4e4e93a6d4dee3bfe146918219) is refused
unless it has the same code at all eleven places.

    tools/build.py --check-zx64

(make test's first step) compares zx64's five files in build/obj that
don't depend on the games (zx81.prg, zx64.prg, zx64mon.prg, zx64mon2.prg,
jcore.bin) with the blessed sums, tools/zx64.sha256, and fails if any
differs: zx64's bytes stay as blessed until a change to zx64 says so, by
blessing them again:

    tools/build.py --bless-zx64

(writes tools/zx64.sha256 from the current build/obj files; only after
checking what changed, and say it in the commit). Only for a build from
the standard ROM (build/obj/zx64-rom.md5, the last zx64 build's); for
another --check-zx64 says it skipped them and --bless-zx64 refuses.
"""
import argparse
import glob
import hashlib
import os
import re
import subprocess
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
for _d in ("tools", "extras/zx0", "extras/zxbasic"):    # (the extras build.py uses)
    sys.path.insert(0, os.path.join(ROOT, _d))
from zxbasic import CHARS, p_file  # noqa: E402
import pcheck  # noqa: E402
BUILD = os.path.join(ROOT, "build")
OBJ = os.path.join(BUILD, "obj")                # everything but the d64
ZX81_MD5 = "db398d4e4e93a6d4dee3bfe146918219"   # the standard ("improved") ROM
ZX64_SUMS = os.path.join(ROOT, "tools", "zx64.sha256")   # zx64's build/obj files as last blessed (--check-zx64, --bless-zx64)
ZX64_FILES = ["zx81.prg", "zx64.prg", "zx64mon.prg", "zx64mon2.prg", "jcore.bin"]   # the five that don't depend on the games

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


def kshift_inc():
    """The ZX81 keys a C64 key presses with SHIFT (DEL is SHIFT 0): (ZX81 row,
    key bit, C64 column, C64 row bit) each, 0 at the end. The type-ahead
    gives such a key SHIFT only while that C64 key is down."""
    out = [f"        db ${keys[1][0]:02X}, ${1 << keys[1][1]:02X}, {pa}, ${1 << pb:02X}"
           for (pa, pb), keys in KEYMAP if len(keys) == 2 and keys[0] == (0xFE, 0)]
    return "\n".join(out) + "\n        db 0\n"


def zx2pet():
    """ZX81 character codes 0-63 -> PETSCII, for file names."""
    t = [ord('_')] * 64                     # graphics: PETSCII left arrow
    t[0] = ord(' ')
    for i, ch in zip(range(11, 28), '"\\$:?()><=+-*/;,.'):   # PETSCII $5C is the pound sign
        t[i] = ord(ch)
    for i in range(10):
        t[28 + i] = ord('0') + i
    for i in range(26):
        t[38 + i] = ord('A') + i
    return t


def zx2pet_inc():
    """zx2pet() for codes 0-27: setname works out the digits and letters."""
    t = zx2pet()
    assert all(t[c] == c + 20 for c in range(28, 38)) and all(t[c] == c + 27 for c in range(38, 64))
    return "".join(f"        db ${v:02X}\n" for v in t[:28])


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
SPECIAL = {"DEL": (20, 148), "RETURN": (13, 141), "CRSRRIGHT": (29, 157), "CRSRDOWN": (17, 145),
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


# The version of all three builds (zx64, zx128, zx128vic): zx64's top row as
# it starts and the monitors' titles (verstr), zx128vic's greeting, zx128's panel.
VERSION = "1.2"

# The settings' messages, shown on the top row: the text, then the key.
# msg_1k, msg_16k and msg_32k must follow each other (F8 counts on it), and
# so must msg_col0-5 (F2).
MESSAGES = [
    ("msg_1k", "1K RAM", "F8"),
    ("msg_16k", "16K RAM", "F8"),
    ("msg_32k", "32K RAM", "F8"),
    ("msg_kbon", "TYPE-AHEAD ON", "F1"),
    ("msg_kboff", "TYPE-AHEAD OFF, AS A ZX81", "F1"),
    ("msg_nomon", "NO ZX64MON ON THE DISK", "F5"),
    ("msg_othmon", "ZX64MON: OTHER ZX64", "F5"),   # (zx64's only: ONLY64)
    ("msg_hello", f"ZX64 {VERSION}", ""),
    ("msg_col0", "BLACK ON WHITE", "F2"),
    ("msg_col1", "WHITE ON BLACK", "F2"),
    ("msg_col2", "GREEN SCREEN", "F2"),
    ("msg_col3", "AMBER SCREEN", "F2"),
    ("msg_col4", "BLACK ON GREEN", "F2"),
    ("msg_col5", "C64 COLOURS", "F2"),
    ("msg_joy", "JOYSTICK  U- D- L- R- F-", "F3"),   # joyshow fills in the keys
]
# zx128's own schemes' names (z80/panelhi.inc's pn_cols): in msgs.inc in
# zx64's msg_col0-5's place, chosen by hw128.inc's SCHEMES (4; hw64.inc's
# 6), so zx64 keeps its own bytes.
COLS128 = [("msg_col0", "WHITE ON BLACK", "F2"), ("msg_col1", "C128 COLOURS", "F2"),
           ("msg_col2", "C64 COLOURS", "F2"), ("msg_col3", "ZX81 COLOURS", "F2")]
# zx128's own text for a zx64 message (", AS A ZX81" too long for the
# panel), chosen by hw128.inc's MSGS128 (hw64.inc's 0: zx64's own bytes);
# zx128vic's too (hwvic128.inc's MSGS128 2), and its own greeting at the
# start, its name and the C128 builds' version (zx128's
# panel says them on its row 0: build_zx128's ver128.inc).
TEXT128 = {"msg_kboff": "TYPE-AHEAD OFF"}
# zx64's own messages (MSGS128 0), not in the C128 builds' msgs.inc: F5's
# zx64mon from another build (the C128 builds' monitor is resident)
ONLY64 = {"msg_othmon"}
TEXTVIC = {"msg_hello": f"ZX128VIC {VERSION}"}


# The joystick's keys on the top row (joyshow): one character a ZX81 key,
# 5 a row in the row selects' order $FE $FD $FB $F7 $EF $DF $BF $7F, then
# one for none. Inverse as the message is, but SHIFT, NEWLINE and SPACE
# plain (S, N, a space), so they stand out from the S and N keys.
KEYROWS = [["SHIFT", "Z", "X", "C", "V"], list("ASDFG"), list("QWERT"), list("12345"),
           list("09876"), list("POIUY"), ["NEWLINE", "L", "K", "J", "H"], ["SPACE", ".", "M", "N", "B"]]


def keychr_inc():
    plain = {"SHIFT": "S", "NEWLINE": "N", "SPACE": " "}
    codes = [CHARS[plain[k]] if k in plain else CHARS[k] | 0x80 for row in KEYROWS for k in row]
    codes.append(CHARS["-"] | 0x80)
    return "keychr:\n" + "".join(f"        db {', '.join(f'${c:02X}' for c in codes[i:i + 8])}\n"
                                 for i in range(0, len(codes), 8))


# Words for the top row while the 6510 loads or saves (lstat): 8 ZX81
# characters each, inverse.
WORDS = [("txt_load", "LOADING "), ("txt_save", "SAVING  "), ("txt_mon", "ZX64MON "), ("txt_rom", "ZX81 ROM")]


def msg_db(label, text, key):
    """A message's label and bytes for msgs_inc."""
    assert len(f" {text}".ljust(29 - len(key)) + f"  {key} ") == 32, text
    assert key == "" or (len(key) == 2 and key[0] == "F"), key
    return [f"{label}:", "        db " + ",".join([str(len(text))] + [f"${CHARS[c] | 0x80:02X}" for c in text]
                                              + [f"${CHARS[key[1]] | 0x80:02X}" if key else "0"])]


def msgs_inc():
    """Each message kept short, ZX81 characters, inverse: its text's length
    and text, then its key's digit (F and the digit; 0: no key). zx64's msgx
    makes the top row of it, " text ... key ", 32 characters."""
    out = []
    for label, text, key in MESSAGES:
        if label == "msg_col0":
            out.append(f"        if SCHEMES = {len(COLS128)}")
            for lb, tx, ky in COLS128:
                out += msg_db(lb, tx, ky)
            out.append("        else")
        if label in ONLY64:
            out.append("        if MSGS128 = 0")
            out += msg_db(label, text, key)
            out.append("        endif")
        elif label in TEXT128:
            out.append("        if MSGS128")
            out += msg_db(label, TEXT128[label], key)
            out.append("        else")
            out += msg_db(label, text, key)
            out.append("        endif")
        elif label in TEXTVIC:
            out.append("        if MSGS128 = 2")
            out += msg_db(label, TEXTVIC[label], key)
            out.append("        else")
            out += msg_db(label, text, key)
            out.append("        endif")
        else:
            out += msg_db(label, text, key)
        if label == "msg_col5":
            out.append("        endif")
    for label, word in WORDS:
        assert len(word) == 8, word
        out.append(f"{label}:")
        out.append("        db " + ",".join(f"${CHARS[c] | 0x80:02X}" for c in word))
    return "\n".join(out) + "\n"


# Why F7 or F8 didn't read the ROM again: the 6510 puts one on the top row.
ROMMSGS = [("rm_none", "ROM NOT RELOADED: NO ZX64"), ("rm_err", "ROM NOT RELOADED: DISK ERROR"),
           ("rm_other", "ROM NOT RELOADED: OTHER ZX64"), ("rm_z64t", "ZX64 CHANGED: LOAD IT AGAIN")]


def romsg_a():
    """ROMMSGS for c64/boot.asm (acme): ZX81 characters, inverse, 0 ended."""
    out = ["rmsgs:"]
    for label, text in ROMMSGS:
        assert len(text) <= 30, text
        out.append(f"{label}: !byte " + ",".join(f"${CHARS[c] | 0x80:02X}" for c in text) + ",0")
    return "\n".join(out) + "\n"


# zx128's disk (c128/boot128.asm): the panel's rows 13 and 14,
# 16 characters each, while the 8502 loads or saves, and its messages.
WORDS128 = [("w_load", " LOADING "), ("w_save", " SAVING  ")]
# Why F7 or F8 didn't put the ROM back: (label, row 13, row 14), into
# show's MSGBUF.
ROMMSGS128 = [("rm_none", "ROM NOT RELOADED", " NO ZX128"), ("rm_err", "ROM NOT RELOADED", " DISK ERROR"),
              ("rm_other", "ROM NOT RELOADED", " OTHER ZX128"), ("rm_chg", " ZX128 CHANGED:", " LOAD IT AGAIN")]
# zx128vic's: on the top row as zx64's (ROMMSGS), the text from column 1,
# its own name in them. "OTHER ZX128VIC" doesn't fit: OTHER BUILD.
ROMMSGSVIC = [("rm_none", "ROM NOT RELOADED: NO ZX128VIC"), ("rm_err", "ROM NOT RELOADED: DISK ERROR"),
              ("rm_other", "ROM NOT RELOADED: OTHER BUILD"), ("rm_chg", "ZX128VIC CHANGED: LOAD IT AGAIN")]


def patches_load128(sym):
    """zx128's game patches at LOAD: (what, [(address, the bytes
    there, what goes there)]). The 8502 puts a game's in only if all of
    its bytes are there, below E_LINE, and takes them out again for SAVE.
    zx64 needs none of them: its IN reads RAM on every row, and its OUTs
    land where they always did."""
    def call(a): return [0xCD, a & 0xFF, a >> 8]
    keys = [0x6088, 0x6093, 0x609E, 0x64B9, 0x64C3, 0x64CD, 0x64D8, 0x6516, 0x6549, 0x6565, 0x6592, 0x65C5,
            0x6654, 0x6671]
    return [
        # IN A,($FE) with A = $DF (the Y-P row) reads I/O 2 on the C128, 0:
        # P held, the game paused. The menu's LD A,$DF / IN A,($FE) reads
        # the IN mirror's $DF row instead, LD A,($DFFE) / NOP; the game's
        # LD A,(HL) / IN A,($FE), the row from its key table ($40EF), calls
        # inrow; REDEFINE KEYS' IN A,(C), row by row, calls zxin (its loop
        # made a byte shorter, JR for JP).
        ("BoulderL: the Y-P row", [(0x75A7, "3E DF DB FE", [0x3A, 0xFE, 0xDF, 0x00])]
         + [(a, "7E DB FE", call(sym["inrow"])) for a in keys]
         + [(0x7A83, "01 FE FE ED 78 2F E6 1F C2 93 7A CB 08 C3 86 7A",
             [0x01, 0xFE, 0xFE] + call(sym["zxin"]) + [0x2F, 0xE6, 0x1F, 0xC2, 0x93, 0x7A, 0xCB, 0x08, 0x18, 0xF3])]),
        # its AY's data, OUT ($0F),A, writes A*256+$0F: zx128's own area
        # ($CC0F, $CD0F), colour RAM ($D80F), common RAM ($F80F)
        # (outscan); now nothing. Its register select, OUT ($DF),A, A 2 to
        # 10, lands in the ROM's copy only (F7 puts it back), as on zx64.
        ("aydemo: OUT ($0F),A", [(0x42FE, "78 D3 DF 79 D3 0F C9", [0x78, 0xD3, 0xDF, 0x79, 0x00, 0x00, 0xC9])]),
    ]


def disk128_a(sym, vic=False):
    """c128/boot128.asm's disk tables (acme): pet2zx (PETSCII $20-$5F to
    ZX81 codes, for the name and the drive's status: zx2pet's other way,
    '?' for what it has not), the rows' words (set 1's inverse ZX81 codes;
    vic, zx128vic's: the inverse ZX81 codes themselves, for the VIC's top
    row), the ROM's messages (32 ZX81 codes, inverse, as show's MSGBUF;
    vic: ROMMSGSVIC's, zx64's way) and the load patches (ptab: a game's
    count of entries, then each: its address, length, the bytes there,
    the new ones; 0 ends)."""
    back = {}
    for c, p in enumerate(zx2pet()):
        back.setdefault(p, c)
    back[ord('_')] = 0x08                         # (every graphic is '_': the grey one back)
    pet = [back.get(p, CHARS['?']) for p in range(0x20, 0x60)]
    out = ["pet2zx: !byte " + ",".join(f"${v:02X}" for v in pet)]
    for label, word in WORDS128:
        assert len(word) == 9, word
        out.append(f"{label}: !byte " + ",".join(f"${CHARS[c] | (0x80 if vic else 0x40):02X}" for c in word))
    if vic:
        for label, text in ROMMSGSVIC:
            assert len(text) <= 31, text
            out.append(f"{label}: !byte " + ",".join(f"${CHARS[c] | 0x80:02X}" for c in f" {text}".ljust(32)))
    else:
        for label, top, bottom in ROMMSGS128:
            assert len(top) <= 16 and len(bottom) <= 16, (top, bottom)
            out.append(f"{label}: !byte " + ",".join(f"${CHARS[c] | 0x80:02X}"
                                                     for c in top.ljust(16) + bottom.ljust(16)))
    out.append("ptab:")
    for what, entries in patches_load128(sym):
        out.append(f"; {what}")
        out.append(f"        !byte {len(entries)}")
        for addr, old, new in entries:
            old = bytes.fromhex(old)
            assert len(old) == len(new) and old != bytes(new), hex(addr)
            out.append(f"        !word ${addr:04X}")
            out.append(f"        !byte {len(old)}, " + ",".join(f"${b:02X}" for b in old) + ", "
                       + ",".join(f"${b:02X}" for b in new))
    out.append("        !byte 0")
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
                 "  macOS: brew install z80asm acme vice\n"
                 "  Ubuntu, Debian: apt install z80asm acme vice (Debian: VICE is in contrib)\n"
                 "  Fedora: dnf install z80asm, VICE from RPM Fusion, acme from source\n"
                 "  (docs/manual.md, Building and booting)")
    if r.returncode:
        sys.exit(f"{' '.join(cmd)} failed:\n{r.stdout}{r.stderr}")
    return r.stdout


def labels(path):
    return {m.group(1).lower(): int(m.group(2), 16)
            for m in re.finditer(r"^(\w+):\s+equ\s+\$([0-9A-Fa-f]+)", open(path).read(), re.M)}


def assemble_z80(src, out, lbl, inc=None):
    """z80asm src to out, labels to lbl (the .inc files are looked for in inc
    if given, build/obj and z80/); returns the labels, name (lower case) ->
    address. (z80asm looks in the -I folders last given first.)"""
    first = ["-I", inc] if inc else []
    run(Z80ASM, "-I", OBJ, "-I", os.path.join(ROOT, "z80"), *first, "-o", out, f"--label={lbl}", src)
    return labels(lbl)


def patches128(sym):
    """zx128's own, after patches(): the command table's CLS and SCROLL
    through z80/vdcpic.inc's hooks, which note them for the VDC's block
    fill and copy; SLOW and FAST through z80/panel.inc's, for the panel's
    row 23."""
    def dw(a): return [a & 0xFF, a >> 8]
    return [
        (0x0C96, "2A 0A", dw(sym["cls_hook"]), "the CLS command: the ROM's, then the VDC's block fill"),
        (0x0CA5, "0E 0C", dw(sym["scr_hook"]), "the SCROLL command: the ROM's, then the VDC's block copy"),
        (0x0CAC, "2B 0F", dw(sym["slow_hook"]), "the SLOW command: the ROM's, then the panel's row 23"),
        (0x0CAF, "23 0F", dw(sym["fast_hook"]), "the FAST command: the ROM's, then the panel's row 23"),
    ]


def patch_rom(rom, sym, which=patches):
    """A copy of rom with which(sym) (patches) in. Each place is checked
    first: a ROM that doesn't have the code zx64 patches is refused
    (SystemExit)."""
    rom = bytearray(rom)
    bad = []
    for addr, was, new, why in which(sym):
        want = bytes.fromhex(was)
        if rom[addr:addr + len(want)] != want:
            bad.append(f"  ${addr:04X} {why}: expected {was}, found "
                       f"{rom[addr:addr + len(want)].hex(' ').upper()}")
        rom[addr:addr + len(new)] = bytes(new)
    if bad:
        sys.exit("this ROM doesn't have the code zx64 patches:\n" + "\n".join(bad))
    return rom


def write_d64(path, files, boot_sector=None, label="zx64,81"):
    """A d64 at path (name,id label) with files, (host path, name on the disk)
    each, as plain PRGs. boot_sector (256 bytes: a C128 boots from it) goes to
    track 1 sector 0: written and marked used in
    the BAM before the first file, so c1541 never gives that sector to one
    (it fills track 1 last, on a nearly full disk)."""
    check_disknames(files)
    for d in (os.path.dirname(os.path.abspath(path)), OBJ):
        os.makedirs(d, exist_ok=True)
    args = [C1541, "-format", label, "d64", path]
    if boot_sector is not None:
        assert len(boot_sector) == 256, len(boot_sector)
        sect = os.path.join(OBJ, "bootsect.bin")
        open(sect, "wb").write(boot_sector)
        # track 1's BAM entry (18/0 offset 4) is 21 free, FF FF 1F after the
        # format: now 20 free, sector 0's bit clear
        args += ["-bwrite", sect, "1", "0", "-bpoke", "18", "0", "4", "20", "254"]
        run(*args)                                # c1541 has its own BAM until it exits: the files in a second run
        args = [C1541, path]
    for host, name in files:
        args += ["-write", host, name]
    if len(args) > 2:
        run(*args)


def write_incs(rom):
    """The .inc files both zx64.asm and zx128.asm include, into build/obj."""
    os.makedirs(OBJ, exist_ok=True)
    open(os.path.join(OBJ, "keymap.inc"), "w").write(keymap_inc())
    open(os.path.join(OBJ, "kshift.inc"), "w").write(kshift_inc())
    open(os.path.join(OBJ, "zx2pet.inc"), "w").write(zx2pet_inc())
    open(os.path.join(OBJ, "msgs.inc"), "w").write(msgs_inc())
    open(os.path.join(OBJ, "keychr.inc"), "w").write(keychr_inc())
    open(os.path.join(OBJ, "rom.inc"), "w").write(   # the K-GRAPH byte zx64 borrows
        f"KALL_ROM: equ ${rom[0x00FE]:02X}\n")


TARGETS = ("zx64", "zx128", "zx128vic")


def target_lines(text, target, where=""):
    """A .bas file's lines for target (TARGETS): a line starting "[t1,t2] "
    is kept, without its tag, only for the targets named; the rest for
    every one. A tag naming anything else stops the build (where: the
    file, for the message)."""
    assert target in TARGETS, target
    out = []
    for n, line in enumerate(text.splitlines(keepends=True), 1):
        m = re.match(r"\[([^]]*)\] ?", line)
        if m:
            tags = m.group(1).split(",")
            if not tags or any(t not in TARGETS for t in tags):
                sys.exit(f"{where}:{n}: [{m.group(1)}]: a line's tag names targets, of {', '.join(TARGETS)}")
            if target not in tags:
                continue
            line = line[m.end():]
        out.append(line)
    return "".join(out)


def build_progs(sym, outdir, target):
    """The test programs (progs/*.bas, with the machine code of progs/*.asm),
    as .p files in outdir, with sym's addresses for their {label}s, each
    with target's lines (target_lines); returns their paths."""
    blobs, psym = {}, dict(sym)                   # machine code for the test programs' REMs
    for asm in sorted(glob.glob(os.path.join(ROOT, "progs", "*.asm"))):
        name = os.path.splitext(os.path.basename(asm))[0]
        out, lb = os.path.join(outdir, name + ".bin"), os.path.join(outdir, name + ".lbl")
        run(Z80ASM, "-o", out, f"--label={lb}", asm)
        blobs[name] = open(out, "rb").read()
        psym.update(labels(lb))
    progs = []                                    # the test programs, with the core's addresses
    for bas in sorted(glob.glob(os.path.join(ROOT, "progs", "*.bas"))):
        p = os.path.join(outdir, os.path.splitext(os.path.basename(bas))[0] + ".p")
        open(p, "wb").write(p_file(target_lines(open(bas).read(), target, os.path.relpath(bas, ROOT)), psym, blobs))
        progs.append(p)
    return progs


def diskname(p):
    """A .p file's name on the d64: its file name in lower case, only the
    letters and digits (what LOAD "NAME" can type on a ZX81 and the disk
    takes plainly), at most 16; said when it differs from the file's."""
    base = os.path.splitext(os.path.basename(p))[0]
    name = re.sub(r"[^a-z0-9]", "", base.lower())[:16]
    if not name:
        sys.exit(f"{p}: no letters or digits in its name for the disk")
    if name != base.lower():
        print(f"{os.path.basename(p)}: on the disk as {name} (LOAD \"{name.upper()}\")")
    return name


def check_disknames(files):
    """Two files with the same name on the d64: stop, naming both."""
    seen = {}
    for p, name in files:
        if name in seen:
            sys.exit(f"{os.path.basename(seen[name])} and {os.path.basename(p)} would both be "
                     f"{name} on the disk: rename one")
        seen[name] = p


JSTAGE = 0x3E00                 # C64: the JiffyDOS reader in ZX64, then zx64's second area,
JSTAGE_END = 0x4000             # both staged in the keyboard page and the mailbox; zx64mon
                                # comes to $4000 on a JiffyDOS drive (c64/stub.asm)


def zx64_parts(sym, blob, jlen):
    """zx64's Z80 code (blob, as z80asm packed it) as its two areas: the core
    (from $2000, to coreend, below KPAGE) and the second area (from ZX64HI,
    to hiend, below ZX64HIEND), and the C64 address start stages the second
    area at, behind the JiffyDOS reader (jlen bytes at JSTAGE): it must end by
    JSTAGE_END. Stops the build past any of those ends."""
    n = sym["coreend"] - 0x2000
    core, hi = blob[:n], blob[n:]
    if 0x2000 + len(core) > 0x2E00:
        sys.exit(f"Z80 code is {len(core)} bytes: it runs into the keyboard page at $2E00")
    if sym["hiend"] > sym["zx64hiend"]:
        sys.exit(f"zx64's second area ends at ${sym['hiend']:04X}: past ZX64HIEND (${sym['zx64hiend']:04X}), "
                 f"where the monitor's stack needs room")
    if not hi or sym["zx64hi"] + len(hi) != sym["hiend"]:
        sys.exit(f"zx64's second area: {len(hi)} bytes after the core, but ZX64HI ${sym['zx64hi']:04X} "
                 f"to hiend ${sym['hiend']:04X}")
    stage = JSTAGE + jlen
    if stage + len(hi) > JSTAGE_END:
        sys.exit(f"zx64's second area is {len(hi)} bytes: behind the JiffyDOS reader (${stage:04X}) the boot "
                 f"file carries {JSTAGE_END - stage}, to ${JSTAGE_END:04X}, where the monitor comes")
    return bytearray(core), bytes(hi), stage


def mbuf64_ok(msym, sym):
    """zx64's monitor buffers (MBUF, z80/mon.asm's LINERV to kprev + 8) end
    below the second area (ZX64HI)."""
    if msym["kprev"] + 8 > sym["zx64hi"]:
        sys.exit(f"the monitor's buffers end at ${msym['kprev'] + 8:04X}: into zx64's second area at ZX64HI "
                 f"(${sym['zx64hi']:04X})")


def build_stamp(blob, mon, mon2):
    """zx64's build stamp (16 bits, never 0): from its Z80 code (blob: the
    core and the second area, as patched, the stamp's own word still 0) and
    the monitor's two parts (theirs 0 too). Any change of the addresses the
    monitor calls, or of the monitor, gives another; the same sources and
    ROM the same. mon_here enters zx64mon only with it beside both tags."""
    h = hashlib.sha256(b"zx64" + bytes(blob) + b"mon" + bytes(mon) + b"mon2" + bytes(mon2)).digest()
    return int.from_bytes(h[:2], "little") or 1


def build_zx64(rom, games):
    """build/zx64.d64 and build/obj/*: rom is the ZX81 ROM (8192 bytes, checked
    by main), games the .p files for the disk."""
    write_incs(rom)
    open(os.path.join(OBJ, "zx64-rom.md5"), "w").write(hashlib.md5(rom).hexdigest() + "\n")   # (--check-zx64)
    z80bin = os.path.join(OBJ, "zx64.bin")
    lbl = os.path.join(OBJ, "zx64.lbl")
    sym = assemble_z80(os.path.join(ROOT, "z80", "zx64.asm"), z80bin, lbl)
    blob = bytearray(open(z80bin, "rb").read())

    # the monitor, zx64mon: two PRGs, for C64 $4000 and $F000 (Z80 $3000
    # and $E000), which zx64 loads the first time F5 is pressed
    open(os.path.join(OBJ, "core.inc"), "w").write(
        f"MON_RET: equ ${sym['mon_ret']:04X}\nMONIFF: equ ${sym['moniff']:04X}\n"
        f"NOTBAD: equ ${sym['notbad']:04X}\nCREAD: equ ${sym['cread']:04X}\nMON128: equ 0\n"
        + "".join(f"{n.upper()}: equ ${sym[n]:04X}\n" for n in ("bp_off", "bpcnt", "bptab", "monwhy",
                                                                  "call6510", "mbox", "setcol", "ghosty")))
    open(os.path.join(OBJ, "version.inc"), "w").write(f'verstr: db "{VERSION}",0\n')
    open(os.path.join(OBJ, "monkeys.inc"), "w").write(monkeys_inc())
    monbin, monlbl = os.path.join(OBJ, "zx64mon.bin"), os.path.join(OBJ, "zx64mon.lbl")
    msym = assemble_z80(os.path.join(ROOT, "z80", "mon.asm"), monbin, monlbl)
    mcols_ok(msym)
    mbuf64_ok(msym, sym)
    monall = open(monbin, "rb").read()                # both parts, packed
    n1 = msym["part1end"] - 0x3000
    mon, mon2 = monall[:n1], monall[n1:]
    if msym["part1end"] > 0x4000:
        sys.exit(f"the monitor's part 1 ends at ${msym['part1end']:04X}: past $3000-$3FFF")
    if msym["monend"] > 0xEFFA:
        sys.exit(f"the monitor's part 2 ends at ${msym['monend']:04X}: into the vectors at $EFFA")
    o = sym["monsz"] - 0x2000                     # their sizes into zx64, for the bar
    blob[o:o + 4] = len(mon).to_bytes(2, "little") + len(mon2).to_bytes(2, "little")
    rom = patch_rom(rom, sym)
    rsum = sum(rom[5:0x2000]) & 0xFFFF            # the patched ROM's sum, for F7's and F8's check
    o = sym["romsum_v"] - 0x2000
    blob[o:o + 2] = rsum.to_bytes(2, "little")

    stamp = build_stamp(blob, mon, mon2)          # this build's, in zx64 and both parts (mon_here)
    mon, mon2 = bytearray(mon), bytearray(mon2)
    for buf, at in ((blob, sym["mstamp"] - 0x2000 - (sym["zx64hi"] - sym["coreend"])),
                    (mon, msym["mstamp"] - 0x3000), (mon2, msym["mstamp2"] - msym["part2"])):
        buf[at:at + 2] = stamp.to_bytes(2, "little")
    monprg = os.path.join(OBJ, "zx64mon.prg")
    open(monprg, "wb").write(bytes([0x00, 0x40]) + mon)       # C64 $4000
    monprg2 = os.path.join(OBJ, "zx64mon2.prg")
    open(monprg2, "wb").write(bytes([0x00, 0xF0]) + mon2)     # C64 $F000

    jcorebin = os.path.join(OBJ, "jcore.bin")   # the JiffyDOS reader, at $3E00; its
    run(ACME, "-f", "plain", "--symbollist", os.path.join(OBJ, "jcore.sym"),   # labels
        "-o", jcorebin, os.path.join(ROOT, "c64", "jcore.asm"))                  # for boot.asm
    jcore = open(jcorebin, "rb").read()
    core, hi, stage = zx64_parts(sym, blob, len(jcore))   # the second area: behind jcore

    bootbin = os.path.join(OBJ, "boot.bin")
    open(os.path.join(OBJ, "romsg.a"), "w").write(romsg_a())
    run(ACME, "-f", "plain", "-I", OBJ, f"-DROMSUM={rsum}", f"-DROMSUMV={sym['romsum_v'] + 0x1000}",
        f"-DMSGBUF={sym['msgbuf'] + 0x1000}", f"-DHISTAGE={stage}", f"-DHILEN={len(hi)}",
        f"-DHIDEST={sym['zx64hi'] + 0x1000}", "-o", bootbin, os.path.join(ROOT, "c64", "boot.asm"))
    boot = open(bootbin, "rb").read()

    mem = bytearray(0x4000)                       # C64 $0000-$3FFF
    mem[0x0801:0x0801 + len(boot)] = boot
    mem[0x1000:0x3000] = rom                      # Z80 $0000
    mem[0x3000:0x3000 + len(core)] = core         # Z80 $2000
    mem[JSTAGE:JSTAGE + len(jcore)] = jcore       # the keyboard page and the mailbox
    mem[stage:stage + len(hi)] = hi               # needn't load, but carry jcore and the
    end = stage + len(hi)                         # second area for start
    prg = bytes([0x01, 0x08]) + bytes(mem[0x0801:end])
    prgpath = os.path.join(OBJ, "zx64.prg")      # ZX64: what the boot file loads
    open(prgpath, "wb").write(prg)
    stubpath = os.path.join(OBJ, "zx81.prg")     # ZX81: the boot file, a stub
    run(ACME, "-f", "cbm", "-I", os.path.join(ROOT, "c64"), "-o", stubpath, os.path.join(ROOT, "c64", "stub.asm"))
    stub = open(stubpath, "rb").read()

    progs = build_progs(sym, OBJ, "zx64")

    for p in games:                               # the games: what may not work on zx64
        lines = pcheck.summary(p)[0]
        print("\n".join(["pcheck: " + lines[0]] + ["      " + x for x in lines[1:]]))

    d64 = os.path.join(BUILD, "zx64.d64")
    files = [(stubpath, "zx81"), (prgpath, "zx64"), (monprg, "zx64mon"), (monprg2, "zx64mon2")]
    for p in progs + games:
        files.append((p, diskname(p)))
    write_d64(d64, files)
    print(f"build/obj/zx81.prg: {len(stub)} bytes, the boot file (it loads zx64, by JiffyDOS where it can)")
    print(f"build/obj/zx64.prg: {len(prg)} bytes (6510 loader {len(boot)}, ROM 8192, Z80 code {len(core)} "
          f"+ {len(hi)} at ${sym['zx64hi']:04X}, JiffyDOS reader {len(jcore)})")
    hiroom = min(sym["zx64hiend"] - sym["hiend"], JSTAGE_END - end)
    print(f"build/obj/zx64mon.prg, zx64mon2.prg: the monitor, {len(mon)} + {len(mon2)} bytes")
    print(f"zx64's spare: core {0x2E00 - sym['coreend']}, zx64's second area {hiroom} spare "
          f"({sym['zx64hiend'] - sym['hiend']} to ZX64HIEND ${sym['zx64hiend']:04X}, the boot file carries "
          f"{JSTAGE_END - end} more to ${JSTAGE_END:04X}), the monitor's part 1 {0x4000 - msym['part1end']}, "
          f"part 2 {0xEFFA - msym['monend']}, its buffers {sym['zx64hi'] - msym['kprev'] - 8}")
    print(f"build/zx64.d64: the boot file, {len(progs)} test program(s) and {len(games)} more")


# Text in set 1 (codes 128-223, ASCII $20-$7F): the ZX81's own glyph where
# it has the character (zxbasic.CHARS), else these, 8 rows each, drawn
# for zx128 in the ZX81's manner (strokes one pixel wide, a clear row at
# the top and the bottom). $7F is blank.
TEXT_GLYPHS = {
    "!": "00 10 10 10 10 00 10 00", "#": "00 24 7E 24 24 7E 24 00", "%": "00 62 64 08 10 26 46 00",
    "&": "00 30 48 30 54 48 34 00", "'": "00 08 10 00 00 00 00 00", "@": "00 3C 4A 56 5E 40 3C 00",
    "[": "00 1C 10 10 10 10 1C 00", "\\": "00 00 40 20 10 08 04 00", "]": "00 38 08 08 08 08 38 00",
    "^": "00 10 28 44 00 00 00 00", "_": "00 00 00 00 00 00 00 7E", "`": "00 10 08 00 00 00 00 00",
    "{": "00 0C 08 30 08 08 0C 00", "|": "00 10 10 10 10 10 10 00", "}": "00 30 10 0C 10 10 30 00",
    "~": "00 00 00 32 4C 00 00 00", "\x7f": "00 00 00 00 00 00 00 00",
    "a": "00 00 38 04 3C 44 3C 00", "b": "00 40 40 78 44 44 78 00", "c": "00 00 38 40 40 40 38 00",
    "d": "00 04 04 3C 44 44 3C 00", "e": "00 00 38 44 78 40 3C 00", "f": "00 0C 10 38 10 10 10 00",
    "g": "00 00 3C 44 44 3C 04 38", "h": "00 40 40 78 44 44 44 00", "i": "00 10 00 30 10 10 38 00",
    "j": "00 04 00 04 04 04 24 18", "k": "00 40 48 50 60 50 48 00", "l": "00 30 10 10 10 10 38 00",
    "m": "00 00 68 54 54 54 54 00", "n": "00 00 78 44 44 44 44 00", "o": "00 00 38 44 44 44 38 00",
    "p": "00 00 78 44 44 78 40 40", "q": "00 00 3C 44 44 3C 04 04", "r": "00 00 5C 60 40 40 40 00",
    "s": "00 00 3C 40 38 04 78 00", "t": "00 20 78 20 20 20 1C 00", "u": "00 00 44 44 44 44 38 00",
    "v": "00 00 44 44 28 28 10 00", "w": "00 00 44 54 54 54 28 00", "x": "00 00 44 28 10 28 44 00",
    "y": "00 00 44 44 44 3C 04 38", "z": "00 00 7C 08 10 20 7C 00",
}


def font128(rom):
    """zx128's two VDC character sets from the ROM's 64 glyphs at $1E00,
    256 glyphs of 8 bytes each (boot128 puts each in a 16-byte cell):
    set 0, the picture: code z the left half of ZX81 character z (0-63,
    128-191), z | $40 its right half, the pixels doubled; set 1:
    codes 0-63 the ZX81's characters as they are (half the picture's
    width), 64-127 their inverses, 128-223 ASCII text $20-$7F, 224-255
    blank."""
    zx = [bytes(rom[0x1E00 + 8 * i:0x1E08 + 8 * i]) for i in range(64)]

    def wide(n):                                  # 4 pixels -> 8
        return sum(3 << 2 * b for b in range(4) if n >> b & 1)
    set0 = bytearray()
    for c in range(256):
        z, inv = c & 0x3F, 0xFF if c & 0x80 else 0
        set0 += bytes(wide(r & 0x0F if c & 0x40 else r >> 4) ^ inv for r in zx[z])
    set1 = bytearray()
    for c in range(64):
        set1 += zx[c]
    for c in range(64):
        set1 += bytes(r ^ 0xFF for r in zx[c])
    for a in range(0x20, 0x80):
        ch = chr(a)
        set1 += zx[CHARS[ch]] if ch in CHARS else bytes.fromhex(TEXT_GLYPHS[ch])
    set1 += bytes(8 * 32)
    return bytes(set0 + set1)


def boot_sector(name, start):
    """A C128 boot sector (the kernal's format):
    "CBM", no extra sectors (4 zero bytes), the message ("BOOTING name..."),
    the file the kernal loads, each 0-ended, then JMP start."""
    sect = b"CBM" + bytes(4) + name + b"\0" + name + b"\0" + bytes([0x4C, start & 0xFF, start >> 8])
    return sect.ljust(256, b"\0")


def p_collapsed(p):
    """A .p file (zxbasic.p_file's, its display expanded) with its display
    collapsed, as a 1K ZX81's: 25 $76s, the pointers past it moved down."""
    p = bytearray(p)

    def w(a):
        return p[a - 0x4009] | p[a - 0x4008] << 8
    d = w(0x400C)
    cut = 24 * 33 + 1 - 25
    p[d - 0x4009:d - 0x4009 + 24 * 33 + 1] = bytes([0x76]) * 25
    for a in (0x4010, 0x4014, 0x4016, 0x401A, 0x401C):     # VARS E_LINE CH_ADD STKBOT STKEND
        v = w(a) - cut
        p[a - 0x4009:a - 0x4007] = v.to_bytes(2, "little")
    return bytes(p)


SPARE = {}                      # the last build_zx128's room left, in bytes: rom
                                # (the function ROM's, packed), own
                                # (the own area's, to $DFFD), core (to KPAGE),
                                # com (common RAM's part, to $F7FD); the monitor's:
                                # mhi (its code in common RAM, to $FBFD),
                                # mon1 (part 1, to $3FFF), mon2 (part 2, to
                                # $EFFD), mon3 (part 3, $FF05 to $FFED),
                                # mbuf (its buffers, to $FDFD)


def mcols_ok(msym):
    """The monitor's width (hw64.inc's, hw128.inc's MCOLS): rowp multiplies
    by 40 or 48 only."""
    if msym["mcols"] not in (40, 48):
        sys.exit(f"the monitor's MCOLS is {msym['mcols']}: z80/mon.asm's rowp has 40 and 48 only")


def kpage_ok(sym, who):
    """k2scan.inc's kp_keys (KPFAST 0): cmat page aligned (cmat + 8 its
    spare byte), kptab's 24 entries in one page (it steps along them by E
    alone)."""
    t = sym.get("kptab", 0x100)
    if sym["cmat"] & 0xFF or t >> 8 != (t + 23) >> 8:
        sys.exit(f"{who}: cmat (${sym['cmat']:04X}) must be page aligned and kptab (${t:04X}) in one page "
                 "(z80/k2scan.inc)")


def monitor128(sym, odir, vic=False):
    """zx64mon (z80/mon.asm) for zx128, resident: assembled with
    zx128's addresses (sym) and its screen on the VDC (MON128 1: hw128.inc,
    z80/monvdc.inc), into build/obj/mon128/; returns its two parts, for
    $3000 and $E000, and its part 3 for $FF05 (the C128 builds' own
    commands, to $FFED), and puts its room in SPARE. vic: zx128vic's, its
    screen on the VIC (MON128 2: hwvic128.inc,
    z80/monvic.inc), into build/obj/zx128vic/mon/ (odir/mon), its room in
    VSPARE."""
    who = "zx128vic" if vic else "zx128"
    mdir = os.path.join(odir, "mon" if vic else "mon128")
    os.makedirs(mdir, exist_ok=True)
    names = {"MON_RET": "mon_ret", "MONIFF": "moniff", "NOTBAD": "notbad", "CREAD": "cread", "BP_OFF": "bp_off",
             "BPCNT": "bpcnt", "BPTAB": "bptab", "MONWHY": "mon_why", "CALL6510": "mon_6510", "MBOX": "mbox",
             "GHOSTY": "ghosty", "CMAT": "cmat", "K2KEYS": "k2keys", "mon_on": "mon_on", "mon_off": "mon_off"}
    if not vic:                                   # (the VDC's screen: its rows changed onto it)
        names.update({n: n for n in ("mon_flush", "mon_all", "mon_cmd", "mon_poll")})
    open(os.path.join(mdir, "core.inc"), "w").write(
        f"MON128: equ {2 if vic else 1}\n" + "".join(f"{k}: equ ${sym[v]:04X}\n" for k, v in names.items()))
    open(os.path.join(mdir, "version.inc"), "w").write(f'verstr: db "{VERSION}",0\n')
    open(os.path.join(mdir, "monkeys.inc"), "w").write(monkeys_inc())
    base = "zx128vicmon" if vic else "zx128mon"
    monbin, monlbl = os.path.join(mdir, base + ".bin"), os.path.join(mdir, base + ".lbl")
    msym = assemble_z80(os.path.join(ROOT, "z80", "mon.asm"), monbin, monlbl, inc=mdir)
    monall = open(monbin, "rb").read()
    n1 = msym["part1end"] - 0x3000
    n2 = msym["monend"] - 0xE000
    if msym["part1end"] > 0x4000:
        sys.exit(f"{who}'s monitor's part 1 ends at ${msym['part1end']:04X}: past $3000-$3FFF")
    if msym["monend"] > 0xEFFE:
        sys.exit(f"{who}'s monitor's part 2 ends at ${msym['monend']:04X}: past $EFFD ($EFFE: IN A,($FE)'s $EF row)")
    if msym["part3"] != 0xFF05 or msym["part3end"] > 0xFFEE or len(monall) != n1 + n2 + msym["part3end"] - 0xFF05:
        sys.exit(f"{who}'s monitor's part 3 is ${msym['part3']:04X}-${msym['part3end'] - 1:04X}: it must be $FF05 to "
                 "$FFED at most ($FFEE: the Z80's entry, JP zentry)")
    mcols_ok(msym)
    if vic:                                       # its buffers from $FC00 to $FDFD at most, its stack from $FEFD
        if (msym["mbuf"] != 0xFC00 or msym["kprev"] + 8 > 0xFDFE or msym["mstack"] != 0xFEFE
                or msym["mscr"] != 0xC400 or msym["mcols"] != 40):
            sys.exit("zx128vic's monitor's buffers, stack or screen are out of place (hwvic128.inc)")
        VSPARE.update(mon1=0x4000 - msym["part1end"], mon2=0xEFFE - msym["monend"], mon3=0xFFEE - msym["part3end"],
                      mbuf=0xFDFE - msym["kprev"] - 8)
    else:
        if msym["kprev"] + 8 > 0xFDFE or msym["mstack"] != 0xFEFE or msym["mscr"] + 25 * msym["mcols"] > 0xC900:
            sys.exit("zx128's monitor's buffers, stack or screen are out of place (hw128.inc)")
        SPARE.update(mon1=0x4000 - msym["part1end"], mon2=0xEFFE - msym["monend"], mon3=0xFFEE - msym["part3end"],
                     mbuf=0xFDFE - msym["kprev"] - 8)
    return monall[:n1], monall[n1:n1 + n2], monall[n1 + n2:]


def crt128(rom, name, chips):
    """A C128 .crt (VICE's cartconv reads it; the header as the Ultimate
    takes it): generic (type 0, EXROM and GAME 0), name, and a CHIP packet
    for each (load address, size) in chips, from rom ($8000 on)."""
    out = bytearray(b"C128 CARTRIDGE  " + (0x40).to_bytes(4, "big") + b"\x02\x00" + bytes(2) + bytes(2) + bytes(6))
    out += name.ljust(32, b"\0")
    for load, size in chips:
        out += b"CHIP" + (16 + size).to_bytes(4, "big") + bytes(4) + load.to_bytes(2, "big") + size.to_bytes(2, "big")
        out += rom[load - 0x8000:load - 0x8000 + size]
    return bytes(out)


ZX0_WEIGHT = 0.035              # extras/zx0/zx0.py's weight for the function ROM's image: the
                                # bits a block may cost to save its time on the 8502 (a bit is worth
                                # 1/0.035 cycles). zx128's at 0: 24,163 bytes, the unpack ~2.1 s at
                                # 1 MHz; at 0.035: 25,404, ~1.46 s: about a second
                                # added at power-on, for a smaller image
ROM_IMG_END = 0xC000            # the image must end below $C000: the function ROM stays at $C000-$FFFF all
                                # through the unpack, so a copy from output up there would read the ROM
ROM_LAST = {}                   # the last build_rom128's: packed (bytes), image (bytes), spare


def page_room(bsym):
    """From boot128's symbols (bsym): the payload's three page cliffs, in
    bytes. page: the own area and the Z80's common-RAM part share their
    pages (phi to phi_tail, then !align), so the bytes either can still
    grow before the PRG takes a page more; prom:
    boot128's code before prom (codeend), likewise; corepg: the Z80's core
    before the !align after it (pcore_end). Whichever is passed, the PRG
    grows by 256."""
    return dict(page=-bsym["phi_tail"] % 256, prom=bsym["prom"] - bsym["codeend"],
                corepg=-bsym["pcore_end"] % 256)


def buf_room(bsym, prg, name):
    """F7 from the disk loads the whole PRG into bank 0's BUF (boot128: prom
    + $2100 to BUFEND), so it must fit there: stops if it doesn't. Returns
    the bytes spare."""
    spare = bsym["BUFEND"] - bsym["BUF"] - (len(prg) - 2)
    if spare < 0:
        sys.exit(f"{name}.prg ({len(prg) - 2} bytes) doesn't fit boot128's BUF (${bsym['BUF']:04X}-"
                 f"${bsym['BUFEND'] - 1:04X}), where F7 loads it from the disk: {-spare} bytes too many")
    return spare


def page_say(sp):
    return (f"{sp['page']} before a page more at phi..phi_tail (the own area + common RAM), {sp['prom']} in "
            f"boot128 before prom, {sp['corepg']} after the core"
            + (f"; {sp['buf']} before the PRG outgrows boot128's BUF (F7 from the disk)" if "buf" in sp else ""))


def build_rom128(prg, name="zx128", odir=None, fast=False, pages=None):
    """build/<name>.rom (zx128's, zx128vic's) from <name>.prg's bytes (prg,
    with its load address, $1300): c128/from.asm's 32K, its image packed
    (extras/zx0/zx0.py, ZX0_WEIGHT) where from.asm's STREAM says, right up
    against the unpacker's first part (PARTB, to $FEFF; its second from
    $FF05); and its two .crt files, build/<name>.crt and
    build/obj/<name>-vice.crt, named <name> in capitals. from.asm is
    assembled twice (once for PARTB, the first part's length), its
    from.bin and from.sym into odir (build/obj's by default); fast:
    from.asm's FAST, the unpack at 2 MHz; pages: page_room's, named when
    the ROM doesn't fit. Stops if it doesn't fit, or if a copy would read
    the ROM where the image is meant (zx0.phase1_reads: from.asm's
    header). Returns the bytes spare, between from.asm's code and the
    stream; ROM_LAST gets the sizes."""
    import zx0
    img = prg[2:]
    if prg[:2] != b"\x00\x13" or 0x1300 + len(img) > ROM_IMG_END:
        sys.exit(f"{name}.prg must load at $1300 and end below ${ROM_IMG_END:04X} (it ends at "
                 f"${0x1300 + len(img):04X}): the function ROM stays at $C000 while it unpacks, so a copy from "
                 f"there would read the ROM")
    odir = odir or OBJ
    fbin, fsym = os.path.join(odir, "from.bin"), os.path.join(odir, "from.sym")

    def assemble(stream, partb, n=0):
        run(ACME, "-f", "plain", "--initmem", "255", f"-DSTREAM={stream}", f"-DSTREAMLEN={n}", f"-DPARTB={partb}",
            f"-DFAST={int(fast)}", "--symbollist", fsym, "-o", fbin, os.path.join(ROOT, "c128", "from.asm"))
        return {mm.group(1): int(mm.group(2), 16) for mm in re.finditer(r"^\s*(\w+)\s*=\s*\$([0-9a-fA-F]+)",
                open(fsym).read(), re.M)}
    fsy = assemble(0x9000, 0xC000)                # (the first part's length: the same wherever it goes)
    partb = 0xFF00 - (fsy["partb_end"] - fsy["PARTB"])
    packed = zx0.pack(img, ZX0_WEIGHT)
    stream = partb - len(packed)
    room = partb - fsy["codeend"]
    if stream < fsy["codeend"]:
        sys.exit(f"the function ROM doesn't fit: {name}.prg's {len(img)} bytes packed to {len(packed)}, "
                 f"{fsy['codeend'] - stream} more than the {room} between from.asm's code (to "
                 f"${fsy['codeend'] - 1:04X}) and its unpacker (from ${partb:04X})"
                 + (f". {name}.prg grows by whole pages: {page_say(pages)} (one near 256 has just taken a page "
                    f"more; packed, a page of padding costs a few bytes)" if pages else ""))
    for at in (stream, stream - 1):               # ("CBM" at $C007 would have the kernal start that half)
        fsy = assemble(at, partb, len(packed))
        rom = bytearray(open(fbin, "rb").read())
        if len(rom) != 0x8000 or (fsy["STREAM"], fsy["PARTB"]) != (at, partb):
            sys.exit(f"c128/from.asm made {len(rom)} bytes, STREAM ${fsy['STREAM']:04X}, PARTB ${fsy['PARTB']:04X}: "
                     f"not 32K, ${at:04X}, ${partb:04X}")
        if rom[at - 0x8000:at - 0x8000 + len(packed)] != b"\xff" * len(packed) or at < fsy["codeend"]:
            sys.exit(f"c128/from.asm has code where the packed image goes (${at:04X}-${partb - 1:04X})")
        rom[at - 0x8000:at - 0x8000 + len(packed)] = packed
        if rom[0x4007:0x400A] != b"CBM":
            break
    else:
        sys.exit("the function ROM has \"CBM\" at $C007: the kernal would start its $C000 half")
    bad = zx0.phase1_reads(packed, fsy["STREAM"])
    if bad:
        sys.exit(f"the function ROM's unpack would read the ROM: {len(bad)} copies read the ROM: $8000 or above while "
                 f"the stream is still below $C000, or $C000 or above (the first to ${bad[0][0]:04X}, reading ${bad[0][1]:04X}; "
                 f"c128/from.asm's header)")
    rom = bytes(rom)
    cname = name.upper().encode()
    open(os.path.join(BUILD, f"{name}.rom"), "wb").write(rom)
    open(os.path.join(BUILD, f"{name}.crt"), "wb").write(crt128(rom, cname, [(0x8000, 0x8000)]))
    open(os.path.join(OBJ, f"{name}-vice.crt"), "wb").write(crt128(rom, cname, [(0x8000, 0x4000), (0xC000, 0x4000)]))
    spare = fsy["STREAM"] - fsy["codeend"]
    ROM_LAST.clear()
    ROM_LAST.update(packed=len(packed), image=len(img), spare=spare)
    return spare


def rom_more(spare, packed, image):
    """About how many bytes more the image can take, packed at the ratio
    it has now, in a function ROM with spare bytes left: no more than
    ROM_IMG_END allows."""
    return min(int(spare * image / packed), ROM_IMG_END - 0x1300 - image)


def rom_say(name):
    """build_rom128's last ROM in words, for the build's report."""
    r = ROM_LAST
    ratio = r["packed"] / r["image"]
    more = rom_more(r["spare"], r["packed"], r["image"])
    return (f"build/{name}.rom, {name}.crt: the same from a function ROM (32K), {name}.prg packed (ZX0) to "
            f"{r['packed']} bytes ({ratio:.3f} of its {r['image']}); {r['spare']} bytes spare: about {more} more "
            f"of {name}.prg" + (f" (to ${ROM_IMG_END:04X}, where the image must end)"
                                if more < int(r["spare"] / ratio) else " at that ratio"))


def build_zx128(rom, games):
    """build/zx128.d64 and build/obj/zx128.prg: the C128's ZX81, rom and games
    as for build_zx64. zx128.prg (boot128 at $1300, the payload behind it)
    is what the boot sector's file ZX128 holds. Returns the d64's path."""
    write_incs(rom)
    odir = OBJ
    name = f" zx128 {VERSION}"                 # (the panel's row 0: pn_row's 16 columns)
    if len(name) > 16:
        sys.exit(f"the panel's row 0, {name!r}, is {len(name)} characters: 16 at most (VERSION)")
    open(os.path.join(odir, "ver128.inc"), "w").write(f'        db 0,{len(name)},"{name}"\n')
    z80bin, lbl = os.path.join(odir, "zx128.bin"), os.path.join(odir, "zx128.lbl")
    sym = assemble_z80(os.path.join(ROOT, "z80", "zx128.asm"), z80bin, lbl, inc=odir)
    blob = open(z80bin, "rb").read()
    n = sym["coreend"] - 0x2000                   # the core, its own area, its part in common RAM,
    h = sym["hiend"] - sym["hicode"]              # (the monitor's there)
    c = n + h + sym["zcomend"] - sym["zcom"]
    core, hi, com, mhi = bytearray(blob[:n]), blob[n:n + h], blob[n + h:c], blob[c:]
    if 0x2000 + len(core) > 0x2E00:
        sys.exit(f"zx128's Z80 code is {len(core)} bytes: it runs into the keyboard page at $2E00")
    kpage_ok(sym, "zx128")
    if sym["hicode"] != 0xC900 or sym["hiend"] > 0xDFFE:
        sys.exit(f"zx128's own code area is ${sym['hicode']:04X}-${sym['hiend'] - 1:04X}: "
                 "it must be $C900 to $DFFD at most ($DFFE is IN A,($FE)'s $DF row)")
    SPARE.clear()
    SPARE.update(own=0xDFFE - sym["hiend"], core=0x2E00 - sym["coreend"])
    if sym["zentry"] != sym["zcom"] or sym["zcomend"] > 0xF7FE or sym["zcom"] + len(com) != sym["zcomend"]:
        sys.exit(f"zx128's common RAM part is {len(com)} bytes at ${sym['zentry']:04X}: ZCOM to $F7FD at most "
                 "($F7FE is IN A,($FE)'s $F7 row)")
    SPARE["com"] = 0xF7FE - sym["zcomend"]
    if sym["moncode"] != sym["pic_qend"] or sym["monend"] > 0xFBFE:
        sys.exit(f"the monitor's code in common RAM is ${sym['moncode']:04X}-${sym['monend'] - 1:04X}: it must "
                 f"start after the picture's queue (${sym['pic_qend']:04X}) and end by $FBFD ($FBFE: IN A,($FE)'s "
                 "$FB row)")
    SPARE["mhi"] = 0xFBFE - sym["monend"]
    mon1, mon2, mon3 = monitor128(sym, odir)

    rom = patch_rom(rom, sym)                     # zx64's patches, at zx128's addresses
    rom = patch_rom(rom, sym, patches128)         # and zx128's own
    rsum = sum(rom[5:0x2000]) & 0xFFFF            # for F7's and F8's check
    o = sym["romsum_v"] - 0x2000
    core[o:o + 2] = rsum.to_bytes(2, "little")
    for name, data in (("zx128rom.bin", rom), ("zx128core.bin", core), ("zx128hi.bin", hi),
                       ("zx128com.bin", com), ("zx128font.bin", font128(rom)[0xC00:0xF00]),
                       ("zx128mon1.bin", mon1), ("zx128mon2.bin", mon2), ("zx128mon3.bin", mon3),
                       ("zx128mhi.bin", mhi)):
        open(os.path.join(odir, name), "wb").write(data)
    prgpath = os.path.join(odir, "zx128.prg")
    blk = [f"-DBLK_CFG={sym['blk_cfg'] - sym['hicode']}", f"-DBLK_AT={sym['blk_at']}",
           f"-DBLK_COPYN={sym['blk_copyn']}", f"-DBLK_FILLN={sym['blk_filln']}"]
    open(os.path.join(odir, "disk128.a"), "w").write(disk128_a(sym))
    blk += [f"-DROMSUM={rsum}", f"-DROMSUMV={sym['romsum_v']}", f"-DOVL={sym['ovl']}", f"-DLKCMP={sym['lk_cmp']}",
            f"-DOVLMSG={sym['ovl_msg']}", f"-DMBOX={sym['mbox']}", f"-DMSGBUF={sym['msgbuf']}", f"-DPND={sym['pn_d']}"]
    run(ACME, "-f", "cbm", "-I", odir, "-I", os.path.join(ROOT, "c128"), "-DVDC=1", f"-DMONCODE={sym['moncode']}",
        f"-DMONUP={sym['mon_up']}", f"-DZENTRY={sym['zentry']}", f"-DHICODE={sym['hicode']}", *blk, "--symbollist",
        os.path.join(odir, "boot128.sym"), "-o", prgpath, os.path.join(ROOT, "c128", "boot128.asm"))
    prg = open(prgpath, "rb").read()
    if prg[:2] != b"\x00\x13":
        sys.exit("zx128.prg must load at $1300 (the boot sector jumps there)")
    bsym = {mm.group(1): int(mm.group(2), 16) for mm in re.finditer(r"^\s*(\w+)\s*=\s*\$([0-9a-fA-F]+)",
            open(os.path.join(odir, "boot128.sym")).read(), re.M)}
    SPARE.update(page_room(bsym))
    SPARE["buf"] = buf_room(bsym, prg, "zx128")
    pdir = os.path.join(OBJ, "zx128")             # the test programs with zx128's addresses
    os.makedirs(pdir, exist_ok=True)
    progs = build_progs(sym, pdir, "zx128")
    d64 = os.path.join(BUILD, "zx128.d64")
    files = [(prgpath, "zx128")]
    for p in progs + games:
        files.append((p, diskname(p)))
    write_d64(d64, files, boot_sector=boot_sector(b"ZX128", 0x1300), label="zx128,81")
    SPARE["rom"] = build_rom128(prg, pages=SPARE)
    print(f"build/obj/zx128.prg: {len(prg)} bytes (ROM 8192, Z80 code {len(core)} + {len(hi)} at $C900 "
          f"+ {len(com)} at $F400, font set 1's text 768: the rest made at boot; the monitor {len(mon1)} at $3000 "
          f"+ {len(mon2)} at $E000 + {len(mon3)} at $FF05 + {len(mhi)} at ${sym['moncode']:04X}); spare: core "
          f"{SPARE['core']}, own area {SPARE['own']}, common RAM {SPARE['com']}, the monitor's part 1 {SPARE['mon1']}, "
          f"part 2 {SPARE['mon2']}, part 3 {SPARE['mon3']}, its code in common RAM {SPARE['mhi']}; {page_say(SPARE)}")
    print(f"build/zx128.d64: boots on a C128; {len(progs)} test program(s) and {len(games)} more")
    print(rom_say("zx128"))
    return d64


VSPARE = {}                     # the last build_zx128vic's room left, in bytes: core
                                # (to KPAGE), own (the own area's, $D800 to $DFFD),
                                # com (common RAM's part, with the monitor's code,
                                # to $F7FD); the monitor's: mon1 (part 1, to
                                # $3FFF), mon2 (part 2, to $EFFD), mon3 (part
                                # 3, $FF05 to $FFED), mbuf (its buffers, to
                                # $FDFD); rom (the function ROM's,
                                # packed)


def build_zx128vic(rom, games):
    """build/zx128vic.d64 and build/obj/zx128vic.prg: the C128's ZX81 with
    zx64's picture on the VIC (z80/zx128vic.asm, c128/boot128.asm with
    VDC=0), rom and games as for build_zx64. zx128vic.prg (boot128 at
    $1300, the payload behind it: the patched ROM, the Z80's core, its own
    area for $D800, its part in common RAM, and zx64mon's two parts,
    resident) is what the boot sector's file ZX128VIC holds. Its pieces and
    boot128's symbols are in build/obj/zx128vic/, its labels in
    build/obj/zx128vic.lbl, the monitor's in build/obj/zx128vic/mon/.
    Returns the d64's path."""
    write_incs(rom)
    odir = os.path.join(OBJ, "zx128vic")
    os.makedirs(odir, exist_ok=True)
    z80bin, lbl = os.path.join(odir, "zx128vic.bin"), os.path.join(OBJ, "zx128vic.lbl")
    sym = assemble_z80(os.path.join(ROOT, "z80", "zx128vic.asm"), z80bin, lbl, inc=odir)
    blob = open(z80bin, "rb").read()
    n = sym["coreend"] - 0x2000                   # the core, its own area, its part in common RAM
    h = sym["hiend"] - sym["hicode"]
    core, hi, com = bytearray(blob[:n]), blob[n:n + h], blob[n + h:]
    if 0x2000 + len(core) > 0x2E00:
        sys.exit(f"zx128vic's Z80 code is {len(core)} bytes: it runs into the keyboard page at $2E00")
    kpage_ok(sym, "zx128vic")
    if sym["hicode"] != 0xD800 or sym["hiend"] > 0xDFFE or not hi:
        sys.exit(f"zx128vic's own code area is ${sym['hicode']:04X}-${sym['hiend'] - 1:04X}: "
                 "it must be $D800 to $DFFD at most ($DFFE is IN A,($FE)'s $DF row), and not empty")
    if sym["zentry"] != sym["zcom"] or sym["zcomend"] > 0xF7FE or sym["zcom"] + len(com) != sym["zcomend"]:
        sys.exit(f"zx128vic's common RAM part is {len(com)} bytes at ${sym['zentry']:04X}: ZCOM to $F7FD at "
                 "most ($F7FE is IN A,($FE)'s $F7 row)")
    VSPARE.clear()
    VSPARE.update(core=0x2E00 - sym["coreend"], own=0xDFFE - sym["hiend"], com=0xF7FE - sym["zcomend"])
    mon1, mon2, mon3 = monitor128(sym, odir, vic=True)  # zx64mon, resident

    rom = patch_rom(rom, sym)                     # zx64's patches, at zx128vic's addresses
    rsum = sum(rom[5:0x2000]) & 0xFFFF            # for F7's and F8's check
    o = sym["romsum_v"] - 0x2000
    core[o:o + 2] = rsum.to_bytes(2, "little")
    for name, data in (("zx128rom.bin", rom), ("zx128core.bin", core), ("zx128hi.bin", hi),
                       ("zx128com.bin", com), ("zx128mon1.bin", mon1), ("zx128mon2.bin", mon2),
                       ("zx128mon3.bin", mon3)):
        open(os.path.join(odir, name), "wb").write(data)
    open(os.path.join(odir, "disk128.a"), "w").write(disk128_a(sym, vic=True))
    prgpath = os.path.join(OBJ, "zx128vic.prg")
    run(ACME, "-f", "cbm", "-I", odir, "-I", os.path.join(ROOT, "c128"), "-DVDC=0",
        f"-DMONUP={sym['mon_up']}", f"-DZENTRY={sym['zentry']}", f"-DHICODE={sym['hicode']}",
        f"-DROMSUM={rsum}", f"-DROMSUMV={sym['romsum_v']}", f"-DOVL={sym['ovl']}", f"-DOVLMSG={sym['ovl_msg']}",
        f"-DMBOX={sym['mbox']}", f"-DMSGBUF={sym['msgbuf']}", "--symbollist", os.path.join(odir, "boot128.sym"),
        "-o", prgpath, os.path.join(ROOT, "c128", "boot128.asm"))
    prg = open(prgpath, "rb").read()
    if prg[:2] != b"\x00\x13":
        sys.exit("zx128vic.prg must load at $1300 (the boot sector jumps there)")
    bsym = {mm.group(1): int(mm.group(2), 16) for mm in re.finditer(
            r"^\s*(\w+)\s*=\s*\$([0-9a-fA-F]+)", open(os.path.join(odir, "boot128.sym")).read(), re.M)}
    VSPARE.update(page_room(bsym))
    VSPARE["buf"] = buf_room(bsym, prg, "zx128vic")

    progs = build_progs(sym, odir, "zx128vic")    # the test programs with zx128vic's addresses
    d64 = os.path.join(BUILD, "zx128vic.d64")
    files = [(prgpath, "zx128vic")]
    for p in progs + games:
        files.append((p, diskname(p)))
    write_d64(d64, files, boot_sector=boot_sector(b"ZX128VIC", 0x1300), label="zx128vic,81")
    # (fast=True: from.asm's FAST, the unpack at 2 MHz, saved ~0.22 s in
    # VICE as a copy; off until the ROM read at 2 MHz is seen to work on the real
    # C128, from the Ultimate's cartridge (with its "Force 2 MHz support" off)
    # and from an EPROM)
    VSPARE["rom"] = build_rom128(prg, "zx128vic", odir, fast=False, pages=VSPARE)
    print(f"build/obj/zx128vic.prg: {len(prg)} bytes (ROM 8192, Z80 code {len(core)} + {len(hi)} at $D800 "
          f"+ {len(com)} at $F400, the monitor {len(mon1)} at $3000 + {len(mon2)} at $E000 + {len(mon3)} at $FF05; "
          f"spare: core {VSPARE['core']}, own area {VSPARE['own']}, common RAM {VSPARE['com']}, the monitor's part 1 "
          f"{VSPARE['mon1']}, part 2 {VSPARE['mon2']}, part 3 {VSPARE['mon3']}, its buffers {VSPARE['mbuf']}; "
          f"{page_say(VSPARE)})")
    print(f"build/zx128vic.d64: boots on a C128, the picture on the VIC (40 columns); {len(progs)} test "
          f"program(s) and {len(games)} more")
    print(rom_say("zx128vic"))
    return d64


def check_zx64():
    """--check-zx64: zx64's build/obj files against the blessed sums
    (ZX64_SUMS), if the last zx64 build was from the standard ROM; exits 1
    if any differs."""
    try:
        md5 = open(os.path.join(OBJ, "zx64-rom.md5")).read().strip()
    except OSError:
        sys.exit("zx64's bytes: no build/obj/zx64-rom.md5 (build zx64 first: make)")
    if md5 != ZX81_MD5:
        print(f"zx64's bytes not compared with the blessed sums: built from another ROM than the standard one (md5 {md5})")
        return
    sums = dict(reversed(line.split()) for line in open(ZX64_SUMS) if line.strip())
    if sorted(sums) != sorted(ZX64_FILES):        # (a short sums file would narrow the guard)
        sys.exit(f"{os.path.relpath(ZX64_SUMS, ROOT)} holds {sorted(sums)}, not ZX64_FILES {sorted(ZX64_FILES)}: "
                 f"tools/build.py --bless-zx64 writes all of them")
    changed = []
    for name, want in sums.items():
        try:
            got = hashlib.sha256(open(os.path.join(OBJ, name), "rb").read()).hexdigest()
        except OSError:
            got = None
        if got != want:
            changed.append(name if got else name + " (missing)")
    if changed:
        sys.exit(f"zx64's bytes changed from the blessed sums: {', '.join(changed)} "
                 f"(build/obj against {os.path.relpath(ZX64_SUMS, ROOT)}; if on purpose: tools/build.py --bless-zx64)")
    print(f"zx64's bytes: as the blessed sums ({os.path.relpath(ZX64_SUMS, ROOT)})")


def bless_zx64():
    """--bless-zx64: write ZX64_SUMS from the current build/obj files (the
    same five --check-zx64 compares), from a standard-ROM build only."""
    try:
        md5 = open(os.path.join(OBJ, "zx64-rom.md5")).read().strip()
    except OSError:
        sys.exit("zx64's bytes: no build/obj/zx64-rom.md5 (build zx64 first: make)")
    if md5 != ZX81_MD5:
        sys.exit(f"not blessed: build/obj is from another ROM than the standard one (md5 {md5})")
    lines = []
    for name in ZX64_FILES:
        try:
            lines.append(f"{hashlib.sha256(open(os.path.join(OBJ, name), 'rb').read()).hexdigest()}  {name}\n")
        except OSError:
            sys.exit(f"not blessed: build/obj/{name} is missing (build zx64 first: make)")
    open(ZX64_SUMS, "w").write("".join(lines))
    print(f"zx64's bytes blessed: {os.path.relpath(ZX64_SUMS, ROOT)} ({len(lines)} files)")


def main():
    if len(sys.argv) < 2:
        sys.exit(__doc__)
    if sys.argv[1:] == ["--check-zx64"]:
        return check_zx64()
    if sys.argv[1:] == ["--bless-zx64"]:
        return bless_zx64()
    ap = argparse.ArgumentParser(usage="tools/build.py [--target zx64|zx128|zx128vic|all] rom [game.p ...]")
    ap.add_argument("--target", choices=["zx64", "zx128", "zx128vic", "all"], default="all")
    ap.add_argument("rom")
    ap.add_argument("games", nargs="*")
    a = ap.parse_args()
    rom_path = a.rom
    if not os.path.exists(rom_path):
        sys.exit(f"{rom_path}: no such file. zx64 needs your own ZX81 ROM image (8192 bytes);\n"
                 "it is not included. Put it at rom/zx81.rom (see rom/README.md) or run\n"
                 "make ROM=path/to/rom")
    rom = bytearray(open(rom_path, "rb").read())
    if len(rom) != 8192:
        sys.exit(f"{rom_path}: {len(rom)} bytes; a ZX81 ROM is 8192")
    if hashlib.md5(rom).hexdigest() != ZX81_MD5:
        print(f"note: {rom_path} is not the standard ZX81 ROM; checking the patch places")
    if a.target in ("zx64", "all"):
        build_zx64(rom, a.games)
    if a.target in ("zx128", "all"):
        build_zx128(rom, a.games)
    if a.target in ("zx128vic", "all"):
        build_zx128vic(rom, a.games)


if __name__ == "__main__":
    main()
