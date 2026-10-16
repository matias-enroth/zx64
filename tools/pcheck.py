#!/usr/bin/env python3
"""Look through ZX81 .p files for what may not work on zx64.

    tools/pcheck.py [-v] game.p ...

make runs it on every .p file it puts on the d64 (games/, P=) and
prints what it finds; -v also lists what is fine.

On the cartridge, IN and OUT are memory accesses: IN A,(n) reads memory
at A*256+n, OUT (n),A writes A there. zx64 puts the keyboard rows where
IN A,($FE) reads them, so a game that reads the keyboard itself works;
any other port reads or writes whatever memory its address lands on.
This follows the machine code from the program's USR calls (USR 16514,
USR VAL "16514") and, for each IN and OUT, works back to the value of A
(or B and C) where it can, then says what that access does on zx64.
Machine code it can't reach that way (computed jumps, code copied
elsewhere, USR with a variable) isn't checked: IN/OUT-like bytes outside
the code it followed are counted, and listed with -v.

Also: LD I,A (a hi-res or own character set display), IM 2, a USR into
zx64's own code, and programs too big for 16K.
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from zxbasic import TOKENS  # noqa: E402

BASE = 0x4009                                    # where a .p file loads
REM, USR, VAL = TOKENS["REM"], TOKENS["USR"], TOKENS["VAL"]
NUMBER, NEWLINE, QUOTE, LPAREN = 0x7E, 0x76, 0x0B, 0x10
DIGITS = range(0x1C, 0x26)
R = ["B", "C", "D", "E", "H", "L", None, "A"]    # register by its 3-bit code
PAIRS = [("B", "C"), ("D", "E"), ("H", "L"), None]   # BC DE HL SP
ROWS = {0xFE: "SHIFT-V", 0xFD: "A-G", 0xFB: "Q-T", 0xF7: "1-5",
        0xEF: "0-6", 0xDF: "P-Y", 0xBF: "NEWLINE-H", 0x7F: "SPACE-B"}
PORTS = {0xFE: "the keyboard / NMI on", 0xFD: "NMI off", 0xFF: "the end of the sync pulse",
         0xFB: "the ZX printer", 0x07: "the ZXpand", 0x17: "the ZXpand",
         0xCF: "an AY sound chip, as on the ZXpand+", 0x0F: "an AY sound chip, as on the ZXpand+"}
DEVICES = {0xFB: "the ZX printer", 0x07: "the ZXpand", 0x17: "the ZXpand",
           0xCF: "an AY sound chip", 0x0F: "an AY sound chip"}


OUTPORTS = (0xFD, 0xFE, 0xFF, 0xFB, 0xCF, 0x0F)   # OUT (n),A worth counting outside the code


def rel(d):
    return d - 256 if d > 127 else d


class Program:
    def __init__(self, data):
        self.data = data
        self.end = BASE + len(data)
        self.eline = self.word(0x4014) or self.end
        self.end = min(self.end, self.eline)      # LOAD stops at E_LINE

    def byte(self, a):
        return self.data[a - BASE] if BASE <= a < self.end else None

    def word(self, a):
        lo, hi = self.byte(a), self.byte(a + 1)
        return None if lo is None or hi is None else lo | hi << 8

    def lines(self):
        """(line number, address of its body, body) for each BASIC line."""
        a, dfile = 0x407D, self.word(0x400C) or self.end
        while a + 4 <= min(dfile, self.end):
            n = self.data[a - BASE] << 8 | self.data[a + 1 - BASE]
            ln = self.word(a + 2)
            yield n, a + 4, self.data[a + 4 - BASE:a + 4 - BASE + ln]
            a += 4 + ln

    def usrs(self):
        """(line, address or None) for each USR in the BASIC."""
        for n, _, body in self.lines():
            if not body or body[0] == REM:
                continue
            i = 0
            while i < len(body):
                c = body[i]
                if c == NUMBER:
                    i += 6
                    continue
                if c == QUOTE:
                    j = body.find(bytes([QUOTE]), i + 1)
                    i = len(body) if j < 0 else j + 1
                    continue
                if c == USR:
                    yield n, usr_arg(body, i + 1)
                i += 1


def zxfloat(b):
    if b[0] == 0:
        return 0
    m = int.from_bytes(b[1:5], "big") | 0x80000000
    v = m * 2.0 ** (b[0] - 160)
    return -v if b[1] & 0x80 else v


def usr_arg(body, i):
    """USR's argument if it is a plain number or VAL "number", else None."""
    while i < len(body) and body[i] == LPAREN:
        i += 1
    if i < len(body) and body[i] == VAL and i + 1 < len(body) and body[i + 1] == QUOTE:
        j = body.find(bytes([QUOTE]), i + 2)
        s = body[i + 2:j]
        if j > 0 and s and all(c in DIGITS for c in s):
            return int("".join(str(c - 0x1C) for c in s))
        return None
    j = i
    while j < len(body) and (body[j] in DIGITS or body[j] == 0x1B):   # digits and .
        j += 1
    if j > i and j + 5 < len(body) and body[j] == NUMBER:
        v = zxfloat(body[j + 1:j + 6])
        if v == int(v) and 0 <= v < 65536:
            return int(v)
    return None


