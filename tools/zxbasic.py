#!/usr/bin/env python3
"""ZX81 BASIC text -> a .p file, as the ROM's SAVE would write it.

    tools/zxbasic.py prog.bas out.p [build/zx64.lbl]

One BASIC line per text line, keywords spelled out as the ZX81 lists
them (PRINT, PEEK, INKEY$, <>, **). Spaces outside strings are ignored.
{name} or {name+1} is replaced by the address of a label of zx64's Z80
code, so test programs can PEEK zx64's own variables.

"10 REM {bin:name}" as the first line puts machine code there, at 16514
(USR 16514), as ZX81 programs did: build.py assembles progs/name.asm,
and its labels can be used as {name} too.

The program runs from its first line as soon as it has loaded, as one
saved by SAVE in a program line would. 16K layout: a full display file,
no variables.
"""
import re
import sys

# ZX81 character codes for what can be typed outside the keyword tokens
CHARS = {' ': 0x00, '"': 0x0B, '£': 0x0C, '$': 0x0D, ':': 0x0E, '?': 0x0F, '(': 0x10,
         ')': 0x11, '>': 0x12, '<': 0x13, '=': 0x14, '+': 0x15, '-': 0x16, '*': 0x17,
         '/': 0x18, ';': 0x19, ',': 0x1A, '.': 0x1B}
CHARS.update({str(d): 0x1C + d for d in range(10)})
CHARS.update({chr(65 + i): 0x26 + i for i in range(26)})

TOKENS = {"RND": 0x40, "INKEY$": 0x41, "PI": 0x42}
TOKENS.update({k: 0xC1 + i for i, k in enumerate(
    "AT TAB ? CODE VAL LEN SIN COS TAN ASN ACS ATN LN EXP INT SQR SGN ABS PEEK USR "
    "STR$ CHR$ NOT ** OR AND <= >= <> THEN TO STEP LPRINT LLIST STOP SLOW FAST NEW "
    "SCROLL CONT DIM REM FOR GOTO GOSUB INPUT LOAD LIST LET PAUSE NEXT POKE PRINT "
    "PLOT RUN SAVE RAND IF CLS UNPLOT CLEAR RETURN COPY".split())})
del TOKENS["?"]                                   # $C3 has no keyword
WORDS = sorted(TOKENS, key=len, reverse=True)     # longest first: INKEY$ before INT

NUMBER = 0x7E                                     # then the value in 5 bytes
NEWLINE = 0x76


def zxfloat(n):
    """A whole number 0-2^31 in the ZX81's 5-byte floating point."""
    if n == 0:
        return bytes(5)
    e = n.bit_length()
    m = (n << (32 - e)) & 0x7FFFFFFF              # top bit: the sign, +
    return bytes([0x80 + e]) + m.to_bytes(4, "big")


def tokenize(text):
    out, i = bytearray(), 0
    while i < len(text):
        c = text[i]
        if c == '"':                              # a string: characters as they are
            j = text.index('"', i + 1)
            out += bytes([0x0B] + [CHARS[ch] for ch in text[i + 1:j]] + [0x0B])
            i = j + 1
            continue
        if c == ' ':
            i += 1
            continue
        if c.isdigit():                           # a number: its digits, then its value
            m = re.match(r"\d+", text[i:])
            out += bytes(CHARS[d] for d in m.group()) + bytes([NUMBER]) + zxfloat(int(m.group()))
            i += m.end()
            continue
        for w in WORDS:
            if text.startswith(w, i):
                alpha = w[0].isalpha()
                after = text[i + len(w):i + len(w) + 1]
                before = text[i - 1:i] if i else ""
                if alpha and (before.isalnum() or (after.isalnum() and not w.endswith("$"))):
                    continue                      # part of a longer name
                out.append(TOKENS[w])
                i += len(w)
                break
        else:
            out.append(CHARS[c])
            i += 1
    return bytes(out)


def p_file(source, sym=None, blobs=None):
    sym, blobs = sym or {}, blobs or {}

    def label(m):
        expr = m.group(1).strip()
        name, _, add = expr.partition("+")
        return str(sym[name.strip().lower()] + int(add or 0))

    prog = bytearray()
    for n, line in enumerate(source.splitlines(), 1):
        line = re.sub(r"\{(?!bin:)([^}]+)\}", label, line).strip()
        if not line:
            continue
        m = re.match(r"(\d+)\s*(.*)", line)
        if not m:
            raise ValueError(f"line {n}: no line number: {line!r}")
        mc = re.fullmatch(r"REM\s*\{bin:(\w+)\}", m.group(2))
        if mc:                                    # machine code in a REM, at 16514
            code = blobs[mc.group(1)]
            if prog:
                raise ValueError(f"line {n}: machine code goes in the first line, at 16514")
            if NEWLINE in code:
                raise ValueError(f"line {n}: {mc.group(1)} has a ${NEWLINE:02X}, which would end the line")
            body = bytes([TOKENS["REM"]]) + code + bytes([NEWLINE])
        else:
            body = tokenize(m.group(2)) + bytes([NEWLINE])
        prog += int(m.group(1)).to_bytes(2, "big") + len(body).to_bytes(2, "little") + body

    PROG = 0x407D
    d_file = PROG + len(prog)
    dfile = bytes([NEWLINE]) + (bytes(32) + bytes([NEWLINE])) * 24
    vars_ = d_file + len(dfile)
    e_line = vars_ + 1

    sv = bytearray(PROG - 0x4009)
    def w(a, v, size=2):
        sv[a - 0x4009:a - 0x4009 + size] = v.to_bytes(size, "little")
    w(0x400C, d_file)                             # D_FILE
    w(0x400E, d_file + 1)                         # DF_CC
    w(0x4010, vars_)                              # VARS
    w(0x4014, e_line)                             # E_LINE
    w(0x4016, e_line - 1)                         # CH_ADD
    w(0x401A, e_line)                             # STKBOT
    w(0x401C, e_line)                             # STKEND
    w(0x401F, 0x405D)                             # MEM: MEMBOT
    w(0x4022, 2, 1)                               # DF_SZ: the lower screen
    w(0x4025, 0xFFFF)                             # LAST_K: no key
    w(0x4028, 55, 1)                              # MARGIN: PAL
    w(0x4029, PROG)                               # NXTLIN: run from the first line
    w(0x4034, 0xFFFF)                             # FRAMES
    w(0x4038, 0xBC, 1)                            # PR_CC
    w(0x4039, 0x1821)                             # S_POSN: top left
    w(0x403B, 0x40, 1)                            # CDFLAG: SLOW
    sv[0x405C - 0x4009] = NEWLINE                 # PRBUFF ends in a NEWLINE
    return bytes(sv) + bytes(prog) + dfile + bytes([0x80])


def main():
    if len(sys.argv) < 3:
        sys.exit(__doc__)
    sym = {}
    if len(sys.argv) > 3:
        sym = {m.group(1).lower(): int(m.group(2), 16) for m in
               re.finditer(r"^(\w+):\s+equ\s+\$([0-9A-Fa-f]+)", open(sys.argv[3]).read(), re.M)}
    open(sys.argv[2], "wb").write(p_file(open(sys.argv[1]).read(), sym))


if __name__ == "__main__":
    main()
