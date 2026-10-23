#!/usr/bin/env python3
"""Run zx64 without a C64.

The patched ZX81 ROM and the Z80 code run in a Z80 emulator, the 6510
loader in a 6502 emulator, and they take turns on one memory the way the
CP/M cartridge makes them: a write to $DE00 (Z80 $CE00) switches. Around
them: a VIC raster flag once a frame, a CIA keyboard matrix, and a disk
drive behind the kernal's OPEN/CHRIN/CHROUT. Then the tests below type
at the ZX81 and read its screen.

    python3 tools/simulate.py          (make test)

Needs build/obj/zx64.prg and build/obj/zx64.lbl (make), and the z80 and py65
packages, e.g. in a venv:

    python3 -m venv .venv && .venv/bin/pip install z80 py65

The Z80 gets 2 T-states per C64 cycle here, as in VICE. VICE delivers the
VIC's IRQ to the Z80's /INT; the original cartridge doesn't (see
docs/cpm-cart.md), so the tests run both ways.
"""
import os
import re
import sys

try:
    import z80
    from py65.devices.mpu6502 import MPU
    from py65.memory import ObservableMemory
except ImportError:
    sys.exit("needs the z80 and py65 emulator packages. From the repo root:\n"
             "  python3 -m venv .venv && .venv/bin/pip install z80 py65\n"
             "then run make test again (it uses .venv automatically)")

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "tools"))
from build import KEYMAP, MATRIX, SHIFTED, zx2pet  # noqa: E402

ZX = ' ??????????"£$:?()><=+-*/;,.0123456789ABCDEFGHIJKLMNOPQRSTUVWXYZ'
FRAME_T = 2 * 19656          # Z80 T-states in a PAL frame (VICE: 2 per cycle)
SLICE_T = 1000
RET_TRAP = 0x7F00            # a HALT the direct calls return to
SCREEN = 0xD000              # the VIC screen, as the Z80 sees it (C64 $E000)

# ZX81 keyboard: key name -> (row select, bit)
ZXROWS = {0xFE: ["SHIFT", "Z", "X", "C", "V"], 0xFD: list("ASDFG"), 0xFB: list("QWERT"),
          0xF7: list("12345"), 0xEF: list("09876"), 0xDF: list("POIUY"),
          0xBF: ["NEWLINE", "L", "K", "J", "H"], 0x7F: ["SPACE", ".", "M", "N", "B"]}
ZXKEY = {name: (row, bit) for row, names in ZXROWS.items() for bit, name in enumerate(names)}
# ... and the C64 key that presses it on its own
C64KEY = {}
for c64, zx in KEYMAP:
    if len(zx) == 1:
        C64KEY.setdefault(zx[0], c64)

# C64 keys with no ZX81 key of their own
C64NAMES = {"LSHIFT": (1, 7), "RSHIFT": (6, 4), "CRSRRIGHT": (0, 2), "CRSRDOWN": (0, 7),
            "F1": (0, 4), "F3": (0, 5), "F5": (0, 6), "F7": (0, 3)}
FKEYS = {"F8": {C64NAMES["LSHIFT"], C64NAMES["F7"]}}   # SHIFT+F7, the same key as F7

# The joystick in port 2: $DC00's bits, 0 when pressed. Its lines are the
# keyboard's column lines, so a held direction selects that column too.
STICK = {"up": 0, "down": 1, "left": 2, "right": 3, "fire": 4}

# The monitor's keys: every C64 key by name, and the ASCII it types
MPOS = {name: (c, r) for c, col in enumerate(MATRIX) for r, name in enumerate(col)}
MKEY = {"\r": [MPOS["RETURN"]], " ": [MPOS["SPACE"]]}
MKEY.update({ch: [MPOS[ch]] for ch in MPOS if len(ch) == 1})
MKEY.update({s: [MPOS["LSHIFT"], MPOS[k]] for k, s in SHIFTED.items() if s != " "})
MSCR = 0xF400                # the monitor's screen, as the Z80 sees it (C64 $0400)

KERNAL = {0xFFBD: "setnam", 0xFFBA: "setlfs", 0xFFC0: "open", 0xFFC3: "close",
          0xFFC6: "chkin", 0xFFC9: "chkout", 0xFFCC: "clrchn", 0xFFCF: "chrin",
          0xFFD2: "chrout", 0xFFB7: "readst", 0xFF81: "init", 0xFF84: "init", 0xFF8A: "init",
          0xFF96: "tksa", 0xFFAB: "untlk"}
CALL_TRAP = 0xFFF0           # where call_6510's routines return to


class Drive:
    """Just enough of a 1541 behind the kernal calls the loader makes."""

    def __init__(self):
        self.files = {}              # name (bytes) -> bytes
        self.status = b"73,CBM DOS V2.6 1541,00,00\r"
        self.protected = False
        self.opens = 0

    def open(self, name, sa):
        self.opens += 1
        if sa == 15:
            if name.startswith(b"S:"):           # scratch
                n = sum(1 for f in name[2:].split(b",") if self.files.pop(f, None) is not None)
                self.status = b"01, FILES SCRATCHED,%02d,00\r" % n
            elif name:
                self.status = b"31,SYNTAX ERROR,00,00\r"
            st, self.status = self.status, b"00, OK,00,00\r"   # read once, as a 1541's
            return {"read": st}
        if name == b"$":
            self.status = b"00, OK,00,00\r"
            return {"read": self.directory()}
        name = name.split(b":", 1)[-1] if b":" in name else name
        write = sa == 1 or name.endswith(b",W") or sa == 2 and b"," in name
        name = name.split(b",", 1)[0]
        if write:
            return {"write": bytearray(), "name": name}
        if name in self.files:
            self.status = b"00, OK,00,00\r"
            return {"read": self.files[name]}
        self.status = b"62,FILE NOT FOUND,00,00\r"
        return {"read": None}

    def directory(self):
        """'$' as a 1541 sends it: a BASIC program, a line a file."""
        def line(blocks, text):
            return b"\x01\x01" + blocks.to_bytes(2, "little") + text + b"\0"
        d = b"\x01\x04" + line(0, b'\x12"ZX64            " 81 2A')
        used = 0
        for name, data in self.files.items():
            n = (len(data) + 253) // 254
            used += n
            d += line(n, b" " * (4 - len(str(n))) + b'"' + name + b'"' + b" " * (17 - len(name)) + b"PRG")
        return d + line(664 - used, b"BLOCKS FREE.") + b"\0\0"

    def close(self, ch):
        if "write" not in ch:
            return
        if self.protected:
            self.status = b"26,WRITE PROTECT ON,00,00\r"
        else:
            self.files[ch["name"]] = bytes(ch["write"])
            self.status = b"00, OK,00,00\r"


class IEC:
    """The serial bus on CIA 2's port A ($DD00), cycle by cycle, with one
    drive on it that may speak JiffyDOS, as jtest saw an SD2IEC do
    (c64/jcore.asm has the protocol): ATN bytes a bit at a time, the ask
    (CLK held low before a byte's last bit: the drive pulls DATA for ~100
    us), then bytes two bits at a time. The kernal's own bus calls are
    the Machine's traps; its TKSA turns the bus around here. Times are
    6510 cycles, taken as microseconds."""

    ASK, ANSWER = 200, 100           # CLK low that long before the last bit; DATA pulled that long
    NEXT = 100                       # the drive's time to have the next byte ready
    PAIRS = ((12, 21), (21, 31), (31, 42), (42, 53))   # bits 0-1 ... 6-7, after the go
    MARK = 53

    def __init__(self, m, jiffy=True, present=True, stuck=False):
        self.m, self.jiffy, self.present = m, jiffy, present
        self.stuck = stuck               # answers ATN, then never lets go of DATA
        self.out = 0                     # what the 6510 wrote: bit 3 ATN, 4 CLK, 5 DATA pulled
        self.state = "idle"
        self.dclk = self.ddata = False   # the drive pulling CLK, DATA
        self.bits = self.byte = 0
        self.clk_low_at = 0
        self.asked = self.talking = False
        self.answer = None               # (from, to): the drive's answer to the ask
        self.ch = {"read": b"", "pos": 0}  # the channel talking (its bytes, where it is)
        self.ready_at = self.go_at = None
        self.atn_bytes = []
        self.sent = 0                    # Jiffy bytes the 6510 took

    def now(self):
        return self.m.cpu.processorCycles + 3        # an absolute access's last cycle

    def write(self, v):
        t, was = self.now(), self.out
        self.out = v & 0x38
        atn, clk, data = v & 8, v & 0x10, v & 0x20
        if clk and not was & 0x10:
            self.clk_low_at = t
        if atn and not was & 8 and self.present:
            self.state, self.ddata, self.dclk, self.asked = "atn", True, False, False
            self.go_at = None
        if self.state == "atn" and was & 0x10 and not clk and not self.stuck:
            self.ddata, self.state, self.bits, self.byte = False, "bits", 0, 0   # ready for data
        elif self.state == "bits" and was & 0x10 and not clk:
            self.byte |= (0 if data else 1) << self.bits                          # a bit, low first
            self.bits += 1
        elif self.state == "bits" and clk and not was & 0x10 and self.bits == 8:
            self.ddata, self.state = True, "atn"                                  # got it
            self.atn_bytes.append(self.byte)
            if self.byte == 0x48:
                self.talking = True
        elif self.state == "jtalk":
            if was & 0x20 and not data and self.go_at is None and t >= self.ready_at:
                self.go_at = t                                                    # go
            elif data and not was & 0x20 and self.go_at is not None:
                self.go_at = None                                                 # got it
                self.sent += 1
                self.ch["pos"] += 1
                if self.ch["pos"] >= len(self.ch["read"]):
                    self.state = "jdone"
                else:
                    self.ready_at = t + self.NEXT

    def lines(self):
        """(CLK low, DATA low), the drive's side."""
        t = self.now()
        if self.state == "bits" and self.bits == 7 and self.out & 0x10 and self.jiffy:
            if self.answer is None and t - self.clk_low_at >= self.ASK:
                self.answer = (self.clk_low_at + self.ASK, self.clk_low_at + self.ASK + self.ANSWER)
                self.asked = True
            if self.answer and self.answer[0] <= t < self.answer[1]:
                return False, True
        if self.state == "bits" and self.bits != 7:
            self.answer = None
        if self.state == "jtalk":
            if self.go_at is None:
                return t < self.ready_at, False                                   # CLK low: busy
            dt, b = t - self.go_at, self.ch["read"][self.ch["pos"]]
            for k, (lo, hi) in enumerate(self.PAIRS):
                if lo <= dt < hi:
                    return not b >> 2 * k & 1, not b >> 2 * k + 1 & 1
            if dt >= self.MARK:
                last = self.ch["pos"] == len(self.ch["read"]) - 1
                return not last, last
            return False, False
        if self.state == "jdone":
            return True, False
        return self.dclk, self.ddata

    def read(self):
        clk, data = self.lines()
        clk |= bool(self.out & 0x10)
        data |= bool(self.out & 0x20)
        return (self.m.ram[0xDD00] & 0x07) | self.out | (0 if clk else 0x40) | (0 if data else 0x80)

    def tksa(self, sa):
        """The kernal's TKSA: the secondary address under ATN, then the turn
        around: ATN and CLK released, DATA pulled; the talker takes CLK."""
        self.atn_bytes.append(sa)
        self.out = 0x20
        self.ddata = self.dclk = False           # (a file that isn't there: the lines let go,
        if self.state != "atn" or not self.talking:   # jget finds no mark: an SD2IEC's under 1 s)
            return
        ch = next((c for c in self.m.channels.values() if c.get("sa") == sa & 0x0F), None)
        if self.asked and ch and ch.get("read") and ch["pos"] < len(ch["read"]):
            self.ch = ch
            self.state, self.ready_at, self.go_at = "jtalk", self.now() + self.NEXT, None
        else:
            self.state = "talk"                  # plain: the kernal's ACPTR, not modelled

    def untlk(self):
        self.out = 0
        self.state, self.talking, self.asked, self.answer = "idle", False, False, None
        self.dclk = self.ddata = False