# ---------------------------------------------------------------- Z80
def uses_mem(op):
    """Does this unprefixed instruction use (HL)? (Then DD/FD give it a displacement.)"""
    x, y, z = op >> 6, op >> 3 & 7, op & 7
    return (x == 0 and z in (4, 5, 6) and y == 6) or (x == 1 and (y == 6 or z == 6) and op != 0x76) \
        or (x == 2 and z == 6)


def operands(op):
    """Operand bytes after an unprefixed opcode (CB and ED handled apart)."""
    x, y, z, q, p = op >> 6, op >> 3 & 7, op & 7, op >> 3 & 1, op >> 4 & 3
    if x == 0:
        if z == 0:
            return 1 if y >= 2 else 0             # DJNZ, JR: a displacement
        if z == 1:
            return 2 if q == 0 else 0             # LD rp,nn
        if z == 2:
            return 2 if p >= 2 else 0             # LD (nn),HL/A, LD HL/A,(nn)
        return 1 if z == 6 else 0                 # LD r,n
    if x in (1, 2):
        return 0
    return {0: 0, 1: 0, 2: 2, 3: 2 if y == 0 else 1 if y in (2, 3) else 0,
            4: 2, 5: 2 if q and p == 0 else 0, 6: 1, 7: 0}[z]


class Instr:
    """One decoded instruction: its bytes, how control goes on, and what it
    does to the registers this tool follows (A, B, C, D, E, H, L)."""

    def __init__(self, prog, a):
        self.a, self.flow, self.target, self.text, self.effect = a, "next", None, None, {}
        self.io = None                            # ("in"/"out", port spec)
        b = [prog.byte(a + i) for i in range(4)]
        if b[0] is None:
            raise ValueError
        op, idx = b[0], 0
        if op in (0xDD, 0xFD):
            if b[1] is None:
                raise ValueError
            if b[1] in (0xDD, 0xFD, 0xED):
                self.n = 1                        # a prefix on its own: as a NOP
                return
            idx, op = 1, b[1]
            if op == 0xCB:
                self.n = 4
                self.effect = None if False else {r: None for r in "BCDEHLA"}
                return
        if op == 0xCB and not idx:
            self.n = 2
            if b[1] is None:
                raise ValueError
            x, z = b[1] >> 6, b[1] & 7
            if x != 1 and z != 6:
                self.effect = {R[z]: None}
            return
        if op == 0xED and not idx:
            self.ed(prog, a, b)
            return
        disp = 1 if idx and uses_mem(op) else 0
        k = operands(op)
        self.n = idx + 1 + disp + k
        o = a + idx + 1 + disp                    # first operand byte
        for i in range(k):
            if prog.byte(o + i) is None:
                raise ValueError
        n8 = prog.byte(o) if k else None
        n16 = prog.word(o) if k == 2 else None
        x, y, z, q, p = op >> 6, op >> 3 & 7, op & 7, op >> 3 & 1, op >> 4 & 3
        e = {}
        if x == 0:
            if z == 0:
                if y == 1:
                    e = {"A": None}
                elif y == 2:
                    self.flow, self.target, e = "branch", a + self.n + rel(n8), {"B": None}
                elif y == 3:
                    self.flow, self.target = "jump", a + self.n + rel(n8)
                elif y >= 4:
                    self.flow, self.target = "branch", a + self.n + rel(n8)
            elif z == 1 and p < 3:
                e = dict(zip(PAIRS[p], [("n", n16 >> 8), ("n", n16 & 255)])) if q == 0 \
                    else {"H": None, "L": None}
            elif z == 2 and q == 1:
                if p < 2:
                    e = {"A": None}               # LD A,(BC), LD A,(DE)
                elif p == 2:
                    e = {"L": ("mem", n16), "H": ("mem", n16 + 1)}
                else:
                    e = {"A": ("mem", n16)}
            elif z == 3 and p < 3:
                e = dict.fromkeys(PAIRS[p])
            elif z in (4, 5) and y != 6:
                e = {R[y]: None}
            elif z == 6 and y != 6:
                e = {R[y]: ("n", n8)}
            elif z == 7 and y <= 5:
                e = {"A": None}
        elif x == 1:
            if op == 0x76:
                self.text = "HALT"
            elif y != 6:
                e = {R[y]: ("hl",) if z == 6 else ("reg", R[z])}
        elif x == 2:
            if y != 7:
                e = {"A": ("n", 0) if z == 7 and y in (2, 5) else None}   # SUB A, XOR A
        else:
            if z == 0:
                self.flow = "next"                # RET cc
            elif z == 1:
                if q == 0:
                    e = dict.fromkeys(PAIRS[p] if p < 3 else ("A",))
                elif p == 0:
                    self.flow = "end"             # RET
                elif p == 1:
                    e = dict.fromkeys("BCDEHL")   # EXX
                elif p == 2:
                    self.flow, self.text = "end", "JP (HL)"
            elif z == 2:
                self.flow, self.target = "branch", n16
            elif z == 3:
                if y == 0:
                    self.flow, self.target = "jump", n16
                elif y == 2:
                    self.text, self.io = f"OUT (${n8:02X}),A", ("out", ("A", n8))
                elif y == 3:
                    self.text, self.io, e = f"IN A,(${n8:02X})", ("in", ("A", n8)), {"A": None}
                elif y in (4, 5):
                    e = dict.fromkeys("DEHL")
            elif z == 4 or (z == 5 and q == 1 and p == 0):
                self.flow, self.target = "call", n16
            elif z == 5 and q == 0:
                pass                              # PUSH
            elif z == 6:
                if y != 7:
                    e = {"A": None}
            elif z == 7:
                self.target = y * 8
                if y * 8 == 0x08:                 # RST 8: an error report, a code byte after it
                    self.flow = "end"
                elif y * 8 in (0x00, 0x28):       # reset; the calculator, its data after it
                    self.flow = "end"
                else:
                    self.flow = "call"
        if idx:                                   # with IX/IY: don't trust any value
            e = dict.fromkeys(e)
            if self.text == "JP (HL)":
                self.text = "JP (IX)" if b[0] == 0xDD else "JP (IY)"
        self.effect = e

    def ed(self, prog, a, b):
        op = b[1]
        if op is None:
            raise ValueError
        x, y, z, q, p = op >> 6, op >> 3 & 7, op & 7, op >> 3 & 1, op >> 4 & 3
        self.n, e = 2, {}
        if x == 1:
            if z == 0:
                self.text = f"IN {R[y] or 'F'},(C)"
                self.io = ("in", ("B", "C"))
                if R[y]:
                    e = {R[y]: None}
            elif z == 1:
                self.text = f"OUT (C),{R[y] or '0'}"
                self.io = ("out", ("B", "C"))
            elif z == 2:
                e = {"H": None, "L": None}
            elif z == 3:
                self.n = 4
                if None in b[2:4]:
                    raise ValueError
                nn = b[2] | b[3] << 8
                if q == 1 and p < 3:
                    e = {PAIRS[p][1]: ("mem", nn), PAIRS[p][0]: ("mem", nn + 1)}
            elif z == 4:
                e = {"A": None}
            elif z == 5:
                self.flow = "end"                 # RETN, RETI
            elif z == 6:
                if y in (3, 7):                   # IM 2
                    self.text = "IM 2"
            elif z == 7:
                if y == 0:
                    self.text = "LD I,A"
                elif y in (2, 3, 4, 5):
                    e = {"A": None}
        elif x == 2 and z <= 3 and y >= 4:
            e = dict.fromkeys("BCDEHL")
            if z in (2, 3):
                self.text = ["INI", "IND", "INIR", "INDR"][y - 4] if z == 2 \
                    else ["OUTI", "OUTD", "OTIR", "OTDR"][y - 4]
                self.io = ("in" if z == 2 else "out", ("B", "C"))
        self.effect = e