class Machine:
    all = []

    def __init__(self, int_wired=True, prg=None, jiffy=False):
        self.int_wired = int_wired
        self.ram = bytearray(0x10000)            # C64 memory (the 6510's view)
        self.mem = ObservableMemory(subject=self.ram)
        self.cpu = MPU(memory=self.mem)
        self.z = z80.Z80Machine()
        self.drive = Drive()
        self.iec = IEC(self, jiffy=jiffy)        # a plain drive unless asked: the kernal's reads
        self.keys = set()                        # C64 keys down: (column, row)
        self.cia_glitch = True                   # see _kbd
        self.ciareads = 0
        self.colreads = 0
        self.pa = 0xFF                           # CIA1 port A, the column select
        self.joy = set()                         # the stick in port 2: STICK names held
        self.latch = 0                           # VIC $D019
        self.enable = 0                          # VIC $D01A
        self.z80_on = False
        self.t = 0                               # Z80 T-states so far
        self.next_frame = FRAME_T
        self.frames = 0
        self.irqs = 0
        self.fast_irqs = 0                       # taken while a FAST program ran
        self.lbl = labels()
        self.channels, self.cin, self.cout, self.name, self.lfs, self.st = {}, None, None, b"", (0, 0, 0), 0
        self.printed = ""                        # what CHROUT put on the C64's screen
        prg = prg or open(os.path.join(ROOT, "build", "obj", "zx64.prg"), "rb").read()
        load = prg[0] | prg[1] << 8
        self.ram[load:load + len(prg) - 2] = prg[2:]
        self.ram[0xBA] = 8
        self.ram[0xDD00] = 0x07                  # as the kernal's IOINIT leaves it: VIC bank 0, PA2 high

        m = self.mem
        m.subscribe_to_write(range(0xDE00, 0xDF00), self._c64_switch)
        self.barlog = []                         # the 6510's writes to the top row's bar and spinner
        m.subscribe_to_write(range(0xE01A, 0xE024), lambda a, v: self.barlog.append((a, v)))
        self.top_at_switch = b""                 # the top row as the Z80 hands over
        m.subscribe_to_write([0xD019], lambda a, v: self._ack(v))
        m.subscribe_to_write([0xD01A], lambda a, v: setattr(self, "enable", v))
        m.subscribe_to_write([0xDC00], lambda a, v: setattr(self, "pa", v))
        m.subscribe_to_read([0xDC01], lambda a: self._kbd())
        m.subscribe_to_read([0xD019], lambda a: self._d019())
        m.subscribe_to_write([0xDD00], lambda a, v: self._dd00(v))
        m.subscribe_to_read([0xDD00], lambda a: self.iec.read())
        m.subscribe_to_read([0xD012], lambda a: self._d012())
        self.rasters = []                        # what the 6510 read from $D012

        z = self.z
        z.set_read_callback(self._z80_read)
        z.set_write_callback(self._z80_write)
        self.d1 = self.lbl["d1active"]           # frame() sets it to 2: the ROM is in DISPLAY-1
        self.reads = {0xC011, 0xC012, 0xC019, 0xCC00, 0xCC01} | set(range(0xC800, 0xCC00))   # colour RAM too
        self.writes = {0xC019, 0xC01A, 0xCC00, self.d1} | set(range(0xCE00, 0xCF00))
        for a in self.reads:
            z.mark_addrs(a, 1, z.READ_MARK)
        for a in self.writes:
            z.mark_addrs(a, 1, z.WRITE_MARK)
        # The cartridge decodes neither IORQ nor MREQ: IN and OUT are memory
        # accesses at the 16-bit port address. Logged, as nothing in the
        # ROM or zx64 should do them any more.
        self.io = []
        z.set_input_callback(self._z80_in)
        z.set_output_callback(self._z80_out)
        Machine.all.append(self)
        self.kwret = self.lbl["kw_call"] + 3     # DISPLAY-1 called from keywait
        self.kwframe = self.lbl["kw_frame"]      # frame() called from its type-ahead loop
        self.keywait = -10

    # ---- the chips
    def _ack(self, v):
        self.latch &= ~v & 0xFF

    def _d019(self):
        on = self.latch & self.enable & 0x0F
        v = 0x70 | (0x80 if on else 0) | self.latch
        line = self.line()
        if 51 <= line < 250 and line % 8 == 4:  # as seen on hardware: the raster flag
            v |= 1                               # read as set just after a bad line
        return v

    def _kbd(self):
        self.ciareads += 1
        if self.cia_glitch and self.ciareads % 211 == 0:
            return 0xD0                          # as seen on hardware: now and then one
        cols = {c for c in range(8) if not (self.pa >> c) & 1}   # read comes back wrong
        cols |= {STICK[d] for d in self.joy}     # the stick pulls column lines low too
        rows, grew = set(), True                 # no diodes: a row a key connects to
        while grew:                              # a selected column, through any path
            grew = False                         # of keys down (three corners of a
            for col, row in self.keys:           # rectangle show the fourth)
                if (col in cols) != (row in rows):
                    cols.add(col)
                    rows.add(row)
                    grew = True
        return 0xFF & ~sum(1 << r for r in rows)

    def line(self):
        """The raster line the VIC is on, roughly: 250 as a frame starts here."""
        return (self.t % FRAME_T // 126 + 250) % 312

    def _z80_read(self, a):
        if 0xC800 <= a < 0xCC00:                 # colour RAM: 4 bits, the rest the bus's;
            self.colreads += 1                   # now and then wrong, as the hardware's
            if self.cia_glitch and self.colreads % 97 == 0:   # I/O reads can be (seen:
                return 0xD0                      # the monitor's colours, 2026-10-15)
            return self.z.memory[a] & 0x0F | 0xF0
        if a == 0xCC01:
            return self._kbd()
        if a == 0xCC00:                          # port A: what was written, the
            self.ciareads += 1                   # stick's lines pulled low (and
            if self.cia_glitch and self.ciareads % 211 == 0:   # wrong now and then, as
                return 0xD0                      # port B is)
            return self.pa & ~sum(1 << STICK[d] for d in self.joy) & 0xFF
        if a == 0xC019:
            return self._d019()
        if a == 0xC011:                          # bit 7 reads as the line's bit 8,
            return self.z.memory[a] & 0x7F | (0x80 if self.line() > 255 else 0)  # not as written
        return self.line() & 0xFF                # $C012

    def _z80_write(self, a, v):
        self.z.memory[a] = v
        if a == self.d1:
            sp = self.z.sp                       # frame() <- DISPLAY-1 <- who?
            ret = [self.z.memory[sp + i] | self.z.memory[sp + i + 1] << 8 for i in (0, 2)]
            if v == 2 and (ret[1] == self.kwret or ret[0] == self.kwframe):
                self.keywait = self.frames       # the editor's key wait, not a PAUSE
        elif a == 0xC019:
            self._ack(v)
        elif a == 0xC01A:
            self.enable = v
        elif a == 0xCC00:
            self.pa = v
        elif v & 1:                              # $CE00-$CEFF: hand over to the 6510
            self.top_at_switch = bytes(self.z.memory[SCREEN + 4:SCREEN + 36])
            self.z80_on = False
            self.ram[0x1000:0x10000] = self.z.memory[0x0000:0xF000]
            self.ram[0x0000:0x1000] = self.z.memory[0xF000:0x10000]
            self.run_6510()

    def _z80_in(self, port):
        self.io.append(("IN", self.z.pc, port))
        return self._z80_read(port) if port in self.reads else self.z.memory[port]

    def _z80_out(self, port, v):
        self.io.append(("OUT", self.z.pc, port, v))
        if port in self.writes:
            self._z80_write(port, v)
        else:
            self.z.memory[port] = v

    def _d012(self):
        line = (self.cpu.processorCycles // 63 + 250) % 312   # 63 cycles a line, PAL
        self.rasters.append(line)
        return line & 0xFF

    def _dd00(self, v):
        self.ram[0xDD00] = v
        self.iec.write(v)

    def _c64_switch(self, a, v):
        if not v & 1:
            self.z80_on = True

    # ---- the 6510 and its kernal
    def run_6510(self, limit=2_000_000):
        for _ in range(limit):
            if self.z80_on:
                self.z.memory[0x0000:0xF000] = self.ram[0x1000:0x10000]
                self.z.memory[0xF000:0x10000] = self.ram[0x0000:0x1000]
                return
            self.step_6510()
        raise AssertionError(f"the 6510 never handed back (pc ${self.cpu.pc:04X})")

    def step_6510(self):
        cpu = self.cpu
        if cpu.pc in KERNAL:
            getattr(self, "k_" + KERNAL[cpu.pc])()
            lo = self.ram[0x100 + ((cpu.sp + 1) & 0xFF)]
            hi = self.ram[0x100 + ((cpu.sp + 2) & 0xFF)]
            cpu.sp = (cpu.sp + 2) & 0xFF
            cpu.pc = ((hi << 8) | lo) + 1
        else:
            cpu.step()

    def call_6510(self, addr, a=0, x=0, y=0, limit=5_000_000):
        """Call a 6510 routine directly (the Z80 stays where it is); returns
        A, X, Y and the carry."""
        cpu = self.cpu
        ret = CALL_TRAP - 1
        self.ram[0x100 + cpu.sp] = ret >> 8
        self.ram[0x100 + ((cpu.sp - 1) & 0xFF)] = ret & 0xFF
        cpu.sp = (cpu.sp - 2) & 0xFF
        cpu.pc, cpu.a, cpu.x, cpu.y = addr, a, x, y
        for _ in range(limit):
            if cpu.pc == CALL_TRAP:
                return cpu.a, cpu.x, cpu.y, bool(cpu.p & cpu.CARRY)
            self.step_6510()
        raise AssertionError(f"6510 ${addr:04X} never returned (pc ${cpu.pc:04X})")

    def carry(self, c):
        self.cpu.p = self.cpu.p | self.cpu.CARRY if c else self.cpu.p & ~self.cpu.CARRY & 0xFF

    def k_setnam(self):
        a = self.cpu.x | self.cpu.y << 8
        self.name = bytes(self.ram[a:a + self.cpu.a])

    def k_setlfs(self):
        self.lfs = (self.cpu.a, self.cpu.x, self.cpu.y)

    def k_open(self):
        lfn, dev, sa = self.lfs
        if lfn in self.channels:
            self.cpu.a = 2                       # file already open
            return self.carry(True)
        self.channels[lfn] = dict(self.drive.open(self.name, sa), pos=0, sa=sa)
        self.carry(False)

    def k_close(self):
        ch = self.channels.pop(self.cpu.a, None)
        if ch:
            self.drive.close(ch)
        self.carry(False)

    def k_chkin(self):
        self.carry(self.cpu.x not in self.channels)
        self.cin = self.cpu.x

    def k_chkout(self):
        self.carry(self.cpu.x not in self.channels)
        self.cout = self.cpu.x

    def k_clrchn(self):
        self.cin = self.cout = None

    def k_chrin(self):
        ch = self.channels.get(self.cin)
        data = ch and ch.get("read")
        if not data:
            self.cpu.a, self.st = 0x0D, 0x42      # nothing there: EOI + time-out
        else:
            self.cpu.a = data[ch["pos"]]
            ch["pos"] += 1
            self.st = 0x40 if ch["pos"] >= len(data) else 0
        self.carry(False)

    def k_init(self):                            # CINT, IOINIT, RESTOR
        pass

    def k_chrout(self):
        if self.cout is None:
            self.printed += chr(self.cpu.a)
        ch = self.channels.get(self.cout)
        if ch and "write" in ch:
            ch["write"].append(self.cpu.a)
        self.carry(False)

    def k_tksa(self):
        self.iec.tksa(self.cpu.a)

    def k_untlk(self):
        self.iec.untlk()

    def k_readst(self):
        self.cpu.a = self.st

    # ---- running
    def boot(self, frames=400, banner=False):
        """To the K cursor, and (unless banner) until the version shown on
        the top row is gone."""
        self.cpu.pc, self.cpu.sp = 2061, 0xF6
        self.run_6510(limit=20_000_000)          # (the boot file may load zx64 by JiffyDOS)
        self.until(lambda: self.cursor() and self.ready(), frames, "the K cursor")
        if not banner:
            self.until(lambda: not self.z.memory[self.lbl["ovl"]], 200, "the version on the top row gone")

    def step(self, ticks):
        z = self.z
        z.ticks_to_stop = ticks
        z.run()
        self.t += ticks - z.ticks_to_stop
        if self.t >= self.next_frame:
            self.next_frame += FRAME_T
            self.frames += 1
            if not self.z.memory[0xC011] & 0x80:  # raster line 250 (or 506, never)
                self.latch |= 1
        if self.int_wired and self.latch & self.enable & 1 and z.iff1 and not z.int_disabled:
            self.irq()                           # /IRQ stays low until acknowledged

    def irq(self):
        z = self.z
        sp = (z.sp - 2) & 0xFFFF
        z.memory[sp], z.memory[(sp + 1) & 0xFFFF] = z.pc & 0xFF, z.pc >> 8
        z.sp, z.pc = sp, 0x0038
        z.iff1 = z.iff2 = False
        self.irqs += 1
        if not z.memory[0x403B] & 0x40 and not z.memory[self.d1]:
            self.fast_irqs += 1

    def run(self, frames):
        end = self.frames + frames
        while self.frames < end:
            self.step(SLICE_T)

    def until(self, cond, frames, what):
        end = self.frames + frames
        while self.frames < end:
            self.step(SLICE_T)
            if cond():
                return
        raise AssertionError(f"no {what} after {frames} frames; screen:\n" + "\n".join(self.screen()))

    def call(self, addr, hl=None, resume=False):
        """Call a Z80 routine directly, with HL if given; returns the
        T-states it took. With resume, the Z80 goes on afterwards where it
        was, its registers as they were (for calls into a running machine);
        without, the registers keep what the routine left (results)."""
        z = self.z
        regs = ("af", "bc", "de", "hl", "ix", "iy", "alt_af", "alt_bc", "alt_de", "alt_hl",
                "pc", "sp", "halted")
        saved = {r: getattr(z, r) for r in regs}
        if hl is not None:
            z.hl = hl
        z.memory[RET_TRAP] = 0x76
        sp = (z.sp - 2) & 0xFFFF
        z.memory[sp], z.memory[sp + 1] = RET_TRAP & 0xFF, RET_TRAP >> 8
        z.sp, z.pc, z.halted = sp, addr, False
        t = 0
        while z.pc not in (RET_TRAP, RET_TRAP + 1):
            z.ticks_to_stop = 100
            z.run()
            t += 100 - z.ticks_to_stop
            if t > 10_000_000:
                raise AssertionError(f"${addr:04X} never returned")
        if resume:
            for r, v in saved.items():
                setattr(z, r, v)
        return t

    # ---- the ZX81's keyboard and screen
    def press(self, *names, frames=900):
        """Hold the keys until the ROM takes them (it sets DEBOUNCE to $FF),
        then let go until it is ready for the next (DEBOUNCE back to 0,
        which only happens in the ROM's key wait)."""
        self.keys = {C64NAMES[n] if n in C64NAMES else C64KEY[ZXKEY[n]] for n in names}
        self.until(lambda: self.z.memory[0x4027] == 0xFF, frames, f"{'+'.join(names)} taken")
        self.keys = set()
        self.until(self.ready, frames, "the ROM ready for a key")

    def ready(self):
        """In the editor's key wait (not a PAUSE, which runs the same
        DISPLAY-1), with the debounce run down."""
        return self.frames - self.keywait <= 1 and self.z.memory[0x4027] == 0

    def type(self, seq):
        """Space-separated keys; SHIFT+X for shifted ones."""
        for k in seq.split():
            self.press(*k.split("+"))

    def screen(self):
        rows = []
        for r in range(24):
            a = SCREEN + 40 * r + 4
            rows.append("".join(ZX[c & 0x3F].lower() if c & 0x80 else ZX[c & 0x3F]
                                for c in self.z.memory[a:a + 32]).rstrip())
        return rows

    def cursor(self):
        return any(r.endswith("k") or r.endswith("l") for r in self.screen()[22:])

    # ---- the monitor's screen and keys
    def mscreen(self):
        """The monitor's 25 rows as text, reverse video as plain."""
        rows = []
        for r in range(25):
            row = self.z.memory[MSCR + 40 * r:MSCR + 40 * r + 40]
            rows.append("".join(chr((c & 0x7F) + 0x40) if c & 0x7F < 0x20 else chr(c & 0x7F)
                                if c & 0x7F < 0x40 else "#" for c in row).rstrip())
        return rows

    def mtype(self, text, settle=10):
        """Type at the monitor: each key down 2 frames, then up 2."""
        for ch in text:
            self.keys = set(MKEY[ch])
            self.run(2)
            self.keys = set()
            self.run(2)
        self.run(settle)

    def mkey(self, *names):
        self.keys = {MPOS[n] for n in names}
        self.run(2)
        self.keys = set()
        self.run(2)

    def tap(self, name, frames=10):
        self.keys = set(FKEYS[name]) if name in FKEYS else {C64NAMES[name]}
        self.run(3)
        self.keys = set()
        self.run(frames)

    def peek16(self, a):
        return self.z.memory[a] | self.z.memory[a + 1] << 8

    def poke16(self, a, v):
        self.z.memory[a], self.z.memory[a + 1] = v & 0xFF, v >> 8


def labels():
    text = open(os.path.join(ROOT, "build", "obj", "zx64.lbl")).read()
    return {m.group(1).lower(): int(m.group(2), 16)
            for m in re.finditer(r"^(\w+):\s+equ\s+\$([0-9A-Fa-f]+)", text, re.M)}


def jlabels():
    """c64/jcore.asm's labels (acme's symbol list), names as written."""
    text = open(os.path.join(ROOT, "build", "obj", "jcore.sym")).read()
    return {m.group(1): int(m.group(2), 16) for m in re.finditer(r"^\s*(\w+)\s*=\s*\$([0-9a-fA-F]+)", text, re.M)}


failures = 0


def check(name, cond, detail=""):
    global failures
    print(f"{'ok  ' if cond else 'FAIL'} {name} {detail}")
    failures += not cond


def report(m):
    """The report code at the bottom of the screen, e.g. '0/10'."""
    for r in m.screen()[22:]:
        mm = re.match(r"^([0-9A-Z])/(\d+)", r)
        if mm:
            return mm.group(0)
    return None


def new(m):
    m.type("A NEWLINE")
    m.run(3)


def enter(m, seq):
    """Type a line and NEWLINE; once the ROM wants a key again, the report."""
    m.type(seq + " NEWLINE")
    m.run(3)                                     # the picture lags a frame or two
    return report(m)


def main():
    if not os.path.exists(os.path.join(ROOT, "build", "obj", "zx64.prg")):
        sys.exit("build/obj/zx64.prg is missing: run make first (it needs your ZX81 ROM)")

    # ---- the CPU switch: "You MUST follow the mode switching store
    # instruction with a NOP" (Commodore's CP/M guide, 6.6.1); the first
    # start of the Z80, at $0000, must find one too. The emulators here
    # don't lose that byte, the hardware can.
    z80 = open(os.path.join(ROOT, "build", "obj", "zx64.bin"), "rb").read()
    c64 = open(os.path.join(ROOT, "build", "obj", "boot.bin"), "rb").read()
    rom0 = open(os.path.join(ROOT, "build", "obj", "zx64.prg"), "rb").read()[0x1000 - 0x0801 + 2]
    zsw = [i for i in range(len(z80) - 3) if z80[i:i + 3] == b"\x32\x00\xce"]
    csw = [i for i in range(len(c64) - 3) if c64[i:i + 3] == b"\x8d\x00\xde"]
    check("a NOP after every switch store (Z80 LD ($CE00),A, 6510 STA $DE00), and at $0000",
          zsw and csw and all(z80[i + 3] == 0x00 for i in zsw) and all(c64[i + 3] == 0xEA for i in csw)
          and rom0 == 0x00, f"{len(zsw)} Z80, {len(csw)} 6510")

    # ---- no CP/M cartridge: the write to $DE00 does nothing
    class NoCart(Machine):
        def _c64_switch(self, a, v):
            pass
    m = NoCart()
    m.ram[0xA002:0xA004] = b"\x7b\xe3"         # BASIC's warm start, $E37B
    m.cpu.pc, m.cpu.sp = 2061, 0xF6
    for _ in range(100_000):
        if m.cpu.pc == 0xE37B:
            break
        if m.cpu.pc in KERNAL:
            getattr(m, "k_" + KERNAL[m.cpu.pc])()
            m.cpu.pc = 0x60                      # (an RTS there)
            m.ram[0x60] = 0x60
        else:
            m.cpu.step()
    check("no cartridge: the boot file says so and goes back to BASIC",
          m.cpu.pc == 0xE37B and "NO Z80" in m.printed and m.ram[0x01] == 0x37,
          repr(m.printed.strip()))

    # ---- the Z80 code on its own
    m = Machine()
    m.boot()
    lb = m.lbl

    m.z.memory[lb["d1active"]] = 0
    m.z.memory[lb["inkbd"]] = 0
    m.poke16(0x4034, 0x8001)
    seen = []
    for _ in range(3):
        m.z.iff1 = False
        m.call(lb["irqh"])
        m.z.memory[lb["d1active"]] = 0
        seen.append(m.peek16(0x4034))
    check("FRAMES counts down as DISPLAY-1 does: $8001, $0000, $FFFF, $FFFE", seen == [0x0000, 0xFFFF, 0xFFFE],
          " ".join(f"${v:04X}" for v in seen))

    costs = {}
    for label, keys, joy in (("no key", set(), set()), ("key down", {C64KEY[ZXKEY["P"]]}, set()),
                             ("stick", set(), {"up"})):
        m.keys, m.joy = keys, joy
        for tick in (0, 1):                      # irqh increments tick first
            m.z.memory[lb["tick"]] = tick
            m.z.memory[lb["d1active"]] = 0
            m.z.memory[lb["inkbd"]] = 0
            costs[label, tick] = m.call(lb["irqh"])
    m.keys, m.joy = set(), set()
    check("IRQs without the VIC's raster flag (all 9 above) are counted as stray",
          m.peek16(lb["stray"]) == 9, f"{m.peek16(lb['stray'])}")
    m.poke16(lb["stray"], 0)
    check("IRQ, no key down, no picture: under 1,300 T", costs["no key", 0] < 1300, f"{costs['no key', 0]} T")
    check("IRQ, a key down, no picture: under 7,500 T", costs["key down", 0] < 7500, f"{costs['key down', 0]} T")
    check("IRQ with the picture: under 15,000 T", costs["no key", 1] < 15000, f"{costs['no key', 1]} T")
    check("IRQ, the stick held, no picture: under 7,500 T", costs["stick", 0] < 7500, f"{costs['stick', 0]} T")
    print(f"     (a PAL frame is {FRAME_T} T at 2 T a cycle, as VICE runs the Z80)")

    # the cursor keys: what KEYBOARD returns for C64 keys and for ZX81 ones
    def kbd(*names):
        m.keys = {C64NAMES[n] if n in C64NAMES else C64KEY[ZXKEY[n]] for n in names}
        m.z.memory[lb["inkbd"]] = 0
        m.call(lb["mykbd"])
        m.keys = set()
        return m.z.hl
    # cread: three reads of a column, each bit as two of them have it; a
    # wrong read ($D0, as seen on hardware) on the first of them
    def cread(col, keys):
        m.keys = keys
        m.ciareads = 210                         # the next read is the wrong one
        m.z.a = col
        m.call(lb["cread"])
        m.keys = set()
        return m.z.a
    held = cread(0x7F, {(7, 6)})                 # Q held: column 7, row 6
    none = cread(0x7F, set())
    check("cread: one wrong read neither hides a key that is down nor shows one that isn't",
          held == 0xBF and none == 0xFF, f"Q held ${held:02X}, nothing ${none:02X}")

    pairs = [(("CRSRRIGHT",), ("SHIFT", "8"), "right"), (("CRSRDOWN",), ("SHIFT", "6"), "down"),
             (("LSHIFT", "CRSRRIGHT"), ("SHIFT", "5"), "left"), (("RSHIFT", "CRSRDOWN"), ("SHIFT", "7"), "up")]
    bad = [why for c64, zx, why in pairs if kbd(*c64) != kbd(*zx)]
    check("CRSR keys: right, down; with SHIFT left, up", not bad, f"wrong: {bad}" if bad else "")


    # IN A,($FE) reads memory at A*256+$FE on the cartridge: each scan puts
    # the rows there, and all of them ANDed at $00FE (A = 0) while a
    # program runs. $7FFE and $BFFE only past the RAM or just under RAMTOP
    def inrows():
        return {r: m.z.memory[r * 256 + 0xFE] for r in [0] + list(ZXROWS)}
    kall_rom = lb["kall_rom"]                    # the ROM's byte there
    m.z.memory[lb["edit"]] = 0                   # a program runs
    kbd("P", "SHIFT", "SPACE")
    down = inrows()
    kbd()
    up = inrows()
    want = {r: 0xFF for r in ZXROWS} | {0xDF: 0xFE, 0xFE: 0xFE, 0x7F: 0xFE, 0: 0xFE}
    check("IN A,($FE): each row where its row select reads, all of them where A = 0 does",
          down == want and set(up.values()) == {0xFF},
          " ".join(f"{r:02X}:{v:02X}" for r, v in down.items()))
    m.z.memory[lb["edit"]] = 1                   # the editor, just after its key wait
    m.z.memory[lb["eframes"]] = 1
    m.z.memory[0x00FE] = kall_rom
    kbd("P")
    kbd()
    ok_edit = m.z.memory[0x00FE] == kall_rom
    m.z.memory[lb["edit"]] = 0
    keep = []
    for size, top in ((2, 0xC000), (1, 0x7000)):  # 32K; 16K with RAMTOP lowered
        m.z.memory[lb["ramsize"]] = size
        m.poke16(0x4004, top)
        m.z.memory[0x7FFE] = m.z.memory[0xBFFE] = 0x55
        kbd("SPACE", "L")
        keep.append((m.z.memory[0x7FFE], m.z.memory[0xBFFE]))
    m.z.memory[lb["ramsize"]] = 1
    m.poke16(0x4004, 0x8000)
    kbd()
    check("IN A,($FE): $00FE left to the editor; $7FFE, $BFFE left alone where they are RAM",
          ok_edit and keep == [(0x55, 0xFD), (0x55, 0xFD)],
          f"{ok_edit} " + " ".join(f"${a:02X} ${b:02X}" for a, b in keep))

    # the stick in port 2: KEYBOARD (LAST_K, INKEY$) gets one key, the one
    # pressed last; the IN A,($FE) copies get every key the stick holds
    def want(*names):                            # KEYBOARD for those keys, no stick
        joy, m.joy = m.joy, set()
        hl = kbd(*names)
        m.joy = joy
        return hl
    nokey = want()
    bad = []
    for d, k in (("up", "7"), ("down", "6"), ("left", "5"), ("right", "8"), ("fire", "0")):
        m.joy = {d}
        if kbd() != want(k):
            bad.append(d)
        m.joy = set()
        kbd()
    check("stick: each direction gives KEYBOARD its 5678+0 key", not bad, f"wrong: {bad}" if bad else "")
    m.z.memory[lb["edit"]] = 0                   # a program runs
    m.joy = {"up"}
    kbd()
    m.joy = {"up", "right"}
    diag = kbd()
    diag_in = inrows()[0xEF]
    m.joy = set()
    kbd()
    check("stick: a diagonal gives KEYBOARD the direction pressed last, the IN mirror both",
          diag == want("8") and diag_in == 0xF3, f"${diag:04X} (8: ${want('8'):04X}), IN row $EF ${diag_in:02X}")
    m.joy = {"left"}
    kbd()
    m.joy = {"left", "fire"}
    fire = kbd()
    m.joy = {"left"}
    back = kbd()
    m.joy = set()
    kbd()
    check("stick: fire while moving gives fire; let go, the direction again",
          fire == want("0") and back == want("5"), f"${fire:04X} ${back:04X}")
    seen = []
    for joy in ({"up"}, set()):
        m.joy = joy
        for _ in range(3):
            m.ciareads = 210                     # the next CIA read is the wrong one
            seen.append(kbd())
    m.joy = set()
    kbd()
    check("stick: a wrong read of port A neither moves nor drops it",
          seen == [want("7")] * 3 + [nokey] * 3, " ".join(f"${v:04X}" for v in seen))
    cus0 = bytes(m.z.memory[lb["joycus"]:lb["joycus"] + 10])
    m.z.memory[lb["joycus"]:lb["joycus"] + 10] = bytes([0xFE, 0xFF, 0xFE, 0xFF, 0xF7, 0xEF, 0xEF, 0xFB, 0xEF, 0xFE])
    m.z.memory[lb["joyidx"]] = 1                 # a custom layout with no up or down: - - 5 8 0
    m.joy = {"right"}
    kbd()
    m.joy = {"right", "up"}
    drift = kbd()
    m.joy = set()
    kbd()
    m.joy = {"up"}                               # only a direction it leaves out,
    kbd()
    m.joy = set()                                # let go, then 5678+0
    kbd()
    m.z.memory[lb["joyidx"]] = 0
    after = kbd()
    m.z.memory[lb["joycus"]:lb["joycus"] + 10] = cus0
    check("stick: a diagonal onto a direction the layout leaves out keeps the other's key",
          drift == want("8"), f"${drift:04X}")
    check("stick: let go from a direction the layout leaves out, it is up for the next layout too",
          after == nokey, f"${after:04X}")

    # a collapsed display (1K programs): a 10-character line, then 21
    df = [0x76]
    for line in (["ABCDEFGHIJ", "KLMNOPQRSTUVWXYZABCDE"] + [""] * 22):
        df += [38 + ord(c) - 65 for c in line] + [0x76]
    old = (m.peek16(0x400C), m.peek16(0x4010))
    m.z.memory[0x6000:0x6000 + len(df)] = bytes(df)
    m.poke16(0x400C, 0x6000)
    m.poke16(0x4010, 0x6000 + len(df))
    m.call(lb["blit"])
    rows = m.screen()
    check("collapsed display: each line on its own row",
          rows[0] == "ABCDEFGHIJ" and rows[1] == "KLMNOPQRSTUVWXYZABCDE" and rows[2] == "", f"{rows[:2]}")
    m.poke16(0x400C, old[0])
    m.poke16(0x4010, old[1])

    # a setting's message goes back over the top row before row 1 is copied:
    # after the whole picture would be when the VIC is drawing that row
    m.call(lb["show"], hl=lb["msg_kbon"])         # (made into 32 characters at MSGBUF)
    msg = bytes(m.z.memory[lb["msgbuf"]:lb["msgbuf"] + 32])
    for df in (False, True):                     # the full display, a collapsed one
        if df:
            m.poke16(0x400C, 0x6000)
            m.poke16(0x4010, 0x6000 + 25)
            m.z.memory[0x6000:0x6000 + 25] = bytes([0x76] * 25)
        m.z.memory[lb["ovl"]] = 100
        m.poke16(lb["ovl_msg"], lb["msgbuf"])
        m.z.memory[SCREEN + 4:SCREEN + 36] = bytes(32)
        seen = []

        def watch(a, v, orig=m._z80_write):
            if a == SCREEN + 44 and not seen:
                seen.append(bytes(m.z.memory[SCREEN + 4:SCREEN + 36]) == msg)
            orig(a, v)
        m.z.set_write_callback(watch)
        m.z.mark_addrs(SCREEN + 44, 1, m.z.WRITE_MARK)
        m.call(lb["blit"])
        m.z.set_write_callback(m._z80_write)
        check(f"the message is on the top row before row 1 is copied ({'collapsed' if df else 'full'} display)",
              seen == [True], f"{seen}")
    m.poke16(0x400C, old[0])
    m.poke16(0x4010, old[1])
    m.z.memory[lb["ovl"]] = 0

    # ---- the whole machine, with /INT wired (as VICE has it)
    m = Machine(int_wired=True)
    m.boot(banner=True)
    ver = re.search(r'VERSION = "([^"]+)"', open(os.path.join(ROOT, "tools", "build.py")).read()).group(1)
    check("the version on the top row as zx64 starts", m.screen()[0].strip() == f"zx64 {ver}",
          f"{m.screen()[0]!r}")
    m.until(lambda: not m.z.memory[lb["ovl"]], 200, "the version gone")

    # F2 (SHIFT+F1): the colour schemes, round; F1 alone still type-ahead
    def colours():
        return (set(c & 15 for c in m.z.memory[0xC800:0xC800 + 1000]), m.z.memory[0xC021] & 15,
                m.z.memory[0xC020] & 15)
    seen, kb = [], m.z.memory[lb["kbuf"]]
    for _ in range(6):
        m.keys = {C64NAMES["LSHIFT"], C64NAMES["F1"]}
        m.run(3)
        m.keys = set()
        m.run(10)
        seen.append((colours(), m.screen()[0].split("  ")[0].strip()))
    want = [({1}, 0, 0), ({13}, 0, 0), ({8}, 0, 0), ({0}, 13, 13), ({14}, 6, 14), ({0}, 1, 1)]
    f2_ok = [c for c, _ in seen] == want and m.z.memory[lb["kbuf"]] == kb and seen[0][1] == "white on black"
    m.tap("F1", frames=10)
    check("F2 steps through 6 colour schemes and back, naming each on the top row; F1 alone is still "
          "type-ahead", f2_ok and m.z.memory[lb["kbuf"]] != kb, f"{seen}")
    m.tap("F1", frames=10)
    m.until(lambda: not m.z.memory[lb["ovl"]], 200, "the message gone")
    check("boots to the K cursor", m.cursor(), f"(frame {m.frames}, {m.irqs} IRQs)")
    m.joy = {"up"}
    m.run(30)
    m.joy = set()
    m.run(10)
    typed = m.screen()[22:]
    m.type("SHIFT+0")
    check("stick in the editor: held 30 frames, one 7 typed", any(r in ("7k", "7l") for r in typed), f"{typed}")
    r = enter(m, "P 2 SHIFT+K 2")
    check("PRINT 2+2", m.screen()[0] == "4" and r == "0/0", f"{m.screen()[0]!r} {r}")

    for line in ("1 0 P SHIFT+P O K SHIFT+P", "2 0 P SHIFT+P B SHIFT+P"):
        m.type(line + " NEWLINE")
    m.barlog = []                                # (booting cleared those cells too)
    r = enter(m, "S SHIFT+P T SHIFT+P")
    t = m.drive.files.get(b"T", b"")
    eline = m.peek16(0x4014)
    names = []                                   # setname: every ZX81 code, inverse too
    for first in range(0, 128, 16):
        m.z.memory[0x7000:0x7010] = bytes(range(first, first + 16))
        m.z.de, m.z.bc = 0x7000, 15
        m.call(lb["setname"], resume=True)
        names.append(bytes(m.z.memory[0x2F03:0x2F13]))
    check("file names: each ZX81 code as its PETSCII", b"".join(names) == bytes(zx2pet()) * 2,
          b"".join(names).hex())
    check('SAVE "T"', r == "0/0" and len(t) == eline - 0x4009, f"{r}, {len(t)} bytes, E_LINE-$4009 = {eline - 0x4009}")

    def zx(codes):                               # inverse codes as text, inverse as plain
        return "".join(ZX[c & 0x3F] for c in codes)
    saving = zx(m.top_at_switch[:22])
    cells = {a: v for a, v in m.barlog if a < 0xE022}
    spins = sum(1 for a, v in m.barlog if a == 0xE023)
    bar_ok = (len([1 for a, v in m.barlog if a < 0xE022]) == 16 and sorted(cells) == list(range(0xE01A, 0xE022))
              and set(cells.values()) == {0x80} and m.top_at_switch[22:30] == bytes(8)
              and all(c & 0x80 for c in m.top_at_switch[:22]))
    check("SAVE shows \" SAVING  T\" on the top row, its white bar filled black half a cell (1/16) at a "
          "time, the spinner turning every 128 bytes", saving.rstrip() == " SAVING  T" and bar_ok and spins >= 5,
          f"{saving!r}, {len(m.barlog)} writes, {spins} spinner steps")
    m.barlog = []

    new(m)
    check("NEW leaves RAMTOP at $8000", m.peek16(0x4004) == 0x8000, f"${m.peek16(0x4004):04X}")
    r = enter(m, "J SHIFT+P T SHIFT+P")
    r2 = enter(m, "R")
    scr = m.screen()
    check('LOAD "T", RUN', r == "0/0" and scr[0] == "OK" and scr[1] == "B", f"{r} {scr[:2]} {r2}")
    check("LOAD shows \" LOADING T\" and fills the bar; afterwards the top row is the program's again",
          zx(m.top_at_switch[:22]).rstrip() == " LOADING T"
          and len([1 for a, v in m.barlog if a < 0xE022]) == 16 and scr[0] == "OK",
          f"{zx(m.top_at_switch[:22])!r}")

    m.drive.files[b"GAME.P"] = t
    new(m)
    r = enter(m, "J SHIFT+P G A M E SHIFT+P")
    check('LOAD "GAME" finds GAME.P', r == "0/0" and m.peek16(0x4014) == eline, f"{r}")

    r = enter(m, "J SHIFT+P N O P E SHIFT+P")
    check('LOAD "NOPE": report D', r is not None and r.startswith("D/"), f"{r}")

    # autorun: SAVE in a program, LOAD carries on after it
    new(m)
    for line in ("1 0 S SHIFT+P A SHIFT+P", "2 0 P SHIFT+P A U T O SHIFT+P"):
        m.type(line + " NEWLINE")
    enter(m, "R")
    new(m)
    r = enter(m, "J SHIFT+P A SHIFT+P")
    check('LOAD "A" runs on from the line after SAVE', m.screen()[0] == "AUTO", f"{m.screen()[0]!r} {r}")

    # trailing junk: the load stops at E_LINE
    m.drive.files[b"BIG"] = t + b"\xff" * 12000
    new(m)
    r = enter(m, "J SHIFT+P B I G SHIFT+P")
    r2 = enter(m, "R")
    junk = m.z.memory[0x4009 + len(t):0x4009 + len(t) + 2000].tobytes().count(0xFF)
    check("LOAD stops at E_LINE, junk after it is left alone",
          r == "0/0" and m.screen()[0] == "OK" and junk < 100, f"{r} {r2} {m.screen()[0]!r}, {junk} $FF bytes after it")

    big = bytearray(t)
    big[0x4014 - 0x4009:0x4016 - 0x4009] = (0x7FFF).to_bytes(2, "little")   # SP is about $7FFA
    m.drive.files[b"HUGE"] = bytes(big) + bytes(0x7FFF - 0x4009 - len(big))
    r = enter(m, "J SHIFT+P H U G E SHIFT+P")
    check("a program into the Z80's stack: report 4, not a crash", r is not None and r.startswith("4/"), f"{r}")
    full = bytearray(t)                          # a full 16K program, as BoulderL is
    full[0x4014 - 0x4009:0x4016 - 0x4009] = (0x7F80).to_bytes(2, "little")
    m.drive.files[b"FULL"] = bytes(full) + bytes(0x7F80 - 0x4009 - len(full))
    r = enter(m, "J SHIFT+P F U L L SHIFT+P")
    check("a program up to $7F80 loads", r == "0/0" and m.peek16(0x4014) == 0x7F80, f"{r}")
    enter(m, "J SHIFT+P T SHIFT+P")              # back to a sane program

    opens = m.drive.opens
    enter(m, "O 5 2 7 3 6 SHIFT+. 1")             # POKE 52736,1: a stray write to $DE00
    r = enter(m, "P 3")
    check("a stray switch to the 6510 does nothing", m.drive.opens == opens and m.screen()[0] == "3",
          f"{m.drive.opens - opens} opens, {m.screen()[0]!r} {r}")

    m.drive.protected = True
    r = enter(m, "S SHIFT+P W P SHIFT+P")
    check("SAVE to a write-protected disk: report D", r is not None and r.startswith("D/"), f"{r}")
    m.drive.protected = False

    # the C64's cursor keys, SHIFT for left and up, in the edit line
    r = enter(m, "P 1 2 LSHIFT+CRSRRIGHT 3")      # PRINT 12, left, 3: PRINT 132
    check("SHIFT+CRSR RIGHT is left", m.screen()[0] == "132", f"{m.screen()[0]!r} {r}")

    # a machine code program reading the keyboard itself, as BoulderL
    # does, started from the edit line: once FRAMES has gone 10 down,
    # XOR A / IN A,($FE) and LD A,$FE / IN A,($FE), as USR's BC. SHIFT
    # is held with NEWLINE: on its own it is no key for the editor
    code = bytes.fromhex("213440 7E D60A BE 20FD"    # wait for FRAMES to go 10 down
                         "AF DBFE 4F 3EFE DBFE 47 C9")  # C: all rows, B: SHIFT Z X C V
    m.z.memory[0x7000:0x7000 + len(code)] = code
    m.type("P SHIFT+NEWLINE L 2 8 6 7 2")         # PRINT USR 28672
    m.keys = {C64KEY[ZXKEY["NEWLINE"]]}
    m.run(2)
    m.keys |= {C64NAMES["LSHIFT"]}
    m.until(lambda: any(x[0] == "IN" and 0x7000 <= x[1] < 0x7000 + len(code) for x in m.io), 300, "the INs")
    m.keys = set()
    m.until(m.ready, 300, "the ROM ready for a key")
    m.run(3)
    m.io = [x for x in m.io if not 0x7000 <= x[1] < 0x7000 + len(code)]
    check("IN A,($FE) in a program: SHIFT and NEWLINE down; $00FE is the ROM's again after it",
          m.screen()[0] == str(0xFEFE) and m.z.memory[0x00FE] == kall_rom,
          f"{m.screen()[0]!r} (want {0xFEFE}), ${m.z.memory[0x00FE]:02X}")

    # ---- FAST and SLOW
    m = Machine(int_wired=True)
    m.boot()
    for line in ("1 0 SHIFT+F",                              # 10 FAST
                 "1 5 M 1 0",                                # 15 PAUSE 10
                 "2 0 L T SHIFT+L SHIFT+NEWLINE O 1 6 4 3 6",  # 20 LET T=PEEK 16436
                 "3 0 F I SHIFT+L 1 SHIFT+4 2 0 0",          # 30 FOR I=1 TO 200
                 "4 0 N I",                                  # 40 NEXT I
                 "5 0 P SHIFT+NEWLINE O 1 6 4 3 6 SHIFT+J T"):  # 50 PRINT PEEK 16436-T
        m.type(line + " NEWLINE")
    f0 = m.frames
    r = enter(m, "R")
    check("FAST: FRAMES stands still while a program runs, also after a PAUSE",
          m.screen()[0] == "0" and r == "0/50", f"{m.screen()[0]!r} {r}, {m.frames - f0} frames")
    check("FAST: no interrupt while a program runs", m.fast_irqs == 0, f"{m.fast_irqs} taken")
    m.type("1 0 SHIFT+D NEWLINE")                            # 10 SLOW
    r = enter(m, "R")
    check("SLOW: FRAMES counts while a program runs", m.screen()[0] not in ("", "0") and r == "0/50",
          f"{m.screen()[0]!r} {r}")
    enter(m, "SHIFT+F")                                      # FAST, as a command
    r = enter(m, "P 9")
    check("FAST: the picture still works while the ROM waits for a key",
          m.screen()[0] == "9" and r == "0/0" and m.fast_irqs == 0, f"{m.screen()[0]!r} {r}")

    # ---- type-ahead (F1 switches it off and on again)
    def roll(m, word, hold=5, step=3):
        """Each key goes down `step` frames after the last and stays down
        `hold` frames: the next is down before the last is up, as in touch
        typing."""
        events = [(i * step, k, True) for i, k in enumerate(word)] + \
                 [(i * step + hold, k, False) for i, k in enumerate(word)]
        down = set()
        for f in range(max(t for t, _, _ in events) + 1):
            for t, k, d in events:
                if t == f:
                    (down.add if d else down.discard)(C64KEY[ZXKEY[k]])
            m.keys = set(down)
            m.run(1)
        m.keys = set()
        m.run(30)                                            # the editor takes them all

    def tap(m, name):
        """Press a key for 3 frames; returns the top row a frame after, where
        a setting's message shows. Then waits the message out (2 seconds)
        and for the ROM to be ready for keys (after a reset, with the K
        cursor; otherwise a report may still be showing)."""
        m.keys = set(FKEYS[name]) if name in FKEYS else {C64NAMES[name]}
        m.run(3)
        m.keys = set()
        m.run(3)
        top = m.screen()[0]
        m.run(110)
        reset = name in ("F7", "F8")
        m.until(lambda: m.ready() and (m.cursor() or not reset), 600, f"the ROM ready after {name}")
        return top

    m = Machine(int_wired=True)
    m.boot()
    lb = m.lbl
    m.type("P SHIFT+P")                                      # PRINT "
    roll(m, "SINCLAIR")
    r = enter(m, "SHIFT+P")
    check("type-ahead: SINCLAIR touch typed, each key down before the last is up",
          m.screen()[0] == "SINCLAIR" and r == "0/0", f"{m.screen()[0]!r} {r}")
    top = tap(m, "F1")
    off = m.z.memory[lb["kbuf"]] == 0 and top.strip().startswith("type-ahead off")
    m.type("P SHIFT+P")
    roll(m, "SINCLAIR")
    r = enter(m, "SHIFT+P")
    check("F1: the ROM's own debounce (said on the top row), which takes only the S",
          off and m.screen()[0] == "S" and r == "0/0", f"{m.screen()[0]!r} {r}")
    top = tap(m, "F1")
    check("F1 again: type-ahead, said on the top row", m.z.memory[lb["kbuf"]] == 1
          and top.strip().startswith("type-ahead on"), f"{top!r}")
    m.type("P SHIFT+P")                                      # PRINT "TEST: E and S still
    roll(m, "TEST", hold=8, step=3)                          # down as the second T goes
    r = enter(m, "SHIFT+P")                                  # down, F reads as down too
    check("type-ahead: TEST typed fast is TEST, not TESFT (the C64 matrix's ghost key)",
          m.screen()[0] == "TEST" and r == "0/0", f"{m.screen()[0]!r} {r}")

    def keys(*steps):                                        # C64 keys by MPOS name, 2 frames each
        for s in steps:
            m.keys = {MPOS[k] for k in s.split()}
            m.run(2)
        m.keys = set()
        m.run(30)
    m.type("P SHIFT+P")                                      # PRINT "
    keys("A", "", "DEL", "DEL G", "G", "",                   # G down before DEL is up
         "B", "", "D", "", "LEFTARROW", "LEFTARROW C", "C",  # C down before <- (SHIFT 5) is up
         "", "CRSRRIGHT")                                    # (back past the D)
    r = enter(m, "SHIFT+P")
    check("type-ahead: a key down while DEL or <- is still down has no SHIFT from them (G, not LLIST)",
          m.screen()[0] == "GBCD" and r == "0/0", f"{m.screen()[0]!r} {r}")

    m.type("1 0 G 1 0 NEWLINE")                              # 10 GOTO 10
    m.type("R")
    m.keys = {C64KEY[ZXKEY["NEWLINE"]]}
    m.until(lambda: m.z.memory[0x4027] == 0xFF, 100, "RUN taken")
    m.keys = set()
    m.run(20)
    roll(m, "ABC", hold=4, step=8)                           # keys while it runs...
    m.keys = {C64KEY[ZXKEY["SPACE"]]}
    m.until(m.ready, 200, "BREAK")
    m.keys = set()
    m.run(5)
    r = enter(m, "P 7")
    check("keys pressed while a program runs don't reach the editor after it",
          m.screen()[0] == "7" and r == "0/0", f"{m.screen()[0]!r} {r}")

    bad = []                                                 # each key, coded as KEYBOARD does
    for name in ZXKEY:
        for shift in ((), ("SHIFT",)) if name != "SHIFT" else ():
            m.z.memory[lb["kq_in"]] = m.z.memory[lb["kq_out"]] = 0
            m.z.memory[lb["kprev"]:lb["kprev"] + 8] = b"\xff" * 8
            m.z.memory[lb["kpup"]] = m.z.memory[lb["inkbd"]] = 0
            m.z.memory[lb["edit"]] = m.z.memory[lb["kbuf"]] = 1
            m.keys = {C64KEY[ZXKEY[k]] for k in (name,) + shift}
            m.call(lb["mykbd"])
            if m.z.memory[lb["kq_in"]] != 1 or m.peek16(lb["kq"]) != m.z.hl:
                bad.append("+".join(shift + (name,)))
    m.keys = set()
    check("type-ahead codes each key, with and without SHIFT, as KEYBOARD does", not bad, f"wrong: {bad}")

    # ---- F7 starts the ZX81 again
    m = Machine(int_wired=True)
    m.boot()
    m.type("1 0 P 1 NEWLINE")                                # 10 PRINT 1
    m.run(3)                                                 # the picture lags a frame or two
    had = m.peek16(0x400C) != 0x407D                         # D_FILE: a program before it
    m.keys = {C64NAMES["F7"]}
    m.run(20)
    held = m.cursor() and m.peek16(0x400C) != 0x407D         # nothing until F7 is let go
    m.keys = set()
    m.until(lambda: m.cursor() and m.ready(), 400, "the K cursor after F7")
    check("F7 at the prompt: the ZX81 starts again, once the key is up",
          had and held and m.peek16(0x400C) == 0x407D, f"(frame {m.frames})")
    for line in ("1 0 SHIFT+F", "2 0 G 2 0"):                # 10 FAST, 20 GOTO 20
        m.type(line + " NEWLINE")
    m.type("R")
    m.keys = {C64KEY[ZXKEY["NEWLINE"]]}
    m.until(lambda: m.z.memory[0x4027] == 0xFF, 100, "RUN taken")
    m.keys = set()
    m.run(50)
    running = not m.ready()
    m.keys = {C64NAMES["F7"]}
    m.run(5)
    m.keys = set()
    m.until(lambda: m.cursor() and m.ready(), 400, "the K cursor after F7 in FAST")
    check("F7 in a FAST program: the ZX81 starts again", running and m.peek16(0x400C) == 0x407D,
          f"(frame {m.frames})")
    for line in ("1 0 SHIFT+F", "2 0 G 2 0"):
        m.type(line + " NEWLINE")
    m.type("R")
    m.keys = {C64KEY[ZXKEY["NEWLINE"]]}
    m.until(lambda: m.z.memory[0x4027] == 0xFF, 100, "RUN taken")
    m.keys = set()
    m.run(50)
    running = not m.ready()
    m.keys = set(FKEYS["F8"])
    m.run(5)
    m.keys = set()
    m.until(lambda: m.cursor() and m.ready(), 400, "the K cursor after F8 in FAST")
    check("F8 in a FAST program: the next memory size (32K), the ZX81 starts again",
          running and m.peek16(0x4004) == 0xC000 and m.peek16(0x400C) == 0x407D, f"RAMTOP ${m.peek16(0x4004):04X}")

    # ---- F7 after a program wrote over the ROM (aydemo.p's AY register
    # selects, OUT ($DF),A with A = 0-15, and its data, OUT ($0F),A: A = 0
    # lands at $000F): the ROM read again from the disk
    m = Machine(int_wired=True)
    m.boot()
    rom = bytes(m.z.memory[0x0000:0x2000])
    m.drive.files[b"ZX64"] = open(os.path.join(ROOT, "build", "obj", "zx64.prg"), "rb").read()
    m.z.memory[0x00FE] = 0x5A                                # the rows zx64 puts there: not damage
    opens = m.drive.opens
    m.tap("F7", 3)
    m.until(lambda: m.cursor() and m.ready(), 400, "the K cursor after F7")
    check("F7 with the ROM as it was: no disk access", m.drive.opens == opens
          and m.z.memory[0x00FE] == rom[0x00FE], f"{m.drive.opens - opens} opens")
    font = bytes(m.z.memory[0xD800:0xE000])                  # the charset, C64 $E800
    for a in list(range(0x00DF, 0x1000, 0x100)) + list(range(0x000F, 0x1000, 0x100)):
        m.z.memory[a] ^= 0x55
    m.z.memory[0x0000:0x0005] = bytes(5)                     # the calculator's own writes: ignored
    m.z.memory[0xD80F] = 0xD8                                # aydemo's A = $D8: char 1's bottom row
    m.z.memory[0xDC0F] = 0xDC                                # and its inverse's
    m.barlog = []
    m.tap("F7", 3)
    m.until(lambda: m.cursor() and m.ready(), 600, "the K cursor after F7, the ROM read again")
    back = bytes(m.z.memory[0x0005:0x2000]) == rom[0x0005:]
    check("F7 with the ROM written over: read again from ZX64 (with the bar), the ZX81 starts",
          back and m.drive.opens == opens + 1 and m.barlog and not m.channels,
          f"ROM {'back' if back else 'still wrong'}, {m.drive.opens - opens} opens, {len(m.barlog)} bar writes")
    check("F7 with the ROM read again: the C64's charset made again from it",
          bytes(m.z.memory[0xD800:0xE000]) == font,
          f"{sum(x != y for x, y in zip(m.z.memory[0xD800:0xE000], font))} bytes differ")
    m.tap("F7", 3)
    m.until(lambda: m.cursor() and m.ready(), 600, "the K cursor after F7 again")
    check("F7 again after the ROM was read again: no disk access", m.drive.opens == opens + 1,
          f"{m.drive.opens - opens - 1} more opens")

    # The ROM read again only if ZX64 is this build's, into the
    # ZX81's RAM first, clear of the Z80's stack; why not, on the top row
    def f7_rom(m, files, damage=0x0100):
        m.drive.files.pop(b"ZX64", None)
        m.drive.files.update(files)
        m.z.memory[damage] ^= 0x55
        hurt = bytes(m.z.memory[0x0005:0x2000])
        opens = m.drive.opens
        m.tap("F7", 3)
        m.until(lambda: m.cursor() and m.ready(), 600, "the K cursor after F7")
        return bytes(m.z.memory[0x0005:0x2000]) == hurt, m.drive.opens - opens, m.screen()[0].strip()
    prg = open(os.path.join(ROOT, "build", "obj", "zx64.prg"), "rb").read()
    other = bytearray(prg)
    other[2 + 0x1000 - 0x0801 + 0x0400] ^= 0xFF                 # another build: a byte of its ROM
    seen = [f7_rom(m, {}), f7_rom(m, {b"ZX64": bytes(other)}, damage=0x0200)]
    m.z.memory[0x0100] ^= 0x55                               # (both left the ROM as it was)
    m.z.memory[0x0200] ^= 0x55
    check("F7: no ZX81 on the disk, or another build's: the ROM left as it was, the ZX81 starts, "
          "the top row says why",
          seen == [(True, 1, "rom not reloaded: no zx64"), (True, 1, "rom not reloaded: other zx64")], f"{seen}")
    sv = lb["romsum_v"]
    m.z.memory[sv] ^= 1                                      # zx64's own copy of the sum
    seen = f7_rom(m, {b"ZX64": prg})
    m.z.memory[sv] ^= 1
    m.z.memory[0x0100] ^= 0x55
    check("F7 with zx64's own code written over (romsum_v): no disk access, the top row says so",
          seen == (True, 0, "zx64 changed: load it again"), f"{seen}")
    for _ in range(2):                                       # 32K, then 1K: the Z80's stack
        m.tap("F8", 3)                                       # under $4400
        m.until(lambda: m.cursor() and m.ready(), 600, "the K cursor after F8")
    m.z.memory[0x6000:0x8000] = bytes(0x2000)
    ok, opens, top = f7_rom(m, {b"ZX64": prg})
    back = bytes(m.z.memory[0x0005:0x2000]) == rom[0x0005:]
    check("F7 in 1K (the stack in the first buffer, Z80 $4000): read into the other ($6000), the ROM back",
          back and opens == 1 and bytes(m.z.memory[0x6005:0x8000]) == rom[0x0005:] and top.startswith("1k ram "),
          f"ROM {'back' if back else 'wrong'}, {opens} opens, {top!r}")

    # ---- the JiffyDOS reader (c64/jcore.asm): put in place by start; jtalk
    # and jget against IEC's drive, a JiffyDOS one, a plain one, none
    jl = jlabels()
    m = Machine(int_wired=True)
    m.boot()
    core = open(os.path.join(ROOT, "build", "obj", "jcore.bin"), "rb").read()
    pieces = [(jl["jimg" + n] - 0x3E00, at, jl["jc" + n + "end"]) for n, at in (("1", 0x0334), ("2", 0x02A7),
                                                                                  ("3", 0x0200))]
    check("the JiffyDOS reader in place after the boot: $0334, $02A7 and $0200; no JiffyDOS read open",
          m.ram[jl["JFLAG"]] == 0 and all(m.ram[at:end] == core[o:o + end - at] for o, at, end in pieces),
          f"JFLAG {m.ram[jl['JFLAG']]}")

    def portbits(m):
        """What jtalk should make of $DD00 and $D011: JREL JPULL JFIX JNY."""
        rel = m.ram[0xDD00] & 7
        fix = rel
        for _ in range(3):
            fix = fix >> 2 ^ rel
        return rel, rel | 0x20, fix, (m.ram[0xD011] & 7) ^ 7

    def jbits(m):
        return tuple(m.ram[jl[n]] for n in ("JREL", "JPULL", "JFIX", "JNY"))

    def jread(m, data, jiffy=True, present=True, stuck=False):
        """OPEN the kernal's way, then jtalk and (if the drive said yes) jget
        to the last byte, jend, CLOSE: (JFLAG, the bytes, JST, the ATN bytes)."""
        m.drive.files[b"JT"] = data
        m.iec = IEC(m, jiffy=jiffy, present=present, stuck=stuck)
        m.ram[0x5000:0x5002] = b"JT"
        m.call_6510(0xFFBD, a=2, x=0x00, y=0x50)            # SETNAM
        m.call_6510(0xFFBA, a=2, x=8, y=2)                  # SETLFS 2,8,2
        m.call_6510(0xFFC0)                                 # OPEN
        m.call_6510(jl["jtalk"], a=8, x=0x62)
        got = bytearray()
        flag = m.ram[jl["JFLAG"]]
        while flag and not m.ram[jl["JST"]] & 0x42 and len(got) <= len(data):
            got.append(m.call_6510(jl["jget"])[0])
        m.call_6510(jl["jend"])
        m.call_6510(0xFFC3, a=2)                            # CLOSE
        return flag, bytes(got), m.ram[jl["JST"]], m.iec.atn_bytes
    data = bytes(range(256)) + bytes(255 - i for i in range(256)) + b"\x00\xff\x55"
    gos = []
    write = IEC.write
    def gowatch(self, v):
        was = self.go_at
        write(self, v)
        if self.go_at is not None and was is None:
            gos.append(self.go_at)
    IEC.write = gowatch
    m.rasters = []
    try:
        seen = jread(m, data)
    finally:
        IEC.write = write
    held = sum(1 for r in m.rasters if r & 7 >= 5)
    line = lambda t: (t // 63 + 250) % 312
    check("jtalk and jget, a JiffyDOS drive: it says yes, every byte as sent, the last one marked; "
          "the port's bits and the y-scroll worked out",
          seen[0] == 1 and seen[1] == data and seen[2] == 0x40 and seen[3] == [0x48, 0x62]
          and jbits(m) == portbits(m) and portbits(m)[0] == 4 and portbits(m)[3] == 0,
          f"JFLAG {seen[0]}, {len(seen[1])} of {len(data)} bytes, "
          f"{'same' if seen[1] == data else 'different'}, JST ${seen[2]:02X}, ATN {seen[3]}")
    check("jget's raster guard: each byte starts on a line 0-4 mod 8, its mark before the bad line (7); "
          "on 5-7 it waits", len(gos) == len(data) and held
          and all(line(t) & 7 < 5 and line(t + 58) & 7 != 7 for t in gos),
          f"{len(gos)} bytes, lines mod 8 {sorted({line(t) & 7 for t in gos})}, {held} reads held back")
    seen = [jread(m, data, jiffy=False)[0::3], jread(m, data, present=False)]
    check("jtalk, a plain drive: no; no drive at all: no, and the lines let go",
          seen[0] == (0, [0x48, 0x62]) and seen[1][0] == 0 and seen[1][3] == [] and m.iec.out == 0,
          f"{seen[0]}, none: JFLAG {seen[1][0]} ATN {seen[1][3]} lines ${m.iec.out:02X}")
    t0 = m.cpu.processorCycles
    stuck = jread(m, data, stuck=True)
    took = m.cpu.processorCycles - t0
    check("jtalk, a drive that answers ATN and then never lets go of DATA: a time-out (about 1 s), "
          "no JiffyDOS, the lines let go", stuck[0] == 0 and stuck[3] == [] and m.iec.out == 0 and took < 2_000_000,
          f"JFLAG {stuck[0]}, {took} cycles, lines ${m.iec.out:02X}")

    # ---- F8 (SHIFT+F7): 16K, 32K, 1K, 16K again; each starts the ZX81 again
    def size(m):
        top = tap(m, "F8")
        return m.peek16(0x4004), top.split()[0] if top.split() else ""

    def dim(m, n):
        """DIM A(n): n*5 bytes, and then the last element set and printed."""
        r = enter(m, "D A SHIFT+I " + " ".join(str(n)) + " SHIFT+O")
        if r != "0/0":
            return r
        enter(m, "L A SHIFT+I " + " ".join(str(n)) + " SHIFT+O SHIFT+L 7")
        r = enter(m, "P A SHIFT+I " + " ".join(str(n)) + " SHIFT+O")
        return r if m.screen()[0] != "7" else "7"

    m = Machine(int_wired=True)
    m.boot()
    m.drive.files[b"BIG"] = b""
    r16 = dim(m, 4000)                                       # 20,000 bytes: too many for 16K
    top32, sz32 = size(m)
    r32 = dim(m, 4000)
    eline = m.peek16(0x4014)
    r = enter(m, "S SHIFT+P B I G SHIFT+P")
    saved = len(m.drive.files[b"BIG"]) == eline - 0x4009
    check("F8: 32K, RAMTOP $C000; DIM A(4000) fits, as it doesn't in 16K",
          top32 == 0xC000 and sz32 == "32k" and r16.startswith("4/") and r32 == "7" and saved,
          f"RAMTOP ${top32:04X} {sz32!r}, 16K: {r16}, 32K: {r32}, E_LINE ${eline:04X}, SAVE {r}")
    new(m)
    r = enter(m, "J SHIFT+P B I G SHIFT+P")
    r2 = enter(m, "P A SHIFT+I 4 0 0 0 SHIFT+O")
    check("32K: the 20K program saved loads again", r == "0/0" and m.screen()[0] == "7", f"{r} {r2}")
    new(m)
    check("32K: NEW keeps RAMTOP", m.peek16(0x4004) == 0xC000, f"${m.peek16(0x4004):04X}")
    top1, sz1 = size(m)
    r1 = enter(m, "P 1 2")
    rd = enter(m, "D A SHIFT+I 3 0 0 SHIFT+O")                # 1,500 bytes
    rl = enter(m, "J SHIFT+P B I G SHIFT+P")
    check("F8 again: 1K, RAMTOP $4400; PRINT works, DIM A(300) and the 20K program don't fit",
          top1 == 0x4400 and sz1 == "1k" and r1 == "0/0" and rd.startswith("4/") and rl.startswith("4/"),
          f"RAMTOP ${top1:04X} {sz1!r}, PRINT {r1}, DIM {rd}, LOAD {rl}")
    top16, sz16 = size(m)
    m.keys = {C64NAMES["F7"]}
    m.run(3)
    m.keys = set()
    m.until(lambda: m.cursor() and m.ready(), 600, "the K cursor after F7")
    check("F8 again: 16K, and F7 keeps the size", top16 == 0x8000 and sz16 == "16k" and m.peek16(0x4004) == 0x8000,
          f"RAMTOP ${top16:04X} {sz16!r}, after F7 ${m.peek16(0x4004):04X}")

    # MEM tests every free byte: 32K, then with a byte that doesn't hold
    class Stuck(Machine):
        stuck = None                             # an address whose writes are lost

        def _z80_write(self, a, v):
            if a != self.stuck:
                super()._z80_write(a, v)

    def mem(m):
        m.drive.files[b"MEM"] = open(os.path.join(ROOT, "build", "obj", "mem.p"), "rb").read()
        r = enter(m, "J SHIFT+P M E M SHIFT+P")
        return r, [x for x in m.screen() if x.strip()]

    m = Stuck(int_wired=True)
    m.boot()
    m.z.mark_addrs(0x9000, 1, m.z.WRITE_MARK)
    tap(m, "F8")
    r, scr = mem(m)
    check("MEM in 32K: every free byte, up to $BFxx, OK",
          "RAM      32K" in scr and "MEMORY OK" in scr and r.startswith("0/"), f"{scr[4:6]} {r}")
    m.stuck = 0x9000
    r, scr = mem(m)
    check("MEM finds a byte that doesn't hold ($9000)", any(x.endswith("FIRST AT 36864") for x in scr),
          f"{scr[-2:]}")

    # ---- the joystick: F3 switches the layouts
    m = Machine(int_wired=True)
    m.boot()
    lb = m.lbl
    kpage = lb["kpage"]

    def f3(frames=3):                            # F3 down, then up; SHIFT's row
        m.keys = {C64NAMES["F3"]}                # bit as the program sees it meanwhile
        m.run(frames)
        shift = m.z.memory[kpage + 0xFE] & 1
        m.keys = set()
        m.run(10)
        return shift

    def joyrow(keys):                            # the top row as screen() shows it
        return (" joystick  " + " ".join(n + k for n, k in zip("udlrf", keys))).ljust(27) + "  f3"

    rows, shifts, reqs = [], [], []
    for _ in range(4):
        shifts.append(f3())
        rows.append(m.screen()[0])
        reqs.append(m.z.memory[lb["monreq"]])
    check("F3 with no keys taught stays on 5678+0, shown on the top row",
          rows == [joyrow("76580")] * 4 and m.z.memory[lb["joyidx"]] == 0, f"{rows}")
    check("F3 is not the monitor, and gives the program no SHIFT",
          reqs == [0] * 4 and shifts == [1] * 4, f"monreq {reqs}, SHIFT bit {shifts}")
    m.run(100)

    mc = lb["mon_call"]                          # BREAK-1's F5 check: F3 isn't F5
    keep = m.z.memory[mc]
    m.z.memory[mc] = 0xC9
    m.z.memory[lb["f5down"]] = 0
    edit = m.z.memory[lb["edit"]]                # (brk says a program runs: the
    m.keys = {C64NAMES["F3"]}                    # editor's state back afterwards)
    m.call(lb["brk"], resume=True)
    took = m.z.memory[lb["f5down"]]
    m.z.memory[lb["f5down"]] = 1                 # F3 taken by scan, still down: BREAK-1
    m.call(lb["brk"], resume=True)               # leaves it (else a held F3 would come
    kept = m.z.memory[lb["f5down"]]              # again and again in a FAST program)
    m.keys = set()
    m.z.memory[mc] = keep
    m.z.memory[lb["f5down"]] = 0
    m.z.memory[lb["edit"]] = edit
    m.z.memory[0x00FE] = lb["kall_rom"]
    m.run(10)
    check("F3 in BREAK-1 is not the monitor, and leaves F3's down for scan", took == 0 and kept == 1,
          f"f5down {took}, held {kept}")
    m.keys = {C64NAMES["LSHIFT"], C64NAMES["F5"]}
    m.run(3)
    m.keys = set()
    m.run(10)
    check("SHIFT+F5 (F6) is F5: the monitor (here not on the disk: said on the top row)",
          m.screen()[0].strip().startswith("no zx64mon"), f"{m.screen()[0]!r}")
    m.run(150)

    for line in ("5 L A SHIFT+L 0", "1 0 L A SHIFT+L A SHIFT+K 1", "2 0 G 1 0"):
        m.type(line + " NEWLINE")                # 5 LET A=0, 10 LET A=A+1, 20 GOTO 10
    m.type("R")
    m.keys = {C64KEY[ZXKEY["NEWLINE"]]}
    m.run(3)
    m.keys = set()
    m.run(30)

    def aval():                                  # A's value, as the calculator holds it
        return bytes(m.z.memory[m.peek16(0x4010) + 1:m.peek16(0x4010) + 6])
    m.z.memory[lb["joyhave"]] = 1                # as if taught: F3 switches
    a1 = aval()
    f3()
    m.run(20)
    check("a tap of F3 doesn't stop the program", aval() != a1 and m.z.memory[lb["joyidx"]] == 1,
          f"joyidx {m.z.memory[lb['joyidx']]}")
    f3()                                         # back to 5678+0 for the stick below
    bad = []
    for d in STICK:
        kb, sch = m.z.memory[lb["kbuf"]], m.z.memory[lb["scheme"]]
        m.joy = {d}
        m.run(3)
        m.tap("F1", frames=10)
        a1 = aval()
        m.run(10)
        if m.z.memory[lb["kbuf"]] == kb or m.z.memory[lb["scheme"]] != sch or m.z.memory[lb["monreq"]] \
                or aval() == a1:
            bad.append(d)
        m.tap("F1", frames=10)
        m.joy = set()
        m.run(3)
    check("with the stick held in any direction F1 does only its own job", not bad, f"wrong: {bad}")
    bad = []                                     # its column's row-3 key shows as F7 in
    for d, k in (("down", "4"), ("left", "6"), ("right", "8"), ("fire", "0"),   # column 0; with up
                 ("up right", "8"), ("up fire", "0"), ("up right", "H"),         # held too, any key
                 ("up left", "F"), ("up right", "U"), ("up right", "B")):        # of the other column
        m.joy, m.keys = set(d.split()), {MPOS[k]}                               # is an F-key there
        a1, kb = aval(), m.z.memory[lb["kbuf"]]
        m.run(60)
        if aval() == a1 or m.z.memory[0x4000] != 0xFF or m.z.memory[lb["ramsize"]] != 1 \
                or m.z.memory[lb["kbuf"]] != kb or m.z.memory[lb["monreq"]]:
            bad.append(f"{d}+{k}")
        m.joy, m.keys = set(), set()
        m.run(3)
    check("the stick held and a key in its column: no F-key, no BREAK, the program runs on", not bad,
          f"wrong: {bad}")
    m2 = Machine(int_wired=True)                 # a key let go between BREAK-1's read of
    m2.boot()                                    # column 7 and its read of the stick's
    seen, kbd0 = [], m2._kbd                     # ghosts: fire held, M (fire's column,
                                                 # SPACE's row) let go just then
    def let_go():
        if m2.pa == 0x7F:
            seen.append(1)
        elif m2.pa == 0xFF and seen:
            m2.keys = set()
        return kbd0()
    m2._kbd = let_go
    m2.joy, m2.keys = {"fire"}, {MPOS["M"]}
    m2.call(m2.lbl["brk"])
    check("BREAK-1: a key in the stick's column let go between its reads is no BREAK",
          seen and m2.z.a == 0xFF, f"A ${m2.z.a:02X}")
    m.keys = {C64KEY[ZXKEY["SPACE"]]}            # BREAK
    m.until(lambda: m.z.memory[0x4000] != 0xFF, 200, "BREAK")
    m.keys = set()
    m.until(m.ready, 300, "the key wait")

    f3()                                         # the custom layout (as if taught)
    m.tap("F7", frames=10)
    m.until(lambda: m.cursor() and m.ready(), 600, "the K cursor after F7")
    after_f7 = m.z.memory[lb["joyidx"]]
    m.tap("F8", frames=10)
    m.until(lambda: m.cursor() and m.ready(), 600, "the K cursor after F8")
    after_f3 = m.z.memory[lb["joyidx"]]
    for _ in range(2):                           # 32K, 1K, back to 16K
        m.tap("F8", frames=10)
        m.until(lambda: m.cursor() and m.ready(), 600, "the K cursor after F8")
    check("F7 and F8 keep the layout", after_f7 == 1 and after_f3 == 1, f"after F7 {after_f7}, F8 {after_f3}")
    m.z.memory[lb["joyidx"]] = m.z.memory[lb["joyhave"]] = 0   # nothing taught yet

    # ---- the joystick: F3 held a second teaches a layout, the program frozen
    def hold3():                                 # F3 down 60 frames, then up
        m.keys = {C64NAMES["F3"]}
        m.run(60)
        m.keys = set()
        m.run(5)

    def answer(*names):                          # a C64 key (by MPOS or C64NAMES name), down and up
        m.keys = {C64NAMES[n] if n in C64NAMES else MPOS[n] for n in names}
        m.run(3)
        m.keys = set()
        m.run(3)

    def cus():
        return bytes(m.z.memory[lb["joycus"]:lb["joycus"] + 10])
    for line in ("5 L A SHIFT+L 0", "1 0 L A SHIFT+L A SHIFT+K 1", "2 0 G 1 0"):
        m.type(line + " NEWLINE")                # 5 LET A=0, 10 LET A=A+1, 20 GOTO 10
    m.type("R")
    m.keys = {C64KEY[ZXKEY["NEWLINE"]]}
    m.run(3)
    m.keys = set()
    m.run(30)
    hold3()
    a1 = aval()
    m.run(50)
    asked = m.screen()[0]
    check("hold F3: the program stops, the top row asks for up", aval() == a1 and asked == joyrow("?----"),
          f"{asked!r}")
    rows = []
    for k in ("R", "F", "J", "K"):
        answer(k)
        rows.append(m.screen()[0])
    m.run(20)
    frozen = aval() == a1
    answer("F1")
    m.run(5)
    shown = m.screen()[0]
    want = bytes([0xFB, 0xF7, 0xFD, 0xF7, 0xBF, 0xF7, 0xBF, 0xFB, 0xFE, 0xFF])
    check("teaching R F J K and F1 (none): the custom layout, shown and selected, the program frozen till then",
          cus() == want and m.z.memory[lb["joyidx"]] == 1 and m.z.memory[lb["joyhave"]] and frozen
          and rows == [joyrow("r?---"), joyrow("rf?--"), joyrow("rfj?-"), joyrow("rfjk?")]
          and shown == joyrow("rfjk-"), f"{cus().hex()} {rows} {shown!r}")
    m.run(20)
    inr = {r: m.z.memory[r * 256 + 0xFE] for r in [0] + list(ZXROWS)}
    check("after teaching the program runs on, no key left down for it (LAST_K, the IN A,($FE) copies)",
          aval() != a1 and m.peek16(0x4025) == 0xFFFF and set(inr.values()) == {0xFF},
          f"LAST_K ${m.peek16(0x4025):04X}, {inr}")

    hold3()
    answer("CRSRRIGHT")
    answer("LSHIFT")
    for _ in range(2):
        answer("F1")
    answer("SPACE")
    space = m.z.memory[SCREEN + 4 + 24]          # fire, SPACE: plain, not inverse
    check("a cursor key answers as its key without SHIFT, SHIFT alone as SHIFT; SPACE shown plain",
          cus()[:4] == bytes([0xEF, 0xFB, 0xFE, 0xFE]) and cus()[8:] == bytes([0x7F, 0xFE]) and space == 0x00,
          f"{cus().hex()}, SPACE's cell ${space:02X}")

    before = (cus(), m.z.memory[lb["joyidx"]])
    hold3()
    answer("R")
    a1 = aval()
    answer("F7")
    m.run(20)
    at_f7 = (m.screen()[0], aval() == a1)
    answer("F5")
    m.run(5)
    check("F7 at a prompt does nothing; F5 gives up, the layout as it was",
          at_f7 == (joyrow("r?---"), True) and (cus(), m.z.memory[lb["joyidx"]]) == before,
          f"{at_f7} {cus().hex()} joyidx {m.z.memory[lb['joyidx']]}, f3old {m.z.memory[lb['f3old']]}, before {before[0].hex()} {before[1]}")

    seen = []
    for _ in range(4):
        f3()
        seen.append(m.z.memory[lb["joyidx"]])
    m.keys = {C64NAMES["F3"]}
    m.run(20)
    m.keys = set()
    m.run(10)
    short = (m.z.memory[lb["joyidx"]], m.screen()[0])
    check("F3 switches 5678+0 and the custom layout once taught; a short hold is a tap",
          seen == [0, 1, 0, 1] and short == (0, joyrow("76580")), f"{seen} {short}")

    hold3()                                      # the stick at a prompt is no answer
    for joy in ({"up"}, {"fire"}):
        m.joy = joy
        m.run(10)
        m.joy = set()
        m.run(5)
    at_u = (m.z.memory[lb["teaching"]], m.screen()[0])
    answer("F1")
    m.joy = {"down"}
    m.run(10)
    m.joy = set()
    m.run(5)
    at_d = m.screen()[0]
    answer("F5")
    check("the stick at a teaching prompt answers nothing and gives up nothing (nor repeats F1)",
          at_u == (1, joyrow("?----")) and at_d == joyrow("-?---"), f"{at_u} {at_d!r}")
    m.keys = {C64KEY[ZXKEY["SPACE"]]}            # BREAK
    m.until(lambda: m.z.memory[0x4000] != 0xFF, 200, "BREAK")
    m.keys = set()
    m.until(m.ready, 300, "the key wait")
    m.type("SHIFT+0")                            # (RUBOUT: an empty edit line)
    hold3()
    for k in ("R", "F", "J", "K", "L"):
        answer(k)
    m.until(m.ready, 300, "the key wait")
    m.run(10)
    check("teaching at the K cursor: nothing it took reaches the edit line", m.screen()[22:] in (["", "k"], ["k", ""]),
          f"{m.screen()[22:]}")

    # ---- the test programs (progs/*.bas, made into .p files by make)
    m = Machine(int_wired=True)
    m.boot()
    m.z.memory[0xF000 + 0x02A6] = 1                          # the kernal's PAL flag
    for name in ("speed", "pause", "mem"):
        m.drive.files[name.upper().encode()] = open(os.path.join(ROOT, "build", "obj", name + ".p"), "rb").read()
    r = enter(m, "J SHIFT+P S P E E D SHIFT+P")
    scr = m.screen()
    frames = next((int(x.split()[0]) for x in scr if x.endswith(" FRAMES")), None)
    check("SPEED runs as it loads", scr[0] == "ZX64 SPEED TEST" and scr[2].endswith("PAL")
          and scr[3].endswith("1") and scr[4].endswith(" 0") and frames and r.startswith("0/"),
          f"{frames} frames for 50 loops, {r}")
    f0 = m.frames
    r = enter(m, "J SHIFT+P P A U S E SHIFT+P")
    scr = m.screen()
    check("PAUSE runs: PAUSE 150 and PAUSE 500, no stray IRQs", scr[10] == "STOP"
          and scr[12].endswith(" 0") and m.frames - f0 >= 650, f"{m.frames - f0} frames, {r}")
    r = enter(m, "J SHIFT+P M E M SHIFT+P")
    scr = m.screen()
    check("MEM in 16K: every free byte OK", "RAM      16K" in scr and "MEMORY OK" in scr, f"{scr[5:7]} {r}")

    def fast_run(stop):
        """RUN FAST to its FAST loop at line 230, noting what the picture
        shows of the count while the FAST count runs (lines 120-140); then
        BREAK with the key given, let go as the ROM takes it."""
        m.keys = {C64KEY[ZXKEY["NEWLINE"]]}
        m.until(lambda: m.z.memory[0x4027] == 0xFF, 100, "NEWLINE taken")
        m.keys, seen, fi = set(), set(), m.fast_irqs
        m.until(lambda: m.peek16(0x4007) < 230, 100, "the program started")

        def watch():
            ppc = m.peek16(0x4007)
            if 120 <= ppc <= 140:
                seen.add(m.screen()[6].strip())
            return ppc == 230
        m.until(watch, 3000, "FAST's loop at line 230")
        m.run(10)
        m.keys = {stop}
        m.until(lambda: m.z.memory[0x4000] != 0xFF, 200, "BREAK")     # ERR_NR
        m.keys = set()
        m.until(m.ready, 200, "the key wait")
        m.run(5)
        return seen, m.fast_irqs - fi, report(m), m.screen()
    m.drive.files[b"FAST"] = open(os.path.join(ROOT, "build", "obj", "fast.p"), "rb").read()
    m.type("J SHIFT+P F A S T SHIFT+P")
    seen, irqs, r, scr = fast_run(C64KEY[ZXKEY["SPACE"]])
    check("FAST: the picture holds while it counts (100 only once SLOW), FRAMES stands still, no IRQ; "
          "SPACE breaks the FAST loop", seen == {""} and scr[6].strip() == "100" and scr[9].endswith(": 0") and not irqs
          and r == "D/230", f"{sorted(seen)[:3]} {scr[9]!r} {irqs} IRQs {r}")
    m.type("R")
    seen, irqs, r, scr = fast_run(MPOS["RUNSTOP"])
    check("FAST: RUN again, RUN/STOP breaks the FAST loop", r == "D/230" and not irqs, f"{r} {irqs} IRQs")

    stray = [mm.peek16(m.lbl["stray"]) for mm in Machine.all if mm.int_wired]
    check("no stray IRQs counted", not any(stray), f"{stray}")

    # ---- the monitor, zx64mon: F5 loads it from the disk the first time
    mon = open(os.path.join(ROOT, "build", "obj", "zx64mon.prg"), "rb").read()
    mon2 = open(os.path.join(ROOT, "build", "obj", "zx64mon2.prg"), "rb").read()
    mlb = {k: v for k, v in (ln.split(":\tequ $") for ln in
                             open(os.path.join(ROOT, "build", "obj", "zx64mon.lbl")).read().split("\n") if ln)}
    mlb = {k.lower(): int(v, 16) for k, v in mlb.items()}
    m = Machine(int_wired=True)
    m.boot()
    m.tap("F5")
    check("F5 without zx64mon on the disk: said on the top row, the ZX81 goes on",
          m.screen()[0].strip().startswith("no zx64mon") and m.z.memory[0xC018] == 0x8A and m.ready(),
          f"{m.screen()[0]!r}")
    m.drive.files[b"ZX64MON"] = mon
    m.drive.files[b"ZX64MON2"] = mon2
    opens = m.drive.opens
    m.barlog = []
    m.tap("F5")
    zxt = "".join(ZX[c & 0x3F] for c in m.top_at_switch[:22]).rstrip()
    check("the first F5: \" LOADING ZX64MON\" on the top row, one bar across both files",
          zxt == " LOADING ZX64MON" and len([1 for a, v in m.barlog if a < 0xE022]) == 16,
          f"{zxt!r}, {len(m.barlog)} writes")
    scr = m.mscreen()
    check("F5: zx64mon loaded to $3000, its own screen (VIC bank 0, $0400, 40x25), the registers",
          m.drive.opens == opens + 2 and bytes(m.z.memory[0x3000:mlb["kmods"]]) == mon[2:mlb["kmods"] - 0x3000 + 2]
          and m.z.memory[0xC018] == 0x14 and m.z.memory[0xCD00] & 3 == 3
          and scr[0].startswith("#ZX64MON 1.1") and scr[2].startswith(";") and scr[4].startswith("'"),
          f"{scr[:5]}")
    f0, d0 = m.frames, m.peek16(mlb["nframes"])
    m.run(100)
    counted = (m.peek16(mlb["nframes"]) - d0) & 0xFFFF
    check("the monitor counts a frame once a frame (its cursor and key repeat), also when the raster "
          "flag reads set after bad lines", abs(counted - (m.frames - f0)) <= 1,
          f"{counted} counted in {m.frames - f0}")
    col = bytes(m.z.memory[0xC800:0xC800 + 1000])
    check("the monitor's colours: every cell light blue (14), however colour RAM reads",
          all(c & 15 == 14 for c in col), f"{sum(1 for c in col if c & 15 != 14)} cells wrong")
    rom = bytes(m.z.memory[0x0000:0x2000])
    before, rows = m.mscreen()[:6], []
    for row in (0, 1, 3):                        # the title (#ZX64MON, else Z), #PC ..., #AF' ...
        m.mkey("HOME")
        for _ in range(row):
            m.mkey("CRSRDOWN")
        m.mtype("\r", settle=20)
        rows.append(m.z.memory[mlb["crow"]])
    check("RETURN on the title and the registers' headings (#ZX64MON, #PC, #AF'): nothing run, no ?, the "
          "screen as it was, the cursor on the line under it", before[1].startswith("#PC")
          and before[3].startswith("#AF'") and before[0].startswith("#ZX64MON")
          and m.mscreen()[:6] == before and rows == [1, 2, 4] and bytes(m.z.memory[0x0000:0x2000]) == rom,
          f"rows {rows}, {m.mscreen()[:6]}")
    m.mkey("HOME", "LSHIFT")                     # CLR
    m.mtype("M 7000", settle=0)
    m.mkey("RETURN", "LSHIFT")
    m.run(10)
    row = m.z.memory[mlb["crow"]]
    check("SHIFT+RETURN: the next row's start, the line not run (as on the C64)",
          m.mscreen()[0].startswith("M 7000") and not any(r.startswith(".:7000") for r in m.mscreen())
          and row == 1 and m.z.memory[mlb["ccol"]] == 0, f"row {row}, {m.mscreen()[:3]}")
    m.mkey("CTRL", "HOME")
    m.mtype("Q", settle=0)
    m.mkey("HOME")
    m.mtype("W", settle=0)
    scr = m.mscreen()
    m.mkey("HOME", "LSHIFT")                     # CLR
    check("CTRL+HOME: the bottom row, column 0; HOME: the top", scr[24] == "Q" and scr[0].startswith("W"),
          f"{scr[0]!r} {scr[24]!r}")
    m.mtype("F 7000 700F AA\r")
    m.mtype(":7000 01 02 03\r")
    m.mtype("M 7000 7008\r")
    scr = m.mscreen()
    check("F, :, M: filled, stored, shown 8 bytes a line with the ZX81 characters",
          bytes(m.z.memory[0x7000:0x7010]) == bytes([1, 2, 3]) + b"\xAA" * 13
          and ".:7000 01 02 03 AA AA AA AA AA ...EEEEE" in scr
          and ".:7008 AA AA AA AA AA AA AA AA EEEEEEEE" in scr, f"{scr[-5:]}")
    m.mkey("CRSRDOWN", "LSHIFT")                 # up, onto the second line
    for _ in range(6):
        m.mkey("CRSRRIGHT")                      # the cursor was in column 1
    m.mtype("55\r")
    check("an M line changed on the screen and RETURN: stored", m.z.memory[0x7008:0x700A] == b"\x55\xAA",
          bytes(m.z.memory[0x7008:0x7010]).hex(" "))
    m.mkey("CRSRDOWN")
    RVS, OFF = ("CTRL", "9"), ("CTRL", "0")
    def medit(col, *keys):                       # M 7300 7300, up onto it, to col, keys
        m.mtype("M 7300 7300\r")                 # (text, or CTRL+9 / CTRL+0), RETURN: the
        m.mkey("CRSRDOWN", "LSHIFT")             # bytes, the row redrawn and its text's
        for _ in range(col - 1):                 # reverse (r), the row after it
            m.mkey("CRSRRIGHT")
        for k in keys:
            if isinstance(k, tuple):
                m.mkey(*k)
            else:
                m.mtype(k, settle=0)
        m.mtype("\r")
        scr = m.mscreen()
        i = max(i for i, r in enumerate(scr) if r.lstrip(".").startswith(":7300"))
        rv = "".join("r" if c & 0x80 else "-" for c in m.z.memory[MSCR + 40 * i + 31:MSCR + 40 * i + 39])
        return bytes(m.z.memory[0x7300:0x7308]).hex().upper(), scr[i], rv, scr[i + 1]
    m.mtype(":7300 35 37 2E 33 39 00 A6 F5\r")   # PRINT, space, inverse A, a token
    m.mtype("M 7300 7300\r")
    scr = m.mscreen()
    i = max(i for i, r in enumerate(scr) if r.startswith(".:7300"))
    shown = (scr[i], "".join("r" if c & 0x80 else "-" for c in m.z.memory[MSCR + 40 * i + 31:MSCR + 40 * i + 39]))
    got = [medit(33, "O"),                       # O for I; the inverse A and token as they were
           medit(37, "B"),                       # B for the inverse A: a B
           medit(37, RVS, "B"),                  # RVS ON, B: an inverse B
           medit(31, RVS, "P"),                  # the same P, reversed: inverse
           medit(37, "A"),                       # an A, not reversed: not inverse
           medit(31, "!")]                       # no ZX81 "!": ?, nothing stored
    check("an M line's characters changed on the screen and RETURN: stored as they show, reversed "
          "ones (RVS ON, CTRL+9) inverse, the others not; as M drew them (reversed too), the hex goes; "
          "! (no ZX81 code): ?, nothing stored",
          shown == (".:7300 35 37 2E 33 39 00 A6 F5 PRINT A.", "------rr")
          and [g[0] for g in got] == ["353734333900A6F5", "35373433390027F5", "353734333900A7F5",
                                      "B53734333900A7F5", "B5373433390026F5", "B5373433390026F5"]
          and got[5][3] == "#?", f"{shown} {got}")
    check("RETURN on an M line: the line drawn again from memory, reversed as stored",
          got[0][1:3] == (".:7300 35 37 34 33 39 00 A6 F5 PRONT A.", "------rr")
          and got[2][1:3] == (".:7300 35 37 34 33 39 00 A7 F5 PRONT B.", "------rr")
          and got[4][1:3] == (".:7300 B5 37 34 33 39 00 26 F5 PRONT A.", "r------r"), f"{got}")
    m.mtype(":7300 01 02 03 04 05 06 07 08\r")   # typed: no text
    m.mtype(":7308 00 00 00 00 00 00 00 00 ")
    m.mkey(*RVS)
    m.mtype("        \r")                         # eight reversed spaces: inverse spaces
    check("a : line with 8 bytes and spaces after them: no text; reversed spaces: text, inverse",
          bytes(m.z.memory[0x7300:0x7310]).hex().upper() == "0102030405060708" + "80" * 8,
          bytes(m.z.memory[0x7300:0x7310]).hex())
    def zxs(text):
        return bytes(ZX.index(c) for c in text)
    def colon(text):                             # a : line, its bytes from a, the row after
        m.mtype(text + "\r")
        scr = m.mscreen()
        i = max((i for i, r in enumerate(scr) if r.lstrip(".") == text), default=24)
        return scr[i + 1] if i < 24 else ":none"
    m.mtype("F 7400 74FF 99\r")
    fox = "THE QUICK BROWN FOX JUMPS OVER THE LAZY DOG"
    nxt = colon(":7400 'THE QUICK BROWN FOX JUMPS OVER T")      # to column 39
    m.mtype("HE LAZY DOG' FF\r")
    scr = m.mscreen()
    end = next((scr[i + 1] for i in range(24, -1, -1) if scr[i] == ":7420 'HE LAZY DOG' FF"), ":none")
    nxt2 = colon(":7500 'THE QUICK BROWN FOX JUMPS")    # the manual's
    m.mtype(" OVER THE LAZY DOG' FF\r")
    rows = [colon(":7440 'A'"), colon(":7450 01 'AB' 02"), colon(":7460 'A!B"), colon(":7470 '"),
            colon(":7480 'AB '")]
    mem = bytes(m.z.memory[0x7400:0x7490])
    check(":7400 'TEXT: ZX81 codes, the next line offered (:7420 ') while the text runs to the end; "
          "'...' closed, mixed with bytes, a trailing space kept; ! (no ZX81 code): ?, nothing stored",
          nxt == ":7420 '" and mem[:0x2C] == zxs(fox) + b"\xFF" and nxt2 == ":7519 '"
          and bytes(m.z.memory[0x7500:0x752C]) == zxs(fox) + b"\xFF" and not end.startswith(":")
          and mem[0x40:0x42] == zxs("A") + b"\x99" and mem[0x50:0x55] == b"\x01" + zxs("AB") + b"\x02\x99"
          and mem[0x60:0x62] == b"\x99\x99" and rows[2] == "#?" and mem[0x70] == 0x99
          and not any(r.startswith(":") for r in rows) and mem[0x80:0x84] == zxs("AB ") + b"\x99",
          f"{nxt!r} {end!r} {rows} {mem[:0x2C].hex()} {mem[0x40:].hex()}")
    m.mtype(":7380 'HELLO ")
    m.mkey(*RVS)
    m.mtype("WORLD")
    m.mkey(*OFF)
    m.mtype("' FF\r")
    m.mkey(*RVS)
    m.mtype(":7390 'AB'")                         # RVS ON, then RETURN: off again
    m.mtype("\r")
    m.mtype(":7390 'AB'\r")
    m.mtype(":73A0 'X")
    m.mkey(*RVS)
    m.mtype(" \r")                               # a reversed space ends the line: kept
    m.mtype("\r")                                # (the next line offered: nothing)
    mem = bytes(m.z.memory[0x7380:0x73A3])
    check(":7380 'HELLO {RVS ON}WORLD{RVS OFF}' FF: WORLD inverse; RVS ON is off again after RETURN; "
          "a reversed space at the text's end is text",
          mem[:12] == zxs("HELLO ") + bytes(c | 0x80 for c in zxs("WORLD")) + b"\xFF"
          and mem[0x10:0x12] == zxs("AB") and mem[0x20:0x22] == zxs("X") + b"\x80", mem.hex())
    boot = open(os.path.join(ROOT, "build", "obj", "zx64.prg"), "rb").read()[2:2 + 0x0F]
    check("scrolling clears the new bottom row, and nothing past the screen (C64 $07E8-$080F: the "
          "sprite pointers, the boot file's start)", m.mscreen()[-1] == "" and
          bytes(m.z.memory[0xF801:0xF810]) == boot and m.z.memory[0xF7F8] != 0x20,
          f"{m.mscreen()[-1]!r} {bytes(m.z.memory[0xF801:0xF810]).hex()} {boot.hex()}")
    m.mtype("T 7000 700F 7100\r")
    m.mtype(":7105 99\r")
    m.mtype("C 7000 700F 7100\r")
    m.mtype(":7200 26 27 28\r")                 # A B C in ZX81 codes
    m.mtype("H 6000 7FFF 99 AA\r", settle=40)
    m.mtype("H 6000 7FFF 'ABC\r", settle=40)
    scr = m.mscreen()
    check("T copies, C finds the difference, H finds bytes and ZX81 text",
          bytes(m.z.memory[0x7100:0x7110]) == bytes(m.z.memory[0x7000:0x7005]) + b"\x99"
          + bytes(m.z.memory[0x7006:0x7010])
          and "7005" in scr and "7105" in scr and "7200" in scr, f"{scr[-8:]}")
    def conv(text):                              # = n: the line it shows
        m.mtype(text + "\r")
        scr = m.mscreen()
        i = max(i for i, r in enumerate(scr) if r == "." + text)
        return scr[i + 1]
    cases = [("= C000", "= $C000 +49152 %11000000 00000000"), ("= +255", "= $00FF +255 %11111111"),
             ("= %1010", "= $000A +10 %00001010"), ("=$1F", "= $001F +31 %00011111"),
             ("= 0", "= $0000 +0 %00000000"), ("= +65535", "= $FFFF +65535 %11111111 11111111"),
             ("= %100000000", "= $0100 +256 %00000001 00000000"),
             ("= $C000 +49152 %11000000 00000000", "= $C000 +49152 %11000000 00000000"),
             ("= +65536", "#?"), ("= 10000", "#?"), ("= +12A", "#?"), ("= %102", "#?"), ("=", "#?"),
             ("= +", "#?")]
    bad = [(t, got) for t, want in cases if (got := conv(t)) != want]
    check("= n: hex, +decimal or %binary in, all three out; RETURN on that line again; "
          "too big or not a number: ?", not bad, f"{bad}")
    pc, af = m.peek16(mlb["r_pc"]), m.peek16(mlb["r_af"])
    m.mtype(";2222 3333\r")
    check("; changes the registers in order (PC, AF ...)",
          m.peek16(mlb["r_pc"]) == 0x2222 and m.peek16(mlb["r_af"]) == 0x3333, "")
    m.mtype(f";{pc:04X} {af:04X}\r")           # back as they were
    # D: the monitor's own disassembler, instruction by instruction
    cases = [
        ("00", "NOP"), ("08", "EX AF,AF'"), ("10FE", "DJNZ $7000"), ("1800", "JR $7002"),
        ("20FE", "JR NZ,$7000"), ("38FC", "JR C,$6FFE"), ("013412", "LD BC,$1234"), ("09", "ADD HL,BC"),
        ("39", "ADD HL,SP"), ("02", "LD (BC),A"), ("223412", "LD ($1234),HL"), ("323412", "LD ($1234),A"),
        ("0A", "LD A,(BC)"), ("2A3412", "LD HL,($1234)"), ("3A3412", "LD A,($1234)"), ("03", "INC BC"),
        ("3B", "DEC SP"), ("04", "INC B"), ("35", "DEC (HL)"), ("3612", "LD (HL),$12"), ("07", "RLCA"),
        ("27", "DAA"), ("3F", "CCF"), ("41", "LD B,C"), ("76", "HALT"), ("7E", "LD A,(HL)"),
        ("77", "LD (HL),A"), ("86", "ADD A,(HL)"), ("8F", "ADC A,A"), ("90", "SUB B"), ("9F", "SBC A,A"),
        ("A1", "AND C"), ("A8", "XOR B"), ("B5", "OR L"), ("BE", "CP (HL)"), ("C0", "RET NZ"),
        ("F8", "RET M"), ("C1", "POP BC"), ("F1", "POP AF"), ("C9", "RET"), ("D9", "EXX"),
        ("E9", "JP (HL)"), ("F9", "LD SP,HL"), ("C23412", "JP NZ,$1234"), ("FA3412", "JP M,$1234"),
        ("C33412", "JP $1234"), ("D3FD", "OUT ($FD),A"), ("DBFE", "IN A,($FE)"), ("E3", "EX (SP),HL"),
        ("EB", "EX DE,HL"), ("F3", "DI"), ("FB", "EI"), ("CC3412", "CALL Z,$1234"), ("C5", "PUSH BC"),
        ("F5", "PUSH AF"), ("CD3412", "CALL $1234"), ("C612", "ADD A,$12"), ("D612", "SUB $12"),
        ("FE12", "CP $12"), ("FF", "RST $38"), ("C7", "RST $00"), ("CB00", "RLC B"),
        ("CB3E", "SRL (HL)"), ("CB30", "SLL B"), ("CB7E", "BIT 7,(HL)"), ("CB87", "RES 0,A"),
        ("CBFF", "SET 7,A"), ("ED78", "IN A,(C)"), ("ED70", "IN (C)"), ("ED79", "OUT (C),A"),
        ("ED71", "OUT (C),0"), ("ED42", "SBC HL,BC"), ("ED7A", "ADC HL,SP"), ("ED433412", "LD ($1234),BC"),
        ("ED7B3412", "LD SP,($1234)"), ("ED6B3412", "LD HL,($1234)"), ("ED44", "NEG"), ("ED45", "RETN"),
        ("ED4D", "RETI"), ("ED46", "IM 0"), ("ED56", "IM 1"), ("ED5E", "IM 2"), ("ED47", "LD I,A"),
        ("ED5F", "LD A,R"), ("ED67", "RRD"), ("ED6F", "RLD"), ("EDB0", "LDIR"), ("EDA1", "CPI"),
        ("EDA3", "OUTI"), ("EDBB", "OTDR"), ("EDB8", "LDDR"), ("ED00", "???"), ("EDFF", "???"),
        ("DD213412", "LD IX,$1234"), ("FD213412", "LD IY,$1234"), ("DD09", "ADD IX,BC"),
        ("DD29", "ADD IX,IX"), ("DD2A3412", "LD IX,($1234)"), ("DD23", "INC IX"),
        ("DD7E05", "LD A,(IX+$05)"), ("DD77FB", "LD (IX-$05),A"), ("DD360512", "LD (IX+$05),$12"),
        ("DD34FF", "INC (IX-$01)"), ("FD8600", "ADD A,(IY+$00)"), ("DD6605", "LD H,(IX+$05)"),
        ("DD7480", "LD (IX-$80),H"), ("DD64", "LD IXH,IXH"), ("DD7C", "LD A,IXH"), ("FD7D", "LD A,IYL"),
        ("DD2612", "LD IXH,$12"), ("FDAC", "XOR IYH"), ("DDE9", "JP (IX)"), ("FDE3", "EX (SP),IY"),
        ("DDF9", "LD SP,IX"), ("DDE5", "PUSH IX"), ("FDE1", "POP IY"), ("DDEB", "EX DE,HL"),
        ("DDCB0546", "BIT 0,(IX+$05)"), ("FDCBFEC6", "SET 0,(IY-$02)"), ("DDCB0506", "RLC (IX+$05)"),
        ("DDCB7F3E", "SRL (IX+$7F)"), ("DDDD", "???"), ("FDED", "???"),
    ]
    want_len = {"DDDD": 1, "FDED": 1}
    bad = []
    for hexes, want in cases:
        code = bytes.fromhex(hexes)
        m.z.memory[0x7000:0x7000 + len(code) + 4] = code + bytes(4)
        m.call(mlb["dis1"], hl=0x7000, resume=True)
        text = bytes(m.z.memory[mlb["dtext"]:mlb["dtext"] + 24]).split(b"\0")[0].decode()
        n = m.peek16(mlb["dptr"]) - 0x7000
        if text != want or n != want_len.get(hexes, len(code)):
            bad.append(f"{hexes}: {text!r} ({n})")
    check(f"D: {len(cases)} instructions, every group, IX/IY and the undocumented ones, as Zilog writes them",
          not bad, f"wrong: {bad[:6]}")
    rom = bytes(m.z.memory[0x0000:0x1E00])       # the ROM's code ($0000-$1DFF)
    a, mism = 0, []
    while a < 0x1D00:
        m.call(mlb["dis1"], hl=a, resume=True)
        n = m.peek16(mlb["dptr"]) - a
        if rom[a] == 0xCF:                       # RST $08 and its report code
            m.poke16(mlb["dptr"], a + 2)
            m.z.memory[mlb["dbnext"]] = 0
            n = 2
        a += n
    check("D: through the ZX81 ROM's code ($0000-$1CFF) without losing its way",
          a >= 0x1D00, f"ended at ${a:04X}")
    # A: assembling is the disassembler backwards. Every case above, from
    # the text D gave, must come back as the same bytes (those with a second
    # encoding come back as the shorter one)
    def asm(text, at=0x7000):
        m.z.memory[at:at + 4] = b"\xAA" * 4
        t = text.encode() + b"\0"
        m.z.memory[mlb["linebuf"]:mlb["linebuf"] + len(t)] = t
        m.poke16(mlb["aaddr"], at)
        m.poke16(mlb["atext"], mlb["linebuf"])
        m.call(mlb["asm1"], resume=True)
        n = m.z.memory[mlb["alen"]]
        got = bytes(m.z.memory[at:at + 4])
        return None if got == b"\xAA" * 4 else got[:n]
    other = {"DDEB": "EB", "ED6B3412": "2A3412"}  # EX DE,HL; LD HL,(nn): the short ones
    bad = []
    for hexes, text in cases:
        if text == "???":
            continue
        want = bytes.fromhex(other.get(hexes, hexes))
        if (got := asm(text)) != want:
            bad.append(f"{text}: {got.hex() if got else None}")
    typed = [("LD A,12", "3E12"), ("ld a, $12", None), ("LD  A , $12", "3E12"), ("JR 7010", "180E"),
             ("JR NZ,$6F90", "208E"), ("LD (IX-5),$12", "DD36FB12"), ("BIT 7,(IY+$7F)", "FDCB7F7E"),
             ("RST 38", "FF"), ("RST 8", "CF"), ("IM 2", "ED5E"), ("EX AF,AF'", "08"),
             ("LD A,$123", None), ("JR $7200", None), ("LD (IX+$80),A", None), ("FOO", None),
             ("LD BC,0", "010000"), ("CALL $0A2A", "CD2A0A"), ("OUT ($FD),A", "D3FD")]
    for text, want in typed:
        got = asm(text)
        if (got.hex().upper() if got else None) != want:
            bad.append(f"{text!r}: {got.hex() if got else None}")
    check(f"A: the {len(cases) - 2} instructions D showed come back as their bytes; typed ones too, and "
          "a byte too big, a JR too far, (IX+$80), nonsense refused", not bad, f"wrong: {bad[:6]}")

    m.mkey("HOME", "LSHIFT")                     # CLR: the calls above moved the cursor
    m.mtype("A 7000 LD A,$12\r", settle=60)
    m.mtype("INC A\r", settle=60)               # at the ".A 7002 " it offers
    m.mtype("\r")
    m.mtype("D 7000 7002\r")
    scr = m.mscreen()
    a_ok = (bytes(m.z.memory[0x7000:0x7003]) == bytes.fromhex("3E123C") and ".A 7003" in scr
            and ".,7000 3E 12       LD A,$12" in scr)
    m.mkey("CRSRDOWN", "LSHIFT")                 # up onto INC A's line: DEC A instead
    for _ in range(18):
        m.mkey("CRSRRIGHT")
    m.mtype("DEC A\r", settle=60)
    check("A at the keyboard: the line becomes D's, .A next is offered; a D line changed, RETURN: assembled",
          a_ok and m.z.memory[0x7002] == 0x3D, f"{a_ok} {bytes(m.z.memory[0x7000:0x7003]).hex()}")
    m.mtype("A 7010\r", settle=60)
    scr = m.mscreen()
    alone = scr[max(i for i, r in enumerate(scr) if r == "A 7010") + 1]
    m.mtype("NOP\r", settle=60)                 # typed on the offered ".A 7010 "
    m.mtype("\r", settle=60)                     # RETURN on ".A 7011 ": the end
    scr = m.mscreen()
    i = max(i for i, r in enumerate(scr) if r.startswith(".,7010"))
    check("A a alone: .A a offered; an instruction there assembled, .A next offered; RETURN on it: the end",
          alone == ".A 7010" and m.z.memory[0x7010] == 0 and scr[i + 1:i + 4] == [".A 7011", ".", ""],
          f"{alone!r} {scr[i:i + 4]}")
    m.mtype(":7020 3E 42 3C 3C\r")
    def dedit(up, text):                         # D 7020 7023, up onto a line, its text
        m.mtype("D 7020 7023\r", settle=60)      # typed over, RETURN: the row after it
        for _ in range(up):
            m.mkey("CRSRDOWN", "LSHIFT")
        for _ in range(18):
            m.mkey("CRSRRIGHT")
        m.mtype(text + "\r", settle=60)
        row = m.z.memory[mlb["crow"]]
        return m.mscreen()[row]
    same = dedit(3, "LD A,$43")                  # as long: the next D line stays
    longer = dedit(3, "RST $10 ")                # 2 bytes to 1: .A 7021 offered
    m.mtype("INC A\r", settle=60)
    check("a D line changed to an instruction as long: the next line left; to a shorter one: .A next "
          "offered, as A does",
          same.startswith(".,7022 3C") and longer == ".A 7021"
          and bytes(m.z.memory[0x7020:0x7023]) == bytes.fromhex("D73C3C"),
          f"{same!r} {longer!r} {bytes(m.z.memory[0x7020:0x7024]).hex()}")

    # the disk: $, W, L, @. last(n): the n lines above the cursor
    def last(n):
        row = m.z.memory[mlb["crow"]]
        return m.mscreen()[max(0, row - n):row]
    m.mkey("HOME", "LSHIFT")
    m.mtype("F 7000 700F 5A\r")
    m.mtype(":7000 01 02 03\r")
    m.mtype('W "T1" 7000 700F\r', settle=30)
    t1 = m.drive.files.get(b"T1", b"")
    w_ok = t1 == b"\x00\x80" + bytes([1, 2, 3]) + b"\x5A" * 13 and last(1) == ["00, OK,00,00"]
    m.mtype("F 7000 701F 00\r")
    m.mtype('L "T1" 7100\r', settle=30)
    l1 = bytes(m.z.memory[0x7100:0x7110]) == t1[2:] and last(1) == ["#LOADED 7100-710F"]
    m.mtype("L T1 7000\r", settle=30)            # no quotes; no address would be a program
    l2 = bytes(m.z.memory[0x7000:0x7010]) == t1[2:] and last(1) == ["#LOADED 7000-700F"]
    m.mtype("L T1\r", settle=30)
    l2 = l2 and last(1) == ["#? NOT A PROGRAM"]
    m.mtype('L "T1" F000\r', settle=30)          # C64 $0000: the 6510's page
    l3 = last(2) == ["#?", "00, OK,00,00"]
    m.mtype('L "NOPE"\r', settle=30)
    l4 = last(2) == ["#?", "62,FILE NOT FOUND,00,00"]
    m.mkey("HOME", "LSHIFT")
    m.mtype("$\r", settle=60)
    scr = m.mscreen()
    d_ok = (scr[1] == '0 "ZX64            " 81 2A' and any('"T1"' in r and r.endswith("PRG") for r in scr)
            and any(r.endswith("BLOCKS FREE.") for r in scr))
    m.mtype("@\r", settle=30)
    a1 = last(1)
    m.mtype("@S:T1\r", settle=30)
    a2 = last(1)
    check("the disk: W writes a PRG (load address the C64's), L loads it to an address (without one: "
          "not a program), "
          "not into the 6510's page, a missing file says so; $ lists; @ the status, @S: scratches",
          w_ok and l1 and l2 and l3 and l4 and d_ok and a1 == ["00, OK,00,00"]
          and a2 == ["01, FILES SCRATCHED,01,00"] and b"T1" not in m.drive.files,
          f"W {w_ok} L {l1} {l2} {l3} {l4} $ {d_ok} {scr[:2]} @ {a1!r} {a2!r}")

    m.mkey("HOME", "LSHIFT")
    m.mtype("D 0000 0008\r")
    scr = m.mscreen()
    check("D 0000 0008 on the screen: Supermon's lines, the ROM's start",
          ".,0000 00          NOP" in scr and ".,0002 01 FF 7F    LD BC,$7FFF" in scr
          and ".,0005 C3 CB 03    JP $03CB" in scr and ".,0008 2A 16 40    LD HL,($4016)" in scr,
          f"{[r for r in scr if r.startswith('.,')][:6]}")
    m.mtype("?\r")
    m.mtype("X\r", settle=20)
    m.run(100)                                   # the first F5's message runs out
    r = enter(m, "P 2 SHIFT+K 2")
    check("? (help); X: back to the ZX81, its picture, colours and raster IRQ as they were; PRINT 2+2",
          any(r.startswith("Z N") for r in m.mscreen()) and m.z.memory[0xC018] == 0x8A
          and m.z.memory[0xCD00] & 3 == 0 and all(c & 15 == 0 for c in m.z.memory[0xC800:0xC800 + 1000])
          and m.z.memory[0xC011] == 0x17 and m.screen()[0] == "4" and r == "0/0",
          f"$D011 ${m.z.memory[0xC011]:02X}, {m.screen()[0]!r} {r}")
    m.keys = {C64NAMES["LSHIFT"], C64NAMES["F1"]}  # green screen, then the monitor and back
    m.run(3)
    m.keys = set()
    m.run(10)
    m.keys = {C64NAMES["LSHIFT"], C64NAMES["F1"]}
    m.run(3)
    m.keys = set()
    m.run(10)
    m.tap("F5")
    m.mtype("X\r", settle=20)
    green = (all(c & 15 == 13 for c in m.z.memory[0xC800:0xC800 + 1000]) and m.z.memory[0xC021] & 15 == 0
             and m.z.memory[0xC020] & 15 == 0)
    check("leaving the monitor puts back the colour scheme F2 chose (green screen)", green, "")

    # S: where an instruction may go next (succ), straight from the registers
    def succ(code, pc=0x7000, **regs):
        m.z.memory[pc:pc + len(code)] = code
        m.poke16(mlb["r_pc"], pc)
        for r, v in regs.items():
            m.poke16(mlb["r_" + r], v)
        m.call(mlb["succ"], resume=True)
        n = m.z.memory[mlb["sbn"]]
        if m.z.memory[mlb["sbad"]] or not n:
            return None                          # can't be stepped
        return sorted(m.peek16(mlb["sbp"] + 2 * i) for i in range(n))
    m.poke16(0x7E00, 0x1234)                     # a return address on a stack
    steps = [
        (bytes.fromhex("3E01"), [0x7002], {}), (bytes.fromhex("1805"), [0x7007], {}),
        (bytes.fromhex("2005"), [0x7002, 0x7007], {}), (bytes.fromhex("10FE"), [0x7002], {}),
        (bytes.fromhex("CD3412"), [0x1234], {}), (bytes.fromhex("C43412"), [0x1234, 0x7003], {}),
        (bytes.fromhex("C9"), [0x1234], {"sp": 0x7E00}), (bytes.fromhex("D8"), [0x1234, 0x7001], {"sp": 0x7E00}),
        (bytes.fromhex("E9"), [0x0123], {"hl": 0x0123}), (bytes.fromhex("DDE9"), [0x0456], {"ix": 0x0456}),
        (bytes.fromhex("ED4D"), [0x1234], {"sp": 0x7E00}), (bytes.fromhex("D7"), [0x0010], {}),
        (bytes.fromhex("DDCB0546"), [0x7004], {}), (bytes.fromhex("FF"), None, {}),
        (bytes.fromhex("CD0020"), None, {}), (bytes.fromhex("18FE"), None, {}),
    ]
    bad = [(c.hex(), got) for c, want, r in steps if (got := succ(c, **r)) != want]
    check("S: where each kind of instruction goes next (JR, DJNZ, CALL, RET, JP (HL), RST ...); "
          "RST $38, a call into zx64 and JR to itself refused", not bad, f"wrong: {bad}")

    stub = open(os.path.join(ROOT, "build", "obj", "zx81.prg"), "rb").read()
    m = Machine(int_wired=True, prg=stub)        # a C64 reset keeps RAM: the last
    m.ram[0x4000:0x4000 + len(mon) - 2] = mon[2:]   # session's monitor, its screen
    m.ram[0xF000:0xF000 + len(mon2) - 2] = mon2[2:]  # cleared once (inited), and
    m.ram[mlb["inited"] + 0x1000] = 1                 # BASIC's text on it
    m.ram[mlb["crow"] + 0x1000] = 12
    m.ram[0x0400:0x0400 + 19] = bytes(ord(c) & 0x3F for c in "THE QUICK BROWN FOX")
    m.drive.files[b"ZX64"] = open(os.path.join(ROOT, "build", "obj", "zx64.prg"), "rb").read()
    m.boot()                                     # by the boot file, on a plain drive
    m.drive.files[b"ZX64MON"] = mon
    m.drive.files[b"ZX64MON2"] = mon2
    opens = m.drive.opens
    m.tap("F5")
    scr = m.mscreen()
    check("after a C64 reset: F5 loads zx64mon again (not the one left in RAM), on a clear screen",
          m.drive.opens == opens + 2 and scr[0].startswith("#ZX64MON") and not any("FOX" in r for r in scr),
          f"{m.drive.opens - opens} opens, {scr[:3]}")

    m = Machine(int_wired=True)                  # a program running: F5 stops it
    m.boot()
    m.drive.files[b"ZX64MON"] = mon
    m.drive.files[b"ZX64MON2"] = mon2
    for line in ("5 L A SHIFT+L 0", "1 0 L A SHIFT+L A SHIFT+K 1", "2 0 G 1 0"):
        m.type(line + " NEWLINE")                # 5 LET A=0, 10 LET A=A+1, 20 GOTO 10
    m.type("R")
    m.keys = {C64KEY[ZXKEY["NEWLINE"]]}
    m.run(3)
    m.keys = set()
    m.run(60)
    m.tap("F5")
    regs = m.mscreen()[2]
    pc = int(regs[1:5], 16)
    a1 = bytes(m.z.memory[m.peek16(0x4010) + 1:m.peek16(0x4010) + 6])   # A's value
    m.run(50)                                    # it stays stopped meanwhile
    a2 = bytes(m.z.memory[m.peek16(0x4010) + 1:m.peek16(0x4010) + 6])   # A's value
    m.mtype("X\r", settle=50)
    a3 = bytes(m.z.memory[m.peek16(0x4010) + 1:m.peek16(0x4010) + 6])   # A's value
    m.keys = {C64KEY[ZXKEY["SPACE"]]}
    m.run(5)
    m.keys = set()
    m.until(m.ready, 300, "the ROM ready for a key")
    m.run(3)
    rep_ = report(m)
    r = enter(m, "P A")
    check("F5 in a running program: stopped in the ROM or zx64's BREAK check, interrupts on; X: it runs on (BREAK D/10 or D/20)",
          pc < 0x3000 and m.mscreen()[4].endswith("01")
          and a1 == a2 and a3 != a2 and rep_ in ("D/10", "D/20") and int(m.screen()[0]) > 0 and r == "0/0",
          f"PC ${pc:04X}, {rep_}, A = {m.screen()[0]}")

    m = Machine(int_wired=False)                 # the original cartridge
    m.boot()
    m.drive.files[b"ZX64MON"] = mon
    m.drive.files[b"ZX64MON2"] = mon2
    m.tap("F5")
    ok = m.z.memory[0xC018] == 0x14
    m.mtype("X\r", settle=20)
    r = enter(m, "P 7")
    check("no /INT: F5 at the prompt enters the monitor, X leaves", ok and m.screen()[0] == "7" and r == "0/0",
          f"{ok} {m.screen()[0]!r} {r}")

    # a breakpoint in machine code called from BASIC; S, then G
    m = Machine(int_wired=True)
    m.boot()
    m.drive.files[b"ZX64MON"] = mon
    m.drive.files[b"ZX64MON2"] = mon2
    m.tap("F5")
    m.mtype(":7000 3E 01 3C 3C 32 00 71 C9\r")   # LD A,1; INC A; INC A; LD ($7100),A; RET
    m.mtype("B 7002\r")
    m.mtype("X\r", settle=20)
    m.type("T SHIFT+NEWLINE L 2 8 6 7 2")       # RAND USR 28672
    m.keys = {C64KEY[ZXKEY["NEWLINE"]]}
    m.run(3)
    m.keys = set()
    m.run(30)
    scr = m.mscreen()
    regs = next((r for r in reversed(scr) if r.startswith(";")), "")
    hit = (m.z.memory[0xC018] == 0x14 and "#BREAKPOINT" in scr and regs.startswith(";7002 01")
           and m.z.memory[0x7002] == 0x3C and ".,7002 3C          INC A" in scr)
    m.mtype("\r")                                 # the prompt is ".": on to S
    m.mtype("S\r", settle=20)
    s1 = next((r for r in reversed(m.mscreen()) if r.startswith(";")), "")
    m.mtype("\r", settle=20)                      # ".S" is there: RETURN steps again
    s2 = next((r for r in reversed(m.mscreen()) if r.startswith(";")), "")
    m.mkey("HOME", "LSHIFT")
    m.mtype("G\r", settle=20)
    m.until(m.ready, 300, "the ROM ready for a key")
    m.run(3)
    check("B 7002, RAND USR 28672: stopped there (A = 1, the byte back); S, S: A = 2, 3; G: on to the "
          "end, the breakpoint set again", hit and s1.startswith(";7003 02") and s2.startswith(";7004 03")
          and m.z.memory[0x7100] == 3 and report(m) == "0/0" and m.z.memory[0x7002] == 0xFF,
          f"{hit} {regs[:10]!r} {s1[:10]!r} {s2[:10]!r} $7100={m.z.memory[0x7100]} {report(m)} "
          f"$7002=${m.z.memory[0x7002]:02X}")

    m.drive.files[b"SPEED"] = open(os.path.join(ROOT, "build", "obj", "speed.p"), "rb").read()
    enter(m, "J SHIFT+P S P E E D SHIFT+P")
    check("LOAD with a breakpoint set: its byte back first, none left armed",
          m.z.memory[0x7002] == 0x3C and m.z.memory[lb["bpcnt"]] == 0, f"$7002=${m.z.memory[0x7002]:02X}")

    m = Machine(int_wired=False)                 # no /INT: a breakpoint is a RST, it works anyway
    m.boot()
    m.drive.files[b"ZX64MON"] = mon
    m.drive.files[b"ZX64MON2"] = mon2
    m.tap("F5")
    m.mtype(":7000 3E 01 3C 3C 32 00 71 C9\r")
    m.mtype("B 7003\r")
    m.mtype("B 7004\r")
    m.mtype("B 7004\r")                          # again: off
    listed = next((r for r in reversed(m.mscreen()) if r.startswith("#BREAKPOINTS")), "")
    m.mtype("X\r", settle=20)
    m.type("T SHIFT+NEWLINE L 2 8 6 7 2")
    m.keys = {C64KEY[ZXKEY["NEWLINE"]]}
    m.run(3)
    m.keys = set()
    m.run(30)
    regs = next((r for r in reversed(m.mscreen()) if r.startswith(";")), "")
    m.mtype("G\r", settle=20)
    m.until(m.ready, 300, "the ROM ready for a key")
    m.run(3)
    check("no /INT: B 7003, B 7004 twice (off); stopped at 7003 (A = 2), G on to the end",
          listed == "#BREAKPOINTS 7003" and regs.startswith(";7003 02") and m.z.memory[0x7100] == 3
          and report(m) == "0/0", f"{listed!r} {regs[:10]!r} {report(m)}")

    # scrolling at the screen's edges: CRSR DOWN on the bottom row goes on
    # from the lowest M or D line, CRSR UP on the top row goes back
    m = Machine(int_wired=True)
    m.boot()
    m.drive.files[b"ZX64MON"] = mon
    m.drive.files[b"ZX64MON2"] = mon2
    m.tap("F5")
    up, dn = ("CRSRDOWN", "LSHIFT"), ("CRSRDOWN",)
    def rows_of(kind):                           # the screen's M or D lines, by address
        return {int(r[2:6], 16): r for r in m.mscreen() if r.startswith(kind)}
    ref = {}                                     # D from $0229 (an instruction's start), 64 lines
    m.mtype("D 0229\r", settle=30)
    for _ in range(3):
        ref.update(rows_of(".,"))
        m.mtype("D\r", settle=30)
    ref.update(rows_of(".,"))
    addrs = sorted(ref)
    m.mkey("HOME", "LSHIFT")                     # CLR: nothing to go on from
    m.mkey(*up)
    nothing = all(r == "" for r in m.mscreen()) and m.z.memory[mlb["crow"]] == 0
    m.mtype(f"D {addrs[30]:04X} {addrs[52]:04X}\r", settle=60)    # 23 lines and the prompt
    scr0 = m.mscreen()
    m.mkey(*dn)                                  # the prompt's row becomes the next line
    m.mkey(*dn)                                  # then it scrolls
    m.mkey(*dn)
    scr1 = m.mscreen()
    for _ in range(24):
        m.mkey(*up)                              # to the top row
    for _ in range(6):
        m.mkey(*up)                              # and back over the ROM's IY code
    scr2 = m.mscreen()
    m.mkey("HOME", "LSHIFT")                     # (not on the top row's D line)
    m.mtype("D\r", settle=30)                    # D alone: on from the bottom
    after = rows_of(".,")
    want_dn = [ref[a] for a in addrs[51:56]]
    want_up = [ref[a] for a in addrs[25:30]]
    check("CRSR DOWN on the bottom row: the next D lines (the prompt's row first), CRSR UP on the top "
          "row: the ones before, as a listing from $0229 has them (IY code); D alone goes on; "
          "no M or D line on the screen: nothing", nothing and scr0[-1] == "." and scr1[-5:] == want_dn
          and scr2[:5] == want_up and m.z.memory[mlb["crow"]] < 25 and addrs[56] in after,
          f"{nothing} {scr0[-2:]} {scr1[-5:]} {want_dn} {scr2[:5]} {want_up}")
    blk = bytes.fromhex("FD360512 DDCB0346 ED4B3412 CB11 FD210040 DD7EFE EDB0 00 CF0C FDCB0186"
                        "DDE5 ED5F 3EDD 06FD 21CBED FDE1 C9")   # every prefix; RST $08's DB;
    m.z.memory[0x7000:0x7000 + 2 * len(blk)] = blk * 2         # data bytes that are prefixes
    m.mkey("HOME", "LSHIFT")                     # back 25 lines over it: the whole screen
    m.mtype("D 7000\r", settle=30)               # as D lists it forward
    ref = {}
    for _ in range(3):
        ref.update(rows_of(".,"))
        m.mtype("D\r", settle=30)
    ref.update(rows_of(".,"))
    addrs = sorted(ref)
    m.mkey("HOME", "LSHIFT")
    m.mtype(f"D {addrs[28]:04X} {addrs[51]:04X}\r", settle=60)   # 24 lines: the command scrolls away
    for _ in range(24 + 25):
        m.mkey(*up)
    got = m.mscreen()
    want = [ref[a] for a in addrs[3:28]]
    check("CRSR UP 25 times over code with every prefix (DD CB d op too), RST $08's DB and prefix "
          "bytes as data: every line as D lists it forward", got == want,
          f"{[(g, w) for g, w in zip(got, want) if g != w][:3]}")
    def short(cmd, kind):                        # a short listing, the cursor taken down
        m.mkey("HOME", "LSHIFT")                 # to row 24, CRSR DOWN: the rows under it
        m.mtype(cmd + "\r", settle=30)           # filled, the cursor staying at the bottom
        while m.z.memory[mlb["crow"]] < 24:
            m.mkey(*dn)
        m.mkey(*dn)
        m.run(20)                                # ~2 lines a frame
        return m.mscreen(), m.z.memory[mlb["crow"]]
    ms, mrow = short("M 7000 7017", ".:")
    ds, drow = short("D 7000 7008", ".,")
    want_d = [ref[a] for a in addrs[:25] if a >= 0x7000][:25]
    check("CRSR DOWN on the bottom row under a short listing: the rows down to the bottom filled "
          "with the next lines, the cursor staying on row 24 (M and D)",
          [r[:6] for r in ms[1:]] == [f".:{0x7000 + 8 * i:04X}" for i in range(24)] and mrow == 24
          and ds[1:] == want_d[:24] and drow == 24, f"{ms[1:4]} {ms[-2:]} {mrow} {ds[1:4]} {ds[-2:]} {drow}")
    m.mkey("HOME", "LSHIFT")
    m.mtype("M 7000 70BF\r", settle=60)          # 24 lines: the first scrolls away
    m.mkey(*dn)
    m.mkey(*dn)
    scr1 = m.mscreen()
    for _ in range(24):
        m.mkey(*up)
    m.mkey(*up)
    m.mkey(*up)
    scr2 = m.mscreen()
    m.mkey("HOME", "LSHIFT")
    m.mtype("M\r", settle=30)
    check("the same with M lines: 70C0 and 70C8 at the bottom, 7000 and 6FF8 back at the top; M alone "
          "goes on from 70D0", scr1[-2].startswith(".:70C0 ") and scr1[-1].startswith(".:70C8 ")
          and scr2[0].startswith(".:6FF8 ") and scr2[1].startswith(".:7000 ")
          and any(r.startswith(".:70D0 ") for r in m.mscreen()), f"{scr1[-3:]} {scr2[:3]}")

    # the manual's hello world: a REM line, A, the text with :, RUN; then
    # a breakpoint on its RST $10; then the ROM's own string printer
    m = Machine(int_wired=True)
    m.boot()
    m.drive.files[b"ZX64MON"] = mon
    m.drive.files[b"ZX64MON2"] = mon2
    m.type("1 E " + " ".join("01234567890123456789012") + " NEWLINE")   # 1 REM ...
    m.type("1 0 T SHIFT+NEWLINE L 1 6 5 1 4 NEWLINE")                   # 10 RAND USR 16514
    m.tap("F5")
    for line in ("A 4082 LD HL,$408D", "LD A,(HL)", "INC A", "RET Z", "DEC A", "RST $10", "INC HL",
                 "JR $4085", "", ":408D 'HELLO WORLD' FF", "X"):
        m.mtype(line + "\r", settle=20)
    m.run(10)
    r = enter(m, "R")
    shown = m.screen()[0]
    m.tap("F5")
    m.mtype("B 4089\r")
    m.mtype("X\r", settle=20)
    m.type("R")
    m.keys = {C64KEY[ZXKEY["NEWLINE"]]}
    m.run(3)
    m.keys = set()
    m.run(30)
    regs = [next((r for r in reversed(m.mscreen()) if r.startswith(";")), "")]
    m.mtype("S\r", settle=20)                  # into the ROM
    regs.append(next((r for r in reversed(m.mscreen()) if r.startswith(";")), ""))
    m.mkey("DEL")                                # ".S" offered: INST/DEL it, then G
    m.mtype("G\r", settle=30)
    regs.append(next((r for r in reversed(m.mscreen()) if r.startswith(";")), ""))
    m.mtype("B 4089\r")
    m.mtype("G\r", settle=20)
    m.until(m.ready, 300, "the ROM ready for a key")
    m.run(3)
    check("hello world as in the manual: A at $4082, :408D 'HELLO WORLD' FF, RUN; B 4089 stops at the "
          "RST $10 with A = H, S: to $0010, G: again with E; B off, G: the rest",
          shown == "HELLO WORLD" and r == "0/10" and regs[0].startswith(";4089 2D")
          and regs[1].startswith(";0010 2D") and regs[2].startswith(";4089 2A") and m.screen()[0] == "HELLO WORLD"
          and report(m) == "0/10",
          f"{shown!r} {r} {regs} {m.screen()[0]!r} {report(m)}")
    m.tap("F5")
    for line in ("A 4082 LD DE,$408B", "LD BC,$000B", "JP $0B6B", "", ":408B 'HELLO WORLD", "", "X"):
        m.mtype(line + "\r", settle=20)
    m.run(10)
    r = enter(m, "R")
    check("and with the ROM's string printer: LD DE / LD BC / JP $0B6B", m.screen()[0] == "HELLO WORLD"
          and r == "0/10", f"{m.screen()[0]!r} {r}")
    m.tap("F5")
    m.mtype('W "HELLO"\r', settle=200)               # the program, for the L tests below
    hello = m.drive.files.get(b"HELLO", b"")

    # Z n: line 1 a REM of n bytes at 16514; a new program gets 10 RAND
    # USR 16514 too; a REM there is resized; then the manual's hello world
    def zout(line):                              # Z ..., the monitor's answer
        m.mtype(line + "\r", settle=20)
        scr = m.mscreen()
        return scr[max(i for i, r in enumerate(scr) if r.lstrip(".") == line) + 1]
    def prog():
        return bytes(m.z.memory[0x407D:m.peek16(0x400C)])
    def zrem(n, code):
        return bytes([0, 1]) + (n + 2).to_bytes(2, "little") + b"\xEA" + code + b"\x76"
    line10 = bytes.fromhex("000A0E00F9D41D22211D207E8F0104000076")
    m = Machine(int_wired=True)
    m.boot()
    m.drive.files[b"ZX64MON"] = mon
    m.drive.files[b"ZX64MON2"] = mon2
    m.tap("F5")
    outs = [zout("Z 0"), zout("Z 4000"), zout("Z"), zout("Z 10")]
    p1 = prog()
    m.mtype("X\r", settle=20)
    m.run(10)
    r0 = report(m)
    r1 = enter(m, "R")
    check("Z 10 with no program: 1 REM, 15 NOPs and a RET, and 10 RAND USR 16514; REM 4082-4091; X: "
          "BASIC, report 0; RUN: the RET, 0/10. Z 0, Z 4000, Z alone: ?",
          outs == ["#?", "#?", "#?", "#REM 4082-4091"] and p1 == zrem(16, bytes(15) + b"\xC9") + line10
          and r0 == "0/0" and r1 == "0/10", f"{outs} {p1.hex()} {r0} {r1}")
    m.tap("F5")
    out = zout("Z 17")
    for line in ("A 4082 LD HL,$408D", "LD A,(HL)", "INC A", "RET Z", "DEC A", "RST $10", "INC HL",
                 "JR $4085", ""):
        m.mtype(line + "\r", settle=20)
    m.mtype(":408D 'HELLO ")
    m.mkey(*RVS)
    m.mtype("WORLD")
    m.mkey(*OFF)
    m.mtype("' FF\r")
    p2 = prog()
    m.mtype("X\r", settle=20)
    m.run(10)
    r2 = enter(m, "R")
    shown = m.screen()[0]
    check("the manual's hello world: Z 17 grows the REM to 23 bytes (NOPs, the RET kept), A at $4082, "
          ":408D 'HELLO {RVS ON}WORLD{RVS OFF}' FF; RUN: HELLO and an inverse WORLD",
          out == "#REM 4082-4098" and p2[:5] == zrem(23, b"")[:5] and p2[29:] == line10
          and shown == "HELLO world" and r2 == "0/10", f"{out} {p2.hex()} {shown!r} {r2}")
    m.tap("F5")
    vars0, eline0 = m.peek16(0x4010), m.peek16(0x4014)
    out = zout("Z 8")
    p3 = prog()
    check("Z 8: the REM cut to its first 8 bytes, the rest moved back (VARS, E_LINE 15 less)",
          out == "#REM 4082-4089" and p3 == zrem(8, p2[5:13]) + line10
          and m.peek16(0x4010) == vars0 - 15 and m.peek16(0x4014) == eline0 - 15,
          f"{out} {p3.hex()} {m.peek16(0x4010):04X} {vars0:04X}")
    big = zout("Z 3F00")
    check("Z 3F00: no room below the ZX81's stack: ?, nothing changed", big == "#?" and prog() == p3, big)

    m = Machine(int_wired=True)                  # a program without line 1; line 1 no REM
    m.boot()
    m.drive.files[b"ZX64MON"] = mon
    m.drive.files[b"ZX64MON2"] = mon2
    m.type("1 0 P 5 NEWLINE")                    # 10 PRINT 5
    p0 = bytes(m.z.memory[0x407D:m.peek16(0x400C)])
    m.tap("F5")
    out = zout("Z 4")
    p4 = prog()
    m.mtype("X\r", settle=20)
    m.run(10)
    r4 = enter(m, "R")
    shown = m.screen()[0]
    m.type("1 P 1 NEWLINE")                      # 1 PRINT 1
    m.tap("F5")
    out2 = zout("Z 4")
    check("Z 4 before 10 PRINT 5: 1 REM (3 NOPs, a RET) made, the program after it; RUN prints 5. "
          "Line 1 a PRINT: ?",
          out == "#REM 4082-4085" and p4 == zrem(4, b"\0\0\0\xC9") + p0 and shown == "5" and r4 == "0/10"
          and out2 == "#?", f"{out} {p4.hex()} {shown!r} {r4} {out2}")

    # L and W without addresses: a program, as BASIC's LOAD and SAVE; with
    # them, memory as a PRG. A file that isn't a program is refused
    speed = open(os.path.join(ROOT, "build", "obj", "speed.p"), "rb").read()
    big = bytearray(speed)
    big[11:13] = (0x8100).to_bytes(2, "little")  # E_LINE past RAMTOP
    m = Machine(int_wired=True)
    m.boot()
    m.drive.files.update({b"ZX64MON": mon, b"ZX64MON2": mon2, b"SPEED": speed, b"BIG": bytes(big)})
    m.tap("F5")
    m.mtype("F 7000 701F 50\r")             # E_LINE $5050: it fits
    m.mtype('W "MYTEST" 7000 701F\r', settle=60)
    sysv = bytes(m.z.memory[0x4009:0x4100])
    outs = []
    for line in ('L "MYTEST"', 'L "BIG"', 'L "NONE"'):
        m.mtype(line + "\r", settle=200)
        scr = m.mscreen()
        outs.append(scr[max(i for i, r in enumerate(scr) if r.lstrip(".") == line) + 1])
    kept = bytes(m.z.memory[0x4009:0x4100]) == sysv
    m.mtype('L "MYTEST" 7100\r', settle=200)
    raw = bytes(m.z.memory[0x7100:0x7120]) == b"\x50" * 32
    m.mtype('L "SPEED"\r', settle=200)
    scr = m.mscreen()
    loaded = next((r for r in reversed(scr) if r.startswith("#LOADED")), "")
    same = bytes(m.z.memory[0x4009:0x4009 + len(speed)]) == speed
    m.mtype("X\r", settle=20)
    m.until(m.ready, 300, "the ROM ready for a key")
    m.run(3)
    r = report(m)
    check("L \"NAME\": a program, as LOAD (SPEED: $4009 on as the file; X: it runs, as it does after LOAD); "
          "a PRG of code: "
          "? NOT A PROGRAM, too big: ? TOO BIG, none: ?, nothing changed; L \"NAME\" a: still raw",
          outs[0] == "#? NOT A PROGRAM" and outs[1] == "#? TOO BIG" and outs[2] == "#?" and kept and raw
          and loaded == "#LOADED 4009-4593" and same and r is not None and r.startswith("0/")
          and m.screen()[0] == "ZX64 SPEED TEST", f"{outs} {kept} {raw} {loaded!r} {same} {r} {m.screen()[0]!r}")
    m.tap("F5")
    m.mtype('W "SAVED"\r', settle=200)
    eline = m.peek16(0x4014)
    check("W \"NAME\": the program, as SAVE ($4009 up to E_LINE)",
          m.drive.files.get(b"SAVED") == bytes(m.z.memory[0x4009:eline]),
          f"{len(m.drive.files.get(b'SAVED', b''))} bytes, E_LINE {eline:04X}")
    m.mtype("X\r", settle=20)
    r = enter(m, 'J SHIFT+P M Y T E S T SHIFT+P')
    check("LOAD \"MYTEST\" in BASIC (a PRG of code): report D, the program as it was",
          r is not None and r.startswith("D/") and m.peek16(0x4014) == eline, f"{r}")

    def dabble(paused):                          # L "HELLO" at the K cursor, or in a PAUSE
        m = Machine(int_wired=True)
        m.boot()
        m.drive.files.update({b"ZX64MON": mon, b"ZX64MON2": mon2, b"HELLO": hello})
        if paused:
            m.type("1 0 M 1 0 0 0 NEWLINE")       # 10 PAUSE 1000
            m.type("R")
            m.keys = {C64KEY[ZXKEY["NEWLINE"]]}
            m.run(3)
            m.keys = set()
            m.run(20)
        m.tap("F5")
        m.mtype('L "HELLO"\r', settle=200)
        m.mtype("D 4082 4082\r")
        d = next((r for r in reversed(m.mscreen()) if r.startswith(".,4082")), "")
        m.mtype("X\r", settle=20)
        m.until(m.ready, 300, "the ROM ready for a key")
        m.run(3)
        r1 = report(m)
        r2 = enter(m, "R")
        return d, r1, r2, m.screen()[0]
    got = [dabble(False), dabble(True)]
    m = Machine(int_wired=True)                  # the same file with BASIC's LOAD
    m.boot()
    m.drive.files[b"HELLO"] = hello
    r = enter(m, "J SHIFT+P H E L L O SHIFT+P")
    basic = (r, m.screen())
    check("W \"HELLO\", then L \"HELLO\" (at the K cursor, or with F5 in a PAUSE): D shows its code, X: "
          "BASIC as after LOAD \"HELLO\" (report, screen), RUN prints HELLO WORLD",
          len(hello) > 100 and all(g[0].endswith("LD DE,$408B") and g[1] == basic[0] and g[2] == "0/10"
                                   and g[3] == "HELLO WORLD" for g in got), f"{len(hello)} {got} {basic[0]}")

    # ---- JiffyDOS in zx64: LOAD (NAME.P too), F7's ROM, F5's monitor, and
    # the monitor's L and $ on its own screen (VIC bank 0, y-scroll 3)
    m = Machine(int_wired=True, jiffy=True)
    m.boot()
    prog = open(os.path.join(ROOT, "build", "obj", "speed.p"), "rb").read()
    m.drive.files[b"SPD.P"] = prog
    sent, opens = m.iec.sent, m.drive.opens
    m.barlog = []
    r = enter(m, "J SHIFT+P S P D SHIFT+P")
    eline = prog[11] | prog[12] << 8                         # the file's E_LINE (it runs itself)
    dfile = prog[3] | prog[4] << 8
    check("JiffyDOS: LOAD \"SPD\" finds SPD.P (SPD itself not found by JiffyDOS either), loads it by "
          "JiffyDOS with the bar, the drive let go",
          r and r.startswith("0/") and bytes(m.z.memory[0x407D:dfile]) == prog[0x407D - 0x4009:dfile - 0x4009]
          and m.iec.sent - sent == eline - 0x4009 and m.drive.opens == opens + 2 and m.barlog
          and not m.channels and m.iec.state == "idle" and m.ram[jl["JFLAG"]] == 0,
          f"{r}, {m.iec.sent - sent} bytes by JiffyDOS of {eline - 0x4009}, {m.drive.opens - opens} opens, "
          f"bus {m.iec.state}")
    r = enter(m, "J SHIFT+P N O N E SHIFT+P")
    check("JiffyDOS: LOAD of a missing file: report D, nothing left open", r and r.startswith("D/")
          and not m.channels and m.iec.state == "idle", f"{r}, bus {m.iec.state}")
    rom = bytes(m.z.memory[0x0000:0x2000])
    m.drive.files[b"ZX64"] = open(os.path.join(ROOT, "build", "obj", "zx64.prg"), "rb").read()
    m.z.memory[0x0123] ^= 0x55
    sent = m.iec.sent
    m.tap("F7", 3)
    m.until(lambda: m.cursor() and m.ready(), 600, "the K cursor after F7")
    check("JiffyDOS: F7 reads the ROM again by it (ZX64's first $2801 bytes)",
          bytes(m.z.memory[0x0005:0x2000]) == rom[0x0005:] and m.iec.sent - sent == 0x2801
          and not m.channels, f"{m.iec.sent - sent} bytes")
    m.drive.files[b"ZX64MON"] = mon
    m.drive.files[b"ZX64MON2"] = mon2
    sent = m.iec.sent
    m.tap("F5")
    check("JiffyDOS: F5 loads zx64mon's two files by it, the monitor runs",
          bytes(m.z.memory[0x3000:mlb["kmods"]]) == mon[2:mlb["kmods"] - 0x3000 + 2]
          and m.iec.sent - sent == len(mon) + len(mon2) and m.mscreen()[0].startswith("#ZX64MON"),
          f"{m.iec.sent - sent} bytes of {len(mon) + len(mon2)}, {m.mscreen()[0]!r}")
    row = lambda: m.z.memory[mlb["crow"]]
    t1 = b"\x00\x80" + bytes(range(1, 200))
    m.drive.files[b"T1"] = t1
    sent = m.iec.sent
    m.mtype('L "T1" 7100\r', settle=30)
    l1 = (bytes(m.z.memory[0x7100:0x7100 + len(t1) - 2]) == t1[2:]
          and m.mscreen()[row() - 1] == f"#LOADED 7100-{0x7100 + len(t1) - 3:04X}")
    check("JiffyDOS: the monitor's L by it on the monitor's screen: the VIC bank kept (0), the guard "
          "on y-scroll 3", l1 and m.iec.sent - sent == len(t1) and jbits(m)[3] == 4
          and jbits(m) == portbits(m) and m.ram[0xDD00] & 3 == 3 and m.z.memory[0xCD00] & 3 == 3,
          f"L {l1}, {m.iec.sent - sent} bytes, JNY {jbits(m)[3]}, $DD00 ${m.ram[0xDD00]:02X}")
    m.mkey("HOME", "LSHIFT")
    m.mtype("$\r", settle=60)
    scr = m.mscreen()
    check("JiffyDOS: $ lists (its start by JiffyDOS, a line at a time by the kernal)",
          scr[1] == '0 "ZX64            " 81 2A' and any('"T1"' in r and r.endswith("PRG") for r in scr)
          and any(r.endswith("BLOCKS FREE.") for r in scr) and not m.channels, f"{scr[:3]}")

    # ---- the boot file, ZX81 (c64/stub.asm): ZX64 by JiffyDOS, and the
    # monitor with it; a plain drive the kernal's way, the monitor left
    body = open(os.path.join(ROOT, "build", "obj", "zx64.prg"), "rb").read()
    def stubboot(jiffy, files):
        m = Machine(int_wired=True, prg=stub, jiffy=jiffy)
        m.drive.files.update(files)
        m.boot()
        return m
    every = {b"ZX64": body, b"ZX64MON": mon, b"ZX64MON2": mon2}
    m = stubboot(True, every)
    said = m.printed.replace("\r", "/")
    opens = m.drive.opens
    m.tap("F5")
    check("the boot file on a JiffyDOS drive: ZX64 and both monitor files by JiffyDOS, said on the "
          "screen; zx64 starts, and the first F5 needs no disk",
          said == "LOADING ZX64/LOADING ZX64MON/LOADING ZX64MON2/" and m.iec.sent == len(body) + len(mon) + len(mon2)
          and m.drive.opens == opens and m.mscreen()[0].startswith("#ZX64MON"),
          f"{said!r}, {m.iec.sent} bytes by JiffyDOS, F5 {m.drive.opens - opens} opens, {m.mscreen()[0]!r}")
    m = stubboot(False, every)
    said = m.printed.replace("\r", "/")
    opens = m.drive.opens
    m.tap("F5")
    check("the boot file on a plain drive: ZX64 the kernal's way, the monitor left for F5",
          said == "LOADING ZX64/" and m.iec.sent == 0 and m.drive.opens == opens + 2
          and m.mscreen()[0].startswith("#ZX64MON"), f"{said!r}, F5 {m.drive.opens - opens} opens")
    m = Machine(int_wired=True, prg=stub, jiffy=True)
    m.cpu.sp = 0xF6
    m.call_6510(2061)
    said = m.printed.replace("\r", "/")
    m2 = stubboot(True, {b"ZX64": body})
    loader = bytes(m.ram[0xCE00:0xD000])
    bad = []
    for at in (0xCE00, 0x0300):                  # over the loader; over the JiffyDOS reader
        m3 = Machine(int_wired=True, prg=stub, jiffy=True)
        m3.drive.files[b"ZX64"] = bytes([at & 0xFF, at >> 8]) + b"\xEA" * 40
        m3.cpu.sp = 0xF6
        m3.call_6510(2061)
        if m3.printed.replace("\r", "/") != "LOADING ZX64/ZX64 NOT LOADED/" or m3.ram[at:at + 40] == b"\xEA" * 40:
            bad.append(f"${at:04X}: {m3.printed!r}")
        if at == 0xCE00 and bytes(m3.ram[0xCE00:0xD000]) != loader:
            bad.append("the loader written over")
    check("the boot file: a ZX64 that would load over the loader ($CE00) or the JiffyDOS reader ($0300): "
          "refused, said, back to BASIC", not bad, f"{bad}")
    check("the boot file: no ZX64 on the disk: said, back to BASIC; no monitor on it: zx64 starts all the same",
          said == "LOADING ZX64/ZX64 NOT LOADED/" and not m.z80_on and m2.cursor()
          and m2.ram[0x4003] == 0, f"{said!r}, {m2.printed!r}")

    # ---- tools/pcheck.py, on a program made for it: each IN and OUT, and
    # what zx64 makes of it
    import pcheck
    from zxbasic import p_file
    code = bytearray.fromhex(
        "3EFD DBFE"                              # LD A,$FD / IN A,($FE): one row
        "AF DBFE"                                # XOR A / IN A,($FE): all rows
        "3EE7 DBFE"                              # LD A,$E7 / IN A,($FE): two rows at once
        "210000 7E DBFE"                         # LD HL,table / LD A,(HL) / IN A,($FE)
        "0107E0 3EC5 ED79"                       # LD BC,$E007 / LD A,$C5 / OUT (C),A: ZXpand
        "3E20 D3FD"                              # LD A,$20 / OUT ($FD),A: into zx64's code
        "CDBB02 D3FD"                            # CALL KEYBOARD / OUT ($FD),A: A not known
        "ED47 ED5E"                              # LD I,A / IM 2
        "C9 DBFE DF")                            # RET; data: IN-like bytes, the table
    t = code.index(bytes.fromhex("210000")) + 1
    code[t:t + 2] = (16514 + len(code) - 1).to_bytes(2, "little")
    path = os.path.join(ROOT, "build", "obj", "pcheck-test.p")
    open(path, "wb").write(p_file('10 REM {bin:t}\n20 RAND USR VAL "16514"\n30 PRINT USR 8192\n',
                                  blobs={"t": bytes(code)}))
    found = pcheck.check(path)[0]

    def has(level, *words):
        return any(lvl == level and all(w in m for w in words) for lvl, _, m in found)
    check("pcheck: keyboard INs with one row, all rows, a row from a table are fine; two rows at once not",
          has("ok", "row A-G") and has("ok", "all rows") and has("ok", "row P-Y", "from $")
          and has("warn", "rows 1-5 + 0-6 at once"), f"{len(found)} findings")
    check("pcheck: OUTs: the ZXpand, into zx64's code ($20FD), A not known; LD I,A, IM 2, USR 8192",
          has("warn", "talks to the ZXpand") and has("warn", "writes $20FD", "zx64's code")
          and has("warn", "A is not known") and has("warn", "LD I,A") and has("warn", "IM 2")
          and has("warn", "USR 8192"), "")
    check("pcheck: IN-like bytes after the RET are data, not an IN; USR VAL \"16514\" followed",
          sum(1 for _, a, m in found if a is not None and m.startswith("IN")) == 4
          and has("note", "1 IN/OUT-like byte pairs outside"), "")

    # ---- the original cartridge: no /INT
    m = Machine(int_wired=False)
    m.boot()
    check("no /INT: boots to the K cursor", m.cursor() and m.irqs == 0, f"(frame {m.frames})")
    r = enter(m, "P 5")
    check("no /INT: PRINT 5", m.screen()[0] == "5" and r == "0/0", f"{m.screen()[0]!r} {r}")
    fr0, f0 = m.peek16(0x4034), m.frames
    m.run(100)
    counted = (fr0 - m.peek16(0x4034)) & 0x7FFF
    check("no /INT: FRAMES counts once a frame in the key wait, also when the raster flag reads set "
          "after bad lines", abs(counted - (m.frames - f0)) <= 1, f"{counted} in {m.frames - f0}")
    enter(m, "T SHIFT+NEWLINE L 8 1 9 2")        # RAND USR 8192: the IRQ handler, called
    try:
        r = enter(m, "P 6")
        ok = m.screen()[0] == "6" and r == "0/0"
    except AssertionError as e:
        ok, r = False, str(e).splitlines()[0]
    check("no /INT: RAND USR 8192 (Mazogs's ZXpand SAVE) runs the IRQ handler; the key wait still "
          "works after it", ok and not m.z.memory[m.lbl["irqseen"]], r)

    m = Machine(int_wired=False)                 # F5 in a running program, twice
    m.boot()
    m.drive.files[b"ZX64MON"] = mon
    m.drive.files[b"ZX64MON2"] = mon2
    for line in ("5 L A SHIFT+L 0", "1 0 L A SHIFT+L A SHIFT+K 1", "2 0 G 1 0"):
        m.type(line + " NEWLINE")                # 5 LET A=0, 10 LET A=A+1, 20 GOTO 10
    m.type("R")
    m.keys = {C64KEY[ZXKEY["NEWLINE"]]}
    m.run(3)
    m.keys = set()
    m.run(30)
    seen = []
    for _ in range(2):
        m.tap("F5", frames=60)
        seen.append(m.z.memory[0xC018] == 0x14)
        m.mtype("X\r", settle=30)
    check("no /INT: F5 stops a running program, X lets it go on, and F5 does it again", seen == [True, True],
          f"{seen}")

    fell = [i for i, mm in enumerate(Machine.all) if mm.int_wired and mm.irqs and not mm.z.memory[mm.lbl["irqseen"]]]
    check("with /INT, the key wait never gave up on the IRQ in all of the above", not fell, f"{fell}")
    io = [x for mm in Machine.all for x in mm.io]
    check("no IN or OUT from the ROM or zx64 in all of the above", not io, f"{io[:4]}")

    print(f"\n{'all passed' if not failures else f'{failures} FAILED'}")
    sys.exit(1 if failures else 0)


if __name__ == "__main__":
    main()