class Code:
    """The machine code reached from the entry points."""

    def __init__(self, prog, entries):
        self.prog, self.ins, self.pred, self.targets = prog, {}, {}, set()
        self.outside = set()                      # jumps and calls to addresses not in the file
        work = list(entries)
        while work:
            a = work.pop()
            while a not in self.ins:
                if not BASE <= a < prog.end:
                    if a >= 0x2000:
                        self.outside.add(a)
                    break
                try:
                    i = Instr(prog, a)
                except ValueError:
                    break
                self.ins[a] = i
                if i.target is not None:
                    self.targets.add(i.target)
                    if i.flow in ("jump", "branch", "call") and BASE <= i.target < prog.end:
                        work.append(i.target)
                    elif i.target >= 0x2000 and not BASE <= i.target < prog.end:
                        self.outside.add(i.target)
                if i.flow in ("jump", "end"):
                    break
                self.pred[a + i.n] = a
                a += i.n

    def bytes_in_code(self):
        return {a + k for a, i in self.ins.items() for k in range(i.n)}

    def value(self, a, reg, depth=0):
        """reg just before the instruction at a: (value or None, notes)."""
        notes = set()
        cur = a
        for _ in range(24):
            if cur in self.targets:
                notes.add("loop")                 # other paths come here too
            prev = self.pred.get(cur)
            if prev is None:
                return None, notes
            i = self.ins[prev]
            if i.flow == "call":
                return None, notes
            if reg in i.effect:
                how = i.effect[reg]
                if how is None:
                    return None, notes
                if how[0] == "n":
                    return how[1], notes
                if how[0] == "mem":
                    v = self.prog.byte(how[1])
                    return v, notes | {f"mem:{how[1]:04X}"} if v is not None else (None, notes)
                if how[0] == "reg" and depth < 4:
                    v, n = self.value(prev, how[1], depth + 1)
                    return v, notes | n
                if how[0] == "hl" and depth < 4:
                    h, n1 = self.value(prev, "H", depth + 1)
                    lo, n2 = self.value(prev, "L", depth + 1)
                    if h is None or lo is None:
                        return None, notes
                    v = self.prog.byte(h << 8 | lo)
                    if v is None:
                        return None, notes
                    return v, notes | n1 | n2 | {f"mem:{h << 8 | lo:04X}"}
                return None, notes
            cur = prev
        return None, notes


# ---------------------------------------------------------------- zx64
def area(z):
    """(harm, what) for a Z80 address on zx64: harm 0 none, 1 some, 2 a crash or hang."""
    if z < 0x1E00:
        return 2, "the ZX81 ROM's code (it is RAM here; F7 reads it again from the disk)"
    if z < 0x2000:
        return 0, "the ROM's character set (zx64 copied it at boot; F7 reads it again from the disk)"
    if z < 0x2E00:
        return 2, "zx64's code"
    if z < 0x2F00:
        return 0, "zx64's keyboard rows (rewritten at each scan)"
    if z < 0x3000:
        return 1, "zx64's mailbox to the 6510"
    if z < 0x4000:
        return 1, "zx64mon (F5 loads it again if its mark is gone)"
    if z < 0x8000:
        return 1, "the ZX81's RAM, the program's own memory"
    if z < 0xC000:
        return 1, "the ZX81's RAM in 32K (free in 16K)"
    if z < 0xCE00:
        return 2, "the C64's I/O chips (C64 $" + f"{z + 0x1000:04X})"
    if z < 0xD000:
        return 2, "the cartridge's CPU switch: the 6510 takes over"
    if z < 0xD400:
        return 0, "the picture (a stray character until the next copy)"
    if z < 0xE000:
        return 0, "free RAM or the font (a character may change shape)"
    if z < 0xF000:
        return 1, "zx64mon's second part (F5 loads it again if its mark is gone)"
    return 2, "the 6510's zero page, stack or loader"


def hexes(v, notes, reg="A"):
    s = f"{reg} = ${v:02X}"
    mem = [n[4:] for n in notes if n.startswith("mem:")]
    if mem:
        s += f" (from ${mem[0]}, as loaded; it may change)"
    if "loop" in notes:
        s += " at first, then it may change (a loop)"
    return s


def judge_in(code, i):
    """(level, message) for an IN."""
    hreg, lreg = i.io[1]
    lo, ln = (lreg, set()) if isinstance(lreg, int) else code.value(i.a, lreg)
    hi, hn = code.value(i.a, hreg)
    block = i.text in ("INI", "IND", "INIR", "INDR")
    if lo is None:
        return "note", "port not known here"
    if lo & 1 == 0 and lo != 0xFE:
        return "warn", (f"port ${lo:02X}: a ZX81 reads the keyboard on any even port, zx64 only "
                        f"where port $FE does (IN A,($FE))")
    if lo != 0xFE:
        dev = PORTS.get(lo, "a device on the expansion port")
        where = f"; it reads memory at ${hi << 8 | lo:04X}" if hi is not None else ""
        return "warn", f"port ${lo:02X}, {dev}: there is none on zx64{where}"
    if block:
        return "warn", "a block IN from the keyboard: B counts down, so most reads find nothing"
    if hi is None:
        return "note", "the keyboard, rows not known here: fine if they are one row, or all (0)"
    v = hexes(hi, hn, hreg)
    if "loop" in hn and hi in ROWS and hreg == "B":
        return "ok", f"the keyboard, row by row from {ROWS[hi]} ({v}): zx64 puts each one there"
    if hi == 0:
        return "ok", f"the keyboard, all rows ({v}): zx64 puts them there"
    if hi in ROWS:
        return "ok", f"the keyboard, row {ROWS[hi]} ({v}): zx64 puts it there"
    rows = [ROWS[r] for r in ROWS if not hi & ~r & 0xFF]
    if hi == 0xFF or not rows:
        return "warn", f"the keyboard with {v}: no row selected"
    return "warn", (f"the keyboard, rows {' + '.join(rows)} at once ({v}): zx64 puts single "
                    f"rows only; this reads whatever is at ${hi << 8 | 0xFE:04X}")


def judge_out(code, i):
    hreg, lreg = i.io[1]
    lo, _ = (lreg, set()) if isinstance(lreg, int) else code.value(i.a, lreg)
    hi, hn = code.value(i.a, hreg)
    dev = f", {PORTS[lo]}" if lo in PORTS else ""
    if i.text in ("OUTI", "OUTD", "OTIR", "OTDR"):
        return "warn", "a block OUT: writes bytes into memory, wherever B and C point"
    if lo is None:
        return "warn", "port not known here: it writes into memory, wherever that lands"
    if hi is None:
        r = "A" if hreg == "A" else "B"
        return "warn", (f"port ${lo:02X}{dev}: writes into memory at {r}*256+${lo:02X}; {r} is not "
                        f"known here, so it may land anywhere, the ROM and zx64's code included")
    z = hi << 8 | lo
    harm, what = area(z)
    tail = {0: "harmless", 1: "may change the program's data", 2: "likely to crash or hang"}[harm]
    return ("note" if harm == 0 else "warn"), \
        f"port ${lo:02X}{dev}, {hexes(hi, hn, hreg)}: writes ${z:04X}, {what}: {tail}"


def check(path):
    """(level, address or None, message) for one .p file."""
    data = open(path, "rb").read()
    out = []
    if len(data) < 0x407D - BASE:
        return [("warn", None, "too short for a .p file")]
    prog = Program(data)
    if prog.eline > 0x7FF0:
        out.append(("warn", None, f"ends at ${prog.eline:04X}: too big for 16K, press F3 for 32K first"))
    entries = []
    for line, a in prog.usrs():
        if a is None:
            out.append(("note", None, f"line {line}: USR with an expression, not followed"))
        elif a == 0x2000:
            out.append(("warn", None, f"line {line}: USR 8192 is the ZXpand's API on a ZX81; on zx64 "
                        "it runs zx64's interrupt handler: harmless, but the ZXpand call does nothing"))
        elif 0x2000 < a < 0x4000:
            out.append(("warn", None, f"line {line}: USR {a} lands in zx64's code (on a ZX81, an "
                        "add-on's own code or RAM is there): likely a crash"))
        elif BASE <= a < prog.end:
            entries.append(a)
        elif a >= prog.end:
            out.append(("note", None, f"line {line}: USR {a} is past the program, not followed"))
    code = Code(prog, sorted(set(entries)))
    for a in sorted(code.ins):
        i = code.ins[a]
        if i.io:
            lvl, msg = (judge_in if i.io[0] == "in" else judge_out)(code, i)
            out.append((lvl, a, f"{i.text}: {msg}"))
        elif i.text == "LD I,A":
            out.append(("warn", a, "LD I,A: a hi-res display or its own character set; zx64 only "
                        "shows the display file, in the ROM's characters"))
        elif i.text == "IM 2":
            out.append(("warn", a, "IM 2: zx64's interrupt goes through RST $38 (IM 1); in IM 2 it "
                        "jumps through a table at I*256, likely a crash"))
    used = {}                                     # add-on devices the code talks to
    for i in code.ins.values():
        if i.io:
            lo = i.io[1][1] if isinstance(i.io[1][1], int) else code.value(i.a, i.io[1][1])[0]
            if lo in DEVICES:
                used.setdefault(DEVICES[lo], set()).add(lo)
    for dev, ports in used.items():
        out.insert(0, ("warn", None, f"talks to {dev} (port{'s' if len(ports) > 1 else ''} "
                       + ", ".join(f"${x:02X}" for x in sorted(ports))
                       + "): there is none on zx64, so whatever needs it won't work"))
    if any(m.startswith("IN") and "the keyboard" in m for _, a, m in out if a is not None):
        fast = any(TOKENS["FAST"] in body for _, _, body in prog.lines() if body and body[0] != REM)
        out.append(("note", None, "reads the keyboard itself: zx64 updates the rows at each scan, "
                    "once a frame in SLOW mode with the /INT wire"
                    + ("; the BASIC has FAST, and while a FAST program runs the rows stand still"
                       if fast else "")))
    incode = code.bytes_in_code()
    loose = []                                    # IN/OUT-like bytes in what wasn't followed
    for k in range(len(prog.data[:prog.end - BASE]) - 1):
        a = BASE + k
        if a in incode:
            continue
        b0, b1 = prog.data[k], prog.data[k + 1]
        if (b0 == 0xDB and b1 == 0xFE) or (b0 == 0xD3 and b1 in OUTPORTS) \
                or (b0 == 0xED and b1 & 0xC6 == 0x40):   # IN r,(C), OUT (C),r
            loose.append(a)
    if loose:
        lvl = "note" if code.ins else "warn"
        why = "outside the machine code followed" if code.ins else \
            "and no machine code could be followed from a USR"
        out.append((lvl, None, f"{len(loose)} IN/OUT-like byte pairs {why} (data, or code this "
                    f"can't follow): " + " ".join(f"${a:04X}" for a in loose[:8])
                    + (" ..." if len(loose) > 8 else "")))
    return out, prog, code, entries


def summary(path, verbose=False, most=6):
    """The report for one file, as lines of text, and the number of warnings.
    Without verbose, only the warnings, at most `most` of them."""
    name = os.path.basename(path)
    found, prog, code, entries = check(path)
    ins = sum(1 for _, a, m in found if a is not None and m.startswith("IN"))
    outs = sum(1 for _, a, m in found if a is not None and m.startswith("OUT"))
    warns = [f for f in found if f[0] == "warn"]
    lines = [f"{name}: {len(code.ins)} instructions followed from {len(entries)} USR address"
             f"{'es' if len(entries) != 1 else ''}; {ins} IN, {outs} OUT"
             + (f": {len(warns)} warning{'s' if len(warns) != 1 else ''}" if warns
                else ": nothing zx64 can't do")]
    shown = found if verbose else warns[:most]
    for lvl, a, msg in shown:
        lines.append(f"  {lvl:4}  {'$%04X' % a if a is not None else '     '}  {msg}")
    if warns and len(shown) < len(found) and not verbose:
        lines.append(f"  (all {len(found)} findings: tools/pcheck.py -v {path})")
    return lines, len(warns)


def main():
    args = sys.argv[1:]
    verbose = "-v" in args
    files = [a for a in args if a != "-v"]
    if not files:
        sys.exit(__doc__)
    for f in files:
        print("\n".join(summary(f, verbose)[0]))


if __name__ == "__main__":
    main()
