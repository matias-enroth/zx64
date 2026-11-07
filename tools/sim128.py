#!/usr/bin/env python3
"""Run zx128 without a C128: the C128 side of make test.

The ZX81 ROM and zx128 run in a Z80 emulator on RAM bank 1, the 8502's
loader in a 6502 emulator on RAM bank 0 (the top 8K is common RAM, the
same bytes in both), and they take turns the way the C128's MMU makes
them: the 8502 stores $B0 to $D505 and the Z80 starts at $FFEE; the Z80
does OUT (C),A with BC = $D505 and A = $B1 and the 8502 goes on after its
own store. Around them: a VIC raster flag once a frame, the CIA keyboard
matrix, a VDC (80 columns, 16K of video RAM) and a fake disk drive
behind the C128 kernal's traps. The Z80 side as VICE's x128 and the real
C128 show it.

    python3 tools/sim128.py            (make test runs it after make)

The model is imported by other checks: C128, selfcheck (register a
check function), main. The model's own checks need no build/ directory;
zx128's need make's build/obj/zx128.prg (and zx64's, kbd_row_df_types
compares the two), and fail without it. The z80 and py65
packages as for tools/simulate.py, whose Drive, check, report, ZX and key
tables are used as they are.

The Z80's ports, by BC (IN/OUT take the whole 16-bit address):
  $D000-$D02F  the VIC: raster line ($D011 bit 7, $D012), IRQ flag and
               enable ($D019, $D01A), $D02F (the C128's extra keyboard
               columns, K0-K2 on bits 0-2, low = selected); the rest are
               plain registers
  $DC00-$DC0F  CIA 1: the keyboard matrix on $DC00/$DC01, as simulate.py's
  $D500-$D50B  the MMU: plain registers, but $D505 switches the CPU
               (bit 0 set = the 8502, clear = the Z80)
  $D600/$D601  the VDC: register select/status, data
  $DF00-$DF0A  absent (read $FF); the rest of $DFxx is I/O 2, open bus:
               reads $00, writes go nowhere
  other $D0xx-$DExx   chips this model has no register for: read $FF,
               writes are logged in .stray_io
  anything else  reads and writes RAM bank 1 at that address (so
               IN A,($FE) with A = $7F reads $7FFE: the ZX81 ROM's
               keyboard scan sees what the IRQ put there)

The 8502 sees memory through the MMU's configuration register ($FF00,
also $D500, shared by both CPUs: the Z80's stores to $FF00 count when it
hands over): bit 6 picks RAM bank 0 or 1, bit 0 clear puts the I/O
above at $D000-$DFFF. Its pages 0 and 1 follow the page pointers
($D507-$D50A; the swap of the pointed-to page isn't modelled), and the
bottom common RAM follows $D506 (as the kernal leaves it: 1K). The ROMs
aren't there (RAM instead; the kernal is the traps), but for a function
ROM's 32K when a check puts one in (fnrom: zx128's own), which
$FF00 bits 2-3 and 4-5 bring in at $8000 and $C000. The Z80 always sees
bank 1 here; that it set $FF00 = $7F (bank 1, I/O off), with the page
pointers on bank 1's pages 0 and 1, before running outside common RAM is
checked instead (map_errors).

  $D600/$D601 the VDC as above; vdc_busy (0: always ready) makes the
               status read busy that many times after each data access,
               and a data access while busy is lost (vdc_lost); register
               writes are counted (vdc_nregs; of them vdc_naddr R18,
               vdc_nbytes R31, vdc_nblocks R30), for the picture's budget
  $D800-$DBFF  colour RAM, $DD00-$DD0F CIA 2: plain memory (timed: its
               timers A and B and their interrupt flags, below)
  $D505        bit 7 reads the 40/80 key (key4080_down, the default)

The VIC raster IRQ is delivered to the Z80's /INT (no wire needed) at
line 250, as in simulate.py: once a frame, while $D011 bit 7 is clear and
$D01A bit 0 set. Writes to $D012 don't move it.
That is the untimed model (SIM128_TIMED=0); the default is the timed one
(C128(timed=True)): the real C128's VDC frame and blank (as measured), the
raster compare moving the IRQ, CIA 2's timers. zx128 needs it: its tick
is locked to the VDC's blank (z80/vdclock.inc), which the untimed model
never shows.
Both CPUs have no time of their own while the other runs; the Z80 gets
2 T-states per C128 cycle (a frame is simulate.FRAME_T). For the checks:
on_irq (called at each IRQ, as it is taken) and traps8502 (8502
addresses where a Python function runs instead: load_p's LOAD).
"""
import collections
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import simulate  # noqa: E402  (exits with a hint if the z80 or py65 package is missing)
from simulate import (C64KEY, C64NAMES, FRAME_T, MKEY, MPOS, SLICE_T, ZX, ZXKEY, Drive, Machine, check,  # noqa: E402
                      matrix_read, porta_read)
import z80  # noqa: E402
from py65.devices.mpu6502 import MPU  # noqa: E402

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
TIMED = os.environ.get("SIM128_TIMED", "1") == "1"   # C128()'s default: the timed VDC and raster (0: untimed)
SWITCH = 0xD505              # the MMU's CPU switch
Z80_START = 0xFFEE           # where the Z80 starts
COMMON = 0xE000              # the top 8K is common RAM
# The C128's own keys zx128 reads: (column, row), columns 8-10 = K0-K2
C128NAMES = {"UP": (10, 3), "DOWN": (10, 4), "LEFT": (10, 5), "RIGHT": (10, 6),   # the top row's
             "CTRL": (7, 2),                     # (and CTRL, the function ROM's skip key)
             # the numeric keypad, as VICE's C128 keymap and the
             # C128 kernal's decode table ($FA80, entries 64-87) have it
             "KP8": (8, 1), "KP5": (8, 2), "KP2": (8, 4), "KP4": (8, 5), "KP7": (8, 6), "KP1": (8, 7),
             "KPPLUS": (9, 1), "KPMINUS": (9, 2), "ENTER": (9, 4), "KP6": (9, 5), "KP9": (9, 6), "KP3": (9, 7),
             "KP0": (10, 1), "KPDOT": (10, 2)}
# the keypad's keys by what they type
KEYPAD = dict({str(d): f"KP{d}" for d in range(10)}, **{"+": "KPPLUS", "-": "KPMINUS", ".": "KPDOT", "\r": "ENTER"})
VDC_READY = 0x80             # the VDC's status: ready
VDC_VBLANK = 0x20            # the VDC's status: vertical blank
# ---- the timed VDC (C128.timed): the real flat C128's numbers, in C128
# cycles (a Z80 T is half a cycle here). The VDC runs its own frame,
# against the VIC's.
WRAP_T = 100_000             # the z80 package's frame_tick wraps (and run() stops) here
VDC_FRAME = int(os.environ.get("SIM128_VDC_FRAME", 19674))   # the VDC's frame (50.08 Hz: measured on the C128)
VDC_BLANK = int(os.environ.get("SIM128_VDC_BLANK", 7065))    # status bit 5 set for this long from the frame's start
VDC_FAST = int(os.environ.get("SIM128_VDC_FAST", 7025))      # accesses are served at once until here (unpolled landed to 7.13 ms)
VDC_FAST_BUSY = int(os.environ.get("SIM128_VDC_BUSY", 9))    # ...each busy this long (18 T apart all landed)
VDC_LINE = VDC_FRAME / 312   # the VDC's scan line
VDC_ROWLINES = 8             # in the display, a character row's lines:
VDC_BLOCKED = (0, 1)         # these have no free memory slot for the CPU
VDC_SLOT = 40.0              # the slot's place in a line
VDC_LAT = 0.0                # an access waits at least this long for a slot
VDC_REG_SLOTS = 1            # an R18/R19 write in the display takes this many slots,
VDC_REG_LAT = 31.0           # and waits at least this long for the first
# The VDC's block operations (R30), as measured on the C128,
# each overridable so the checks can be run across a range:
def _pair(name, default):
    v = os.environ.get(name)
    return tuple(float(x) for x in v.split(",")) if v else default


# Measured on the C128: a byte's time, in the
# blank and in the display (the slope from 64 to 255 bytes), and in the display
# a start that grows through the frame: busy = bytes x rate + DLAT's own
# (fill, copy) + DLAT's growth x the cycles since the blank ended, at least
# the blank's rate (fill 64: 113, 204, 294 cycles 1.2, 5.2, 9.2 ms into the
# display; copy 64: 174, 278, 369).
VDC_BLK_FILL = _pair("SIM128_BLK_FILL", (0.52, 2.68))  # a fill's cycles a byte, in the blank and in the display
VDC_BLK_COPY = _pair("SIM128_BLK_COPY", (1.04, 5.59))  # a copy's
VDC_BLK_DLAT = _pair("SIM128_BLK_DLAT", (-85.0, -213.0, 0.0235))   # the display's start: fill's, copy's, growth
VDC_BLK_FILLX = int(os.environ.get("SIM128_BLK_FILLX", 0))   # a fill writes R31's byte, R30 more and this many
VDC_BLK_COPYX = int(os.environ.get("SIM128_BLK_COPYX", 0))   # a copy writes R30 and this many
VDC_BLK_ZERO = int(os.environ.get("SIM128_BLK_ZERO", 256))   # R30 = 0 counts as this
CPU_SLOW = 0.019             # (timed) the real Z80 runs this much slower than 2 T a cycle
                             # (the quiet editor's pic_step: 5,318 us on the C128)
IO_EXTRA_T = 1               # (timed) T-states each I/O access ($Dxxx) adds: the
                             # Z80 meets the 1 MHz bus (0-1 cycles, 1 T on average)
CR = 0xFF00                  # the MMU's configuration register, as both CPUs see it
Z80_CR = 0x7F                # the Z80's: bank 1, all RAM, I/O off
Z80_PAGES = bytes([0x00, 0x01, 0x01, 0x01])   # P0L P0H P1L P1H: pages 0 and 1 bank 1's

# C128 kernal entry points the 8502 loader calls: trapped, as simulate.py does
KERNAL128 = {0xFF68: "setbnk", 0xFFBA: "setlfs", 0xFFBD: "setnam", 0xFFD5: "load", 0xFFD8: "save",
             0xFFC0: "open", 0xFFC3: "close", 0xFFC6: "chkin", 0xFFC9: "chkout", 0xFFCC: "clrchn",
             0xFFCF: "chrin", 0xFFD2: "chrout", 0xFFB7: "readst", 0xFF90: "setmsg",
             0xFF81: "init", 0xFF84: "ioinit", 0xFF87: "ramtas", 0xFF8A: "init"}   # CINT IOINIT RAMTAS RESTOR
ISTOP = 0x0328                  # the kernal's STOP vector: its LOAD calls it before each block (VICE)
EAL = 0xAE                      # LOAD's pointer then, where the block goes


class Bus8502:
    """The 8502's memory: what py65 reads and writes, through the MMU."""

    def __init__(self, m):
        self.m = m

    def __getitem__(self, a):
        m = self.m
        if a == CR:
            return m.cr
        if a < 2:                                # the 8502's own I/O port
            return m.port8502[a]
        if m.rom8502(a):                         # a ROM there: not the RAM below it
            f = m.fnrom_byte(a)
            if f is not None:
                return f
            m.rom_reads.append((m.cpu.pc, a))
            return (a ^ a >> 8 ^ 0x5A) & 0xFF
        p = m.phys8502(a)
        if p is None:
            return m.io_read(a, m.cpu.pc)
        return (m.bank1 if p[0] else m.bank0)[p[1]]

    def __setitem__(self, a, v):
        m = self.m
        if a == CR:
            return m.set_cr(v)
        if a < 2:
            m.port8502[a] = v
            return
        p = m.phys8502(a)
        if p is None:
            return m.io_write(a, v, m.cpu.pc)
        if p[0] and m.writes1 is not None:
            m.writes1.add(p[1])
        (m.bank1 if p[0] else m.bank0)[p[1]] = v


class C128:
    """The C128 as zx128 sees it. bank1 is the Z80's memory (the Z80
    emulator's own buffer, a writable memoryview of 64K), bank0 the
    8502's (a bytearray). The top 8K is common RAM: bank0's copy is brought
    up to date when the Z80 hands over, bank1's when the 8502 does, and
    poke() writes both. There are no ROMs: the kernal is the traps.
    bank1 is a memoryview: only slice assignment of the same length works
    (bank1[a:a+3] = b"abc"), and no bytearray methods."""

    # these need nothing of Machine but the attributes this class has too
    carry = Machine.carry
    line = Machine.line
    k_close, k_clrchn = Machine.k_close, Machine.k_clrchn
    k_chrout, k_readst, k_init = Machine.k_chrout, Machine.k_readst, Machine.k_init
    k_setlfs = Machine.k_setlfs

    def __init__(self, vdc_k=16, timed=None, vdc_phase=0):
        self.timed = TIMED if timed is None else timed   # the timed VDC and raster compare
        self.vdc_phase = vdc_phase               # the VDC frame's start, cycles before t = 0
        self.vdc_ready_at = 0.0                  # (timed) cycle the VDC is ready again
        self.vdc_nlost_blank = 0                 # (timed) lost data accesses inside status bit 5
        self.vdc_nselbusy = 0                    # (timed) register selects while busy
        self.on_vdc = None                       # (timed) called (m, kind, cycle, pos, ok) for each data access
        self.on_blk = None                       # (timed) called (m, start, end, copy, bytes) for each block operation
        self.vdc_blk_until = 0.0                 # (timed) the last block operation busy till here,
        self.vdc_nblkbusy = 0                    # and VDC accesses (selects too) made meanwhile
        self._in_run = False
        self._t0 = self._ft0 = 0
        self._io_t = 0                           # (timed) I/O stretch this run
        self.next_irq_t = FRAME_T                # (timed) when the raster compare next matches
        self.z = z80.Z80Machine()
        self.bank1 = self.z.memory
        self.bank0 = bytearray(0x10000)
        self.cpu = MPU(memory=Bus8502(self))
        self.drive = Drive()
        self.z.set_input_callback(self.z_in)
        self.z.set_output_callback(self.z_out)
        self.z80_on = False
        self.z80_started = False                 # the Z80 starts at $FFEE once, then resumes
        self.t = 0                               # Z80 T-states so far
        self.next_frame = FRAME_T
        self.nframes = 0
        self.irqs = 0
        self.keys = set()                        # keys down: (column, row), columns 8-10 = K0-K2
        self.joy = set()                         # the stick in port 2: STICK names held
        self.cia_glitch = False                  # as simulate.py's: every 211th read wrong
        self.ciareads = 0
        self.pa = 0xFF                           # CIA 1 port A, the column select
        self.cia = bytearray(16)
        self.k2f = 0xFF                          # $D02F
        self.vic = bytearray(0x30)
        self.latch = 0                           # $D019
        self.enable = 0                          # $D01A
        self.mmu = bytearray(16)
        self.mmu[6] = 0x04                       # RCR: 1K common RAM at the bottom, as the kernal leaves it
        self.mmu[9] = 0x01                       # P1L: page 1 is page 1
        self.mmu[0xB] = 0x20                     # the MMU's version
        self.cr = 0x00                           # $FF00: the kernal's bank 15 (ROMs here are RAM)
        self.key4080_down = True                 # the 40/80 key: down, 80 columns
        self.cia2 = bytearray(16)
        self._t_base = [(0.0, 0xFFFF), (0.0, 0xFFFF)]   # (timed) timers A, B: (cycle, count then)
        self._t_run = [False, False]
        self._icr, self._icr_mask, self._icr_c = 0, 0, [0.0, 0.0]
        self.colour = bytearray(1024)
        self.stray_io = []                       # ("IN"/"OUT", pc, port[, value]) nobody answers
        self.map_errors = []                     # (pc, $FF00, pointers): the Z80 outside common
                                                 # RAM, $FF00 not $7F or pages 0/1 not bank 1's
        self.vram = bytearray(vdc_k * 1024)      # the VDC
        self.vdc_busy = 0                        # status reads busy after a data access (0: never)
        self.vdc_wait = 0
        self.vdc_lost = 0                        # data accesses made while busy
        self.vdc_naddr = 0                       # R18 writes (an update address set)
        self.vdc_nbytes = 0                      # R31 writes (bytes written)
        self.vdc_nblocks = 0                     # R30 writes (block fills and copies)
        self.vdc_nregs = 0                       # every register write, data and these
        self.on_irq = None                       # called with the C128 at each IRQ (a check's log)
        self.traps8502 = {}                      # 8502 address -> called with the C128 there
        self.vdc = bytearray(64)
        self.vdc[20] = 0x08                      # R20: the attributes at $0800, as the kernal sets them
        self.vdc_sel = 0
        self.vdc_addr = 0
        self.vdc_src = 0
        self.vdc_last = 0
        self.channels, self.cin, self.cout, self.name, self.lfs, self.st = {}, None, None, b"", (0, 0, 0), 0
        self.printed = ""                        # what CHROUT put on the screen
        self.data_bank, self.name_bank = 0, 0    # SETBNK
        self.msgflag = 0x80                      # SETMSG (the kernal's messages: on, as in direct mode)
        self.tod_c0 = 0.0                        # CIA 1's clock: when its tenths were written
        self.port8502 = bytearray(2)             # the 8502's I/O port, $00 and $01 whatever the MMU says
        self.fnrom = None                        # a function ROM's 32K, $8000-$FFFF: external (a
        self.fnrom_ext = True                    # cartridge, $FF00's bits 10) or internal (01)
        self.cia_ddr = False                     # CIA 1's data directions ($DC02, $DC03) count:
                                                 # port A drives only its output lines (the others float
                                                 # high), port B's outputs read back their latch
        self.joy1 = 0                            # joystick 1's lines held low on port B, whatever
                                                 # the column: $10 fire, $04 left (as CTRL)
        self.irq8502 = False                     # the 8502's IRQ line held low (the VIC's, not
        self.irqs8502 = 0                        # acknowledged): taken while I is clear, counted
        self.nmi8502 = False                     # RESTORE: an NMI edge the 8502 has latched,
                                                 # taken before its next instruction; while the Z80 runs, at the
                                                 # first once the Z80 hands back (the 8502 stopped holds it)
        self.nmis8502 = []                       # (pc, S, $FF00, the page pointers) at each NMI taken
        self.rom_reads = []                      # (pc, address): the 8502's reads where $FF00 has a ROM
        self.on_vdc8502 = None                   # called (m, register, value, VDC address) for each data write the 8502 makes
        self.writes1 = None                      # a set: the bank 1 addresses the 8502 writes go into it
        self.absent_t = 0                        # T-states each command the 8502 serves takes (the Z80 stopped):
                                                 # the clock, the VDC's frame and the CIA's timers go on meanwhile

    # ---- memory
    def poke(self, addr, data, bank=0):
        """Put bytes into a bank's memory; common RAM goes into both."""
        data = bytes(data)
        for b, mem in ((0, self.bank0), (1, self.bank1)):
            for i, v in enumerate(data):
                a = addr + i
                if b == bank or a >= COMMON:
                    mem[a] = v

    def peek16(self, a):
        return self.bank1[a] | self.bank1[a + 1] << 8

    def _bank(self, n):
        return self.bank1 if n == 1 else self.bank0   # (a 128K C128 has two)

    # ---- the CPU switch
    def _switch(self, v):
        """A write to $D505, by either CPU; takes effect after it."""
        self.mmu[5] = v
        if v & 1:                                # the Z80 hands over to the 8502
            if self.z80_on:
                self.z80_on = False
                self.bank0[COMMON:] = self.bank1[COMMON:]
                self.cr = self.bank1[CR]             # as the Z80 stored it
                self.run_8502()
                if not self.z80_on:              # it didn't start the Z80 again: stop after the OUT
                    self.z.ticks_to_stop = 1
        elif not self.z80_on:                    # the 8502 hands over to the Z80
            self.z80_on = True
            self.bank0[CR] = self.cr
            self.bank1[COMMON:] = self.bank0[COMMON:]
            if self.z80_started and self.absent_t:
                self._absent(self.absent_t)
            if not self.z80_started:
                self.z80_started = True
                z = self.z
                z.pc, z.halted, z.iff1, z.iff2 = Z80_START, False, False, False

    def _absent(self, t):
        """t T-states pass while the 8502 has the machine: frames, the
        raster compare, the VDC's frame and CIA 2's timers go on (they
        follow the clock), but no IRQ is taken (the Z80 has the VIC's off)."""
        self.t += t
        self._t0 += t                            # (inside the Z80's run: now_t follows)
        while self.next_frame <= self.t:
            self.next_frame += FRAME_T
            self.nframes += 1
        if self.timed and self.next_irq_t != float("inf"):
            self.next_irq_t = self._next_cmp(self.t)

    # ---- the Z80's ports
    def z_in(self, port):
        """IN: the byte the Z80 reads at BC = port."""
        if 0xD000 <= port <= 0xDFFF:
            return self.io_read(port, self.z.pc)
        return self.bank1[port]

    out_guard = None                             # (lo, hi): OUTs there don't reach RAM (logged in .out_guarded)

    def z_out(self, port, v):
        """OUT: the Z80 writes v at BC = port."""
        if 0xD000 <= port <= 0xDFFF:
            self.io_write(port, v, self.z.pc)
        elif self.out_guard and self.out_guard[0] <= port < self.out_guard[1]:
            self.out_guarded = getattr(self, "out_guarded", 0) + 1
        else:
            self.bank1[port] = v

    def io_read(self, port, pc):
        """The I/O chips at $D000-$DFFF, for either CPU (pc: who, for stray_io)."""
        hi = port >> 8
        if self.timed and self._in_run:
            self._io_t += IO_EXTRA_T
        if 0xD000 <= port <= 0xD02F:
            return self._vic_read(port & 0x3F)
        if 0xDC00 <= port <= 0xDC0F:
            return self._cia_read(port & 0x0F)
        if 0xDD00 <= port <= 0xDD0F:
            if self.timed and 0xDD04 <= port <= 0xDD07:
                return self._tnow(port >> 1 & 1) >> (8 if port & 1 else 0) & 0xFF
            if self.timed and port == 0xDD0D:
                return self._icr_read()
            return self.cia2[port & 0x0F]
        if 0xD800 <= port <= 0xDBFF:
            return self.colour[port & 0x3FF] | 0xF0
        if port == 0xD500:
            return self.cr
        if port == SWITCH:
            return self.mmu[5] & 0x7F | (0 if self.key4080_down else 0x80)
        if 0xD500 <= port <= 0xD50B:
            return self.mmu[port & 0x0F]
        if port in (0xD600, 0xD601):
            return self._vdc_read(port)
        if 0xDF00 <= port <= 0xDF0A:
            return 0xFF
        if hi == 0xDF:
            return 0x00
        self.stray_io.append(("IN", pc, port))
        return 0xFF

    def io_write(self, port, v, pc):
        hi = port >> 8
        if self.timed and self._in_run:
            self._io_t += IO_EXTRA_T
        if 0xD000 <= port <= 0xD02F:
            self._vic_write(port & 0x3F, v)
        elif 0xDC00 <= port <= 0xDC0F:
            self.cia[port & 0x0F] = v
            if port == 0xDC08:                   # (the clock goes from 0, the tenths written)
                self.tod_c0 = self.now_c()
            if port == 0xDC00:
                self.pa = v
            if self.cia_ddr and port in (0xDC00, 0xDC02):
                self.pa = self.cia[0] | ~self.cia[2] & 0xFF
        elif 0xDD00 <= port <= 0xDD0F:
            if self.timed and port in (0xDD0E, 0xDD0F):  # timer A/B: started, stopped (force load)
                i = port & 1
                self._icr_update()
                self._t_base[i] = (self.now_c(), self._latch(i) if v & 0x10 else self._tnow(i))
                self._t_run[i] = bool(v & 1)
                v &= 0xEF
            elif self.timed and port == 0xDD0D:        # the interrupt mask: bit 7 sets, else clears
                self._icr_update()
                self._icr_mask = self._icr_mask | v & 0x1F if v & 0x80 else self._icr_mask & ~v & 0x1F
                return
            self.cia2[port & 0x0F] = v
        elif 0xD800 <= port <= 0xDBFF:
            self.colour[port & 0x3FF] = v & 0x0F
        elif port == 0xD500:
            self.set_cr(v)
        elif port == SWITCH:
            self._switch(v)
        elif 0xD500 <= port <= 0xD50B:
            self.mmu[port & 0x0F] = v
        elif port in (0xD600, 0xD601):
            self._vdc_write(port, v)
        elif hi == 0xDF:
            pass
        else:
            self.stray_io.append(("OUT", pc, port, v))

    # ---- the 8502's view of memory (see the top)
    def set_cr(self, v):
        self.cr = self.bank0[CR] = v

    def rom8502(self, a):
        """$FF00 puts a ROM at a for the 8502's reads (bit 1: BASIC's low
        $4000-$7FFF, bits 2-3: $8000-$BFFF, bits 4-5: $C000-$FFFF, the
        kernal; set: RAM). The model has no ROMs: such a read gets a byte
        of no use (and goes into rom_reads); writes go to the RAM below."""
        cr = self.cr
        if 0x4000 <= a < 0x8000:
            return not cr & 2
        if 0x8000 <= a < 0xC000:
            return cr >> 2 & 3 != 3
        if a >= 0xC000 and not (0xD000 <= a < 0xE000 and not cr & 1) and not 0xFF00 <= a <= 0xFF04:
            return cr >> 4 & 3 != 3
        return False

    def fnrom_byte(self, a):
        """The function ROM's byte at a, where rom8502 has a ROM, if $FF00
        brings fnrom in there; else None."""
        if self.fnrom is None or a < 0x8000:
            return None
        if self.cr >> (2 if a < 0xC000 else 4) & 3 != (2 if self.fnrom_ext else 1):
            return None
        return self.fnrom[a - 0x8000]

    def phys8502(self, a):
        """(bank, address) the 8502 reaches at a, or None for I/O ($FF00 is
        dealt with by Bus8502)."""
        if a < 0x200:                            # the page pointers
            p = 7 if a < 0x100 else 9
            return self.mmu[p + 1] & 1, self.mmu[p] << 8 | a & 0xFF
        if a >= COMMON:
            return 0, a
        if 0xD000 <= a <= 0xDFFF and not self.cr & 1:
            return None
        if self.mmu[6] & 4 and a < (0x400, 0x1000, 0x2000, 0x4000)[self.mmu[6] & 3]:
            return 0, a                          # common RAM at the bottom
        return (1 if self.cr & 0x40 else 0), a

    # ---- the VIC and CIA 1
    def _vic_read(self, r):
        if r == 0x11:                            # bit 7 reads as the line's bit 8
            return self.vic[0x11] & 0x7F | (0x80 if self.line() > 255 else 0)
        if r == 0x12:
            return self.line() & 0xFF
        if r == 0x19:
            on = self.latch & self.enable & 0x0F
            return 0x70 | (0x80 if on else 0) | self.latch
        if r == 0x1A:
            return 0xF0 | self.enable
        if r == 0x2F:
            return 0xF8 | self.k2f & 7
        return self.vic[r] if r < 0x30 else 0xFF

    def _vic_write(self, r, v):
        if r == 0x19:
            self.latch &= ~v & 0xFF
        elif r == 0x1A:
            self.enable = v & 0x0F
        elif r == 0x2F:
            self.k2f = v | 0xF8
        elif r < 0x30:
            self.vic[r] = v
            if self.timed and r in (0x11, 0x12):
                self.next_irq_t = self._next_cmp(self.now_t() + 1)

    def _cia_read(self, r):
        if r == 0:                               # port A: simulate.py's
            return porta_read(self)
        if r == 1:
            v = self._kbd() & ~self.joy1
            if self.cia_ddr:
                return v & ~self.cia[3] | self.cia[1] & self.cia[3]
            return v
        if 8 <= r <= 11:                         # the clock (TOD): tenths since its tenths were
            n = int((self.now_c() - self.tod_c0) * 10 / 985248)   # written, by the model's time (the
            t, sec = n % 10, n // 10             # 8502's own takes none: absent_t's only)
            v = (t, sec % 60, sec // 60 % 60, sec // 3600)[r - 8]
            return v if r == 8 else v // 10 << 4 | v % 10
        return self.cia[r]

    def _kbd(self):
        """Port B: simulate.py's matrix, plus the columns $D02F selects (8-10)."""
        return matrix_read(self, {8 + b for b in range(3) if not (self.k2f >> b) & 1})

    # ---- the VDC: R18/R19 the address, R31 data (the address goes up after
    # each access), R30 a block fill or copy (R24 bit 7: copy from R32/R33),
    # the status always ready (timed: busy for the operation's VDC_BLK_*).
    # A count of 0 in R30 is taken as 256 (a guess).
    def _vdc_timed_access(self, kind):
        """(timed) A data access now: True if the VDC takes it."""
        c = self.now_c()
        self.vdc_nblkbusy += c < self.vdc_blk_until
        pos = self.vdc_pos(c)
        ok = c >= self.vdc_ready_at
        if ok:
            reg = kind in ("w18", "w19")
            self.vdc_ready_at = self._vdc_serve(c, VDC_REG_SLOTS if reg else 1, VDC_REG_LAT if reg else 0.0)
        else:
            self.vdc_lost += 1
            self.vdc_nlost_blank += pos < VDC_BLANK
        if self.on_vdc:
            self.on_vdc(self, kind, c, pos, ok)
        return ok

    def _vdc_read(self, port):
        timed = self.timed
        if not self.z80_on:                      # (the 8502: it has no time of its own here)
            self.timed = False
        try:
            return self._vdc_read_z(port)
        finally:
            self.timed = timed

    def _vdc_read_z(self, port):
        if self.timed and port == 0xD600:
            c = self.now_c()
            return (VDC_READY if c >= self.vdc_ready_at else 0) | (VDC_VBLANK if self.vdc_pos(c) < VDC_BLANK else 0)
        if self.timed:
            if not self._vdc_timed_access("r"):
                return 0xFF
        elif port == 0xD600:
            if self.vdc_wait:
                self.vdc_wait -= 1
                return 0
            return VDC_READY
        if not self.timed:
            if self.vdc_wait:
                self.vdc_lost += 1
            self.vdc_wait = self.vdc_busy
        r = self.vdc_sel
        if r == 31:
            v = self.vram[self.vdc_addr % len(self.vram)]
            self.vdc_addr = (self.vdc_addr + 1) & 0xFFFF
            return v
        if r == 18:
            return self.vdc_addr >> 8
        if r == 19:
            return self.vdc_addr & 0xFF
        if r == 32:
            return self.vdc_src >> 8
        if r == 33:
            return self.vdc_src & 0xFF
        return self.vdc[r]

    def _vdc_write(self, port, v):
        timed = self.timed
        if not self.z80_on:                      # (the 8502, see _vdc_read)
            self.timed = False
            if self.on_vdc8502 and port == 0xD601:
                self.on_vdc8502(self, self.vdc_sel, v, self.vdc_addr)
        try:
            self._vdc_write_z(port, v)
        finally:
            self.timed = timed

    def _vdc_write_z(self, port, v):
        if port == 0xD600:
            if self.timed and self.now_c() < self.vdc_ready_at:
                self.vdc_nselbusy += 1
            if self.timed and self.now_c() < self.vdc_blk_until:
                self.vdc_nblkbusy += 1
            self.vdc_sel = v & 0x3F
            return
        if self.timed:
            if not self._vdc_timed_access("w%d" % self.vdc_sel):
                return
        else:
            if self.vdc_wait:
                self.vdc_lost += 1
                return
            self.vdc_wait = self.vdc_busy
        r, n = self.vdc_sel, len(self.vram)
        self.vdc_nregs += 1
        self.vdc_naddr += r == 18
        self.vdc_nbytes += r == 31
        self.vdc_nblocks += r == 30
        if r == 31:
            self.vram[self.vdc_addr % n] = self.vdc_last = v
            self.vdc_addr = (self.vdc_addr + 1) & 0xFFFF
        elif r == 18:
            self.vdc_addr = v << 8 | self.vdc_addr & 0xFF
        elif r == 19:
            self.vdc_addr = self.vdc_addr & 0xFF00 | v
        elif r == 32:
            self.vdc_src = v << 8 | self.vdc_src & 0xFF
        elif r == 33:
            self.vdc_src = self.vdc_src & 0xFF00 | v
        elif r == 30:
            copy = self.vdc[24] & 0x80
            count = max(0, (v or VDC_BLK_ZERO) + (VDC_BLK_COPYX if copy else VDC_BLK_FILLX))
            for i in range(count):
                a = (self.vdc_addr + i) & 0xFFFF
                if copy:
                    self.vram[a % n] = self.vdc_last = self.vram[(self.vdc_src + i) % n]
                else:
                    self.vram[a % n] = self.vdc_last
            self.vdc_addr = (self.vdc_addr + count) & 0xFFFF
            if copy:
                self.vdc_src = (self.vdc_src + count) & 0xFFFF
            if self.timed:                       # busy until the last byte is done (at once in memory here)
                c = self.now_c()
                self.vdc_blk_until = self._vdc_block_end(c, count, copy)
                self.vdc_ready_at = max(self.vdc_ready_at, self.vdc_blk_until)
                if self.on_blk:
                    self.on_blk(self, c, self.vdc_blk_until, bool(copy), count)
        else:
            self.vdc[r] = v

    def vdc_raw(self, addr, n):
        """n bytes of the VDC's video RAM."""
        return bytes(self.vram[(addr + i) % len(self.vram)] for i in range(n))

    def vdc_shown(self, addr, n):
        """n bytes of the screen the VDC shows: addr $0000-$07CF
        its characters (from R12/R13), $0800 on its attributes (R20/R21).
        $0000 and $0800 but while the monitor's screen is up (z80/monvdc.inc:
        $1000, $1800)."""
        v = self.vdc
        base = (v[20] << 8 | v[21]) - 0x800 if addr >= 0x800 else v[12] << 8 | v[13]
        return self.vdc_raw(base + addr, n)

    def vdc_text(self, row, col, n):
        """n cells of the 80x25 VDC screen as it is shown (vdc_shown:
        characters at $0000, attributes at $0800, but while the monitor's
        screen is up) as text. Character set 0 (attribute bit 7 clear) is the
        ZX81's, double width: a left half (code z, bit 6 clear) shows as
        ZX81 character z and its right half (z | $40) is skipped, so the
        string is shorter than n; a right half with no left shows as '~'. Set 1 (bit 7 set): codes 0-127 are half-width ZX81 characters
        ((z & $3F) | (z & $80) >> 1), 128-223 ASCII $20-$7F; 224-255 show
        as '~'. ZX81 characters come from simulate.py's ZX table, inverse
        ones in lower case (so a lower-case ASCII letter from set 1 is
        not told from one: look at vdc_raw for that)."""
        out, i = [], 0
        while i < n:
            a = row * 80 + col + i
            code, attr = self.vdc_shown(a, 1)[0], self.vdc_shown(0x0800 + a, 1)[0]
            if attr & 0x80:
                if code < 128:
                    z = code & 0x3F | (code & 0x40) << 1
                    out.append(ZX[z & 0x3F].lower() if z & 0x80 else ZX[z])
                elif code < 224:
                    out.append(chr(code - 128 + 0x20))
                else:
                    out.append("~")
            elif code & 0x40:
                out.append("~")
            else:
                z = code
                out.append(ZX[z & 0x3F].lower() if z & 0x80 else ZX[z])
                i += 1                           # the right half
            i += 1
        return "".join(out)

    # ---- the 8502 and its kernal
    def start_8502(self, pc, sp=0xFF):
        """Run 8502 code at pc until it starts the Z80 (it stores $B0 to
        $D505 and carries on after the store once the Z80 hands back) or
        ends in JMP * (an idle loop)."""
        self.cpu.pc, self.cpu.sp = pc, sp
        self.z80_on = False
        self.run_8502()

    def run_8502(self, limit=20_000_000):
        """Step the 8502 from where it is: until it starts the Z80, or sits
        in JMP * (another store of $B0 after the Z80 hands back is the
        same thing again). A kernal call is done at its entry point."""
        cpu = self.cpu
        for _ in range(limit):
            if self.z80_on:
                return
            pc = cpu.pc
            if pc in self.traps8502:
                self.traps8502[pc](self)
                continue
            if not self._step8502() and cpu.pc == pc and self.bank0[pc] == 0x4C:   # JMP *
                return
        raise AssertionError(f"the 8502 never stopped (pc ${cpu.pc:04X})")

    def _step8502(self):
        """An instruction, or a kernal call done at its entry point (True):
        not where $FF00 has the function ROM instead of the kernal (its
        unpacker runs there)."""
        cpu = self.cpu
        if cpu.pc not in KERNAL128 or self.fnrom_byte(cpu.pc) is not None:
            if self.nmi8502:
                self.nmi8502 = False
                self.nmis8502.append((cpu.pc, cpu.sp, self.cr, bytes(self.mmu[7:11])))
                cpu.nmi()                        # (into whatever the page pointers make page 1)
            if self.irq8502 and not cpu.p & cpu.INTERRUPT:
                cpu.irq()
                self.irqs8502 += 1
            cpu.step()
            return False
        getattr(self, "k_" + KERNAL128[cpu.pc])()
        lo = self.bank0[0x100 + ((cpu.sp + 1) & 0xFF)]
        hi = self.bank0[0x100 + ((cpu.sp + 2) & 0xFF)]
        cpu.sp = (cpu.sp + 2) & 0xFF
        cpu.pc = ((hi << 8) | lo) + 1
        return True

    def _jsr8502(self, addr, limit=200_000):
        """The 8502 subroutine at addr, called from a kernal trap (as the
        kernal's LOAD calls STOP); returns its Z flag. Its stack is page 1
        (bank 0's: the page pointers there while the 8502 runs)."""
        cpu, back = self.cpu, 0x0002             # (a return address no code has)
        pc = cpu.pc
        self.bank0[0x100 + cpu.sp] = (back - 1) >> 8
        self.bank0[0x100 + ((cpu.sp - 1) & 0xFF)] = (back - 1) & 0xFF
        cpu.sp = (cpu.sp - 2) & 0xFF
        cpu.pc = addr
        for _ in range(limit):
            if cpu.pc == back:
                cpu.pc = pc
                return bool(cpu.p & cpu.ZERO)
            self._step8502()
        raise AssertionError(f"the 8502's ${addr:04X} never returned (pc ${cpu.pc:04X})")

    def k_ioinit(self):                          # IOINIT: CIA 1's keyboard ports as the C128's sets them
        self.io_write(0xDC00, 0x7F, self.cpu.pc)  # ($E109: port A out, $7F; port B in)
        self.io_write(0xDC02, 0xFF, self.cpu.pc)
        self.io_write(0xDC03, 0x00, self.cpu.pc)

    def k_ramtas(self):                          # RAMTAS: zero page cleared ($0002,Y for Y 0-255: to
        self.bank0[0x0002:0x0102] = bytes(0x100)  # $0101), as the C128's does ($E093)

    def k_setmsg(self):                          # A: the kernal's messages (bit 7 control, 6 errors)
        self.msgflag = self.cpu.a

    def k_setbnk(self):                          # A = data bank, X = file name bank
        self.data_bank, self.name_bank = self.cpu.a, self.cpu.x

    def k_setnam(self):
        a = self.cpu.x | self.cpu.y << 8
        self.name = bytes(self._bank(self.name_bank)[a:a + self.cpu.a])

    def k_load(self):
        """LOAD: A 0 = load (1 = verify), X/Y the address if the secondary
        address is 0, else the file's own. Returns X/Y = the end address,
        or carry and A = 4 for no such file. Into the SETBNK data bank."""
        cpu = self.cpu
        sa = self.lfs[2]
        if self.nodrive():
            return
        data = self.drive.open(self.name, 0).get("read")
        data = getattr(self.drive, "swapped", {}).get(self.name, data)   # (another disk since)
        if data is None or len(data) < 2:
            cpu.a = 4
            return self.carry(True)
        addr = (cpu.x | cpu.y << 8) if sa == 0 else data[0] | data[1] << 8
        body = data[2:]
        mem = self._bank(self.data_bank)
        if cpu.a == 1:                           # verify
            self.st = 0x40 | (0x10 if bytes(mem[addr:addr + len(body)]) != body else 0)
            end = addr + len(body)
        else:                                    # a block (a sector's 254 bytes, the first's 252) at a
            end, i, n = addr, 0, 252             # time, STOP called before each with EAL, but the last
            stop = self.bank0[ISTOP] | self.bank0[ISTOP + 1] << 8   # (the C128's burst LOAD: VICE showed
            bad = getattr(self.drive, "bad", {}).get(self.name)     # STOP's calls; the kernal's
            if bad is not None:                                     # $F468-$F47F: the last block unguarded)
                body = body[:max(0, bad - 2)]    # (the drive's read error there: what came before it)
            while i < len(body):
                if stop and i + n < len(data) - 2:
                    self.bank0[EAL], self.bank0[EAL + 1] = end & 0xFF, end >> 8
                    if self._jsr8502(stop):      # stopped: BREAK, nothing more
                        cpu.a, cpu.x, cpu.y, self.st = 0, 0, 0, 0
                        return self.carry(True)
                self.poke(end, body[i:i + n], self.data_bank)
                end += len(body[i:i + n])
                i, n = i + n, 254
            self.st = 0x40
            if bad is not None:
                self.st = 0x02
                self.drive.status = b"23,READ ERROR,18,01\r"
        cpu.x, cpu.y = end & 0xFF, end >> 8
        self.carry(False)

    def nodrive(self, bus=True):
        """No drive (drive.absent): what goes out on the bus finds
        none, the kernal's device not present (A 5, carry, ST bit 7). True
        then."""
        if not (bus and getattr(self.drive, "absent", False)):
            return False
        self.cpu.a, self.st = 5, 0x80
        self.carry(True)
        return True

    def k_chkin(self):
        if not self.nodrive(self.cpu.x in self.channels):
            Machine.k_chkin(self)

    def k_chkout(self):
        if not self.nodrive(self.cpu.x in self.channels):
            Machine.k_chkout(self)

    def k_open(self):
        """OPEN, as simulate.py's; the channel keeps the file's name (k_chrin's
        read errors). No drive: an OPEN with a name finds none (one without
        sends nothing: its CHKIN does)."""
        if self.nodrive(bool(self.name)):
            return
        Machine.k_open(self)
        ch = self.channels.get(self.lfs[0])
        if ch is not None:
            ch["file"] = self.name

    def k_chrin(self):
        """CHRIN, as simulate.py's; a read error (drive.bad: name -> where)
        there: a time-out, and the drive says so."""
        ch = self.channels.get(self.cin)
        bad = ch and getattr(self.drive, "bad", {}).get(ch.get("file"))
        if bad is not None and ch.get("read") and ch["pos"] >= bad:
            self.cpu.a, self.st = 0x0D, 0x02
            self.drive.status = b"23,READ ERROR,18,01\r"
            return self.carry(False)
        Machine.k_chrin(self)

    def k_save(self):
        """SAVE: A = zero-page pointer to the start address, X/Y = the end
        address + 1, out of the SETBNK data bank."""
        cpu = self.cpu
        zp = cpu.a
        start = self.bank0[zp] | self.bank0[zp + 1] << 8
        end = cpu.x | cpu.y << 8
        ch = self.drive.open(self.name, 1)
        ch["write"] += bytes([start & 0xFF, start >> 8]) + bytes(self._bank(self.data_bank)[start:end])
        self.drive.close(ch)
        self.carry(False)

    # ---- the Z80 running
    def step(self, ticks):
        """Run the Z80 for about ticks T-states (it stops short when it
        hands over to an 8502 that doesn't start it again), then the
        frame and its IRQ."""
        if not self.z80_on:
            return
        z = self.z
        if self.timed:
            if self.next_irq_t != float("inf"):
                ticks = max(1, min(ticks, int((self.next_irq_t - self.t) / (1 + CPU_SLOW)) + 1))
            if self.latch & self.enable & 1 and not z.iff1:
                ticks = min(ticks, 40)           # (an IRQ waiting: taken soon after EI)
        z.ticks_to_stop = ticks
        self._t0, self._ft0, self._in_run, self._io_t = self.t, z.frame_tick, True, 0
        z.run()
        self._in_run = False
        if self.timed:                           # exact: what ran (an instruction may go past)
            self.t += (z.frame_tick - self._ft0) % WRAP_T * (1 + CPU_SLOW) + self._io_t
        else:
            self.t += ticks - z.ticks_to_stop
        if self.z80_on and z.pc < COMMON and (self.bank1[CR] != Z80_CR or self.mmu[7:11] != Z80_PAGES):
            self.map_errors.append((z.pc, self.bank1[CR], bytes(self.mmu[7:11]).hex()))
        if self.t >= self.next_frame:
            self.next_frame += FRAME_T
            self.nframes += 1
            if not self.timed and not self.vic[0x11] & 0x80:   # raster line 250 (or 506, never)
                self.latch |= 1
        if self.timed:
            while self.t >= self.next_irq_t:     # the compare line's start
                self.latch |= 1
                self.next_irq_t = self._next_cmp(self.next_irq_t + 1)
        if self.latch & self.enable & 1 and z.iff1 and not z.int_disabled and self.z80_on:
            self.irq()                           # /INT stays low until acknowledged

    def irq(self):
        z = self.z
        sp = (z.sp - 2) & 0xFFFF
        z.memory[sp], z.memory[(sp + 1) & 0xFFFF] = z.pc & 0xFF, z.pc >> 8
        z.sp, z.pc = sp, 0x0038
        z.iff1 = z.iff2 = False
        self.irqs += 1
        if self.on_irq:
            self.on_irq(self)

    # ---- (timed) CIA 2's timers A and B, counting phi2 down, continuous
    # (the latches $DD04/5, $DD06/7); their counts read live. The interrupt
    # control register ($DD0D): each timer's underflow flag (bits 0, 1),
    # bit 7 if a flag is in the mask, cleared by the read; a flag in the
    # mask also counts in cia2_nmi (the 8502 would take an NMI: nothing
    # else is modelled of that)
    cia2_nmi = 0

    def _latch(self, i):
        return (self.cia2[5 + 2 * i] << 8 | self.cia2[4 + 2 * i]) or 0x10000

    def _tnow(self, i, c=None):
        c0, v0 = self._t_base[i]
        if not self._t_run[i]:
            return v0
        latch = self._latch(i)
        n = int((self.now_c() if c is None else c) - c0)
        if n <= v0:
            return v0 - n
        return latch - (n - v0 - 1) % (latch + 1)

    def _nunder(self, i, c):
        """Timer i's underflows from its start to cycle c."""
        c0, v0 = self._t_base[i]
        n = int(c - c0)
        return 0 if n <= v0 else 1 + (n - v0 - 1) // (self._latch(i) + 1)

    def _icr_update(self):
        c = self.now_c()
        for i in (0, 1):
            if self._t_run[i] and self._nunder(i, c) > self._nunder(i, max(self._icr_c[i], self._t_base[i][0])):
                if not self._icr & 1 << i and self._icr_mask & 1 << i:
                    self.cia2_nmi += 1
                self._icr |= 1 << i
            self._icr_c[i] = c

    def _icr_read(self):
        self._icr_update()
        v = self._icr | (0x80 if self._icr & self._icr_mask else 0)
        self._icr = 0
        return v

    def _tb_now(self):
        return self._tnow(1)

    # ---- the timed model's clock
    def now_t(self):
        """The Z80's T-states so far, live (inside a run too)."""
        if self._in_run:
            return self._t0 + (self.z.frame_tick - self._ft0) % WRAP_T * (1 + CPU_SLOW) + self._io_t
        return self.t

    def now_c(self):
        return self.now_t() / 2.0

    def vdc_pos(self, c=None):
        """Where the VDC is in its frame (cycles from its blank's start)."""
        return ((self.now_c() if c is None else c) + self.vdc_phase) % VDC_FRAME

    def line(self):
        t = self.now_t() if self.timed else self.t
        return int(t % FRAME_T // 126 + 250) % 312

    def _next_cmp(self, t):
        """The first T >= t where the raster compare line starts (inf: never)."""
        cmp_ = (self.vic[0x11] & 0x80) << 1 | self.vic[0x12]
        if cmp_ >= 312:
            return float("inf")
        off = ((cmp_ - 250) % 312) * 126
        c = t - t % FRAME_T + off
        return c if c >= t else c + FRAME_T

    def _vdc_serve(self, c, slots=1, lat=0.0):
        """A data access made at cycle c: the cycle the VDC is ready again.
        In its blank (and a little past: VDC_FAST) at once; in the display at
        the next free slot, one a line but on VDC_BLOCKED lines of each
        character row."""
        pos = self.vdc_pos(c)
        if pos < VDC_FAST:
            return c + VDC_FAST_BUSY
        want = pos + VDC_LAT + lat
        k = int((want - VDC_FAST) // VDC_LINE)
        while True:
            start = VDC_FAST + k * VDC_LINE
            if start >= VDC_FRAME:
                served = VDC_FRAME                # the next blank's start
                break
            slot = start + VDC_SLOT
            if k % VDC_ROWLINES not in VDC_BLOCKED and slot >= want:
                slots -= 1
                if not slots:
                    served = slot
                    break
            k += 1
        return c + (served - pos) + 1

    def _vdc_block_end(self, c, count, copy):
        """(timed) A block operation of count bytes from cycle c: when it is
        done, each byte VDC_BLK_* cycles, the blank's rate or the display's;
        begun in the display, VDC_BLK_DLAT's start on top (the blank's rate
        at least)."""
        rate = VDC_BLK_COPY if copy else VDC_BLK_FILL
        c0, pos = c, self.vdc_pos(c)
        for _ in range(count):
            c += rate[self.vdc_pos(c) >= VDC_BLANK]
        if pos >= VDC_BLANK:
            c = max(c0 + count * rate[0], c + VDC_BLK_DLAT[1 if copy else 0] + VDC_BLK_DLAT[2] * (pos - VDC_BLANK))
        return c

    def frames(self, n):
        """Let the Z80 run n frames (39,312 T each)."""
        if not self.z80_on:
            raise AssertionError("the Z80 isn't running (the 8502 has the machine)")
        end = self.nframes + n
        while self.nframes < end and self.z80_on:
            self.step(SLICE_T)

    def until(self, cond, frames, what):
        """Run the Z80 until cond() or frames have passed (AssertionError).
        Also an error if the Z80 isn't running, or hands over for good:
        no frames would pass, and this would wait for ever."""
        end = self.nframes + frames
        while self.nframes < end:
            if not self.z80_on:
                raise AssertionError(f"the Z80 isn't running (the 8502 has the machine) while waiting for {what}")
            self.step(SLICE_T)
            if cond():
                return
        raise AssertionError(f"no {what} after {frames} frames; screen:\n" + "\n".join(self.zx_screen()))

    # ---- the ZX81's keyboard and screen
    def press(self, *names, frames=900):
        """Hold the keys until the ROM takes them (it sets DEBOUNCE, $4027,
        to $FF), then let go until it has run down (0) for the next, and
        a scan has seen every key up (zx128's kpup: with the type-ahead on,
        DEBOUNCE is 0 at once, and a key pressed again before a scan saw
        it up is no new key to the queue)."""
        self.keys = {C128NAMES.get(n) or C64NAMES.get(n) or C64KEY[ZXKEY[n]] for n in names}
        self.until(lambda: self.bank1[0x4027] == 0xFF, frames, f"{'+'.join(names)} taken")
        self.keys = set()
        self.until(lambda: self.bank1[0x4027] == 0, frames, "the ROM ready for a key")
        kpup = keys_up_flag()
        if kpup is not None:
            self.until(lambda: self.bank1[kpup] == 1, frames, "every key seen up")

    def type(self, keys):
        """Type at the ZX81: space-separated keys, SHIFT+X for shifted ones
        (simulate.py's names: ZX81 keys, and the C64 ones it knows). Each
        waits for the ROM to take it; only usable once zx128 runs."""
        for k in keys.split():
            self.press(*k.split("+"))

    def zx_screen(self):
        """The ZX81's picture, decoded from D_FILE as the ROM has it in
        bank 1: 24 rows of text (inverse in lower case, trailing spaces
        off), a row for each line up to the next $76, as many as the
        display file has (a collapsed one has fewer; the rest are empty)."""
        a, end = self.peek16(0x400C) + 1, self.peek16(0x4010)   # D_FILE (a $76 first), VARS
        rows = []
        for _ in range(24):
            row = []
            while a < end and self.bank1[a] != 0x76:
                c = self.bank1[a]
                row.append(ZX[c & 0x3F].lower() if c & 0x80 else ZX[c & 0x3F])
                a += 1
            rows.append("".join(row).rstrip())
            a += 1
        return rows


def keys_up_flag():
    """zx128's kpup (romkbd.inc: 1 once a scan saw no key down), or None
    without a build."""
    try:
        return sym128()["kpup"]
    except (OSError, KeyError):
        return None


# ---- the checks: the model's own, then the ones added with @selfcheck
CHECKS = []


def selfcheck(fn):
    CHECKS.append(fn)
    return fn


@selfcheck
def model_vdc_autoinc():
    m = C128()
    for reg, v in ((0x12, 0x00), (0x13, 0x10)):          # R18 = $00, R19 = $10
        m.z_out(0xD600, reg)
        m.z_out(0xD601, v)
    m.z_out(0xD600, 0x1F)                                # R31, three times
    for v in (0xA1, 0xB2, 0xC3):
        m.z_out(0xD601, v)
    got = m.vdc_raw(0x10, 3)
    check("model_vdc_autoinc", got == bytes([0xA1, 0xB2, 0xC3]), got.hex())


@selfcheck
def model_in_mirror():
    m = C128()
    m.bank1[0x7FFE] = 0x5A
    got = (m.z_in(0x7FFE), m.z_in(0xDFFE))               # RAM; I/O 2, open bus
    check("model_in_mirror", got == (0x5A, 0x00), f"{got[0]:02X} {got[1]:02X}")


@selfcheck
def model_cpu_switch():
    m = C128()
    m.poke(0x0400, [0xA9, 0xB0,                          # lda #$B0
                    0x8D, 0x05, 0xD5,                    # sta $D505: starts the Z80
                    0xEA,                                # nop
                    0xA9, 0x5A,                          # lda #$5A
                    0x8D, 0x10, 0x03,                    # sta $0310: the marker
                    0x4C, 0x0B, 0x04])                   # jmp * (the one above)
    m.poke(0xFFEE, [0x01, 0x05, 0xD5,                    # ld bc,$D505
                    0x3E, 0xB1,                          # ld a,$B1
                    0xED, 0x79,                          # out (c),a: hand back
                    0x18, 0xFE])                         # jr $
    m.start_8502(0x0400)
    started = m.z80_on and m.bank0[0x0310] == 0          # the 8502 waits while the Z80 runs
    m.until(lambda: not m.z80_on, 1, "the Z80 to hand back")
    check("model_cpu_switch", started and m.bank0[0x0310] == 0x5A and m.z.pc == 0xFFF5,
          f"started {started}, marker ${m.bank0[0x0310]:02X}, Z80 at ${m.z.pc:04X}")


@selfcheck
def model_until_stopped():
    m = C128()
    m.poke(0x0400, [0x4C, 0x00, 0x04])                   # jmp * : the 8502 idle, the Z80 never started
    m.start_8502(0x0400)
    try:
        m.until(lambda: False, 5, "nothing")
        raised = False
    except AssertionError:
        raised = True
    # the Z80 handing over mid-wait: ld bc,$D505 / ld a,$B1 / out (c),a, then the 8502 idles
    m.poke(0xFFEE, [0x01, 0x05, 0xD5, 0x3E, 0xB1, 0xED, 0x79, 0x18, 0xFE])
    m.poke(0x0500, [0xA9, 0xB0, 0x8D, 0x05, 0xD5, 0xEA, 0x4C, 0x06, 0x05])
    m.start_8502(0x0500)
    try:
        m.until(lambda: False, 5, "nothing")
        raised2 = False
    except AssertionError:
        raised2 = True
    check("model_until_stopped", raised and raised2 and not m.z80_on, f"{raised} {raised2}")


@selfcheck
def model_vdc_text():
    m = C128()
    cells = []                                           # (code, attribute)

    def pair(z):                                         # set 0: a ZX81 character, double width
        return [(z, 0), (z | 0x40, 0)]
    cells += pair(0x2D)                                  # H
    cells += pair(0x26 | 0x80)                           # inverse A
    cells += [((0x2A & 0x3F) | (0x2A & 0x80) >> 1, 0x80)]                    # set 1: E
    cells += [((0x2D & 0x3F) | (0xAD & 0x80) >> 1, 0x80)]                    # set 1: inverse H
    cells += [(128 + ord("a") - 0x20, 0x80), (128 + ord("!") - 0x20, 0x80)]  # set 1: ASCII text
    cells += [(240, 0x80), (0x43, 0)]                    # a spare code; a right half on its own
    for i, (code, attr) in enumerate(cells):
        m.vram[5 * 80 + 3 + i], m.vram[0x0800 + 5 * 80 + 3 + i] = code, attr
    got = m.vdc_text(5, 3, len(cells))
    check("model_vdc_text", got == "HaEha!~~" and m.vdc_text(5, 4, 1) == "~",
          repr(got))


@selfcheck
def model_vdc_fill_copy():
    # The R30 count semantics: a fill writes R31's byte and R30 more, a copy
    # R30 (0: 256), give or take SIM128_BLK_FILLX / COPYX: the measured
    # 8563's.
    m = C128()

    def reg(r, v):
        m.z_out(0xD600, r)
        m.z_out(0xD601, v)
    reg(24, 0x00)                                        # fill
    reg(18, 0x01)
    reg(19, 0x00)
    reg(31, 0x41)                                        # one byte at $0100 ...
    reg(30, 9)                                           # ... and 9 more
    fill = m.vdc_raw(0x00FF, 12)
    reg(24, 0x80)                                        # copy
    reg(18, 0x02)
    reg(19, 0x00)                                        # to $0200
    reg(32, 0x01)
    reg(33, 0x02)                                        # from $0102
    reg(30, 5)
    copy = m.vdc_raw(0x01FF, 1) + m.vdc_raw(0x0200, 6)
    nf, nc = 10 + VDC_BLK_FILLX, 5 + VDC_BLK_COPYX
    check("model_vdc_fill_copy",
          fill == bytes([0]) + b"A" * nf + bytes(11 - nf) and copy == bytes([0]) + b"A" * nc + bytes(6 - nc),
          f"{fill.hex()} {copy.hex()}")


# ---- zx128 itself (build/obj/zx128.prg, made by make)
PRG = os.path.join(ROOT, "build", "obj", "zx128.prg")


US_CYCLE = 1e6 / 985248          # us a cycle (PAL phi2)
BUSY_US = 9000                  # the picture's share of a frame at most
QUIET_US = (5578, 5903)         # a still screen's pic_step, mean and most
ROW_CYC = 760                   # cycles an expanded row's compare takes in the
                                # sweep at most, nothing found (pic_t: ~720)
FIX_CYC = 700                   # a window frame's own before the sweep's rows,
                                # the hints' rows aside (pic_t: ~550)
HINT_CYC = 950                  # a hint's row (pic_try's way, nothing found;
                                # ~900)
RUN_CYC = 1600                  # a row's compare with a run of 32 copied and
                                # queued, at most (pic_t: ~1,450)
WR_CYC = 1150                   # a run of 32 written, with its own work (~1,140)


def rows_quiet():
    """Expanded rows the sweep compares in a quiet window frame at least:
    rows begin up to LIM_Q steps (256 cycles) after the rise, after the
    frame's own work and two hint rows (DF_CC's, or the editor's); the
    one begun last counts."""
    sym = sym128()
    return (sym["lim_q"] * 256 - FIX_CYC - 2 * HINT_CYC) // ROW_CYC + 1


def rows_busy():
    """Expanded rows, each with 32 characters to write, done in a busy
    window frame at least: LIM_B steps for their compares and copies and
    the writes of as many queued the frame before (in its window)."""
    sym = sym128()
    return (sym["lim_b"] * 256 - FIX_CYC - 2 * HINT_CYC) // (RUN_CYC + WR_CYC)


def zx128(down=True, frames=200, ntsc=False):
    """A C128 with zx128.prg where the boot sector's LOAD puts it (bank 0,
    its load address), started at boot128's entry, then frames frames
    (the ROM's K cursor comes after ~160: it builds its display in SLOW
    mode, with the picture's budget taken out of each frame). down: the
    40/80 key; ntsc: the VIC an NTSC one (ntsc_vic) from the start."""
    m = C128()
    m.key4080_down = down
    prg = open(PRG, "rb").read()
    load = prg[0] | prg[1] << 8
    watch_left(m)
    m.poke(load, prg[2:])
    if ntsc:
        ntsc_vic(m)
    m.start_8502(load)
    m.frames(frames)
    return m


NTSC_LINE_T = 130                               # an NTSC VIC: 65 cycles a line (2 T each), 263 lines
NTSC_LINES = 263


def ntsc_vic(m):
    """m's VIC timed as an NTSC one from now: its raster line (line():
    $D011 bit 7, $D012) and its compare (the raster flag) on 263 lines of
    130 T. Only the VIC: the model's frames stay PAL's. (For zx128vic's
    monitor, and SPEED for both builds.)"""
    def line():
        return int(m.now_t() // NTSC_LINE_T) % NTSC_LINES

    def next_cmp(t):
        cmp_ = (m.vic[0x11] & 0x80) << 1 | m.vic[0x12]
        if cmp_ >= NTSC_LINES:
            return float("inf")
        per = NTSC_LINES * NTSC_LINE_T
        c = t - t % per + cmp_ * NTSC_LINE_T
        return c if c >= t else c + per
    m.line, m._next_cmp = line, next_cmp
    m.next_irq_t = next_cmp(m.now_t() + 1)


LEFT_UPS = []                   # (pc, before, after): pic_left gone up where it mustn't
LEFT_STORES = [0]               # stores to pic_left seen
WINDOWS = [0]                   # windows opened (stores to lk_t0)


def watch_left(m):
    """Every store to the picture's budget left (vdcpic.inc's pic_left),
    as the Z80 makes it: it only goes down within a pic_step, but where a
    frame starts, where the sweep gets its share back (ps_sweep, ps_s0) and in
    pic_all (no budget). A store that takes it up anywhere else (an
    unchecked subtraction wrapping, say) goes into LEFT_UPS; zx128check
    fails a pic_ check that saw one. (The model's write callback stores
    the byte itself.)"""
    try:
        sym = sym128()
    except OSError:
        return
    left, t0 = sym["pic_left"], sym["lk_t0"]
    allowed = [(sym["pic_step"], sym["pic_step"] + 8), (sym["ps_s0"], sym["ps_sweep"]), (sym["ps_sweep"], sym["psw_go"]),
               (sym["pic_all"], sym["pa_ch"])]
    mem = m.z.memory

    def store(a, v):
        mem[a] = v if a != left else mem[a]
        if a == t0:                              # (a window opened: vdclock.inc's lk_t0)
            WINDOWS[0] += 1
            return
        before = mem[a]
        mem[a] = v
        LEFT_STORES[0] += 1
        pc = m.z.pc                              # (past the store)
        if v > before and not any(lo < pc <= hi for lo, hi in allowed):
            LEFT_UPS.append((pc, before, v))
    m.z.set_write_callback(store)
    m.z.mark_addr(left, m.z.WRITE_MARK)
    m.z.mark_addr(t0, m.z.WRITE_MARK)


def e_line(m):
    """The edit line's bytes, E_LINE up to its $76."""
    a = m.peek16(0x4014)
    end = bytes(m.bank1[a:a + 200]).index(0x76)
    return bytes(m.bank1[a:a + end])


def zx128check(fn):
    """A check that needs zx128.prg: FAIL, not a crash, without it (or with
    a build older than the check: a label, build.py function or tool
    missing).
    A pic_ check also fails if the budget left went up where it mustn't
    while it ran (watch_left)."""
    def run():
        del LEFT_UPS[:]
        try:
            fn()
        except (AssertionError, OSError, SystemExit, KeyError, AttributeError, ImportError) as e:
            check(fn.__name__, False, str(e).splitlines()[0] if str(e) else type(e).__name__)
        if fn.__name__.startswith("pic_"):
            LEFT_SEEN.append((fn.__name__, list(LEFT_UPS)))
            if LEFT_UPS:
                check(fn.__name__ + " (pic_left)", False, f"went up {LEFT_UPS[:3]} (pc past the store, before, after)")
    run.__name__ = fn.__name__
    return selfcheck(run)


LEFT_SEEN = []                  # (a pic_ check, what went up while it ran)


@zx128check
def boot_k_cursor():
    m = zx128()
    row = m.zx_screen()[23]
    check("boot_k_cursor", row.startswith("k"), repr(row))


@zx128check
def boot_sysvars():
    m = zx128()
    got = (m.peek16(0x4004), m.peek16(0x400C))           # RAMTOP, D_FILE
    check("boot_sysvars", got == (0x8000, 0x407D), " ".join(f"${v:04X}" for v in got))


@zx128check
def boot_clean():
    # nothing the model has no chip for was touched, the Z80 ran outside
    # common RAM only with $FF00 = $7F, and the VDC is laid out as boot128
    # says: screen $0000, attributes $0800, character sets $2000 and $3000,
    # the picture's attributes (rows 0-23, columns 0-63) in set 0, the rest
    # in set 1
    m = zx128()
    attr = m.vdc_raw(0x0800, 2000)
    layout = (m.vdc[12], m.vdc[13], m.vdc[20], m.vdc[21], m.vdc[28] & 0xE0)
    sets = all((attr[r * 80 + c] & 0x80 == 0) == (r < 24 and c < 64) for r in range(25) for c in range(80))
    check("boot_clean", not m.stray_io and not m.map_errors and layout == (0, 0, 8, 0, 0x20) and sets,
          f"stray {m.stray_io[:3]} map {m.map_errors[:3]} VDC {layout} sets {sets}")


@zx128check
def boot_4080_up():
    m = zx128(down=False)
    row = "".join(chr(c + 64) if 1 <= c <= 26 else chr(c) for c in m.bank0[0x0400:0x0400 + 40]).rstrip()
    check("boot_4080_up", row == "ZX128: THE 80-COLUMN SCREEN, PLEASE" and m.zx_screen()[23].startswith("k"),
          repr(row))


@zx128check
def kbd_types_print():
    m = zx128()
    m.type('P SHIFT+P H E L L O SHIFT+P NEWLINE')       # PRINT "HELLO"
    m.until(lambda: m.zx_screen()[0].startswith("HELLO"), 50, "HELLO")
    check("kbd_types_print", m.zx_screen()[0].startswith("HELLO"), repr(m.zx_screen()[0]))


@zx128check
def kbd_row_df_types():
    # Y U I O P: the row the Z80's IN can't read on a C128 (B = $DF is
    # I/O 2); KEYBOARD reads zx128's rows, so they type as on zx64
    keys = "Y U I O P"
    m = zx128()
    m.type(keys)
    got = e_line(m)
    z = Machine()
    z.boot()
    z.type(keys)
    a = z.peek16(0x4014)
    want = bytes(z.z.memory[a:a + bytes(z.z.memory[a:a + 200]).index(0x76)])
    check("kbd_row_df_types", got == want and all(c in got for c in (0x3A, 0x2E, 0x34, 0x35)),
          f"{got.hex()} (zx64: {want.hex()})")


@zx128check
def kbd_c128_cursor():
    # the top row's cursor keys: LEFT as SHIFT 5, RIGHT as SHIFT 8 (the
    # cursor in the edit line), UP as SHIFT 7, DOWN as SHIFT 6 (the
    # current line, E_PPC, in a program of two)
    m = zx128()
    m.type("P 1 2")
    end = e_line(m)
    m.type("LEFT")
    left = e_line(m)
    m.type("RIGHT")
    right = e_line(m)
    m.type("SHIFT+5")
    left5 = e_line(m)
    m.type("SHIFT+8 SHIFT+0 SHIFT+0 SHIFT+0 SHIFT+0")   # RUBOUT the line
    m.type("1 0 P NEWLINE 2 0 P NEWLINE")
    ppc = [m.peek16(0x400A)]
    for k in ("UP", "DOWN", "SHIFT+7", "SHIFT+6"):
        m.type(k)
        ppc.append(m.peek16(0x400A))
    check("kbd_c128_cursor", left != end and right == end and left5 == left and ppc == [20, 10, 20, 10, 20],
          f"{end.hex()} {left.hex()} {right.hex()} {left5.hex()} E_PPC {ppc}")


def tap(m, keys, frames=10):
    """keys down a while, then up as long: for a key the ROM takes nothing
    for (press would wait for ever)."""
    m.keys = set(keys)
    m.frames(frames)
    m.keys = set()
    m.frames(frames)


def keypad_zx(m):
    """10 PRINT 123+4.5-6 typed at the ZX81 by the main keys, then
    (the line deleted) again with the digits, + - . and NEWLINE on the
    C128's keypad (PRINT by P): the program after each (+ and - are the C64's keys, which type
    nothing on the ZX81: tapped). Then keypad 1 held with the stick (left:
    5 in 5678+0) and without: $F7FE, the IN copy of the 1-5 row, each
    time (k2scan leaves the keypad alone while the stick is held)."""
    def prog():
        return bytes(m.bank1[0x407D:m.peek16(0x400C)])

    def line(pad):
        for ch in "10P123+4.5-6\r":
            if ch in "+-":
                tap(m, {C128NAMES[KEYPAD[ch]] if pad else MPOS[ch]})
            elif ch == "P":
                m.press("P")
            else:
                m.press(KEYPAD[ch] if pad else "NEWLINE" if ch == "\r" else ch)
        return prog()
    main = line(False)
    m.type("1 0 NEWLINE")                                # (line 10 gone: the program empty again)
    gone = prog()
    pad = line(True)
    rows = {}
    for joy in ((), ("left",)):
        m.joy = set(joy)
        m.keys = {C128NAMES["KP1"]}
        m.frames(8)
        rows[joy] = m.bank1[0xF7FE]
        m.keys, m.joy = set(), set()
        m.frames(8)
    return dict(main=main, gone=gone, pad=pad, free=rows[()], stick=rows[("left",)], list=m.zx_screen()[0])


def keypad_zx_ok(st):
    return (st["pad"] == st["main"] and st["main"].startswith(b"\x00\x0a") and not st["gone"]
            and "PRINT 1234.56" in st["list"] and st["free"] & 0x1F == 0x1E and st["stick"] & 0x1F == 0x0F)


def keypad_zx_say(st):
    return (f"the program by the keypad {st['pad'].hex()}, by the main keys {st['main'].hex()} ({st['list']!r}: "
            f"+ and - type nothing, as the C64's); keypad 1: $F7FE ${st['free']:02X}, with the stick left "
            f"${st['stick']:02X}")


# A program's speed with a key held: SCROLL_LOOP, 10 lines, frames to its
# report. scan runs from the IRQ and from the ROM's KEYBOARD, so a held
# key's cost in k2scan is the program's. Each C128 key against the C64 key
# it stands for, held in the same run: RIGHT against CRSR RIGHT, keypad 8
# against 8. A build without the keypad: zx128 RIGHT 253 against 252
# (+0.4%), zx128vic 589 against 581 (+1.4%). Bounds: zx128's keypad pays
# for its voted column reads (k2scan.inc; 270 against 250, +8.0%),
# zx128vic's cache for nothing much.
HELD_PAIRS = (("RIGHT", "CRSRRIGHT"), ("KP8", "8"))
HELD_BOUND = {"zx128": dict(RIGHT=1.04, KP8=1.09), "zx128vic": dict(RIGHT=1.03, KP8=1.03)}


def held_frames(new, pos):
    """Frames from LOAD to the report (0/40) of SCROLL_LOOP with 10 lines,
    the key at pos held, on a machine from new()."""
    m = new()
    load_p(m, p_prog(SCROLL_LOOP.replace("TO 30", "TO 10")))
    m.keys = {pos}
    f0 = m.nframes
    m.until(lambda: zx_report(m) == "0/40", 3000, "the report")
    return m.nframes - f0


def held_check(name, who, new):
    got, ok = [], True
    for k, c in HELD_PAIRS:
        f, base = held_frames(new, C128NAMES[k]), held_frames(new, MPOS[c])
        bound = HELD_BOUND[who][k]
        ok = ok and f <= base * bound
        got.append(f"{k} held: {f} frames, {c} {base} ({100 * (f - base) / base:+.1f}%, bound "
                   f"{100 * (bound - 1):.0f}%)")
    check(name, ok, "; ".join(got))


# The cartridge's misreads (one CIA read in 211 wrong, $D0: simulate.py's
# cia_glitch) with keypad digits typed, 6 frames down, 6 up: none doubled
# or lost, none wrong. With one read a column zx128 types 3 more in 100.
def keypad_glitch(new, n=100):
    m = new()
    m.cia_glitch = True
    m.press("1")
    digits = ("8264" * n)[:n]
    for ch in digits:
        m.keys = {C128NAMES[KEYPAD[ch]]}
        m.frames(6)
        m.keys = set()
        m.frames(6)
    m.frames(20)
    got = "".join(ZX[c] if c < 0x40 else "?" for c in e_line(m) if c != 0x7F)
    return got, "1" + digits


# Each C128 key read into cmat as the C64 key it
# stands for (k2scan.inc: zx128's by kptab, zx128vic's in code)
K128AS = dict({f"KP{d}": str(d) for d in range(10)}, KPPLUS="+", KPMINUS="-", KPDOT=".", ENTER="RETURN",
              UP="UPARROW", DOWN="CRSRDOWN", LEFT="LEFTARROW", RIGHT="CRSRRIGHT")


def keypad_map(new):
    """Each of K128AS's keys held alone, then keypad 7 held and RIGHT for
    it at once (the same row, another column): cmat at the end of 4 frames
    after the first, each time, against the C64 key's. A frame can end
    inside scan, between its C64 columns and k2scan (cmat all up then), so
    each look is the key's or all up, and one at least the key's. Returns
    the keys that differed."""
    sym = sym128()
    m = new()
    bad = []

    def seen(name):
        col, row = MPOS[K128AS[name]]
        want = bytes(0xFF & ~(1 << row) if c == col else 0xFF for c in range(8))
        looks = set()
        m.frames(1)
        for _ in range(4):
            m.frames(1)
            looks.add(bytes(m.bank1[sym["cmat"]:sym["cmat"] + 8]))
        if want not in looks or looks - {want, b"\xff" * 8}:
            bad.append(f"{name} {sorted(x.hex() for x in looks)}")
    for name in K128AS:
        m.keys = {C128NAMES[name]}
        seen(name)
        m.keys = set()
        m.frames(4)
    m.keys = {C128NAMES["KP7"]}
    m.frames(4)
    m.keys = {C128NAMES["RIGHT"]}
    seen("RIGHT")
    m.keys = set()
    m.frames(4)
    return bad


@zx128check
def kbd_c128_map():
    # each keypad and cursor key into cmat as its C64 key (keypad_map)
    bad = keypad_map(zx128)
    check("kbd_c128_map", not bad, f"{len(K128AS)} keys and KP7 then RIGHT: "
          + (f"differ: {bad}" if bad else "each as its C64 key"))


@zx128check
def kbd_c128_held():
    # a key in K0-K2 held costs a program about what an arrow does without
    # the keypad (HELD_PAIRS): RIGHT and keypad 8
    held_check("kbd_c128_held", "zx128", zx128)


@zx128check
def kbd_c128_glitch():
    # keypad digits typed with the cartridge's misreads on
    # (keypad_glitch): the line as typed
    got, want = keypad_glitch(zx128)
    check("kbd_c128_glitch", got == want, f"{len(want) - 1} keypad digits, misreads on: "
          f"{'as typed' if got == want else f'{got!r}'}")


@zx128check
def kbd_c128_keypad():
    # the C128's numeric keypad at the ZX81 as the main keys
    # (k2scan.inc: K0-K2 into cmat by kptab): a line typed with it is the
    # line typed with them; not while the stick is held
    st = keypad_zx(zx128())
    check("kbd_c128_keypad", keypad_zx_ok(st), keypad_zx_say(st))


@zx128check
def kbd_lastk_race():
    # an IRQ just after keywait's kb_key has put a key from the type-ahead
    # in LAST_K (before the ROM decodes it): the IRQ's scan (no key down)
    # mustn't replace it (zx128.asm's kb_lkhold), or DECODE loops for ever
    # on $FFFF. Seen with the probe build's longer IRQ
    sym = sym128()
    m = zx128()
    k = sym["kb_key"]                                   # just past its LD (LAST_K),HL
    at = bytes(m.bank1[k:k + 16]).index(bytes([0x22, 0x25, 0x40])) + k + 3
    m.keys = keyset(["P"])
    n = 0
    while m.z.pc != at and n < 2_000_000:
        m.step(1)
        n += 1
    key = m.peek16(0x4025)
    m.keys = set()
    took = m.z.pc == at and m.z.iff1
    if took:
        m.bank1[sym["d1active"]] = 0                     # (the worst case: DISPLAY-1 not seen for a while)
        m.latch |= 1
        m.irq()                                          # the IRQ, there
    try:
        m.until(lambda: m.bank1[0x4027] == 0 and 0xF5 in e_line(m), 100, "PRINT in the edit line")
    except AssertionError:
        pass
    check("kbd_lastk_race", took and key != 0xFFFF and e_line(m) == bytes([0xF5, 0x7F]),
          f"IRQ just past the store (${at:04X}) {took}, LAST_K ${key:04X}, edit line {e_line(m).hex()}")


@zx128check
def io_server_answers():
    # LOAD hands over to the 8502 (call6510) and back: X isn't on the
    # disk, report D; then BASIC goes on
    m = zx128()
    m.type("J SHIFT+P X SHIFT+P NEWLINE")               # LOAD "X"
    m.until(lambda: m.zx_screen()[23].startswith("D/0"), 50, "report D")
    m.type("P 7 NEWLINE")
    m.until(lambda: m.zx_screen()[0] == "7", 50, "PRINT 7")
    check("io_server_answers", not m.map_errors, repr(m.zx_screen()[0]))


@zx128check
def nmi_while_z80():
    # RESTORE while the Z80 runs: the 8502, stopped,
    # holds the NMI and takes it at its first instruction once the Z80
    # hands back (LOAD), in tozx, its pages 0 and 1 still bank 1's: PC
    # and P go to bank 1's $01FD-$01FF, the ROM's. tozx puts them back
    # from ROM01 (nmi counted it) before the page pointers go back to
    # bank 0's
    m = zx128()
    before = bytes(m.bank1[0:0x200])
    m.nmi8502 = True
    m.type("J SHIFT+P X SHIFT+P NEWLINE")               # LOAD "X": report D
    m.until(lambda: m.zx_screen()[23].startswith("D/0"), 50, "report D")
    after = bytes(m.bank1[0:0x200])
    m.type("P 7 NEWLINE")
    m.until(lambda: m.zx_screen()[0] == "7", 50, "PRINT 7")
    sym, taken = sym8502(), m.nmis8502
    bad = [f"${a:04X}" for a in range(0x200) if after[a] != before[a]]
    check("nmi_while_z80", len(taken) == 1 and sym["tozx"] < taken[0][0] < sym["nmi"] and taken[0][1] == 0xFF
          and taken[0][3] == Z80_PAGES and not bad and not m.map_errors,
          f"NMI taken at {[(f'${pc:04X}', f'S ${sp:02X}', f'$FF00 ${cr:02X}', pp.hex()) for pc, sp, cr, pp in taken]};"
          f" bank 1's $0000-$01FF {'changed at ' + ' '.join(bad) if bad else 'as before'}")


D64 = os.path.join(ROOT, "build", "zx128.d64")
D64_TRACK = [21] * 17 + [19] * 7 + [18] * 6 + [17] * 5   # sectors a track (1541 layout)


def d64_at(t, s):
    """Track t sector s's offset in a d64 image."""
    return (sum(D64_TRACK[:t - 1]) + s) * 256


def d64_chain(d, t, s):
    """The sectors from t/s on, by each one's link."""
    out = []
    while t and (t, s) not in out:
        out.append((t, s))
        t, s = d[d64_at(t, s)], d[d64_at(t, s) + 1]
    return out


def d64_files(d):
    """A d64's directory: [(name, its first track and sector)] in its order
    (track 18 sector 0 is the BAM, the directory follows by the chain from
    18/1)."""
    out = []
    for t, s in d64_chain(d, 18, 1):
        for e in range(8):
            o = d64_at(t, s) + e * 32
            if d[o + 2] & 7:
                out.append((d[o + 5:o + 21].rstrip(b"\xa0"), (d[o + 3], d[o + 4])))
    return out


class Drive128(Drive):
    """The drive with build/zx128.d64's files (the d64 as the
    1571 has it, and its directory as it sends it: the header's name, ID
    and DOS type, and the BAM's blocks free, less what has been written
    since); absent: no drive on the bus (C128.nodrive)."""

    def __init__(self, path=D64):
        super().__init__()
        d = open(path, "rb").read()
        bam = d64_at(18, 0)
        self.head = (d[bam + 0x90:bam + 0xA0].replace(b"\xa0", b" "), d[bam + 0xA2:bam + 0xA4],
                     d[bam + 0xA5:bam + 0xA7])
        self.free0 = sum(d[bam + 4 * t] for t in range(1, 36) if t != 18)
        for name, (t, s) in d64_files(d):
            data = b""
            for tt, ss in d64_chain(d, t, s):
                o = d64_at(tt, ss)
                data += d[o + 2:o + 256] if d[o] else d[o + 2:o + d[o + 1] + 1]
            self.files[name] = data
        self.used0 = self.used()
        self.absent = False

    def used(self):
        return sum((len(f) + 253) // 254 for f in self.files.values())

    def directory(self):
        def line(blocks, text):
            return b"\x01\x01" + blocks.to_bytes(2, "little") + text + b"\0"
        name, did, dos = self.head
        d = b"\x01\x04" + line(0, b'\x12"' + name + b'" ' + did + b" " + dos)
        for name, data in self.files.items():
            n = (len(data) + 253) // 254
            d += line(n, b" " * (4 - len(str(n))) + b'"' + name + b'"' + b" " * (17 - len(name)) + b"PRG")
        free = max(0, self.free0 + self.used0 - self.used())    # a full disk shows 0 (the
        return d + line(free, b"BLOCKS FREE.") + b"\0\0"         # long $'s files, on a full one)


def dir_lines(drive):
    """The directory's lines as the monitor shows them: the blocks, a space,
    the text as ppet prints it (shifted space a space, control codes not)."""
    d, out, i = drive.directory(), [], 2
    while d[i] | d[i + 1]:
        end = d.index(0, i + 4)
        text = "".join(" " if c == 0xA0 else chr(c & 0x7F) for c in d[i + 4:end] if c == 0xA0 or c & 0x7F >= 0x20)
        out.append(f"{d[i + 2] | d[i + 3] << 8} {text}".rstrip())
        i = end + 1
    return out


@zx128check
def d64_boot_sector():
    # build/zx128.d64 (1541 layout: track 18 sector 0 is the BAM, its entry
    # for track 1 at offset 4, the directory follows by the chain from 18/1):
    # T1S0 is build.py's boot sector, marked used, no file's chain goes
    # through it, and the file ZX128 is in the directory
    import build
    d = open(D64, "rb").read()
    bam = d[d64_at(18, 0) + 4:d64_at(18, 0) + 8]
    chains = {name.decode("latin-1").upper(): d64_chain(d, t, s) for name, (t, s) in d64_files(d)}
    free = bin(bam[1] | bam[2] << 8 | bam[3] << 16).count("1")
    ok = (d[:256] == build.boot_sector(b"ZX128", 0x1300) and not bam[1] & 1 and bam[0] == free
          and "ZX128" in chains and not any((1, 0) in c for c in chains.values()))
    check("d64_boot_sector", ok, f"BAM track 1 {bam.hex(' ')} files {sorted(chains)}")


@zx128check
def hw128_macros():
    # z80/hw128.inc's macros: each keeps every register but A and F (HL
    # as given), and the VDC's wait for ready, with a VDC that is busy
    # after each access
    import build
    src = os.path.join(ROOT, "build", "obj", "hw128t.asm")
    keep = " push bc\n push de\n push hl\n"
    ops = [(" ld a,$05\n vic_wr $20", 0x9ABC), (" vic_rd $20\n ld ($7F00),a", 0x9ABC),
           (" ld a,$3C\n cia1_wr 2", 0x9ABC), (" cia1_rd 2\n ld ($7F01),a", 0x9ABC),
           (" ld a,$3F\n cia2_wr 2", 0x9ABC), (" cia2_rd3\n ld ($7F02),a", 0x9ABC),
           (" ld a,$07\n col_wr", 0xD805), (" kbd_all\n ld ($7F03),a", 0x9ABC),
           (" ld a,$1A\n vdc_wr 26", 0x9ABC), (" vdc_addr", 0x9ABC), (" ld a,$41\n vdc_put", 0x9ABC),
           (" ld a,$42\n vdc_put", 0x9ABC),
           (" ld bc,VDC\n ld a,$43\n vdc_bput\n cp $43\n jr nz,$\n ld bc,$1234", 0x9ABC)]
    body = "".join(f" ld bc,$1234\n ld de,$5678\n ld hl,${hl:04X}\n{op}\n{keep}" for op, hl in ops)
    open(src, "w").write(f' include "hw128.inc"\n org $8000\n ld sp,$7E00\n{body} halt\n end\n')
    build.assemble_z80(src, src[:-3] + "bin", src[:-3] + "lbl")
    m = C128()
    m.vdc_busy = 2
    m.cia2[0] = 0x5A                                     # cia2_rd3 reads port A
    m.keys = {C128NAMES["UP"]}                           # kbd_all sees K2's keys: row 3
    code = open(src[:-3] + "bin", "rb").read()
    m.bank1[0x8000:0x8000 + len(code)] = code
    m.z80_on = m.z80_started = True
    m.z.pc = 0x8000
    for _ in range(100):
        m.step(SLICE_T)
        if m.z.halted:
            break
    stack = bytes(m.bank1[0x7E00 - 6 * len(ops):0x7E00])
    want = b"".join(bytes([hl & 0xFF, hl >> 8]) + bytes.fromhex("78563412") for _, hl in reversed(ops))
    ok = (m.z.halted and stack == want and m.vic[0x20] == 5 and m.bank1[0x7F00] == 5
          and m.cia[2] == 0x3C and m.bank1[0x7F01] == 0x3C and m.cia2[2] == 0x3F and m.bank1[0x7F02] == 0x5A
          and m.colour[5] == 7 and m.bank1[0x7F03] == 0xF7 and m.k2f == 0xFF and m.vdc[26] == 0x1A
          and m.vdc_raw(0x9ABC % len(m.vram), 3) == b"ABC" and m.vdc_sel == 31 and m.vdc_lost == 0 and not m.stray_io)
    check("hw128_macros", ok, f"halted {m.z.halted} lost {m.vdc_lost} stack {stack == want} "
          f"rd3 ${m.bank1[0x7F02]:02X} col {m.colour[5]} all ${m.bank1[0x7F03]:02X} stray {m.stray_io[:2]}")


# ---- the picture: z80/vdcpic.inc
LBL = os.path.join(ROOT, "build", "obj", "zx128.lbl")


def sym128():
    """zx128's Z80 labels (build/obj/zx128.lbl), lower case."""
    import build
    return build.labels(LBL)


def sym8502():
    """boot128's labels (acme's symbol list), names as written."""
    import re
    text = open(os.path.join(ROOT, "build", "obj", "boot128.sym")).read()
    return {mm.group(1): int(mm.group(2), 16) for mm in re.finditer(r"^\s*(\w+)\s*=\s*\$([0-9a-fA-F]+)", text, re.M)}


def keyset(names):
    return {C128NAMES.get(n) or C64NAMES.get(n) or C64KEY[ZXKEY[n]] for n in names}


def load_p(m, data):
    """LOAD "P" with data (a .p file) as the file, at once: the 8502 is
    stopped at its server and the file put at $4009 in bank 1, as the
    server does (its checks, the bar, the drive: the disk's own checks),
    and the answer is ok. The
    program runs from its first line once loaded (zxbasic.py's .p files).
    Returns once the Z80 is back in the ROM: past LOAD's blit (the whole
    picture)."""
    sym, served = sym8502(), []

    def serve(m):
        m.poke(0x4009, data, bank=1)
        m.cpu.a = 0
        m.cpu.pc = sym["answer"]
        served.append(m.nframes)
    m.traps8502[sym["server"]] = serve
    m.type("J SHIFT+P P SHIFT+P")
    m.keys = keyset(["NEWLINE"])
    m.until(lambda: served, 100, "the LOAD")
    m.keys = set()
    del m.traps8502[sym["server"]]
    m.until(lambda: m.z.pc < 0x2000, 20, "the ROM after LOAD")


def vdc_codes(m):
    """The VDC's picture, rows 0-23 columns 0-63, as 24 rows of 32 ZX81
    codes: each a pair of set-0 cells, left z and right z | $40, or a
    space's (inverse space's) left twice; None where
    the cells are neither."""
    rows = []
    for r in range(24):
        cells = m.vdc_raw(r * 80, 64)
        row = []
        for c in range(32):
            left, right = cells[2 * c], cells[2 * c + 1]
            ok = not left & 0x40 and (right == left | 0x40 or (not left & 0x3F and right == left))
            row.append(left if ok else None)
        rows.append(row)
    return rows


def df_codes(m):
    """D_FILE as 24 rows of 32 codes, a collapsed row padded with spaces
    (as zx64's blit_c)."""
    a, end = m.peek16(0x400C) + 1, m.peek16(0x4010)
    rows = []
    for _ in range(24):
        row = []
        while a < end and m.bank1[a] != 0x76:
            if len(row) < 32:
                row.append(m.bank1[a])
            a += 1
        rows.append(row + [0] * (32 - len(row)))
        a += 1
    return rows


def shadow_codes(m):
    """The picture's shadow (z80/vdcpic.inc's SHADOW) as 24 rows of 32
    codes: what the VDC shows once the runs waiting are written."""
    a = sym128()["shadow"]
    return [list(m.bank1[a + (r >> 3) * 256 + (r & 7) * 32:a + (r >> 3) * 256 + (r & 7) * 32 + 32]) for r in range(24)]


def pic_same(m, rows=range(24)):
    v, d = vdc_codes(m), df_codes(m)
    return all(v[r] == d[r] for r in rows)


def pic_busy(m):
    """Every row of the picture's shadow (z80/vdcpic.inc's SHADOW) made
    unlike D_FILE ($FF is no ZX81 code): the sweep has every row to write
    again, ~17 frames, so what gets there sooner came by a hint."""
    a = sym128()["shadow"]
    m.bank1[a:a + 24 * 32] = b"\xff" * (24 * 32)


def pic_diff(m):
    """Where the VDC and D_FILE differ, for a FAIL's detail."""
    v, d = vdc_codes(m), df_codes(m)
    bad = [(r, c) for r in range(24) for c in range(32) if v[r][c] != d[r][c]]
    return f"{len(bad)} differ {bad[:4]}"


def frames_until(m, cond, frames, what):
    """Frames run until cond(): until's, counted."""
    f0 = m.nframes
    m.until(cond, frames, what)
    return m.nframes - f0


MVD_SLOTS = collections.Counter()  # pic_mvd from the IRQ in pic_t: irq_early's return 6 or 8 bytes up (None: neither)


def pic_t(m, frames, nowin=False):
    """The next frames pic_steps, each run an instruction at a time: [(its
    time in us on the C128, from the model's clock (the timed model's: the
    Z80 ~2% slower than 2 T a cycle, I/O's extra); the units it charged
    (pic_used))]. nowin: each as if its IRQ had found no window (pic_unp
    0: late, missed, or the lock searching)."""
    sym = sym128()
    ps, used = sym["pic_step"], sym["pic_used"]
    mvd, nirq, iret = sym["pic_mvd"], sym["pic_nirq"], sym["pic_iret"]
    z, out = m.z, []
    for _ in range(frames):
        while z.pc != ps:
            m.step(1)
        if nowin:
            z.memory[sym["pic_unp"]] = 0
        sp = z.sp
        ret = z.memory[sp] | z.memory[sp + 1] << 8
        t0 = m.now_t()
        while not (z.pc == ret and z.sp == sp + 2):
            if z.pc == mvd and not z.memory[nirq]:        # (pic_mvd_slots)
                MVD_SLOTS[next((o for o in (6, 8) if z.memory[z.sp + o] | z.memory[z.sp + o + 1] << 8 == iret),
                               None)] += 1
            m.step(1)
        out.append(((m.now_t() - t0) / 2 * US_CYCLE, m.bank1[used]))
    return out


def zx_report(m):
    """The report code on the ZX81's lower screen, '0/20', or None."""
    import re
    for r in m.zx_screen()[22:]:
        mm = re.match(r"^([0-9A-Z])/(\d+)", r)
        if mm:
            return mm.group(0)
    return None


def p_prog(text, blobs=None):
    from zxbasic import p_file
    return p_file(text, blobs=blobs)


@zx128check
def pic_k_cursor():
    # 30 frames after the K cursor is in D_FILE, it is on the VDC: the
    # inverse K, $B0, as its set-0 pair ($B0, $F0)
    m = zx128(frames=1)
    m.until(lambda: m.zx_screen()[23].startswith("k"), 400, "the K cursor in D_FILE")
    k = m.nframes
    m.frames(30)
    got = m.vdc_raw(23 * 80, 2)
    check("pic_k_cursor", got == bytes([0xB0, 0xF0]), f"{got.hex()} (the K in D_FILE at frame {k})")


@zx128check
def pic_fonts():
    # set 0 at $2000 and set 1 at $3000: 16 bytes a cell, the glyph
    # build.py made from the ROM's $1E00 in the first 8, then 0s
    import build
    rom = open(os.path.join(ROOT, "build", "obj", "zx128rom.bin"), "rb").read()
    font = build.font128(rom)
    m = zx128(frames=1)
    want = b"".join(font[8 * c:8 * c + 8] + bytes(8) for c in range(512))
    got = m.vdc_raw(0x2000, 0x2000)
    bad = [c for c in range(512) if got[16 * c:16 * c + 16] != want[16 * c:16 * c + 16]]
    k = font[8 * 0xB0:8 * 0xB0 + 8]                      # the inverse K's left half: its top row solid
    a = (font[8 * 0x26 + 1], font[8 * 0x66 + 1])           # A's second row, $3C, doubled: 0F F0
    check("pic_fonts", not bad and k[0] == 0xFF and a == (0x0F, 0xF0), f"cells wrong {bad[:4]} A {a}")


def typing_frames(m):
    """Types PRINT "HELLO" with the sweep made busy (pic_busy) as each key
    is taken: the frames from the ROM being back in its key wait (its
    echo done: a closing quote has it clear the edit line and print it
    again, over up to 3 frames of its own) until the lower screen is on
    the VDC, each key."""
    worst = []
    for k in "P SHIFT+P H E L L O SHIFT+P".split():
        m.keys = keyset(k.split("+"))
        m.until(lambda: m.bank1[0x4027] == 0xFF, 900, f"{k} taken")
        pic_busy(m)
        m.keys = set()
        m.until(lambda: m.bank1[0x4027] == 0, 900, "the ROM ready for a key")
        lower = range(24 - m.bank1[0x4022], 24)
        worst.append(frames_until(m, lambda: pic_same(m, lower), 20, f"{k} on the VDC"))
    return worst


@zx128check
def pic_typing_hint():
    # each key the editor takes is on the VDC (the lower screen equal to
    # D_FILE's) within 2 frames of the ROM having echoed it, with the
    # sweep busy (pic_busy) each time: the editor's hint
    m = zx128()
    worst = typing_frames(m)
    m.until(lambda: pic_same(m), 30, "the rest caught up")
    check("pic_typing_hint", max(worst) <= 2 and m.zx_screen()[23].startswith('PRINT "HELLO"'),
          f"frames {worst} {m.zx_screen()[23]!r}")


@zx128check
def pic_typing_1k():
    # in 1K, where the display is collapsed (its rows found back from
    # VARS, or the table carried over): each key typed with the sweep
    # busy (pic_busy as it is taken), the editor's rows on the VDC within
    # hint_bound_1k's frames of the ROM being ready for the next (not
    # before: what the ROM echoes comes over a few frames)
    m = zx128()
    to_1k(m)
    worst, bounds = [], []
    for k in "P SHIFT+P H E L L O SHIFT+P".split():
        m.keys = keyset(k.split("+"))
        m.until(lambda: m.bank1[0x4027] == 0xFF, 900, f"{k} taken")
        pic_busy(m)
        m.keys = set()
        m.until(lambda: m.bank1[0x4027] == 0, 900, "the ROM ready for a key")
        lower = range(24 - m.bank1[0x4022], 24)
        bounds.append(hint_bound_1k(m))
        worst.append(frames_until(m, lambda: pic_same(m, lower), bounds[-1], f"{k} on the VDC"))
        m.until(lambda: m.bank1[keys_up_flag()] == 1, 900, "every key seen up")
    collapsed = m.peek16(0x4010) - m.peek16(0x400C) != 24 * 33 + 1
    m.until(lambda: pic_same(m), 400, "the rest caught up")
    check("pic_typing_1k", collapsed and m.zx_screen()[23].startswith('PRINT "HELLO"'),
          f"frames {worst} (bound {max(bounds)}) {m.zx_screen()[23]!r}")


@zx128check
def pic_print_at():
    # with the sweep busy (pic_busy, after LOAD's whole picture) and just
    # past row 10 as it prints, a few frames later: DF_CC's hint
    m = zx128()
    load_p(m, p_prog('5 FOR I=1 TO 6\n6 NEXT I\n10 PRINT AT 10,5;"A"\n20 GOTO 20'))

    def a_there():
        return m.bank1[m.peek16(0x400C) + 1 + 33 * 10 + 5] == 0x26
    early = a_there()
    pic_busy(m)
    m.bank1[sym128()["pic_row"]] = 11
    m.until(a_there, 200, "the A in D_FILE")
    n = frames_until(m, lambda: m.vdc_text(10, 10, 2) == "A", 10, "the A on the VDC")
    check("pic_print_at", n <= 3 and not early, f"{n} frame(s) (printed before the sweep was busy: {early})")





def poke_bound():
    """pic_poke_shows' bound, from the clock: the POKE lands just past the
    sweep at worst, which goes round 24 rows at rows_quiet() a frame (the
    editor's hints are its 2 rows, besides); its run written in the next
    window if it was found past this one; and the frame it lands in."""
    return 1 + -(-24 // rows_quiet()) + 1


@zx128check
def pic_poke_shows():
    # an A POKEd into D_FILE shows within poke_bound() frames: as it
    # comes, and with the sweep put just past its row as it lands
    bound, got = poke_bound(), []
    for worst in (False, True):
        m = zx128()
        load_p(m, p_prog("10 POKE PEEK 16396+256*PEEK 16397+1+33*3+7,38"))
        m.until(lambda: m.bank1[m.peek16(0x400C) + 1 + 33 * 3 + 7] == 0x26, 200, "the A in D_FILE")
        if worst:
            sym = sym128()
            m.bank1[sym["pic_row"]], m.bank1[sym["pic_scol"]] = 4, 0
        got.append(frames_until(m, lambda: m.vdc_text(3, 14, 2) == "A", bound, "the A on the VDC"))
    check("pic_poke_shows", max(got) <= bound, f"{got[0]} frame(s), {got[1]} with the sweep just past it "
          f"(bound {bound})")


@zx128check
def pic_collapsed_1k():
    # F8 twice: 32K, then 1K (RAMTOP $4400), where the ROM keeps the
    # display collapsed: row 0 is X, then spaces, nothing of the next line
    m = zx128()
    to_1k(m)
    m.type("P SHIFT+P X SHIFT+P NEWLINE")
    m.until(lambda: m.zx_screen()[0] == "X", 100, "X in D_FILE")
    m.until(lambda: m.vdc_text(0, 0, 2) == "X" and pic_same(m), 30, "X on the VDC")
    collapsed = m.peek16(0x4010) - m.peek16(0x400C) != 24 * 33 + 1
    rest = m.vdc_text(0, 2, 62)
    check("pic_collapsed_1k", collapsed and rest == " " * 31, f"collapsed {collapsed} {rest!r}")


@zx128check
def pic_fast_holds():
    # FAST: while the program runs (no interrupts) the picture on the VDC
    # holds (its columns 0-63 of rows 0-24; the panel's row 23 says FAST
    # at once: panel_fastprog); at the key wait it catches up
    m = zx128()
    load_p(m, p_prog("10 FAST\n20 FOR I=1 TO 30\n30 PRINT AT 0,0;I\n40 NEXT I"))
    m.until(lambda: not m.bank1[0x403B] & 0x40, 100, "FAST")
    pic = lambda: [m.vdc_raw(r * 80, 64) for r in range(25)]
    snap, seen, held = pic(), set(), True
    for _ in range(20):
        m.frames(1)
        seen.add(m.zx_screen()[0])
        held = held and pic() == snap
    running = zx_report(m) is None
    m.until(lambda: zx_report(m) == "0/40", 1000, "the report")
    n = frames_until(m, lambda: pic_same(m), 30, "the picture caught up")
    check("pic_fast_holds", held and running and len(seen) >= 2, f"held {held} counts seen {len(seen)}; "
          f"caught up in {n} frame(s)")


# Every character of D_FILE inverted, again and again, for 200 frames:
#        ld d,200
# loop:  ld a,(FRAMES)  ld e,a      ; FRAMES now
#        ld hl,(D_FILE) ld c,24
# row:   inc hl         ld b,32     ; past the $76
# ch:    ld a,(hl)  xor $80  ld (hl),a  inc hl  djnz ch
#        dec c  jr nz,row
# wait:  ld a,(FRAMES)  cp e  jr z,wait   ; at least to the next frame
#        dec d  jr nz,loop  ret
INVERT = bytes([0x16, 200,
                0x3A, 0x34, 0x40, 0x5F,
                0x2A, 0x0C, 0x40, 0x0E, 24,
                0x23, 0x06, 32,
                0x7E, 0xEE, 0x80, 0x77, 0x23, 0x10, 0xF9,
                0x0D, 0x20, 0xF3,
                0x3A, 0x34, 0x40, 0xBB, 0x28, 0xFA,
                0x15, 0x20, 0xE1, 0xC9])


@zx128check
def pic_budget():
    # every character changing all the time: each VDC write made in the
    # window (pic_unp set) lands in the VDC's blank (status bit 5) and no
    # later than LK_WIN steps of 256 cycles after the rise (as the
    # window's clock sees it, ~40 cycles late at most), nothing written
    # while the VDC is busy (vdc_lost); then the picture is D_FILE's
    # within bound_16k's frames of the loop stopping
    sym = sym128()
    unp, lim = sym["pic_unp"], sym["lk_win"] * 256 + 40
    m = zx128()
    load_p(m, p_prog("10 REM {bin:inv}\n20 RAND USR 16514", {"inv": INVERT}))
    m.until(lambda: m.bank1[m.peek16(0x400C) + 1] & 0x80, 100, "the loop running")
    seen = []

    def on_vdc(m, kind, c, pos, ok):
        if kind[0] == "w" and m.bank1[unp]:              # (a block operation's registers too)
            seen.append(pos)
    m.on_vdc = on_vdc
    m.until(lambda: zx_report(m) == "0/20", 600, "the loop's end")
    m.on_vdc = None
    bound = bound_16k(m)
    n = frames_until(m, lambda: pic_same(m), bound, "the picture equal to D_FILE")
    out = [p for p in seen if p >= lim or p >= VDC_BLANK]
    global budget_seen
    budget_seen = (len(seen), max(seen), n, bound)
    check("pic_budget", len(seen) > 10000 and not out and not m.vdc_lost,
          f"{len(seen)} writes in windows, the latest {max(seen):.0f} cycles after the rise (LK_WIN's {lim - 40}, "
          f"bit 5 {VDC_BLANK}), {len(out)} past; equal {n} frame(s) after (bound {bound}); lost {m.vdc_lost}")


budget_seen = None


# Every other character of D_FILE (columns 0, 2, ... 30 of every row) one
# code on, every frame, 250 times: a row of 16 runs and 16 gaps, the
# dearest a row is to compare and copy (the 9 ms cap's worst):
#        ld d,250
# loop:  ld a,(FRAMES)  ld e,a
#        ld hl,(D_FILE) ld c,24
# row:   inc hl         ld b,16
# ch:    ld a,(hl)  add a,1  and $BF  ld (hl),a  inc hl  inc hl  djnz ch
#        dec c  jr nz,row
# wait:  ld a,(FRAMES)  cp e  jr z,wait
#        dec d  jr nz,loop  ret
ALTERNATE = bytes([0x16, 0xFA, 0x3A, 0x34, 0x40, 0x5F, 0x2A, 0x0C, 0x40, 0x0E, 0x18, 0x23, 0x06, 0x10, 0x7E, 0xC6,
                   0x01, 0xE6, 0xBF, 0x77, 0x23, 0x23, 0x10, 0xF6, 0x0D, 0x20, 0xF0, 0x3A, 0x34, 0x40, 0xBB, 0x28,
                   0xFA, 0x15, 0x20, 0xDE, 0xC9])


def bound_16k(m):
    """Frames within which an expanded display that doesn't change any
    more is on the VDC, from the clock: rows_busy() rows with their runs a
    frame (once much is found the frames are busy; a quiet one compares
    more), the sweep round once (24 rows and the one it is in), the last
    runs written in the next frame's window; and the frame it is now
    in."""
    return 1 + -(-25 // rows_busy()) + 1


def scatter_code():
    """z80/scatter.asm assembled: random characters into random cells of
    D_FILE, 20 a frame for 250 frames."""
    import build
    out = os.path.join(ROOT, "build", "obj", "scatter")
    build.assemble_z80(os.path.join(ROOT, "z80", "scatter.asm"), out + ".bin", out + ".lbl")
    return open(out + ".bin", "rb").read()


@zx128check
def pic_converges():
    # SCATTER for 250 frames, then quiet: the VDC is D_FILE's, from the
    # report on, within bound_16k's frames
    code = scatter_code()
    m = zx128()
    load_p(m, p_prog("10 REM {bin:scatter}\n20 RAND USR 16514", {"scatter": code}))
    m.frames(100)
    behind = len([1 for r, c in zip(vdc_codes(m), df_codes(m)) for a, b in zip(r, c) if a != b])
    m.until(lambda: zx_report(m) == "0/20", 400, "the report")
    bound = bound_16k(m)
    n = frames_until(m, lambda: pic_same(m), bound, "the picture equal to D_FILE")
    set_ = sum(c != 0 for row in df_codes(m)[:22] for c in row)
    check("pic_converges", set_ > 300, f"{set_} characters set ({behind} behind while it ran), "
          f"equal {n} frame(s) after the report (bound {bound})")


def onek_lines():
    """1K (collapsed), six lines of 31 characters printed by a program, then
    the editor."""
    m = zx128()
    to_1k(m)
    m.type("1 0 F I SHIFT+L 1 SHIFT+4 6 NEWLINE")      # 10 FOR I=1 TO 6
    m.type("2 0 P SHIFT+P " + " ".join("ABCDEFGHIJKLMNOPQRSTUVWXYZ01234") + " SHIFT+P NEWLINE")
    m.type("3 0 N I NEWLINE R NEWLINE")                 # 30 NEXT I, RUN
    m.until(lambda: zx_report(m) == "0/30", 600, "the report")
    return m


def to_1k(m):
    """F8 twice: 32K, then 1K (RAMTOP $4400), to the K cursor."""
    for top in (0xC000, 0x4400):
        m.keys = keyset(["LSHIFT", "F7"])
        m.frames(3)
        m.keys = set()
        m.until(lambda: m.peek16(0x4004) == top, 300, f"RAMTOP ${top:04X}")
        m.until(lambda: m.zx_screen()[23].startswith("k") and m.bank1[0x4027] == 0, 600, "the K cursor")


T_UNIT = 92                     # T-states a unit: 50 us at the C128's ~1.85 MHz
ZX_PTRS = (0x400E, 0x4010, 0x4012, 0x4014, 0x4016, 0x4018, 0x401A, 0x401C, 0x4029)


def df_lines(m):
    """Where a collapsed display's rows start (D_FILE + 1, then past each
    $76), and VARS last."""
    d, v = m.peek16(0x400C), m.peek16(0x4010)
    return [d + 1] + [a + 1 for a in range(d + 1, v) if m.bank1[a] == 0x76]


def df_shift(m, p, n):
    """Room for a byte at p (n = 1), or the byte at p taken out (n = -1),
    the system variables' pointers past it moved, as the ROM's MAKE-ROOM
    and RECLAIM do."""
    end = m.peek16(0x401C) + 1                           # STKEND
    b = m.bank1
    if n > 0:
        b[p + 1:end + 1] = bytes(b[p:end])
    else:
        b[p:end - 1] = bytes(b[p + 1:end])
    for a in ZX_PTRS:
        v = m.peek16(a)
        if v and v > p or (v == p and n > 0 and a != 0x400E):
            v += n
            b[a], b[a + 1] = v & 0xFF, v >> 8


def bound_1k(m, have=None, rebuild=None):
    """Frames within which a collapsed display that doesn't change any
    more is on the VDC, from the costs. A frame after one where the sweep
    got no row done gives the hints BUDGET - COST_STEP - COST_MODE -
    CHK_MAX - SWEEP_COL, too little to start a collapsed row (WALK_MAX,
    or a row's compare and copy): the sweep has all of that frame (u),
    and such a frame comes every other frame at least (those between may
    be all the hints'). In one, a row's work is its copy and compare
    (COST_COPY + its line / 2, and spaces put back, 32 / 4 at most, in
    its first frame only; + COST_ROW) and, rebuild given, the table made
    again each frame (but for row 0: no walk): 2 frames a row. Its runs
    cost no units: written in the window, or queued and written in the
    next (+ 1). Without rebuild: the table made once, WALK_MAX a row, the
    same way. have: what the sweep thinks the VDC shows (vdc_codes: the
    shadow; only checked for the costs here)."""
    sym = sym128()
    k = {n: sym[n] for n in ("budget", "cost_step", "cost_mode", "chk_max", "sweep_col", "walk_max", "back_max",
                             "cost_row", "cost_copy", "copy_max")}
    a = k["budget"] - k["cost_step"] - k["cost_mode"] - k["chk_max"]
    u = a if a - k["sweep_col"] < min(k["walk_max"], k["back_max"], k["cost_row"] + k["cost_copy"] + 32 // 4) \
        else k["sweep_col"]
    st = df_lines(m)
    frames = 1 if rebuild else 1 + 2 * -(-24 * k["walk_max"] // u)
    for r in range(24):
        look = min(33, st[r + 1] - st[r]) if r + 1 < len(st) else 33
        p0 = u - (k["cost_copy"] + look // 2) - k["cost_row"] - (rebuild or 0 if r else 0)
        if p0 - 32 // 4 < 0:
            raise AssertionError(f"row {r} never fits a frame: {p0} units over")
        frames += 2
    return frames + 1


def hint_bound_1k(m):
    """Frames within which the editor's rows are on the VDC once the ROM
    is ready for a key, with the sweep busy (every row unlike the
    shadow), from the costs at the rows' own lengths. VARS doesn't move
    any more: after one frame (pic_mode's try of a meet, the table made
    whole), the hints have every other frame at least, BUDGET -
    COST_STEP - COST_MODE - CHK_MAX of it. Each frame they start again
    at row 23: found back (BACK_ROW + its bytes / COST_WALK), copied
    (COST_COPY + bytes / 2 + 32 / 4), compared (COST_ROW); then row 22
    so, each of the lower screen's rows (the ROM's echo may change any of
    them over a few frames). Their runs cost no units: written in the
    window, or the next (+ 1). If they don't all fit one frame, the rest
    is the sweep's (bound_1k)."""
    sym = sym128()
    k = {n: sym[n] for n in ("budget", "cost_step", "cost_mode", "chk_max", "back_row",
                             "cost_walk", "cost_copy", "cost_row")}
    h = k["budget"] - k["cost_step"] - k["cost_mode"] - k["chk_max"]
    st = df_lines(m)
    rows = [r for r in range(23, 23 - m.bank1[0x4022], -1)]
    need = {r: (k["back_row"] + (st[r + 1] - st[r]) // k["cost_walk"]
                + k["cost_copy"] + (st[r + 1] - st[r]) // 2 + 32 // 4 + k["cost_row"]) for r in rows}
    left = set(rows)                                    # (the ROM's echo changes them over frames)
    frames = 0
    while left:
        frames += 1
        if frames > 100:
            raise AssertionError("the hints can't get the editor's rows done")
        b = h
        for r in rows:
            if b < need[r]:
                break
            b -= need[r]
            left.discard(r)
        if left and need[rows[0]] + sum(need[r] for r in rows if r in left) > h:
            return 1 + 2 * frames + bound_1k(m)          # (the rest: the sweep's)
    return 1 + 2 * frames + 1


def onek_cls():
    """1K: 10 CLS / 20 FOR I=1 TO 10 / 30 PRINT "HELLO WORLD" / 40 NEXT I /
    50 GOTO 10, running (the display made and grown again and again)."""
    m = zx128()
    to_1k(m)
    for line in ("1 0 V NEWLINE", "2 0 F I SHIFT+L 1 SHIFT+4 1 0 NEWLINE",
                 "3 0 P SHIFT+P H E L L O SPACE W O R L D SHIFT+P NEWLINE", "4 0 N I NEWLINE", "5 0 G 1 0 NEWLINE"):
        m.type(line)
    m.frames(20)
    m.type("R")
    m.keys = keyset(["NEWLINE"])
    m.frames(3)
    m.keys = set()
    m.frames(10)
    return m


def onek_edits(m, frames, edit):
    """pic_t over frames frames of a 1K display, edit(m, frame) changing
    its lines (df_shift) before each."""
    out = []
    for f in range(frames):
        edit(m, f)
        out += pic_t(m, 1)
    return out


def edit_two(m, f):
    # lines 0 and 12 a character longer, then shorter again: every row
    # from 1 on moves each frame
    for r in (12, 0):
        a = df_lines(m)[r]
        if f & 1:
            df_shift(m, a, -1)
        else:
            df_shift(m, a, 1)
            m.bank1[a] = 0x26


def edit_random(rnd):
    def edit(m, f):
        # one to five lines among 0-21 a character longer or shorter
        for _ in range(rnd.choice([1, 1, 2, 3, 5])):
            st = df_lines(m)
            r = rnd.randrange(22)
            n = st[r + 1] - 1 - st[r]
            if (rnd.random() < 0.5 or n == 0) and n < 32:
                a = st[r] + rnd.randrange(n + 1)
                df_shift(m, a, 1)
                m.bank1[a] = rnd.choice([0x26, 0x27, 0x3D, 0xA6])
            elif n > 0:
                df_shift(m, st[r] + rnd.randrange(n), -1)
    return edit


def alternate_1k(full=23):
    """ALTERNATE on a collapsed display: rows 0 to full - 1 full, the rest
    empty. The program waits on a flag while the display is collapsed
    here (df_shift, as the ROM's RECLAIM), then runs."""
    alt = bytearray(ALTERNATE)
    alt[10] = full                                       # (its ld c,24)
    flag = 16514 + 6 + len(alt)
    code = bytes([0x3A, flag & 0xFF, flag >> 8, 0xB7, 0x28, 0xFA]) + bytes(alt) + b"\x00"   # ld a,(flag) or a jr z
    m = zx128()
    load_p(m, p_prog("10 REM {bin:c}\n20 RAND USR 16514", {"c": code}))
    m.frames(10)
    for r in range(23, full - 1, -1):
        for _ in range(32):
            df_shift(m, df_lines(m)[r], -1)
    m.bank1[flag] = 1
    m.frames(5)
    return m


def scroll_1k_t(frames=120, period=4):
    """pic_t over a display of full lines that scrolls, as a 1K program
    printing full lines does: every period frames row 0 goes and an empty
    line comes in at the bottom (collapsed), the frame after it is printed
    (expanded again; every row changes at each scroll). A program waits
    in a loop meanwhile."""
    import random
    rnd = random.Random(3)
    wait = bytes([0x3A, 0x34, 0x40, 0x5F, 0x3A, 0x34, 0x40, 0xBB, 0x28, 0xFA, 0x18, 0xF4])
    m = zx128()
    load_p(m, p_prog("10 REM {bin:w}\n20 RAND USR 16514", {"w": wait}))
    m.frames(10)
    d = m.peek16(0x400C) + 1
    for i in range(24 * 33):
        if m.bank1[d + i] != 0x76:
            m.bank1[d + i] = rnd.randrange(0x00, 0x40) | rnd.choice([0, 0x80])
    m.frames(60)
    out = []
    for f in range(frames):
        if f % period == 0:                              # row 0 out, an empty line in
            for _ in range(33):
                df_shift(m, m.peek16(0x400C) + 1, -1)
            v = m.peek16(0x4010)
            df_shift(m, v, 1)
            m.bank1[v] = 0x76
        elif f % period == 1:                            # the bottom line printed
            for _ in range(32):
                a = m.peek16(0x4010) - 1
                df_shift(m, a, 1)
                m.bank1[a] = rnd.randrange(0x00, 0x40) | rnd.choice([0, 0x80])
        out += pic_t(m, 1)
    return out


def collapse_queued_t(full=23):
    """pic_t just after an expanded display is collapsed (rows 0 to full -
    1 full) with the queue near its fullest: ALTERNATE runs till pic_qn is
    40 or more at its wait loop, which then counts full rows."""
    sym = sym128()
    m = zx128()
    load_p(m, p_prog("10 REM {bin:alt}\n20 RAND USR 16514", {"alt": ALTERNATE}))
    z, wait = m.z, 16514 + 0x1B                          # (ld a,(FRAMES) cp e jr z)
    for _ in range(60):
        m.frames(1)
        while not (wait <= z.pc < wait + 7):
            m.step(1)
        if m.bank1[sym["pic_qn"]] >= 40:
            break
    qn = m.bank1[sym["pic_qn"]]
    for r in range(23, full - 1, -1):
        for _ in range(32):
            df_shift(m, df_lines(m)[r], -1)
    m.bank1[16514 + 10] = full
    if qn < 40:
        raise AssertionError(f"the queue only {qn} as it collapsed")
    return pic_t(m, 8)


@zx128check
def pic_time():
    # pic_step's time (us on the C128, the model's clock): a quiet 16K
    # screen in the editor no more than QUIET_US (mean and most); and at
    # most BUSY_US with everything changing (INVERT), random characters in
    # random cells (SCATTER), every other column changing (ALTERNATE, the
    # dearest rows; also as if no IRQ found the window, polled; and on a
    # collapsed display, alternate_1k, both ways), full lines scrolling,
    # collapsed and expanded in turn (scroll_1k_t), a display collapsed with
    # the queue nearly full (collapse_queued_t), a big redraw starting just
    # after LOAD (the lock not found yet), a 1K collapsed screen of long
    # lines in the editor, catching up and quiet, and three 1K screens whose
    # lines move: a program clearing and printing (1K cls), lines 0 and 12 a
    # character longer and shorter each frame (1K two), random lines so (1K
    # random); a full screen's SCROLLs and CLSs (the VDC's block
    # operations), and SCROLL as fast as BASIC goes
    import random
    got = {}
    m = zx128()
    m.frames(20)
    got["quiet"] = pic_t(m, 30)
    m = zx128()
    load_p(m, p_prog("10 REM {bin:inv}\n20 RAND USR 16514", {"inv": INVERT}))
    m.frames(5)
    got["invert"] = pic_t(m, 40)
    m = zx128()
    load_p(m, p_prog("10 REM {bin:scatter}\n20 RAND USR 16514", {"scatter": scatter_code()}))
    m.frames(20)
    got["scatter"] = pic_t(m, 40)
    m = zx128()
    load_p(m, p_prog("10 REM {bin:alt}\n20 RAND USR 16514", {"alt": ALTERNATE}))
    m.frames(5)
    got["alternate"] = pic_t(m, 40)
    got["alternate, no window"] = pic_t(m, 40, nowin=True)
    got["scroll 1K"] = scroll_1k_t()
    got["collapsed, queued"] = collapse_queued_t()
    m = alternate_1k()
    got["alternate 1K"] = pic_t(m, 40)
    got["alternate 1K, no window"] = pic_t(m, 40, nowin=True)
    m = zx128()
    load_p(m, redraw_prog("mazogs", nflip=2, wait=30))
    got["after LOAD"] = pic_t(m, 12)                    # (no window yet: polled, a redraw starting)
    m = onek_lines()
    m.frames(10)
    collapsed = m.peek16(0x4010) - m.peek16(0x400C) != 24 * 33 + 1
    got["1K"] = pic_t(m, 8)                             # catching up
    m.until(lambda: pic_same(m), 200, "the 1K picture")
    got["1K quiet"] = pic_t(m, 4)
    got["1K two"] = onek_edits(m, 60, edit_two)
    m = onek_lines()
    got["1K random"] = onek_edits(m, 60, edit_random(random.Random(1)))
    m = onek_cls()
    got["1K cls"] = pic_t(m, 100)
    for op, name in ((1, "scroll"), (2, "cls")):          # a full screen's SCROLL and CLS
        m = zx128()
        load_p(m, blk_prog(op, 4, 20)[0])
        got[name] = pic_t(m, 160)
    m = zx128()                                         # SCROLL alone as fast as BASIC goes
    load_p(m, p_prog(SCROLL_FAST))
    m.until(lambda: m.zx_screen()[21].startswith("ROW 21") and pic_same(m), 600, "the full screen")
    got["scroll loop"] = pic_t(m, 80)
    worst = {k: round(max(t for t, u in v)) for k, v in got.items()}
    q = [t for t, u in got["quiet"]]
    qmean = sum(q) / len(q)
    global time_seen
    time_seen = (worst, qmean)
    check("pic_time", collapsed and qmean <= QUIET_US[0] and max(q) <= QUIET_US[1]
          and all(w <= BUSY_US for w in worst.values()),
          f"us most {worst} (of {BUSY_US}); quiet mean {qmean:.0f} (of {QUIET_US[0]}), most {max(q):.0f} "
          f"(of {QUIET_US[1]}); 1K collapsed {collapsed}")


# Rows 0 and 1 of D_FILE changed every frame, every character one code on
# (never the same for 128 frames), 200 times:
#        ld d,200
# loop:  ld a,(FRAMES)  ld e,a
#        ld hl,(D_FILE) ld c,2
# row:   inc hl         ld b,32
# ch:    ld a,(hl)  add a,1  and $BF  ld (hl),a  inc hl  djnz ch
#        dec c  jr nz,row
# wait:  ld a,(FRAMES)  cp e  jr z,wait
#        dec d  jr nz,loop  ret
CHURN = bytes([0x16, 200,
               0x3A, 0x34, 0x40, 0x5F,
               0x2A, 0x0C, 0x40, 0x0E, 2,
               0x23, 0x06, 32,
               0x7E, 0xC6, 0x01, 0xE6, 0xBF, 0x77, 0x23, 0x10, 0xF7,
               0x0D, 0x20, 0xF1,
               0x3A, 0x34, 0x40, 0xBB, 0x28, 0xFA,
               0x15, 0x20, 0xDF, 0xC9])
STARVE_BOUND = 20


@zx128check
def pic_starve():
    # two rows changing every frame, DF_CC (the hint) in one of them: a
    # POKE at row 12 still shows within STARVE_BOUND frames. The hints
    # take their two rows first, the sweep the rest of the frame's time
    # (LIM_Q, LIM_B once much is found) and goes on in a row from where
    # it stopped, so it gets round (measured: 1-7 frames)
    m = zx128()
    load_p(m, p_prog("10 REM {bin:churn}\n20 RAND USR 16514", {"churn": CHURN}))
    m.frames(40)
    d = m.peek16(0x400C)
    row0 = bytes(m.bank1[d + 1:d + 33])
    m.bank1[d + 1 + 33 * 12 + 4] = 0x26                  # an A at row 12, column 4
    n = frames_until(m, lambda: m.vdc_text(12, 8, 2) == "A", 100, "the A on the VDC")
    m.frames(2)
    churning = bytes(m.bank1[d + 1:d + 33]) != row0 and zx_report(m) is None
    check("pic_starve", churning and n <= STARVE_BOUND, f"the A in {n} frame(s) (bound {STARVE_BOUND}); "
          f"rows changing {churning}")


@zx128check
def pic_bad76():
    # a POKE over a line's $76 in a 1K display (now not a display's: 24 of
    # them): pic_step stays within BUSY_US, and nothing hangs; the $76
    # back, the picture is D_FILE's again
    limit = BUSY_US
    m = onek_lines()
    m.until(lambda: pic_same(m), 100, "the 1K picture")
    a = m.peek16(0x400C) + 1 + 31                       # line 0's $76
    m.bank1[a] = 0x26
    t = pic_t(m, 20)
    m.frames(20)
    m.bank1[a] = 0x76
    n = frames_until(m, lambda: pic_same(m), 100, "the picture back")
    worst = max(x for x, u in t)
    check("pic_bad76", worst <= limit, f"us most {worst:.0f} of {limit} with a $76 gone; equal {n} frame(s) after it is "
          f"back")


@zx128check
def pic_toggle1k():
    # 1K, six lines of 31 characters; every frame line 0 loses a character
    # to line 1 and gets it back (one $76 moving, VARS where it was), and
    # the shadow is made unlike every row first: all rows but line 1
    # (which keeps changing) are on the VDC within bound_1k's frames,
    # the table carried over each frame (pic_fix: VARS where it was, row 1
    # not after a $76: found back from row 2, BACK_ROW + 32 / COST_WALK).
    # The sweep starts at row 2: round the long lines first
    sym = sym128()
    m = onek_lines()
    m.until(lambda: pic_same(m), 100, "the 1K picture")
    l0 = m.peek16(0x400C) + 1
    m.bank1[sym["shadow"]:sym["shadow"] + 24 * 32] = b"\xff" * (24 * 32)
    m.bank1[sym["pic_row"]], m.bank1[sym["pic_scol"]] = 2, 0
    rebuild = sym["back_row"] + 32 // sym["cost_walk"]
    bound = bound_1k(m, have=[[0xFF] * 32] * 24, rebuild=rebuild)
    rows = [r for r in range(24) if r != 1]
    n = None
    for f in range(1, bound + 1):
        if f & 1:
            m.bank1[l0 + 30], m.bank1[l0 + 31] = 0x76, 0x3D       # line 0 30 characters, line 1 32
        else:
            m.bank1[l0 + 30], m.bank1[l0 + 31] = 0x3A, 0x76
        m.frames(1)
        if pic_same(m, rows):
            n = f
            break
    check("pic_toggle1k", n is not None, f"all rows but line 1 on the VDC after {n} frame(s) (bound {bound})")


@zx128check
def pic_extra76():
    # a $76 POKEd into the middle of a 1K line (25 line ends: the ZX81
    # shows the line split, the rows below one lower, the last gone): on
    # the VDC within bound_1k's frames, though every row the table had
    # still has its $76 (the copy finds the new one); then taken out again
    m = onek_lines()
    m.until(lambda: pic_same(m), 100, "the 1K picture")
    a = df_lines(m)[2] + 10                               # line 2, column 10
    got = []
    for v in (0x76, m.bank1[a]):
        m.bank1[a] = v
        bound = bound_1k(m)
        got.append((frames_until(m, lambda: pic_same(m), bound, "the picture equal to D_FILE"), bound))
    check("pic_extra76", True, f"split: equal after {got[0][0]} frame(s) (bound {got[0][1]}); back: {got[1][0]} "
          f"(bound {got[1][1]})")


def onek_run():
    """1K: 10 PRINT "HELLO" / 20 PRINT "X", RUN: the listing's display
    cleared and printed again (VARS moving), to the report."""
    m = zx128()
    to_1k(m)
    m.type("1 0 P SHIFT+P H E L L O SHIFT+P NEWLINE")
    m.type("2 0 P SHIFT+P X SHIFT+P NEWLINE")
    m.frames(30)
    m.type("R NEWLINE")
    m.until(lambda: zx_report(m) == "0/20", 300, "the report")
    return m


@zx128check
def pic_1k_run():
    # the program's picture on the VDC within bound_1k's frames of the
    # report: no row taken from the listing's table
    m = onek_run()
    bound = bound_1k(m)
    n = frames_until(m, lambda: pic_same(m), bound, "the picture equal to D_FILE")
    rows = m.zx_screen()
    check("pic_1k_run", rows[0] == "HELLO" and rows[1] == "X", f"equal {n} frame(s) after the report (bound {bound}); "
          f"rows 0, 1 {rows[:2]}")


@zx128check
def pic_1k_edit_after_run():
    # then NEWLINE (the listing back) and PRINT "AB typed: the picture,
    # edit line and all, on the VDC within bound_1k's frames of the last
    # key
    m = onek_run()
    m.type("NEWLINE")
    m.frames(50)
    m.type("P SHIFT+P A B")
    bound = bound_1k(m)
    n = frames_until(m, lambda: pic_same(m), bound, "the picture equal to D_FILE")
    row = m.zx_screen()[23]
    check("pic_1k_edit_after_run", row.startswith('PRINT "AB'), f"equal {n} frame(s) after the last key "
          f"(bound {bound}); row 23 {row!r}")


@zx128check
def pic_1k_resync():
    # a 1K display written over in one go, its length the same (VARS
    # where it was), three of its $76s moved: lines 0-8 'X', '', '', '',
    # '', 'X', '', '', '' then 'AAA..' lines, and then '', 'X', '', '',
    # '', '', '', '', 'X': on the VDC within bound_1k's frames each time
    m = onek_lines()
    m.until(lambda: pic_same(m), 100, "the 1K picture")
    d = m.peek16(0x400C)
    total = df_lines(m)[22] - (d + 1)                      # lines 0-21; 22 and 23 as they are

    def disp(first):
        chars, fill = total - 22 - sum(len(x) for x in first), []
        for i in range(22 - len(first)):
            k = min(32, chars)
            fill.append(bytes([0x26 + i % 20]) * k)
            chars -= k
        assert chars == 0
        return b"".join(x + b"\x76" for x in first + fill)
    got = []
    for first in ([b"\x3d", b"", b"", b"", b"", b"\x3d", b"", b"", b""],
                  [b"", b"\x3d", b"", b"", b"", b"", b"", b"", b"\x3d"]):
        m.bank1[d + 1:d + 1 + total] = disp(first)
        bound = bound_1k(m)
        got.append((frames_until(m, lambda: pic_same(m), bound, "the picture equal to D_FILE"), bound))
    check("pic_1k_resync", m.zx_screen()[8] == "X", f"equal after {got[0][0]} frame(s) (bound {got[0][1]}), "
          f"then {got[1][0]} (bound {got[1][1]})")


def redraw_screens(kind):
    """Two screens (768 codes each) for redraw8l.asm, one flipped to the
    other: the shape of a real big redraw captured from the game, its
    characters made up. mazogs: a maze step,
    rows 8-19 columns 8-23 and row 21 columns 2-30 (221 characters, 13
    runs); monstermaze: a 3D step, every row, two walls from columns 0
    and 23 inwards, 1 to 15 characters a row (248, 46 runs)."""
    import random
    rnd = random.Random(81)
    a = [rnd.choice([0, 0, 0, 0x80, 0x08, 0x88, 0x03]) for _ in range(768)]
    b = list(a)
    if kind == "mazogs":
        cells = [(r, c) for r in range(8, 20) for c in range(8, 24)] + [(21, c) for c in range(2, 31)]
    else:
        cells = []
        for r, n in enumerate([1, 3, 5, 7, 9, 11, 13] + [15] * 10 + [13, 11, 9, 7, 5, 3, 1]):
            left = (n + 1) // 2 if n > 1 else 1
            cells += [(r, c) for c in range(left)] + [(r, c) for c in range(24 - (n - left), 24)]
    for r, c in cells:
        b[32 * r + c] = rnd.choice([0x80, 0x88, 0x05, 0x85, 0x3F])
        if b[32 * r + c] == a[32 * r + c]:
            b[32 * r + c] ^= 0x01
    return bytes(a), bytes(b)


def redraw_prog(kind, nflip=12, wait=60):
    """z80/redraw8l.asm with redraw_screens(kind), as a .p: flips them
    every wait frames, nflip times, each flip's frames to settle (the
    shadow D_FILE's, no run waiting) at 16516."""
    import build
    a, b = redraw_screens(kind)
    odir = os.path.join(ROOT, "build", "obj", "redraw")
    os.makedirs(odir, exist_ok=True)
    open(os.path.join(odir, "redrawcfg.inc"), "w").write(f"NFLIP: equ {nflip}\nWAIT: equ {wait}\n")
    out = os.path.join(odir, "redraw8l.bin")
    build.assemble_z80(os.path.join(ROOT, "z80", "redraw8l.asm"), out, out[:-4] + ".lbl", inc=odir)
    return p_prog("10 REM {bin:rd}\n20 RAND USR 16514", {"rd": open(out, "rb").read() + a + b})


REDRAW_BOUND = {"mazogs": 6.2, "monstermaze": 9.2}  # frames to settle, mean. The
                                                   # phase moves it: the VDC's against the
                                                   # program's start, so any change in the
                                                   # time typing takes (scan's) moves it too.
                                                   # 6 and 9 are met only at phase 0; over
                                                   # 12 phases the scan measures 5.0-6.0 and
                                                   # 9.0-9.18 (without its padding 5.0-6.0
                                                   # and 9.0-9.09): the bound is the worst, a
                                                   # frame or two in 11 flips above 6 and 9


@zx128check
def pic_redraw():
    # big redraws flipped back and forth (redraw_prog, the shapes of
    # Mazogs' and Monster Maze's): the frames each flip takes to settle,
    # the first (from the program's own screen) left out, within
    # REDRAW_BOUND on the mean, and the VDC D_FILE's at the end
    got, ok = {}, True
    for kind, bound in REDRAW_BOUND.items():
        m = zx128()
        load_p(m, redraw_prog(kind))
        m.until(lambda: m.bank1[16516 + 11] != 255, 1500, "the flips")
        res = list(m.bank1[16516:16528])
        mean = sum(res[1:]) / 11
        got[kind] = (round(mean, 2), max(res[1:]), bound)
        ok = ok and mean <= bound and pic_same(m)
    check("pic_redraw", ok, " ".join(f"{k}: mean {v[0]} (bound {v[2]}), most {v[1]}" for k, v in got.items()))


# ---- CLS and SCROLL as the VDC's block fill and copy
BLK_BOUND = 2                   # frames from a full screen's SCROLL or CLS (the
                                # command's return) to VDC = D_FILE: the target,
                                # met at the C128's rates (a row: its own work,
                                # ~120-155 cycles, and its 64 bytes; ~16-23 rows
                                # a window)
BLK_LOOP_LAG = 4                # frames a SCROLL loop may lag at most
BLK_LOOP_EQ = 5                 # and to the picture's with the report's text in
                                # (3-5 by phase: pic_blk_loop; 5 at the
                                # default phase, after its boot)
BLK_LOOP_PLAG = 7               # PRINT and SCROLL: frames it may lag at most (the
                                # target, 4, missed: pic_blk_loop): 5-7 across
                                # its variants, by the phase of the IRQ
                                # against PRINT's MAKE-ROOMs alone (the C128
                                # measured 0 for PRINT and SCROLL)
BLK_LOOP_NONE = 4               # and frames a row may match none of the last 30,
                                # for each block operation


def blk_prog(op, nflip=6, wait=40):
    """z80/blk8l.asm as a .p (OP 1: SCROLL, 2: CLS of a full screen, nflip
    times, wait frames apart); also its labels (opn: the commands done)."""
    import build
    import shutil
    import tempfile
    os.makedirs(os.path.join(ROOT, "build", "obj"), exist_ok=True)
    odir = tempfile.mkdtemp(prefix="blk", dir=os.path.join(ROOT, "build", "obj"))   # (checks run side by side)
    try:
        open(os.path.join(odir, "blkcfg.inc"), "w").write(f"NFLIP: equ {nflip}\nWAIT: equ {wait}\nOP: equ {op}\n")
        out = os.path.join(odir, "blk8l.bin")
        lbl = build.assemble_z80(os.path.join(ROOT, "z80", "blk8l.asm"), out, out[:-4] + ".lbl", inc=odir)
        code = open(out, "rb").read()
    finally:
        shutil.rmtree(odir, ignore_errors=True)
    assert 0x76 not in code, "blk8l.asm has a $76 in its code"
    return p_prog("10 REM {bin:b}\n20 RAND USR 16514", {"b": code}), lbl


# The panel (z80/panel.inc) as it should be: columns 64-79 of rows 0-24 and
# row 24's columns 0-63, their text (set 1: ASCII at $80-$DF, ZX81 codes
# below) and attributes, and the picture's attributes (rows 0-23, columns
# 0-63), from the settings in bank 1. Row 0 zx128's name and version
# (build.py's VERSION), row 24 the CPU that has the machine: the Z80,
# or the 8502 while it serves a command (no placeholders, no dim rows).
def _version128():
    sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
    import build
    return build.VERSION


PANEL_TEXT = {0: f" zx128 {_version128()}", 2: "F1 type-ahead", 3: "F2 colours", 4: "F3 joy", 6: "F5 debugger",
              8: "F7 reset", 9: "F8 memory", 24: " Z80"}
PANEL_COLS = [(0xF0, 0x0F, 0x8F), (0x50, 0x05, 0x85), (0x32, 0x03, 0x83),   # R26, the picture's
              (0x0E, 0x00, 0x80)]               # attribute, the panel's: a scheme (F2)
PANEL_NAMES = ("WHITE ON BLACK", "C128 COLOURS", "C64 COLOURS", "ZX81 COLOURS")   # their messages
PANEL_SIZES = ("  1K", " 16K", " 32K")


def panel_rows(m):
    """The panel's 25 rows of 16 set-1 codes as they should be now."""
    sym = sym128()
    rows = []
    for r in range(25):
        t = list(PANEL_TEXT.get(r, "").ljust(16))
        size = PANEL_SIZES[m.bank1[sym["ramsize"]]]
        if r == 4:
            t[8:16] = ("5678+0", "own keys")[m.bank1[sym["joyidx"]]].ljust(8)
        if r == 9:
            t[10:14] = size
        if r == 23:
            t[1:5] = "SLOW" if m.bank1[0x403B] & 0x40 else "FAST"     # (the size only on row 9)
        codes = [ord(c) + 0x60 for c in t]
        if r in (13, 14) and m.bank1[sym["ovl"]]:
            a = m.peek16(sym["ovl_msg"]) + 16 * (r - 13)
            codes = [(z & 0x3F | 0x40) if z & 0x80 else z & 0x3F for z in m.bank1[a:a + 16]]
        rows.append(codes)
    return rows


def panel_want(m):
    """{VDC address: byte} for every cell the panel draws (panel_rows), and
    every attribute."""
    sym = sym128()
    r26, pic, nrm = PANEL_COLS[m.bank1[sym["scheme"]]]
    want = {}
    for r, codes in enumerate(panel_rows(m)):
        for c in range(16):
            want[r * 80 + 64 + c] = codes[c]
            want[0x800 + r * 80 + 64 + c] = nrm
        for c in range(64):
            if r == 24:
                want[r * 80 + c] = 0x80
            want[0x800 + r * 80 + c] = nrm if r == 24 else pic
    return want


def panel_busy(m):
    """The panel has jobs waiting (z80/panel.inc's pn_d, pn_r26), or a
    message whose time is over still shown."""
    sym = sym128()
    return (any(m.bank1[sym["pn_d"]:sym["pn_d"] + 25]) or m.bank1[sym["pn_r26"]]
            or (m.bank1[sym["pn_shown"]] and not m.bank1[sym["ovl"]]))


def panel_bad(m):
    """The panel's cells (and the attributes) that aren't as they should be,
    and R26: [(address, got, want)]."""
    bad = [(a, m.vram[a], v) for a, v in panel_want(m).items() if m.vram[a] != v]
    r26 = PANEL_COLS[m.bank1[sym128()["scheme"]]][0]
    return bad + ([("R26", m.vdc[26], r26)] if m.vdc[26] != r26 else [])


def panel_ok(m, settle=100):
    """The panel's cells and every attribute as they should be, once the
    panel's jobs are done (settle frames at most): a picture's or a block
    operation's write there shows."""
    if settle:
        m.until(lambda: not panel_busy(m), settle, "the panel's jobs done")
    return not panel_bad(m)


def blk_settle(op, nflip=6):
    """blk_prog's commands: for each, the frames from its return to VDC =
    D_FILE (the model's VDC read), and blk8l.asm's own count (the shadow
    D_FILE's too, nothing waiting or going on)."""
    prog, lbl = blk_prog(op, nflip)
    m = zx128()
    load_p(m, prog)
    opn, got = lbl["opn"], []
    for k in range(nflip):
        m.until(lambda: m.bank1[opn] > k, 1500, f"command {k + 1}")
        n = 0
        while not pic_same(m) and n < 20:
            m.frames(1)
            n += 1
        got.append(n)
    m.until(lambda: m.bank1[16516 + nflip - 1] != 255, 200, "the program's counts")
    return got, list(m.bank1[16516:16516 + nflip]), m


def blk_used(m):
    sym = sym128()
    return m.peek16(sym["blk_ns"]), m.peek16(sym["blk_nd"])


@zx128check
def pic_blk_scroll():
    # a full 16K screen (rows 0-21, each its own) SCROLLed: VDC = D_FILE
    # within BLK_BOUND frames of the command, six times; no VDC access while
    # a block operation is busy, none lost; the panel's columns 64-79,
    # row 24 and the attributes as the panel has them (panel_ok)
    got, own, m = blk_settle(1)
    ns, nd = blk_used(m)
    check("pic_blk_scroll", max(got) <= BLK_BOUND and ns >= 6 and not m.vdc_nblkbusy and not m.vdc_lost
          and panel_ok(m),
          f"VDC = D_FILE after {got} frame(s) (bound {BLK_BOUND}), the shadow too after {own}; block operations "
          f"{ns}, dropped {nd}; accesses while busy {m.vdc_nblkbusy}, lost {m.vdc_lost}; the panel's columns and "
          f"row 24 as the panel has them {not panel_bad(m)}")


@zx128check
def pic_blk_cls():
    # the same with CLS
    got, own, m = blk_settle(2)
    ns, nd = blk_used(m)
    check("pic_blk_cls", max(got) <= BLK_BOUND and ns >= 6 and not m.vdc_nblkbusy and not m.vdc_lost
          and panel_ok(m),
          f"VDC = D_FILE after {got} frame(s) (bound {BLK_BOUND}), the shadow too after {own}; block operations "
          f"{ns}, dropped {nd}; accesses while busy {m.vdc_nblkbusy}, lost {m.vdc_lost}; the panel's columns and "
          f"row 24 as the panel has them {not panel_bad(m)}")


@zx128check
def pic_blk_nowin():
    # a full screen's SCROLL, then CLS, with no window in the frames after
    # each (as if every IRQ had missed it: the rows polled, for units):
    # pic_step within BUSY_US, VDC = D_FILE within BLK_NOWIN frames, the
    # panel's columns and row 24 untouched, no access while busy
    sym = sym128()
    got, worst, ok = [], 0, True
    for op in (1, 2):
        prog, lbl = blk_prog(op, 1)
        m = zx128()
        load_p(m, prog)
        m.until(lambda: m.bank1[lbl["opn"]], 1500, "the command")
        ns = blk_used(m)[0]
        t, n = [], 0
        while not pic_same(m) and n < BLK_NOWIN:
            t += pic_t(m, 1, nowin=True)
            n += 1
        got.append(n)
        worst = max([worst] + [x for x, u in t])
        ok = ok and pic_same(m) and panel_ok(m) and not m.vdc_nblkbusy and blk_used(m)[0] > ns
    check("pic_blk_nowin", ok and worst <= BUSY_US,
          f"VDC = D_FILE after {got} frame(s) without the window (bound {BLK_NOWIN}); pic_step at most {worst:.0f} us "
          f"(of {BUSY_US}); the panel and row 24 untouched {ok}")


BLK_NOWIN = 12                  # frames a SCROLL or CLS may take with no window


@zx128check
def pic_blk_bit5():
    # pic_bit5_net for block operations: as a SCROLL's or a CLS's rows go
    # in the window, the VDC's frame jumps 8,000 cycles (a wrong window: a
    # row's registers, unpolled, lost in the display, or its operation run
    # from wherever the address was). The row's own bit 5 test (bv_lost)
    # makes the whole shadow unknown and drops the operation, so the
    # picture is D_FILE's again within bound_16k's frames; an operation run
    # from a stale address may have hit the panel or the attributes: pw_chk
    # has the panel draw them all again (pn_rep), right within PANEL_REP
    # frames more; no VDC access while an operation is busy
    sym = sym128()
    got, ok = [], True
    for op in (1, 2):
        prog, lbl = blk_prog(op, 1)
        m = zx128()
        load_p(m, prog)
        m.until(lambda: m.bank1[lbl["opn"]], 1500, "the command")
        z = m.z
        while not (z.pc in (sym["bv_cw"], sym["bv_fw"]) and m.bank1[sym["pic_unp"]] and m.bank1[sym["blk_i"]] >= 3):
            m.step(1)                                    # (a row in the window, the fourth or later)
        lost0, ns = m.vdc_lost, blk_used(m)[0]
        for _ in range(4):                               # (into the row's registers)
            m.step(1)
        m.vdc_phase += 8000
        m.frames(1)
        lost = m.vdc_lost - lost0
        dropped = not m.bank1[sym["blk_k"]]
        bound = bound_16k(m)
        n = frames_until(m, lambda: pic_same(m), bound, "the picture equal to D_FILE")
        pn = frames_until(m, lambda: not panel_busy(m) and not panel_bad(m), PANEL_REP, "the panel mended")
        got.append((lost, dropped, n, bound, m.vdc_nblkbusy, n + pn))
        ok = ok and lost > 0 and dropped and not m.vdc_nblkbusy
    check("pic_blk_bit5", ok, "; ".join(f"{name}: {lost} accesses lost in the wrong window, the operation dropped "
                                        f"{d}, equal {n} frame(s) after (bound {b}), the panel and the attributes "
                                        f"{p} (bound {n} + {PANEL_REP}); accesses while busy {nb}"
                                        for name, (lost, d, n, b, nb, p) in zip(("scroll", "cls"), got)))


def blk_loop(m, report, frames=1500):
    """Until the report: each frame, how far the VDC lags D_FILE: for each
    row, the frames back to a D_FILE (one a frame) it equals; the most of
    them (None: none within 30 frames). Returns [lag a frame]."""
    hist, lags = [df_codes(m)], []                       # (D_FILE as the loop starts)
    end = m.nframes + frames
    while zx_report(m) != report:
        if m.nframes > end:
            raise AssertionError(f"no report {report} after {frames} frames")
        m.frames(1)
        hist.append(df_codes(m))
        hist = hist[-31:]
        v = vdc_codes(m)
        lag = 0
        for r in range(24):
            back = next((i for i, h in enumerate(reversed(hist)) if h[r] == v[r]), None)
            if back is None:
                lag = None
                break
            lag = max(lag, back)
        lags.append(lag)
    return lags


SCROLL_LOOP = "10 FOR I=1 TO 30\n20 PRINT AT 21,0;\"LINE \";I;\" ABCDEFGHIJKLMNOPQRS\"\n30 SCROLL\n40 NEXT I"
SCROLL_FAST = ("10 FOR I=0 TO 21\n20 PRINT AT I,0;\"ROW \";I;\" ABCDEFGHIJKLMNOPQRSTUVW\"\n30 NEXT I\n"
               "35 PAUSE 50\n40 FOR I=1 TO 40\n50 SCROLL\n60 NEXT I")


@zx128check
def pic_blk_loop():
    # SCROLL alone, 40 times as fast as BASIC goes, on a full screen: the
    # VDC never more than BLK_LOOP_LAG frames behind D_FILE (each row equal
    # to D_FILE as it was that many frames before at most), and D_FILE's
    # (the report printed too) within BLK_LOOP_LAG frames of the report.
    # And BASIC printing a line at the bottom and scrolling, 30 times
    # (SCROLL leaves a 16K display collapsed): no more than BLK_LOOP_PLAG
    # frames behind, D_FILE's within BLK_LOOP_LAG frames of the report. A
    # row may match none of the last 30 D_FILEs in some frames (at most
    # BLK_LOOP_NONE a block operation): the picture looks at D_FILE at the
    # IRQ, so a row being printed can show what was there then, between two
    # frames' ends; and in the SCROLL's own frames, its last row moved shows
    # that until pic_srow's compare is written; those frames aren't in the
    # lag. The target, 4, is missed: the IRQ often comes while PRINT's
    # MAKE-ROOM moves the display (one frame in seven here), and the
    # table waits (pic_mvd): that frame compares nothing, and a PRINT
    # loses 2-3 frames so; a line's last characters can then be as old as
    # SCROLL starts, and its 2-3 frames (the hold, the block operation) add.
    # Equal within BLK_LOOP_EQ frames of the report: the last SCROLL runs
    # in the report's frames (its hold, its block operation, pic_srow's row,
    # then the report's row 23), 3 to 5 frames by where the IRQs fall
    # (the run started 0-9 frames later). No VDC access while a block
    # operation is busy, in either.
    got, ok = [], True
    for prog, report in ((SCROLL_FAST, "0/60"), (SCROLL_LOOP, "0/40")):
        m = zx128()
        load_p(m, p_prog(prog))
        if prog == SCROLL_FAST:                       # (from the full screen on the VDC)
            m.until(lambda: m.zx_screen()[21].startswith("ROW 21") and pic_same(m), 600, "the full screen")
        f0, ns0 = m.nframes, blk_used(m)[0]
        lags = blk_loop(m, report)
        frames, ns = m.nframes - f0, blk_used(m)[0] - ns0
        n = frames_until(m, lambda: pic_same(m), BLK_LOOP_EQ, "the picture equal to D_FILE")
        known = [x for x in lags if x is not None]
        got.append((max(known), round(sum(known) / len(known), 1), lags.count(None), len(lags), n, frames, ns))
        ok = ok and not m.vdc_nblkbusy
        if prog == SCROLL_FAST:
            ok = ok and None not in lags and max(lags) <= BLK_LOOP_LAG
        else:
            ok = ok and max(known) <= BLK_LOOP_PLAG and lags.count(None) <= BLK_LOOP_NONE * ns
    check("pic_blk_loop", ok, "; ".join(
        f"{name}: lag at most {w} frame(s) (mean {a}; {nn} of {nl} frames a row not in D_FILE's last 30), equal {n} "
        f"frame(s) after the report; {f} frames, {s_} block operations"
        for name, (w, a, nn, nl, n, f, s_) in zip(("scroll alone", "print and scroll"), got))
        + f" (bounds: lag {BLK_LOOP_LAG} and {BLK_LOOP_PLAG}, equal {BLK_LOOP_EQ})")


BLK_1K = ("10 FOR I=1 TO 12\n20 PRINT \"LINE \";I;\" ABCDEFGHIJKLMNOP\"\n30 NEXT I\n40 PAUSE 60\n50 SCROLL\n"
          "60 PAUSE 60\n70 SCROLL\n80 PRINT AT 0,0;\"X\"\n90 PAUSE 60\n100 CLS\n110 PAUSE 60\n120 PRINT \"Y\"")


@zx128check
def pic_blk_1k():
    # 1K (collapsed): twelve lines printed, SCROLL, SCROLL and a line at
    # the top, CLS, a line: the VDC D_FILE's within bound_1k's frames of
    # each command (a block operation on a collapsed display: the compare
    # still the authority); the panel's columns and row 24 untouched
    import build
    sym = sym128()
    m = zx128()
    to_1k(m)
    load_p(m, build.p_collapsed(p_prog(BLK_1K)))
    collapsed = m.peek16(0x4010) - m.peek16(0x400C) != 24 * 33 + 1
    got = []
    for k in range(3):
        ns = blk_used(m)[0]
        m.until(lambda: blk_used(m)[0] > ns or m.bank1[sym["blk_pend"]], 600, f"command {k + 1}")
        bound = bound_1k(m)
        got.append((frames_until(m, lambda: pic_same(m), bound, "the picture equal to D_FILE"), bound))
    m.until(lambda: zx_report(m) == "0/120", 300, "the report")
    n = frames_until(m, lambda: pic_same(m), 60, "the picture equal to D_FILE")
    ns, nd = blk_used(m)
    check("pic_blk_1k", collapsed and ns >= 3 and not m.vdc_nblkbusy and panel_ok(m),
          f"collapsed {collapsed}; equal after {[g for g, b in got]} frame(s) (bound {[b for g, b in got]}), "
          f"{n} after the report; block operations {ns}, dropped {nd}; accesses while busy {m.vdc_nblkbusy}; "
          f"the panel and row 24 as they should be {not panel_bad(m)}")


COLL_EDIT = ("10 FOR I=0 TO 21\n20 PRINT AT I,0;\"ROW \";I;\" ABCDEFGHIJKLMNOPQRSTUVW\"\n30 NEXT I\n40 SCROLL\n"
             "50 PAUSE 20\n60 FOR J=0 TO 11\n70 PRINT AT 21-(J>3)-(J>7),J;\"X\";\n80 PAUSE 6\n90 NEXT J")
COLL_EDIT_16K = 2               # frames a PRINT into a collapsed 16K display takes
COLL_EDIT_1K = 6                # and a key in a collapsed 1K one's editor: its
                                # rows a frame each at most, the hints' every
                                # other frame, in turn (4), a run queued (1),
                                # the ROM's echo changing a row again (1)


def shadow_unlike(m, keep):
    """Every row of the picture's shadow but those in keep made unlike
    D_FILE (pic_busy's $FF): the sweep has them to write again."""
    a = sym128()["shadow"]
    for r in range(24):
        if r not in keep:
            o = a + (r >> 3) * 256 + (r & 7) * 32
            m.bank1[o:o + 32] = b"\xff" * 32


@zx128check
def pic_coll_edit():
    # a full 16K screen SCROLLed (collapsed now: its new line one $76),
    # then PRINT AT the bottom row, the one above and the one above that,
    # four times each, a character at a time (inserted into the collapsed
    # line; written over in the full ones): each on the VDC within
    # COLL_EDIT_16K frames of DF_CC's move, with the sweep busy (every row
    # but the hints', DF_CC's and the one above, unlike the shadow). And a
    # collapsed 1K screen's editor, keys typed with the sweep busy the same
    # way (but the editor's rows): its lower screen on the VDC within
    # COLL_EDIT_1K frames of the ROM being ready for the next
    m = zx128()
    load_p(m, p_prog(COLL_EDIT))
    m.until(lambda: m.peek16(0x4010) - m.peek16(0x400C) != 24 * 33 + 1 and zx_report(m) is None
            and m.zx_screen()[20].startswith("ROW 21"), 1500, "the SCROLL")
    cc, got = m.peek16(0x400E), []
    while zx_report(m) != "0/90":
        if len(got) > 40:
            raise AssertionError("no report 0/90")
        m.until(lambda: m.peek16(0x400E) != cc or zx_report(m) == "0/90", 300, "DF_CC's move")
        cc = m.peek16(0x400E)
        a, r = m.peek16(0x400C) + 1, 0
        while a < cc:
            r += m.bank1[a] == 0x76
            a += 1
        if r > 21 or zx_report(m) == "0/90":
            continue
        shadow_unlike(m, (r - 1, r))
        got.append((r, frames_until(m, lambda: vdc_codes(m)[r] == df_codes(m)[r] or m.peek16(0x400E) != cc, 30,
                                    f"row {r} on the VDC")))
    collapsed = m.peek16(0x4010) - m.peek16(0x400C) != 24 * 33 + 1
    m = zx128()
    to_1k(m)
    keys = []
    for k in "P SHIFT+P H E L L O SHIFT+P SPACE 1 2 3".split():
        m.keys = keyset(k.split("+"))
        m.until(lambda: m.bank1[0x4027] == 0xFF, 900, f"{k} taken")
        m.keys = set()
        m.until(lambda: m.bank1[0x4027] == 0, 900, "the ROM ready for a key")
        lower = range(24 - m.bank1[0x4022], 24)
        shadow_unlike(m, lower)
        keys.append(frames_until(m, lambda: pic_same(m, lower), 60, f"{k} on the VDC"))
        m.until(lambda: m.bank1[keys_up_flag()] == 1, 900, "every key seen up")
    rows = sorted({r for r, n in got})
    check("pic_coll_edit", collapsed and rows == [19, 20, 21] and max(n for r, n in got) <= COLL_EDIT_16K
          and max(keys) <= COLL_EDIT_1K,
          f"16K, collapsed {collapsed}: PRINT on the VDC after {[n for r, n in got]} frame(s) (rows {rows}; bound "
          f"{COLL_EDIT_16K}); 1K editor: {keys} (bound {COLL_EDIT_1K}) {m.zx_screen()[23]!r}")


@zx128check
def pic_window():
    # a long mixed run (typing, SCATTER, a program going FAST and SLOW,
    # Mazogs' redraw, POKEs, SCROLLs and CLSs of a full screen, then a 1K
    # display typed and run): no VDC write made in a window (pic_unp set;
    # a character's, or a block operation's registers) lands outside the
    # blank or past LK_WIN steps after the rise, no block operation begun
    # in one is busy past the blank, none is lost, nothing is written while
    # a block operation is busy, and 90% of the IRQs at least open a window;
    # the panel's writes among them (F2 twice and F1 twice: its jobs), and
    # the panel right at the end
    sym = sym128()
    unp, lim = sym["pic_unp"], sym["lk_win"] * 256 + 40
    out, n, irqs, blk, npn = [], [0], [], [], [0]
    m = zx128()

    def on_vdc(m, kind, c, pos, ok):
        if kind[0] == "w" and m.bank1[unp]:
            n[0] += kind == "w31"
            npn[0] += m.z.pc >= sym["zcom"]               # (the panel's: panel.inc, in common RAM)
            if pos >= lim or pos >= VDC_BLANK:
                out.append((kind, round(pos)))

    def on_blk(m, c, end, copy, nb):
        if m.bank1[unp]:
            blk.append(m.vdc_pos(c) + end - c)
    m.on_vdc, m.on_blk = on_vdc, on_blk
    i0, w0 = m.irqs, WINDOWS[0]
    m.type("P SHIFT+P H E L L O SHIFT+P NEWLINE")
    m.until(lambda: zx_report(m) == "0/0", 100, "PRINT's report")
    load_p(m, p_prog("10 REM {bin:scatter}\n20 RAND USR 16514", {"scatter": scatter_code()}))
    m.until(lambda: zx_report(m) == "0/20", 600, "SCATTER's report")
    load_p(m, p_prog("10 FOR J=1 TO 3\n20 FAST\n30 FOR I=1 TO 40\n40 NEXT I\n50 SLOW\n60 FOR I=1 TO 15\n"
                     "70 PRINT AT J,0;I\n80 NEXT I\n90 NEXT J"))
    m.until(lambda: zx_report(m) == "0/90", 1500, "FAST and SLOW's report")
    load_p(m, redraw_prog("mazogs", nflip=4, wait=30))
    m.until(lambda: m.bank1[16516 + 3] != 255 and zx_report(m) == "0/20", 600, "the flips")
    load_p(m, p_prog("10 FOR I=0 TO 200\n20 POKE PEEK 16396+256*PEEK 16397+1+I*3,38\n30 NEXT I"))
    m.until(lambda: zx_report(m) == "0/30", 1500, "the POKEs' report")
    for op in (1, 2):
        load_p(m, blk_prog(op, 3)[0])
        m.until(lambda: m.bank1[16516 + 2] != 255 and zx_report(m) == "0/20", 900, "the SCROLLs and CLSs")
    for keys in (("LSHIFT", "F1"), ("LSHIFT", "F1"), ("F1",), ("F1",)):   # the panel's jobs: F2 twice,
        fkey(m, *keys)                                                   # F1 twice
        m.until(lambda: not panel_busy(m), 200, "the panel's jobs")
    to_1k(m)                                             # then a 1K display: typed, RUN
    m.type("1 0 P SHIFT+P H E L L O SHIFT+P NEWLINE")
    m.type("2 0 P SHIFT+P " + " ".join("ABCDEFGHIJKLMNOPQRSTUVWXYZ") + " SHIFT+P NEWLINE")
    m.type("R NEWLINE")
    m.until(lambda: zx_report(m) == "0/20", 300, "the 1K program's report")
    m.frames(100)
    frames, windows = m.irqs - i0, WINDOWS[0] - w0
    past = [round(e) for e in blk if e >= VDC_BLANK]
    check("pic_window", n[0] > 20000 and not out and not m.vdc_lost and pic_same(m) and windows >= 0.9 * frames
          and len(blk) > 100 and not past and not m.vdc_nblkbusy and npn[0] > 500 and panel_ok(m),
          f"{frames} IRQs, {windows} windows, {n[0]} writes in them ({npn[0]} the panel's), {len(out)} outside {out[:3]}; "
          f"{len(blk)} block operations in them, ending {max(blk or [0]):.0f} cycles after the rise at the latest "
          f"({len(past)} past the blank); lost {m.vdc_lost}, accesses while busy {m.vdc_nblkbusy}; "
          f"VDC = D_FILE {pic_same(m)}")


@zx128check
def pic_bit5_net():
    # rows 2-11 of D_FILE changed at once, then the VDC's frame jumps
    # 8,000 cycles as a window's run starts (a wrong window: its writes,
    # and its address's, lost in the display): pw_chk sees bit 5 clear
    # after the run and makes the whole shadow unlike D_FILE, so the
    # picture is D_FILE's again within bound_16k's frames (without it,
    # some cells stay wrong for good)
    sym = sym128()
    m = zx128()
    m.frames(30)
    z = m.z
    d = m.peek16(0x400C) + 1
    for r in range(2, 12):
        for c in range(32):
            m.bank1[d + 33 * r + c] = 0x26 + (r + c) % 20
    while not (z.pc == sym["pw_one"] and m.bank1[sym["pic_unp"]]):
        m.step(1)
    lost0 = m.vdc_lost
    m.vdc_phase += 8000
    m.frames(1)
    lost = m.vdc_lost - lost0
    bound = bound_16k(m)
    n = frames_until(m, lambda: pic_same(m), bound, "the picture equal to D_FILE")
    check("pic_bit5_net", lost > 0, f"{lost} writes lost in the wrong window; equal {n} frame(s) after (bound {bound})")


@zx128check
def pic_short_blank():
    # a VDC whose blank (status bit 5) is shorter than the one measured
    # (another revision, an NTSC machine), the window outliving it: bit 5
    # for 4,500 cycles (the window cut) and 2,500 (cut below LK_WMIN:
    # polled), accesses served at once to 40 before it. Rows 0-19 changed
    # once: the first trip cuts the window (lk_wcut), the shadow is
    # written again, and the picture is D_FILE's within bound_16k's
    # frames (polled: 768 / FB_CHARS + 3). Then F2 (the panel's jobs) and
    # 1,280 frames with two rows changed every 40, the window
    # winning a step back every 256 frames with no trip (and tripping
    # again where it is too long): the picture is D_FILE's before each
    # change, the cut grows again 1,280 / 256 + 2 times at most, and
    # pic_step is BUSY_US at most after; the panel right then
    global VDC_BLANK, VDC_FAST
    sym = sym128()
    keep, got, ok = (VDC_BLANK, VDC_FAST), [], True
    try:
        for blank, polled in ((4500, False), (2500, True)):
            VDC_BLANK, VDC_FAST = blank, blank - 40
            m = zx128()
            m.frames(30)
            d = m.peek16(0x400C) + 1
            for r in range(20):
                for c in range(32):
                    m.bank1[d + 33 * r + c] = 0x26 + (r + c) % 20
            bound = bound_16k(m)                         # (polled: the whole shadow made
            if polled:                                   # unlike, FB_CHARS characters a frame)
                bound = max(bound, -(-768 // sym["fb_chars"]) + 3)
            n = frames_until(m, lambda: pic_same(m), bound, f"the picture equal to D_FILE (bit 5 {blank})")
            cut0 = m.bank1[sym["lk_wcut"]]
            first = cut0 > 0 and (cut0 >= sym["lk_win"] - sym["lk_wmin"] + 1) == polled
            prev, grows, steps, wrong = cut0, 0, 0, 0
            m.keys = keyset(["LSHIFT", "F1"])            # (F2: the panel's jobs in the short blank too)
            for f in range(1280):
                if f == 5:
                    m.keys = set()
                if f % 40 == 0:
                    wrong += not pic_same(m)
                    r = f // 40 % 23
                    for rr in (r, r + 1):
                        for c in range(32):
                            m.bank1[d + 33 * rr + c] = (m.bank1[d + 33 * rr + c] + 1) & 0xBF
                m.frames(1)
                cut = m.bank1[sym["lk_wcut"]]
                grows += cut > prev
                steps += cut < prev
                prev = cut
            m.frames(40)
            t = max(x for x, u in pic_t(m, 40))
            got.append(f"bit 5 {blank}: equal {n} frame(s) after (bound {bound}), cut {cut0} steps"
                       f"{' (polled)' if polled else ''}; then {steps} step(s) back, {grows} trip(s) cutting again, "
                       f"{wrong} of 32 checkpoints wrong, us most {t:.0f}")
            pn = panel_ok(m)
            got[-1] += f"; the panel (F2's colours) right {pn}"
            ok = ok and first and not wrong and grows <= 1280 // 256 + 2 and t <= BUSY_US and pic_same(m) and pn
    finally:
        VDC_BLANK, VDC_FAST = keep
    check("pic_short_blank", ok, "; ".join(got))


# ---- the panel (z80/panel.inc)
PANEL_SET = 12                  # frames a setting's rows may take to show
PANEL_REP = 70                  # frames the whole panel and every attribute may take, drawn again (PN_REPW 32 first)
PANEL_COLS_N = 30               # frames F2's colours may take


def panel_text_rows(m):
    return [m.vdc_text(r, 64, 16).rstrip() for r in range(25)]


def fkey(m, *names, frames=5):
    """F-keys (C64NAMES') held for a few frames, then let go."""
    m.keys = keyset(names)
    m.frames(frames)
    m.keys = set()
    m.frames(3)


@zx128check
def panel_text():
    # the panel at boot, done before the first key wait (the K cursor):
    # every row of the contents (row 0 with the version, row 24
    # " Z80", no placeholders), row 9 "F8 memory  16K", row 23 " SLOW"
    # (the size only on row 9), every panel row in
    # the panel's attribute (none dim), row 24's columns 0-63 spaces, the
    # attributes as the scheme has them
    # in scheme 0, white on black, from the 8502's set-up on
    # (R26 and the picture's attributes before the Z80's first frame)
    sym = sym128()
    m = zx128(frames=1)
    r26, pic, nrm = PANEL_COLS[0]
    early = (m.vdc[26], m.vram[0x800], m.vram[0x800 + 24 * 80])
    done = frames_until(m, lambda: not panel_busy(m) and not panel_bad(m), 400, "the panel at boot") + 1
    k = frames_until(m, lambda: m.zx_screen()[23].startswith("k"), 400, "the K cursor") + done
    want = {**PANEL_TEXT, 4: "F3 joy  5678+0", 9: "F8 memory  16K", 23: " SLOW"}
    rows = panel_text_rows(m)
    wrong = [(r, rows[r]) for r in range(25) if rows[r] != want.get(r, "")]
    attrs = [m.vram[0x800 + r * 80 + 64] for r in range(25)]
    dim_ok = all(a == nrm for a in attrs)
    check("panel_text", m.vdc_text(9, 64, 16).rstrip() == "F8 memory  16K" and not wrong and dim_ok and done < k
          and panel_ok(m) and not m.bank1[sym["hello"]] and m.bank1[sym["scheme"]] == 0
          and early == (r26, pic, nrm),
          f"drawn {done} frame(s) after the reset, the K cursor at {k}; rows wrong {wrong[:3]}; attributes "
          f"{''.join('.' if a == nrm else '?' for a in attrs)}; {len(panel_bad(m))} cells off; "
          f"scheme {m.bank1[sym['scheme']]}, at the first frame R26 and attributes "
          f"{' '.join(f'${v:02X}' for v in early)}")


@zx128check
def panel_cpu():
    # Row 24 of the panel: the CPU that has the machine, as the
    # LED mod shows it on the C64 cartridge. " Z80" at the start; " 8502"
    # while the 8502 serves LOAD (as it writes the loading row); " Z80"
    # once it has handed back. And at once (no panel job: F7 in 32K runs
    # the ZX81's RAM test with interrupts off for seconds after the 8502
    # put the ROM back): every frame from the one after the ROM is back
    # to the K cursor " Z80" (the frame it comes back in may end within
    # a row's write)
    m = zx128()
    boot = m.vdc_text(24, 64, 16).strip()
    seen = []
    m.on_vdc8502 = lambda m, r, v, a: seen.append(m.vdc_text(24, 64, 16).strip()) if not seen else None
    m.drive.files[b"SPEED"] = open(os.path.join(ROOT, "build", "obj", "zx128", "speed.p"), "rb").read()
    r = cmd128(m, "J SHIFT+P S P E E D SHIFT+P", 1500)
    m.on_vdc8502 = None
    after = m.vdc_text(24, 64, 16).strip()
    fkey(m, "LSHIFT", "F7", frames=3)                    # F8: 32K
    m.until(lambda: m.peek16(0x4004) == 0xC000, 300, "RAMTOP $C000 after F8")
    m.until(lambda: m.zx_screen()[23].startswith("k") and zx_editor(m), 600, "the K cursor after F8")
    m.bank1[0x0A00:0x0A01] = bytes([m.bank1[0x0A00] ^ 0x55])   # (the ROM written over: F7's 8502 puts it back)
    m.keys = keyset(["F7"])
    f7, started, fixed = [], False, None
    for i in range(600):
        m.frames(1)
        if i == 5:
            m.keys = set()
        if fixed is None and rom_now(m) == rom_want():
            fixed = i
        elif fixed is not None:
            f7.append(m.vdc_text(24, 64, 16).strip())
        started = started or not zx_editor(m)
        if started and m.zx_screen()[23].startswith("k") and zx_editor(m):
            break
    back = rom_now(m) == rom_want()
    odd = sorted(set(f7) - {"Z80"})
    check("panel_cpu", boot == "Z80" and seen == ["8502"] and r.startswith("0/") and after == "Z80" and back
          and not odd and len(f7) > 50 and i < 599,
          f"at the start {boot!r}; LOAD: {seen[:1]} as the 8502 wrote its row, {after!r} after ({r}); F7 in 32K: "
          f"the ROM back {back} at frame {fixed}, {len(f7)} frames on to the K cursor, row 24 otherwise {odd}")


@zx128check
def panel_f8():
    # F8 (SHIFT+F7) three times: row 9 ends 32K and row 23 is " SLOW"
    # (no size there), then 1K, then 16K again, within PANEL_SET frames of the ZX81
    # starting (RAMTOP set); F7 keeps it, the panel right after it too
    sym = sym128()
    m = zx128()
    got, ok = [], True
    for top, size in ((0xC000, "32K"), (0x4400, "1K"), (0x8000, "16K"), (0x8000, "16K")):
        f7 = len(got) == 3
        fkey(m, *(["F7"] if f7 else ["LSHIFT", "F7"]), frames=3)
        if f7:
            m.until(lambda: m.peek16(0x4004) != top, 300, "the ZX81 starting again")
        m.until(lambda: m.peek16(0x4004) == top, 300, f"RAMTOP ${top:04X}")
        n = frames_until(m, lambda: m.vdc_text(9, 64, 16).rstrip().endswith(size)
                         and m.vdc_text(23, 64, 16).rstrip() == " SLOW", 300, f"{size} on the panel")
        m.until(lambda: m.zx_screen()[23].startswith("k") and m.bank1[0x4027] == 0, 600, "the K cursor")
        right = panel_ok(m)
        got.append(f"{'F7' if f7 else 'F8'} {size} after {n}{'' if right else ' (panel wrong)'}")
        ok = ok and n <= PANEL_SET and right
    check("panel_f8", ok, f"{'; '.join(got)} frame(s) (bound {PANEL_SET})")


@zx128check
def panel_f8_now():
    # F8, F7, and F8 in a FAST program (BREAK-1's f7brk): while
    # the ROM's RAM test runs (RAM-FILL, then RAM-READ, where this looks:
    # interrupts off, no IRQ to draw the panel), rows 13-14 show the size's message already and
    # row 9 the new size (reset.inc's rs_show: polled, before the restart)
    sym = sym128()
    m = zx128()
    m.frames(20)
    got, ok = [], True
    for keys, size, top, fast in ((("LSHIFT", "F7"), "32K", 0xC000, False), (("F7",), "32K", 0xC000, False),
                                  (("LSHIFT", "F7"), "1K", 0x4400, True)):
        if fast:
            load_p(m, p_prog("10 FAST\n20 GOTO 20"))
            m.frames(20)
        m.until(lambda: not (m.vdc_text(13, 64, 16) + m.vdc_text(14, 64, 16)).strip(), 300,
                "the message rows empty")                # (the last message's time over)
        m.keys = keyset(keys)
        m.until(lambda: sym["rs_up"] <= m.z.pc < sym["rs_up"] + 16, 30, "reset.inc's wait for the key up")
        m.keys = set()
        m.until(lambda: 0x03D5 <= m.z.pc < 0x03E2, 100, "the ROM's RAM test")   # (RAM-READ: RAM-FILL done)
        msg = (m.vdc_text(13, 64, 16) + m.vdc_text(14, 64, 16)).upper()
        row9 = m.vdc_text(9, 64, 16).rstrip()
        good = f"{size} RAM" in msg and row9.endswith(size)
        got.append(f"{'+'.join(keys)}{' (FAST)' if fast else ''}: {msg.strip()!r}, row 9 {row9!r}")
        ok = ok and good
        m.until(lambda: m.peek16(0x4004) == top, 300, f"RAMTOP ${top:04X}")
        m.until(lambda: m.z.iff1, 600, "the interrupts on again")   # (the restart's RAM test over:
        m.until(lambda: m.zx_screen()[23].startswith("k") and m.bank1[0x4027] == 0, 600, "the K cursor")
        m.frames(25)                            # F7 in 32K keeps RAMTOP, and the old screen's K shows
                                                # before it; then the ROM settled before the next key)
    check("panel_f8_now", ok and panel_ok(m), "in the RAM test: " + "; ".join(got))


@zx128check
def panel_fastprog():
    # FAST in a running program (SET-FAST turns the interrupts off: no IRQ
    # to do the panel's jobs): row 23 says FAST at once, not at the next
    # key wait
    m = zx128()
    m.frames(20)
    load_p(m, p_prog("10 FAST\n20 GOTO 20"))
    m.until(lambda: not m.bank1[0x403B] & 0x40, 300, "FAST")
    n = frames_until(m, lambda: m.vdc_text(23, 64, 16).rstrip() == " FAST", 10, "row 23 FAST")
    check("panel_fastprog", n <= 2, f"row 23 FAST {n} frame(s) after the program's FAST")


@zx128check
def panel_slowfast():
    # FAST typed: row 23 says FAST; SLOW: SLOW again
    m = zx128()
    got = []
    for key, word in (("SHIFT+F", "FAST"), ("SHIFT+D", "SLOW")):
        m.type(f"{key} NEWLINE")
        m.until(lambda: bool(m.bank1[0x403B] & 0x40) == (word == "SLOW"), 100, word)
        got.append(frames_until(m, lambda: m.vdc_text(23, 64, 16).rstrip().endswith(word), PANEL_SET, word))
    check("panel_slowfast", panel_ok(m), f"FAST shown {got[0]} frame(s) after, SLOW {got[1]} (bound {PANEL_SET})")


@zx128check
def panel_msg():
    # F1 (the type-ahead off): its message ("TYPE-AHEAD OFF", zx128's own
    # text) on rows 13-14, not over the
    # picture (VDC = D_FILE, row 0 too), for as long as ovl runs, then the
    # rows empty again
    sym = sym128()
    m = zx128()
    m.frames(20)
    fkey(m, "F1")
    n = frames_until(m, lambda: "type-ahead off" in m.vdc_text(13, 64, 16) + m.vdc_text(14, 64, 16), PANEL_SET,
                     "the message")
    shown = m.vdc_text(13, 64, 16) + "|" + m.vdc_text(14, 64, 16)
    same = pic_same(m)
    whole = not panel_bad(m)
    m.until(lambda: not m.bank1[sym["ovl"]], 200, "the message's time over")
    gone = frames_until(m, lambda: not (m.vdc_text(13, 64, 16).strip() + m.vdc_text(14, 64, 16).strip()), PANEL_SET,
                        "the message rows empty")
    short = "zx81" not in shown                      # zx128's own text: no ", AS A ZX81"
    check("panel_msg", short and same and pic_same(m) and m.bank1[sym["kbuf"]] == 0 and panel_ok(m),
          f"shown {n} frame(s) after F1: {shown!r} (whole {whole}); VDC = D_FILE {same}; empty {gone} frame(s) "
          f"after ovl ran out (bound {PANEL_SET})")


@zx128check
def panel_f2():
    # F2 (SHIFT+F1) four times round: each scheme's R26 and attributes (the
    # picture's, the panel's) within PANEL_COLS_N frames, the
    # panel's foregrounds not the background, its name in the message
    # (PANEL_NAMES: zx128's own); back to white on black. Then F2
    # once more, F7 and F8: the ZX81 starts again in that scheme each time.
    # PANEL_COLS_N is for an idle screen, as here: while the picture is busy
    # (pic_bsy: a job a frame in the window, none without it) F2's repaint
    # takes ~140-220 frames (SCATTER: 141 with the window, 216 without)
    sym = sym128()
    m = zx128()
    m.frames(20)
    got, ok = [], True
    for i in range(len(PANEL_COLS)):
        fkey(m, "LSHIFT", "F1")
        s = m.bank1[sym["scheme"]]
        n = frames_until(m, lambda: not panel_busy(m) and not panel_bad(m), PANEL_COLS_N, f"scheme {s}")
        r26, pic, nrm = PANEL_COLS[s]
        readable = nrm & 15 != r26 & 15 and pic & 15 != r26 & 15
        msg = (m.vdc_text(13, 64, 16) + m.vdc_text(14, 64, 16)).upper()
        named = PANEL_NAMES[s] in msg
        got.append(f"{s}: {n}{'' if named else ' (' + msg.strip() + ')'}")
        ok = ok and s == (i + 1) % len(PANEL_COLS) and readable and named and m.vdc[26] == r26 and pic_same(m)
    fkey(m, "LSHIFT", "F1")
    m.frames(20)
    fkey(m, "F7", frames=3)
    m.until(lambda: m.peek16(0x4004) != 0x8000, 300, "the ZX81 starting again")
    m.until(lambda: m.zx_screen()[23].startswith("k") and m.bank1[0x4027] == 0, 600, "the K cursor after F7")
    f7 = (m.bank1[sym["scheme"]], m.vdc[26])
    fkey(m, "LSHIFT", "F7", frames=3)                    # F8: 32K, the ZX81 started again
    m.until(lambda: m.peek16(0x4004) == 0xC000, 300, "RAMTOP $C000 after F8")
    m.until(lambda: m.zx_screen()[23].startswith("k") and m.bank1[0x4027] == 0, 600, "the K cursor after F8")
    f8 = (m.bank1[sym["scheme"]], m.vdc[26])
    kept = f7 == f8 == (1, PANEL_COLS[1][0])
    check("panel_f2", ok and kept and panel_ok(m), f"scheme: frames {', '.join(got)} (bound {PANEL_COLS_N}); "
          f"F7 in scheme 1: {f7[0]}, R26 ${f7[1]:02X}; F8: {f8[0]}, R26 ${f8[1]:02X}")


@zx128check
def panel_joy():
    # F3 with a layout taught (joyhave): row 4 "own keys", F3 again
    # "5678+0"
    sym = sym128()
    m = zx128()
    m.frames(20)
    m.bank1[sym["joyhave"]] = 1
    got = []
    for want in ("own keys", "5678+0"):
        fkey(m, "F3")
        got.append(frames_until(m, lambda: m.vdc_text(4, 64, 16).rstrip() == f"F3 joy  {want}", PANEL_SET, want))
    check("panel_joy", panel_ok(m), f"own keys {got[0]} frame(s) after F3, 5678+0 {got[1]} (bound {PANEL_SET})")


@zx128check
def panel_repaint():
    # pic_bit5_net with the panel's cells and some attributes hit first (as
    # a write in a wrong window can): the wrong window's run trips pw_chk,
    # which has the panel draw everything again (after PN_REPW frames: the
    # picture first): right within PANEL_REP frames of the picture. Then
    # the same with the wrong window in the panel's own run (F3, a layout
    # taught: row 4's text, unpolled): its bit 5 test after the run trips
    # pw_chk the same way
    sym = sym128()
    got, ok = [], True
    for case in ("the picture's run", "the panel's run"):
        m = zx128()
        m.frames(30)
        z = m.z
        for a in list(range(64, 80)) + list(range(9 * 80 + 64, 9 * 80 + 80)) + list(range(24 * 80, 24 * 80 + 8)):
            m.vram[a] = 0x2A
        for a in (0x800 + 5, 0x800 + 13 * 80 + 70, 0x800 + 24 * 80 + 3):
            m.vram[a] = 0x47
        d = m.peek16(0x400C) + 1
        for r in range(2, 12):
            for c in range(32):
                m.bank1[d + 33 * r + c] = 0x26 + (r + c) % 20
        if case == "the panel's run":
            m.bank1[sym["joyhave"]] = 1
            m.keys = keyset(["F3"])
            at = sym["pw_c"]
        else:
            at = sym["pw_one"]
        while not (z.pc == at and m.bank1[sym["pic_unp"]]):
            m.step(1)
        m.keys = set()
        lost0 = m.vdc_lost
        m.vdc_phase += 8000
        m.frames(1)
        lost = m.vdc_lost - lost0
        rep = m.bank1[sym["pn_wait"]] > 0
        bound = bound_16k(m)
        n = frames_until(m, lambda: pic_same(m), bound, "the picture equal to D_FILE")
        p = frames_until(m, lambda: not panel_busy(m) and not panel_bad(m), PANEL_REP, "the panel right again")
        got.append(f"{case}: {lost} writes lost in the wrong window, pw_chk {rep}; the picture equal {n} frame(s) after "
                   f"(bound {bound}), the panel and the attributes {p} more (bound {PANEL_REP})")
        ok = ok and lost > 0 and rep and pic_same(m)
    if ok:
        ok = m.vdc_text(4, 64, 16).rstrip() == "F3 joy  own keys"
    check("panel_repaint", ok, "; ".join(got))


# ---------------------------------------------------------------- the disk
# LOAD, SAVE and F7's ROM through the C128 kernal (the model's
# traps, simulate.py's Drive behind them), c128/boot128.asm's server.
LOAD_ABSENT = 357 * FRAME_T     # zx128's LOAD of MAZOGS on VICE's 1571: 7.1 s
RELOCK = 12                     # frames for the lock to find the VDC's blank again after it (8-9
                                # measured across 12 phases: pic_all, then the search's 2-5 IRQs)
ROW13, ROW14 = 13 * 80 + 64, 14 * 80 + 64   # the panel's message rows, its columns
BAR_EMPTY, BAR_FULL = 0x08, 0x40            # the bar's cells (set 1): grey, black


def cmd128(m, keys, frames=900):
    """keys typed, then NEWLINE, once the editor waits for them (zx_editor:
    keys typed before are a program's, flushed at its key wait): the report
    the command ends with ('0/0', 'D/0'), once the editor waits again."""
    m.until(lambda: zx_editor(m), frames, "the editor")
    m.type(keys + " NEWLINE")
    m.until(lambda: zx_report(m) is not None and zx_editor(m), frames, f"the report after {keys}")
    m.frames(2)
    return zx_report(m)


def zx_editor(m):
    """The editor in its key wait (rompatch.inc's keywait: edit 1, and
    eframes under 2, as romkbd.inc's mirror tells it from a program's
    run: the IRQ counts eframes up, 1 a frame, while a program runs and
    frame hasn't set d1active. keywait clears it before frame sets
    d1active, so an IRQ in between can leave the idle key wait at 1:
    harmless, a race not to be waited out)."""
    if not EDIT_AT:
        sym = sym128()
        EDIT_AT[:] = [sym["edit"], sym["eframes"]]
    return m.bank1[EDIT_AT[0]] == 1 and m.bank1[EDIT_AT[1]] < 2


EDIT_AT = []                    # (zx_editor's edit and eframes)


def load128(m, name, frames=100):
    """LOAD "name" typed, NEWLINE held until the 8502 has opened the file
    (as load_p): for a game, which runs as it loads and never reports."""
    m.type("J SHIFT+P " + " ".join(name) + " SHIFT+P")
    opens = m.drive.opens
    m.keys = keyset(["NEWLINE"])
    m.until(lambda: m.drive.opens > opens, frames, f'LOAD "{name}"')
    m.keys = set()


def log8502(m):
    """[(VDC address, byte)] the 8502 writes from now on."""
    log = []
    m.on_vdc8502 = lambda m, r, v, a: log.append((a, v)) if r == 31 else None
    return log


def row_text(codes):
    """Set 1's codes as vdc_text shows them (inverse ZX81 ones lower case)."""
    return "".join(ZX[c & 0x3F].lower() if c & 0x40 else ZX[c & 0x3F] for c in codes if c < 0x80)


def bar_seen(log):
    """Row 14's writes in log: (its empty cells, then each cell filled, in
    order), and whether every write was in rows 13-14, columns 64-79."""
    row14 = [(a - ROW14, v) for a, v in log if ROW14 <= a < ROW14 + 16]
    first = next((i for i, (c, v) in enumerate(row14) if v == BAR_EMPTY), None)
    empty = first is not None and [v for c, v in row14[first:first + 16]] == [BAR_EMPTY] * 16
    full = [c for c, v in row14 if v == BAR_FULL]
    inside = all(ROW13 <= a < ROW13 + 16 or ROW14 <= a < ROW14 + 16 for a, v in log)
    return empty, full, inside


def msg_rows(m):
    return m.vdc_text(13, 64, 16).rstrip() + "|" + m.vdc_text(14, 64, 16).rstrip()


def keyrow_df(m, frames=8):
    """P held (the $DF row's bit 0) for a few frames: the IRQ's scan has it
    in KPAGE and the IN mirror's $DFFE."""
    m.keys = keyset(["P"])
    m.frames(frames)


def z80_run(m, at, stop, frames=5):
    """The Z80 from at until its PC is stop, interrupts off; then back where
    it was. Returns (A, B)."""
    z = m.z
    pc, iff1, iff2 = z.pc, z.iff1, z.iff2
    z.pc, z.iff1, z.iff2 = at, False, False
    end = m.nframes + frames
    while z.pc != stop and m.nframes < end:
        m.step(1)
    got = (z.af >> 8, z.bc >> 8)
    z.pc, z.iff1, z.iff2 = pc, iff1, iff2
    if m.nframes >= end:
        raise AssertionError(f"the Z80 never got from ${at:04X} to ${stop:04X}")
    return got


@zx128check
def load_speed():
    # LOAD "SPEED" from the drive: the 8502 reads its first 13 bytes, then
    # the whole file by the kernal's LOAD into bank 0, and copies it to
    # bank 1; it runs as it loads, as on zx64; RUN runs it again.
    # zx128's own SPEED (progs/speed.bas's C128 lines): its title, the
    # VIC's PAL or NTSC as the Z80 measured it at the start (the model's
    # VIC: PAL), no /INT line (the C64 cartridge's wire)
    speed = open(os.path.join(ROOT, "build", "obj", "zx128", "speed.p"), "rb").read()
    m = zx128()
    m.drive.files[b"SPEED"] = speed
    r = cmd128(m, "J SHIFT+P S P E E D SHIFT+P", 1500)
    first = m.zx_screen()
    r2 = cmd128(m, "R", 1500)
    scr = m.zx_screen()
    frames = next((x for x in scr if x.endswith(" FRAMES")), None)
    check("load_speed", first[0] == "ZX128 SPEED TEST" and r.startswith("0/") and scr[0] == "ZX128 SPEED TEST"
          and r2.startswith("0/") and frames is not None and not m.map_errors and speed_video(scr) == "PAL",
          f"LOAD: {first[0]!r}, {r}; RUN: {scr[0]!r}, {frames!r}, {r2}; video {speed_video(scr)!r}")


def speed_video(scr):
    """SPEED's video line on the C128 builds: "PAL" or "NTSC" from "VIC
    VIDEO:   ...", None if it isn't there or a C64 line ("C64 VIDEO",
    "/INT SEEN") is."""
    if any(x.startswith(("C64 VIDEO", "/INT SEEN")) for x in scr):
        return None
    got = [x[len("VIC VIDEO:"):].strip() for x in scr if x.startswith("VIC VIDEO:")]
    return got[0] if len(got) == 1 else None


@zx128check
def load_speed_ntsc():
    # SPEED on a C128 whose VIC is NTSC's (263 lines, ntsc_vic)
    # as zx128 starts (vidpal.inc measures it then): "VIC VIDEO:   NTSC".
    # The VIC PAL's again once zx128 is up: its tick on the model's VDC
    # (50 Hz) with an NTSC VIC's raster IRQ takes no keys here (not a
    # pairing the model has to have: SPEED's line is what this checks)
    m = zx128(ntsc=True)
    del m.line, m._next_cmp
    m.next_irq_t = m._next_cmp(m.now_t() + 1)
    m.drive.files[b"SPEED"] = open(os.path.join(ROOT, "build", "obj", "zx128", "speed.p"), "rb").read()
    r = cmd128(m, "J SHIFT+P S P E E D SHIFT+P", 1500)
    scr = m.zx_screen()
    check("load_speed_ntsc", r.startswith("0/") and speed_video(scr) == "NTSC",
          f"{r}; video {speed_video(scr)!r}; {scr[:4]}")


@zx128check
def save_roundtrip():
    # SAVE "T": $4009 up to E_LINE, " SAVING  T" on row 13 and the bar on
    # row 14 as it goes; NEW, LOAD "T": the same program, RUN as before;
    # SAVE "T" again replaces it ("@0:"); a write-protected disk: report D,
    # the drive's words on rows 13-14
    m = zx128()
    for line in ("1 0 P SHIFT+P O K SHIFT+P", "2 0 P SHIFT+P B SHIFT+P"):
        m.type(line + " NEWLINE")
    log = log8502(m)
    vars_, dfile = m.peek16(0x4010), m.peek16(0x400C)
    prog = bytes(m.bank1[0x407D:dfile])
    r = cmd128(m, "S SHIFT+P T SHIFT+P")
    eline = m.peek16(0x4014)
    t = m.drive.files.get(b"T", b"")
    words = row_text([v for a, v in log if ROW13 <= a < ROW13 + 16][:16])
    empty, full, inside = bar_seen(log)
    m.on_vdc8502 = None
    m.type("A NEWLINE")                                  # NEW
    m.frames(5)
    r2 = cmd128(m, "J SHIFT+P T SHIFT+P")
    same = bytes(m.bank1[0x407D:m.peek16(0x400C)]) == prog and m.peek16(0x4014) == eline
    r3 = cmd128(m, "R")
    scr = m.zx_screen()
    m.type("3 0 P SHIFT+P C SHIFT+P NEWLINE")
    r4 = cmd128(m, "S SHIFT+P T SHIFT+P")
    over = len(m.drive.files.get(b"T", b"")) == m.peek16(0x4014) - 0x4009 > len(t)
    m.drive.protected = True
    r5 = cmd128(m, "S SHIFT+P W SHIFT+P")
    m.drive.protected = False
    m.until(lambda: "write protect" in m.vdc_text(13, 64, 16), PANEL_SET, "the drive's words")
    m.frames(2)
    msg = msg_rows(m)
    m.until(lambda: pic_same(m), 30, "VDC = D_FILE")
    check("save_roundtrip", r == "0/0" and len(t) == eline - 0x4009 and t[0x407D - 0x4009:dfile - 0x4009] == prog
          and words.rstrip() == " saving  t" and empty and full == list(range(16)) and inside
          and r2 == "0/0" and same and r3 == "0/20" and scr[:2] == ["OK", "B"] and r4 == "0/0" and over
          and r5.startswith("D/") and msg == "write protect on|26,00,00" and pic_same(m) and panel_ok(m),
          f"SAVE {r}, {len(t)} bytes (E_LINE-$4009 {eline - 0x4009}), row 13 {words!r}, the bar empty {empty} then "
          f"filled {full}, only rows 13-14 {inside}; LOAD {r2}, the same {same}; RUN {r3} {scr[:2]}; SAVE again {r4}, "
          f"replaced {over}; write-protected {r5} {msg!r}")


@zx128check
def load_versn():
    # a .P with VERSN 1 (some TOSEC files have it; the ROM never reads it)
    # loads as any other
    m = zx128()
    p = bytearray(p_prog('10 PRINT "OK"'))
    p[0] = 1
    m.drive.files[b"V1"] = bytes(p)
    r = cmd128(m, "J SHIFT+P V 1 SHIFT+P")
    eline = p[0x4014 - 0x4009] | p[0x4015 - 0x4009] << 8
    check("load_versn", r.startswith("0/") and m.peek16(0x4014) == eline, f"{r}, E_LINE ${m.peek16(0x4014):04X}")


@zx128check
def load_missing():
    # LOAD "NOPE": NOPE, then NOPE.P, neither there: report D; " LOADING
    # NOPE" on row 13 meanwhile, no bar (no data came); the drive's status
    # on rows 13-14 (its words, its numbers) for ovl's 2 seconds, then
    # the rows empty again; the picture untouched
    m = zx128()
    names, real = [], m.drive.open

    def opened(name, sa):
        names.append(name)
        return real(name, sa)
    m.drive.open = opened
    log = log8502(m)
    r = cmd128(m, "J SHIFT+P N O P E SHIFT+P")
    words = row_text([v for a, v in log if ROW13 <= a < ROW13 + 16][:16])
    empty, full, inside = bar_seen(log)
    blank14 = all(v == 0x80 for a, v in log if ROW14 <= a < ROW14 + 16)
    n = frames_until(m, lambda: msg_rows(m) == "file not found|62,00,00", PANEL_SET, "the drive's status")
    same = frames_until(m, lambda: pic_same(m), 20, "VDC = D_FILE")
    m.until(lambda: not m.bank1[sym128()["ovl"]], 200, "the message's time over")
    gone = frames_until(m, lambda: msg_rows(m) == "|", PANEL_SET, "the rows empty")
    m.frames(2)                                          # (a row's run may be half done)
    check("load_missing", r.startswith("D/") and names == [b"NOPE", b"NOPE.P", b""] and words == " loading nope   "
          and not empty and not full and blank14 and inside and pic_same(m) and panel_ok(m),
          f"{r}; opened {names}; row 13 {words!r}, row 14 blank {blank14} (bar {empty} {full}); the status shown "
          f"{n} frame(s) after; VDC = D_FILE {same} frame(s) after; empty {gone} frame(s) after ovl ran out")


@zx128check
def load_too_big():
    # a 32K-sized program (E_LINE $9000) on 16K: report 4 from its first
    # 13 bytes, E_LINE and the program unchanged (nothing read past them);
    # a program that fits but trails more than BUF holds: the kernal's
    # LOAD stopped before BUFEND (its STOP), report 4, nothing changed;
    # with 32K (F8) BIG loads, into $4000-$BFFF
    m = zx128()
    small = p_prog('10 PRINT "OK"')
    big = bytearray(small)
    big[0x4014 - 0x4009:0x4016 - 0x4009] = (0x9000).to_bytes(2, "little")
    big[0x4029 - 0x4009:0x402B - 0x4009] = big[0x400C - 0x4009:0x400E - 0x4009]   # (NXTLIN at D_FILE: it stops)
    m.drive.files[b"BIG"] = bytes(big) + bytes(0x9000 - 0x4009 - len(big))
    m.drive.files[b"JUNK"] = small + bytes(60000)
    m.type("1 0 P SHIFT+P K SHIFT+P NEWLINE")
    eline, dfile = m.peek16(0x4014), m.peek16(0x400C)
    prog = bytes(m.bank1[0x407D:dfile])
    got = []
    for name in ("BIG", "JUNK"):
        r = cmd128(m, "J SHIFT+P " + " ".join(name) + " SHIFT+P")
        got.append((r, m.peek16(0x4014) == eline and bytes(m.bank1[0x407D:m.peek16(0x400C)]) == prog))
    r = cmd128(m, "R")
    run = m.zx_screen()[0]
    fkey(m, "LSHIFT", "F7", frames=3)                    # F8: 32K, and BIG fits ($4000-$BFFF)
    m.until(lambda: m.peek16(0x4004) == 0xC000, 300, "RAMTOP $C000")
    m.until(lambda: m.zx_screen()[23].startswith("k") and zx_editor(m), 600, "the K cursor")
    r32 = cmd128(m, "J SHIFT+P B I G SHIFT+P")
    fits = m.peek16(0x4014) == 0x9000 and bytes(m.bank1[0x407D:m.peek16(0x400C)]) == big[0x407D - 0x4009:m.peek16(0x400C) - 0x4009]
    r32run = cmd128(m, "R")
    check("load_too_big", [g[0][:2] for g in got] == ["4/", "4/"] and all(g[1] for g in got) and run == "K"
          and r32 == "0/0" and fits and m.zx_screen()[0] == "OK",
          f"BIG {got[0]}, JUNK {got[1]} (report, E_LINE and the program unchanged); RUN {r} {run!r}; "
          f"32K: BIG {r32}, E_LINE ${m.peek16(0x4014):04X} and the program as the file {fits}, RUN {r32run} {m.zx_screen()[0]!r}")


@zx128check
def load_bar():
    # LOAD "MAZOGS" (51 blocks), the 8502 away as long as on VICE's 1571
    # (7.1 s): " LOADING MAZOGS" on row 13; on row 14 the empty bar once
    # data has come, its 16 cells filled in order as the kernal's LOAD
    # goes (its STOP, a block at a time); the 8502 writes nowhere else;
    # the program as the file has it, up to E_LINE; then the picture at
    # once (pn_blit), the lock found again (a window), VDC = D_FILE, the
    # panel right, no write in a window outside the blank
    sym, b8 = sym128(), sym8502()
    game = simulate.game("mazogs.p", "load_bar")
    if game is None:
        return
    eline = game[11] | game[12] << 8
    m = zx128()
    m.drive.files[b"MAZOGS"] = game
    m.absent_t = LOAD_ABSENT
    log, snap = log8502(m), []

    def at_answer(m):
        snap.append(bytes(m.bank1[0x4009:eline]))
        back.append((m.nframes, WINDOWS[0]))
        m.cpu.step()
    back = []
    m.traps8502[b8["answer"]] = at_answer
    out, lim = [], sym["lk_win"] * 256 + 40

    def on_vdc(m, kind, c, pos, ok):
        if kind[0] == "w" and m.bank1[sym["pic_unp"]] and (pos >= lim or pos >= VDC_BLANK):
            out.append((kind, round(pos)))
    m.on_vdc = on_vdc
    load128(m, "MAZOGS")
    del m.traps8502[b8["answer"]]
    words = row_text([v for a, v in log if ROW13 <= a < ROW13 + 16][:16])
    empty, full, inside = bar_seen(log)
    (f0, w0), = back                                     # (the frame and the windows as the 8502 answered:
    away = LOAD_ABSENT // FRAME_T                         # the LOAD's frames after it, absent_t)
    m.until(lambda: WINDOWS[0] > w0, away + 60, "a window after the LOAD")
    relock = m.nframes - f0 - away
    pic = frames_until(m, lambda: pic_same(m), 60, "VDC = D_FILE") + relock
    m.frames(300)
    check("load_bar", words == " loading mazogs " and empty and full == list(range(16)) and inside
          and snap == [game[:eline - 0x4009]] and relock <= RELOCK and m.bank1[sym["lk_on"]] == 1 and not out
          and not m.vdc_lost
          and panel_ok(m) and not m.map_errors,
          f"row 13 {words!r}; row 14 empty {empty}, then cells {full}; only rows 13-14 {inside}; the program as the "
          f"file {snap == [game[:eline - 0x4009]]}; {away} frames away, then a window {relock} frame(s) after the "
          f"Z80 has the machine again (bound {RELOCK}), VDC = D_FILE after {pic}; "
          f"{len(out)} writes in a window outside the blank, lost {m.vdc_lost}")


def rom_now(m):
    """Bank 1's ROM from $0005, but KALL's byte ($00FE: the IN mirror's)."""
    rom = bytearray(m.bank1[0x0005:0x2000])
    rom[0xFE - 5] = 0
    return bytes(rom)


def rom_want():
    rom = bytearray(open(os.path.join(ROOT, "build", "obj", "zx128rom.bin"), "rb").read()[0x0005:0x2000])
    rom[0xFE - 5] = 0
    return bytes(rom)


def f7_k(m):
    """F7, and the ZX81 started again: out of the editor, then back."""
    fkey(m, "F7")
    m.until(lambda: not zx_editor(m), 100, "the ZX81 starting again")
    m.until(lambda: m.zx_screen()[23].startswith("k") and zx_editor(m), 600, "the K cursor after F7")


@zx128check
def f7_repairs_rom_128():
    # POKE 15 (aydemo's OUT ($0F),A with A = 0 writes $000F) and bytes
    # here and there in the ROM, then F7: romsum sees it, the 8502 puts
    # the boot file's copy (still in its bank 0) back, no disk; the ROM
    # adds up again, BASIC works, F7 again does nothing more
    m = zx128()
    v = m.bank1[0x000F] ^ 0x55
    cmd128(m, f"O 1 5 SHIFT+. {' '.join(str(v))}")
    for a in (0x0100, 0x0A00, 0x1234):
        m.bank1[a:a + 1] = bytes([m.bank1[a] ^ 0x55])
    m.bank1[0:2] = b"\x12\x34"                           # (and $0000/$0001, the 8502's port's addresses)
    hurt = rom_now(m) != rom_want()
    opens = m.drive.opens
    f7_k(m)
    back = rom_now(m) == rom_want()
    zero = bytes(m.bank1[0:2]) == rom_page01()[0:2]
    r = cmd128(m, "P 1 SHIFT+K 1")
    two = m.zx_screen()[0]
    f7_k(m)
    check("f7_repairs_rom_128", hurt and back and zero and two == "2" and r == "0/0" and m.drive.opens == opens
          and rom_now(m) == rom_want() and m.port8502 == bytearray(2),
          f"ROM {'back' if back else 'still wrong'} (written over {hurt}), $0000/$0001 {zero}, the 8502's port "
          f"{m.port8502.hex()}; PRINT 1+1 {two!r} {r}; {m.drive.opens - opens} opens")


def rom_page01():
    return open(os.path.join(ROOT, "build", "obj", "zx128rom.bin"), "rb").read()[:0x200]


@zx128check
def f7_from_disk():
    # the boot file's copy in bank 0 written over too: F7 reads ZX128 from
    # the drive (the bar on row 14), puts its ROM back, the bank-0 copy
    # too (F7 again: no disk)
    b8 = sym8502()
    m = zx128()
    prom = b8["prom"]
    m.bank0[prom + 0x0100] ^= 0x55
    m.bank1[0x0100:0x0101] = bytes([m.bank1[0x0100] ^ 0x55])
    m.drive.files[b"ZX128"] = open(PRG, "rb").read()
    log = log8502(m)
    opens = m.drive.opens
    f7_k(m)
    back = rom_now(m) == rom_want()
    copy = bytes(m.bank0[prom + 5:prom + 0x2000]) == open(os.path.join(ROOT, "build", "obj", "zx128rom.bin"),
                                                           "rb").read()[5:]
    words = row_text([v for a, v in log if ROW13 <= a < ROW13 + 16][:16])
    empty, full, inside = bar_seen(log)
    m.bank1[0x0100:0x0101] = bytes([m.bank1[0x0100] ^ 0x55])
    f7_k(m)
    again = rom_now(m) == rom_want()
    r = cmd128(m, "P 1 SHIFT+K 1")
    check("f7_from_disk", back and copy and m.drive.opens == opens + 1 and words == " loading zx128  " and empty
          and full == list(range(16)) and inside and again and m.zx_screen()[0] == "2",
          f"ROM {'back' if back else 'still wrong'}, bank 0's copy {copy}; {m.drive.opens - opens} opens; row 13 "
          f"{words!r}, the bar {empty} {full}; F7 again: ROM back {again}, PRINT 1+1 {m.zx_screen()[0]!r} {r}")


@zx128check
def f7_both_bad():
    # the ROM and its bank-0 copy written over (a glyph), and on the
    # drive no ZX128 (no bar: no data came), another build's (the bar
    # across it), or zx128's own sum written over (romsum_v: no disk
    # then): why, on the panel's rows 13-14; the ZX81 starts with the ROM
    # as it is and BASIC works
    sym, b8 = sym128(), sym8502()
    prg = open(PRG, "rb").read()
    other = bytearray(prg)
    other[2 + b8["prom"] - 0x1300 + 0x0400] ^= 0xFF
    m = zx128()
    m.bank0[b8["prom"] + 0x1F00] ^= 0x55
    m.bank1[0x1F00:0x1F01] = bytes([m.bank1[0x1F00] ^ 0x55])
    hurt = rom_now(m)
    got, ok = [], True
    for files, sv, want, nopen in (({}, 0, "rom not reloaded| no zx128", 1),
                                   ({b"ZX128": bytes(other)}, 0, "rom not reloaded| other zx128", 1),
                                   ({b"ZX128": prg}, 1, " zx128 changed:| load it again", 0)):
        m.drive.files.pop(b"ZX128", None)
        m.drive.files.update(files)
        m.bank1[sym["romsum_v"]:sym["romsum_v"] + 1] = bytes([m.bank1[sym["romsum_v"]] ^ sv])
        opens = m.drive.opens
        log = log8502(m)
        fkey(m, "F7")
        n = frames_until(m, lambda: msg_rows(m) == want, 300, f"{want!r} on the panel")
        empty, full, inside = bar_seen(log)
        m.on_vdc8502 = None
        m.until(lambda: m.zx_screen()[23].startswith("k") and zx_editor(m), 600, "the K cursor")
        m.bank1[sym["romsum_v"]:sym["romsum_v"] + 1] = bytes([m.bank1[sym["romsum_v"]] ^ sv])
        r = cmd128(m, "P 1 SHIFT+K 1")
        bar = empty and full == list(range(16)) if "other" in want else not empty and not full
        good = rom_now(m) == hurt and m.zx_screen()[0] == "2" and m.drive.opens - opens == nopen and bar and inside
        got.append(f"{want.split('|')[1].strip()!r} after {n}, {m.drive.opens - opens} opens, the bar "
                   f"{'filled' if full == list(range(16)) else 'none' if not empty else 'empty'}, PRINT 1+1 "
                   f"{m.zx_screen()[0]!r} {r}{'' if good else ' (WRONG)'}")
        ok = ok and good
    m.until(lambda: pic_same(m), 30, "VDC = D_FILE")
    check("f7_both_bad", ok and panel_ok(m), "; ".join(got))


@zx128check
def load_patches():
    # BoulderL loaded: its reads of the Y-P row ($DF, I/O 2 on the C128)
    # patched (build.py's patches_load128): with P held, the menu's
    # (LD A,($DFFE)), the game's (CALL inrow) and REDEFINE KEYS' (CALL
    # zxin) see P, and only P; a BoulderL with one of those bytes changed is
    # left as it is, all of it; aydemo's OUT ($0F),A gone: a few hundred
    # frames of it write nothing from $C000 up; SAVE writes the bytes as
    # they were (aydemo stopped after its LOAD)
    import build
    sym = sym128()
    boulder = simulate.game("BoulderL.p", "load_patches")
    ay = simulate.game("test/aydemo.p", "load_patches")      # (not on the disk)
    if boulder is None or ay is None:
        return
    tab = dict((what.split(":")[0], ents) for what, ents in build.patches_load128(sym))

    def placed(m, ents, new=True):
        return all(bytes(m.bank1[a:a + len(n)]) == (bytes(n) if new else bytes.fromhex(o)) for a, o, n in ents)
    m = zx128()
    m.drive.files[b"BL"] = boulder
    load128(m, "BL")
    m.frames(20)
    inb = placed(m, tab["BoulderL"])
    keyrow_df(m)
    menu = z80_run(m, 0x75A7, 0x75AB)[0]                  # LD A,($DFFE) / NOP
    game = z80_run(m, 0x6085, 0x608D)[0]                  # LD HL,$40F9 / CALL inrow / INC HL / AND (HL)
    redef = z80_run(m, 0x7A83, 0x7A93)                     # REDEFINE KEYS' scan: A the keys, B the row
    m.keys = set()
    m.frames(8)
    game_up = z80_run(m, 0x6085, 0x608D)[0]
    m.joy = {"right", "fire"}                            # the stick (5678+0): 8 and 0, both on row $EF,
    m.frames(8)                                          # both held for the game's reads, as on zx64
    two = (z80_run(m, 0x64C0, 0x64C8)[0], z80_run(m, 0x6513, 0x651B)[0])   # its 8 ($40F1), its 0 ($40F7)
    m.joy = set()
    m.frames(8)
    m = zx128()
    odd = bytearray(boulder)
    odd[0x64C3 - 0x4009] = 0x7F                           # one of the game's reads: LD A,A, not LD A,(HL)
    m.drive.files[b"BL"] = bytes(odd)
    load128(m, "BL")
    m.frames(5)
    alone = bytes(m.bank1[0x4009:0x4009 + len(odd) - 1]) == bytes(odd[:-1]) or placed(m, tab["BoulderL"][:1], False)
    m = zx128()
    m.drive.files[b"AY"] = ay
    high = []

    def out(port, v):
        if port >= 0xC000 and 0x4000 <= m.z.pc < 0xC000:
            high.append((m.z.pc, port))
        m.z_out(port, v)
    m.z.set_output_callback(out)
    load128(m, "AY")
    m.frames(400)
    ayin = placed(m, tab["aydemo"])
    m.z.set_output_callback(m.z_out)
    m = zx128()                                           # aydemo stopped after its LOAD (NXTLIN at
    stop = bytearray(ay)                                  # D_FILE: no line to run), then SAVE
    stop[0x4029 - 0x4009:0x402B - 0x4009] = stop[0x400C - 0x4009:0x400E - 0x4009]
    m.drive.files[b"AY"] = bytes(stop)
    r = cmd128(m, "J SHIFT+P A Y SHIFT+P")
    stopped = placed(m, tab["aydemo"])
    r2 = cmd128(m, "S SHIFT+P A Z SHIFT+P")
    saved = m.drive.files.get(b"AZ", b"")
    a, o, n = tab["aydemo"][0]
    out_ok = saved[a - 0x4009:a - 0x4009 + len(n)] == bytes.fromhex(o) and placed(m, tab["aydemo"])
    check("load_patches", inb and not menu & 1 and not game & 1 and game_up & 1 and redef == (0x01, 0xDF)
          and two == (0, 0)
          and alone and ayin and not high and r == "0/0" and stopped and r2 == "0/0" and out_ok,
          f"BoulderL patched {inb}; P held: the menu's row ${menu:02X}, the game's AND ${game:02X} (up ${game_up:02X}); "
          f"the stick's right and fire: the game's 8 and 0 ANDs ${two[0]:02X} ${two[1]:02X}; "
          f"REDEFINE KEYS A ${redef[0]:02X} B ${redef[1]:02X}; one byte changed: left alone {alone}; aydemo patched "
          f"{ayin}, its OUTs from $C000 up in 400 frames {len(high)} {high[:3]}; stopped {r} {stopped}, SAVE {r2}: "
          f"the bytes as they were {out_ok}")


@zx128check
def save_32k():
    # 32K (F8) and a program up to E_LINE $BE00 (its last 1K in BUF's
    # $C000 up, where $FF00 = $0E has the kernal's ROM for the 8502's
    # reads): SAVE writes what bank 1 holds, every byte of it
    b8 = sym8502()
    m = zx128()
    fkey(m, "LSHIFT", "F7", frames=3)
    m.until(lambda: m.peek16(0x4004) == 0xC000, 300, "RAMTOP $C000")
    m.until(lambda: m.zx_screen()[23].startswith("k") and zx_editor(m), 600, "the K cursor")
    big = bytearray(p_prog('10 PRINT "OK"'))
    el = 0xBE00
    big[0x4014 - 0x4009:0x4016 - 0x4009] = el.to_bytes(2, "little")
    big[0x4029 - 0x4009:0x402B - 0x4009] = big[0x400C - 0x4009:0x400E - 0x4009]   # (it stops after LOAD)
    m.drive.files[b"BIG"] = bytes(big) + bytes((i * 7 + 3) & 0x7F for i in range(el - 0x4009 - len(big)))
    r = cmd128(m, "J SHIFT+P B I G SHIFT+P")
    held = []

    def at_save(m):                                      # (bank 1 as the 8502 starts on it)
        held.append(bytes(m.bank1[0x4009:el]))
        m.cpu.step()
    m.traps8502[b8["dosave"]] = at_save
    m.rom_reads.clear()
    r2 = cmd128(m, "S SHIFT+P B 2 SHIFT+P")
    del m.traps8502[b8["dosave"]]
    saved = m.drive.files.get(b"B2", b"")
    diff = [0x4009 + i for i in range(min(len(saved), el - 0x4009)) if held and saved[i] != held[0][i]]
    roms = sorted({pc for pc, a in m.rom_reads})
    check("save_32k", r == "0/0" and r2 == "0/0" and len(saved) == el - 0x4009 and not diff and not m.rom_reads,
          f"LOAD {r}, SAVE {r2}, {len(saved)} bytes (E_LINE-$4009 {el - 0x4009}), {len(diff)} unlike bank 1 "
          f"{[hex(a) for a in diff[:3]]}; the 8502's reads where a ROM is: {len(m.rom_reads)} "
          f"(pc {[hex(pc) for pc in roms[:3]]})")


@zx128check
def load_bufend():
    # files longer than BUF, each a whole block more, around BUFEND: the
    # kernal's burst LOAD calls STOP before every block but the last
    # (k_load as the kernal does), so a last block that starts just short
    # of BUFEND is read unguarded; none may reach common RAM ($E000 up,
    # but STAGE and com, the 8502's own, and the IN mirror's bytes) or
    # the ROM's copy in bank 0 (prom). The picture's queue is the Z80's
    # too, written as the LOAD's command is typed: there the 8502's own
    # turns are looked at (its bytes as each began and ended); and so is
    # vidpal (the Z80's at its start, in bank 0's copy of common
    # RAM from the first handover, the model's)
    b8, q = sym8502(), sym128()
    vidpal = q["vidpal"]
    q = slice(q["pic_q"], q["pic_qend"])
    buf, bufend, prom = b8["BUF"], b8["BUFEND"], b8["prom"]
    small = p_prog('10 PRINT "OK"')
    start, k, a = buf + 0x0B, 0, buf + 0x0B
    while a < bufend + 0x100:
        a += 252 if k == 0 else 254
        k += 1
    got, ok = [], True
    m = zx128()
    keep = [i for i in range(0xE000, 0x10000) if not 0xF200 <= i < 0xF400 and i & 0xFF != 0xFE and i != 0xFF00
            and not q.start <= i < q.stop and i != vidpal]
    qhit, run = [], m.run_8502

    def run_8502(*a, **k):
        q0 = bytes(m.bank0[q])
        run(*a, **k)
        qhit.append(sum(x != y for x, y in zip(q0, m.bank0[q])))
    m.run_8502 = run_8502
    for blocks in range(k - 3, k + 2):                    # the last block from below BUFEND - 254 to past $DF00
        n = 252 + 254 * (blocks - 1)
        name = f"J{blocks}"
        m.drive.files[name.encode()] = small + bytes([0xAA]) * (n + 2 - len(small))
        com0 = [m.bank0[i] for i in keep]
        rom0 = bytes(m.bank0[prom:prom + 0x2000])
        r = cmd128(m, "J SHIFT+P " + " ".join(name) + " SHIFT+P")
        last = start + 252 + 254 * (blocks - 2)
        com = sum(1 for i, v in zip(keep, com0) if m.bank0[i] != v) + sum(qhit)
        del qhit[:]
        good = com == 0 and bytes(m.bank0[prom:prom + 0x2000]) == rom0 and r[:1] in "04"
        got.append(f"last block ${last:04X}-${last + 253:04X}: {r}, common RAM {com} changed{'' if good else ' (WRONG)'}")
        ok = ok and good
    check("load_bufend", ok, f"BUF ${buf:04X}, BUFEND ${bufend:04X}: " + "; ".join(got))


@zx128check
def load_errors():
    # LOAD's ways to fail on the disk, each report D and the program as it
    # was: a file of 5 bytes (it ends in the 13); a read error in the 13
    # (the drive's words on the panel); one in the kernal's LOAD; a file
    # that ends before its E_LINE; another disk's file by LOAD's time (its
    # bytes not the 13 read); a file that isn't a ZX81 program (a PRG:
    # ZX128 itself)
    m = zx128()
    m.type("1 0 P SHIFT+P K SHIFT+P NEWLINE")
    eline, dfile = m.peek16(0x4014), m.peek16(0x400C)
    prog = bytes(m.bank1[0x407D:dfile])
    t = p_prog('10 PRINT "OK"\n20 PRINT "B"') + bytes(600)
    t = bytearray(t)
    t[0x4014 - 0x4009:0x4016 - 0x4009] = (0x4009 + len(t)).to_bytes(2, "little")
    t = bytes(t)
    short = bytearray(t)
    short[0x4014 - 0x4009:0x4016 - 0x4009] = (0x4009 + len(t) + 300).to_bytes(2, "little")
    other = bytearray(t)
    other[12] ^= 1
    m.drive.files.update({b"FIVE": t[:5], b"HBAD": t, b"LBAD": t, b"SHORT": bytes(short), b"SWAP": t,
                          b"PRG": open(PRG, "rb").read()})
    m.drive.bad = {b"HBAD": 7, b"LBAD": 500}
    m.drive.swapped = {b"SWAP": bytes(other[:2]) + bytes(other[2:])}
    got, ok = [], True
    for name, words in (("FIVE", None), ("HBAD", "read error"), ("LBAD", "read error"), ("SHORT", None),
                        ("SWAP", None), ("PRG", None)):
        r = cmd128(m, "J SHIFT+P " + " ".join(name) + " SHIFT+P")
        if words:
            m.until(lambda: words in m.vdc_text(13, 64, 16), PANEL_SET, f"{words} on the panel")
        same = m.peek16(0x4014) == eline and bytes(m.bank1[0x407D:m.peek16(0x400C)]) == prog
        good = r[:2] == "D/" and same
        got.append(f"{name} {r}{' ' + repr(msg_rows(m)) if words else ''}{'' if good else ' (WRONG)'}")
        ok = ok and good
    r = cmd128(m, "R")
    check("load_errors", ok and m.zx_screen()[0] == "K", "; ".join(got) + f"; RUN {r} {m.zx_screen()[0]!r}")


# ---------------------------------------------------------------- the monitor
# zx64mon, resident, on the VDC's columns 32-79 (z80/mon.asm, its
# screen through z80/monvdc.inc), the ZX81 at half width in columns 0-31
# (pic_half) beside it. One booted zx128 for all of them (mon_session).
MON_STATE = {}
MSTACK_N = 254                  # the monitor's stack: $FE00-$FEFD (hw128.inc's MSTACK)


def mon_type(m, text, settle=10):
    """Type at the monitor (it reads the keyboard itself): each key down 2
    frames, then up 2, as simulate.py's mtype."""
    for ch in text:
        m.keys = set(MKEY[ch])
        m.frames(2)
        m.keys = set()
        m.frames(2)
    m.frames(settle)


def mon_rows(m):
    """The monitor's screen (MSCR, 25 rows of MCOLS screen codes) as text,
    reversed as plain, as simulate.py's mscreen."""
    sym = sym128()
    a, n = sym["mscr"], sym["mcols"]
    rows = []
    for r in range(25):
        row = m.bank1[a + n * r:a + n * r + n]
        rows.append("".join(chr((c & 0x7F) + 0x40) if c & 0x7F < 0x20 else chr(c & 0x7F) if c & 0x7F < 0x40
                            else "#" for c in row).rstrip())
    return rows


def mon_vdc(m):
    """The VDC's columns 32-79 of its 25 rows as text (vdc_text)."""
    return [m.vdc_text(r, 32, 48).rstrip() for r in range(25)]


def mon_pc(m):
    """The PC on the monitor's last ";" line (its registers), or None."""
    regs = [r for r in mon_rows(m) if r.startswith(";")]
    return regs[-1][1:5] if regs else None


def half_codes(m):
    """The VDC's columns 0-31 of rows 0-23 as ZX81 codes, from set 1's
    half-width ones (0-63, inverse 64-127); None where a cell isn't one."""
    rows = []
    for r in range(24):
        cells, attrs = m.vdc_shown(r * 80, 32), m.vdc_shown(0x800 + r * 80, 32)
        rows.append([(c & 0x3F | (c & 0x40) << 1) if c < 0x80 and a & 0x80 else None for c, a in zip(cells, attrs)])
    return rows


def call_us(m, entry, frames=30):
    """Run on until the Z80 enters entry, then until that call returns: its
    time in us (pic_t's clock)."""
    z, end = m.z, m.nframes + frames
    while z.pc != entry:
        if m.nframes >= end:
            raise AssertionError(f"${entry:04X} never called")
        m.step(1)
    sp = z.sp
    ret = z.memory[sp] | z.memory[sp + 1] << 8
    t0 = m.now_t()
    while not (z.pc == ret and z.sp == sp + 2):
        m.step(1)
    return (m.now_t() - t0) / 2 * US_CYCLE


SPIN = bytes([0x3A, 0x8F, 0x40,              # 4082 ld a,($408F): until it isn't 0
              0xB7, 0x28, 0xFA,              #      or a / jr z,4082
              0x2A, 0x0C, 0x40, 0x23,        #      ld hl,(D_FILE) / inc hl
              0x36, 0x26,                    #      ld (hl),$26: "A" at row 0, column 0
              0xC9, 0x00])                   #      ret; 408F: the flag


def mon_session():
    """The monitor's checks' one machine, what each saw in MON_STATE:
    F5 at the K cursor (the layout); $ (an error, the monitor alive); ":"
    into D_FILE's row 2 (the half picture, pic_half's time); a D listing
    and an A line (the stack's depth); X (the picture back, the lock);
    then a program spinning on a flag, F5, the flag set, S until it has
    put "A" at row 0 (the half picture after each step), X."""
    if MON_STATE:
        if "error" in MON_STATE:
            raise AssertionError(MON_STATE["error"])
        return MON_STATE
    try:
        mon_run(MON_STATE)
    except (AssertionError, KeyError, OSError) as e:
        MON_STATE["error"] = str(e).splitlines()[0] if str(e) else type(e).__name__
        raise
    return MON_STATE


def mon_back_seen(m, sym, st, key, leave="X", fast=False):
    """After leave (X, G: typed; F5: the key; None: the keys let go, the
    monitor waiting for that in kup): the frames from the
    monitor's leaving (the IRQ's call of pic_irq put back) to a window
    (fast: a FAST program, no IRQs: none); VDC = D_FILE; the panel; writes
    in a window outside the blank."""
    out, lim = [], sym["lk_win"] * 256 + 40

    def on_vdc(m, kind, c, pos, ok):
        if kind[0] == "w" and m.bank1[sym["pic_unp"]] and (pos >= lim or pos >= VDC_BLANK):
            out.append((kind, round(pos)))
    m.on_vdc = on_vdc
    w0 = WINDOWS[0]
    call = sym["pic_iret"] - 2
    if leave is None:
        m.keys = set()
    elif leave == "F5":
        fkey(m, "F5")
    else:
        mon_type(m, leave + "\r", settle=0)
    m.until(lambda: m.peek16(call) == sym["pic_irq"], 100, "the monitor gone")
    f0, relock = m.nframes, 0
    if not fast:
        m.until(lambda: WINDOWS[0] > w0, 60, "a window after the monitor")
        relock = m.nframes - f0
    pic = frames_until(m, lambda: pic_same(m), 60, "VDC = D_FILE") + relock
    m.frames(100)
    m.on_vdc = None
    st[key] = dict(relock=relock, pic=pic, out=len(out), panel=panel_ok(m), f8=m.vdc_text(9, 64, 16),
                   same=pic_same(m), lost=m.vdc_lost)


def mon_run(st):
    sym = sym128()
    m = zx128()
    stack = sym.get("mstack")
    if stack:                                            # (the stack's depth: the bytes it changes, of
        m.bank1[stack - MSTACK_N:stack] = b"\xa5" * MSTACK_N   # its page)
    fkey(m, "F5")
    k = frames_until(m, lambda: "#PC   AF   BC" in m.vdc_text(1, 32, 48), 60, "the monitor's registers")
    m.frames(50)                                         # (the IRQ draws nothing meanwhile)
    st["layout"] = dict(frames=k + 8, rows=mon_rows(m), vdc=mon_vdc(m), k=m.vdc_shown(23 * 80, 1),
                        half=half_codes(m) == df_codes(m), regs=m.vdc_text(1, 32, 13))
    m.drive.absent = True                                # no drive: $ and @ say "#?", and go on
    mon_type(m, "$\r", settle=30)
    mon_type(m, "@\r", settle=30)
    mon_type(m, "=FF\r")
    st["disk"] = dict(rows=mon_rows(m), vdc=mon_vdc(m))
    mon_disk(m, st)                                      # $, W, L, @ on the d64's files
    a = m.peek16(0x400C) + 1 + 2 * 33                    # D_FILE's row 2, column 0
    for ch in f":{a:04X} 26":
        mon_type(m, ch, settle=0)
    m.keys = set(MKEY["\r"])
    us = call_us(m, sym["pic_half"])
    m.keys = set()
    m.frames(20)
    st["store"] = dict(us=us, df=m.bank1[a], vdc=m.vdc_shown(2 * 80, 1), half=half_codes(m) == df_codes(m))
    mon_type(m, "D 0\r", settle=30)
    mon_type(m, "A 7000 LD (IX+5),A\r", settle=0)
    m.until(lambda: ".A 7003" in mon_rows(m), 200, "A's next prompt")
    m.frames(10)                                         # (its pic_half)
    mon_type(m, "\r")                                  # (nothing more: A's end)
    st["asm"] = bytes(m.bank1[0x7000:0x7003])
    st["arrows"] = {n: mon_arrow_moves(m, way) for n, way in ARROW_WAYS.items()}
    st["keypad"] = mon_keypad(m)
    mclr(m)                                              # X, RETURN with DOWN (K2) down: kup holds the
    mon_type(m, "X", settle=0)                           # monitor until it is up too
    m.keys = {MPOS["RETURN"], C128NAMES["DOWN"]}
    m.frames(2)
    m.keys = {C128NAMES["DOWN"]}
    m.frames(30)
    st["arrows"]["held"] = m.bank1[sym["mon_up"]]
    m.keys = {C128NAMES["KP5"]}                          # then keypad 5 for DOWN: kup waits
    m.frames(30)                                         # for it too
    st["keypad"]["held"] = m.bank1[sym["mon_up"]]
    mon_back_seen(m, sym, st, "back", leave=None)        # (DOWN let go: the monitor leaves)
    used = next((i for i in range(MSTACK_N) if m.bank1[stack - MSTACK_N + i] != 0xA5), MSTACK_N)
    st["stack"] = MSTACK_N - used

    spin = p_prog("10 REM {bin:spin}\n20 RAND USR 16514", blobs={"spin": SPIN})
    load_p(m, spin)
    m.frames(20)
    fkey(m, "F5")                                        # (a later F5: quiet, R for the registers)
    m.until(lambda: m.bank1[sym["mon_up"]], 60, "the monitor in the program")
    m.frames(10)
    mon_type(m, "R\r", settle=20)
    pc0 = mon_pc(m)
    d = m.peek16(0x400C) + 1
    m.bank1[0x408F] = 1
    before = m.vdc_shown(0, 1)
    mon_type(m, "S\r", settle=20)
    steps = 1
    while m.bank1[d] != 0x26 and steps < 12:
        mon_type(m, "\r", settle=20)                     # ".S": RETURN steps again
        steps += 1
    m.frames(10)
    st["step"] = dict(pc0=pc0, steps=steps, df=m.bank1[d], before=before, vdc=m.vdc_shown(0, 1),
                      half=half_codes(m) == df_codes(m), mon=mon_rows(m) == mon_vdc(m), pc=mon_pc(m))
    m.keys = {MPOS["HOME"], MPOS["LSHIFT"]}            # (CLR: X on a row of its own, not after ".S")
    m.frames(2)
    m.keys = set()
    m.frames(10)
    mon_back_seen(m, sym, st, "back2")
    m.until(lambda: zx_report(m) is not None and zx_editor(m), 300, "the program's end")
    st["back2"]["report"] = zx_report(m)

    fkey(m, "F5")                                        # B, then G at it (gostep)
    m.until(lambda: m.bank1[sym["mon_up"]], 60, "the monitor")
    m.frames(15)
    mon_type(m, ":7000 3E 01 3C 3C 32 00 71 C9\r", settle=20)   # LD A,1; INC A; INC A; LD ($7100),A; RET
    mon_type(m, "B 7002\r")
    mon_back_seen(m, sym, st, "back3", leave="G")
    m.type("T SHIFT+NEWLINE L 2 8 6 7 2")               # RAND USR 28672
    m.keys = keyset(["NEWLINE"])
    m.until(lambda: m.bank1[sym["mon_up"]], 60, "the breakpoint")
    m.keys = set()
    m.frames(15)
    rows = mon_rows(m)
    hit = "#BREAKPOINT" in rows and mon_pc(m) == "7002" and m.bank1[0x7002] == 0x3C
    mon_type(m, "G\r", settle=0)
    m.until(lambda: zx_report(m) is not None and zx_editor(m), 300, "the program's end")
    m.frames(10)
    st["bpgo"] = dict(hit=hit, regs=next((r for r in reversed(rows) if r.startswith(";")), ""), report=zx_report(m),
                      a=m.bank1[0x7100], armed=m.bank1[0x7002], same=pic_same(m), panel=panel_ok(m))

    load_p(m, p_prog("10 FAST\n20 GOTO 20"))            # F5 in a FAST program: BREAK-1's (brk_f5)
    m.frames(20)
    a = sym["mscr"]
    m.bank1[a:a + 25 * sym["mcols"]] = b"\x20" * (25 * sym["mcols"])   # (the screen blank: what comes is new)
    fast = not m.z.iff1
    fkey(m, "F5")
    m.until(lambda: m.bank1[sym["mon_up"]], 60, "the monitor in a FAST program")
    m.frames(15)
    rows = [r for r in mon_rows(m) if r]
    st["fast"] = dict(fast=fast, rows=rows, pc=mon_pc(m))
    mon_back_seen(m, sym, st, "back4", leave="F5", fast=True)
    mon_lprog(m, sym, st)


# The monitor's cursor moves made two ways: the C64's cursor keys
# (LEFT and UP with SHIFT), and the C128's top-row keys (K2), which it is
# to take as those
ARROW_WAYS = {"C64": {"RIGHT": (MPOS["CRSRRIGHT"],), "DOWN": (MPOS["CRSRDOWN"],),
                      "LEFT": (MPOS["LSHIFT"], MPOS["CRSRRIGHT"]), "UP": (MPOS["LSHIFT"], MPOS["CRSRDOWN"])},
              "C128": {n: (C128NAMES[n],) for n in ("RIGHT", "DOWN", "LEFT", "UP")}}


def mon_arrow_moves(m, way):
    """On M 4000 40BF's lines (24: its command scrolled away): RIGHT, LEFT,
    UP, DOWN (on the bottom row: M's next line), each held a while (the
    repeat), with SHIFT, with a C64 cursor key, and UP at the top row (M's
    lines back), each key's names as way has them: the cursor and the
    screen after each."""
    crow, ccol = mon_lbl()["crow"], mon_lbl()["ccol"]
    seen = []

    def ks(names):
        return {p for n in names for p in (way[n] if n in way else (MPOS[n],))}

    def press(*names, held=(), frames=2):
        h = ks(held)
        m.keys = h                                       # (what is held first: a key of its own)
        m.frames(2)
        m.keys = h | ks(names)
        m.frames(frames)
        m.keys = h
        m.frames(2)
        m.keys = set()
        m.frames(8)                                      # (a scroll's rows drawn)
        seen.append(((m.bank1[crow], m.bank1[ccol]), mon_rows(m)))
    mclr(m)
    mon_type(m, "M 4000 40BF\r", settle=60)
    for k in ("RIGHT", "RIGHT", "LEFT", "UP", "DOWN", "DOWN", "LEFT"):
        press(k)
    press("RIGHT", frames=40)                            # held: the repeat
    press("UP", frames=40)
    press("UP", held=("RSHIFT",))                        # SHIFT+UP: up
    press("RIGHT", held=("RSHIFT",))                     # SHIFT+RIGHT: left
    press("CRSRRIGHT", held=("UP",))                     # UP held, CRSR RIGHT: left (UP's SHIFT; the
    press("DOWN", held=("CRSRRIGHT",))                   # C64's: a ghost, see mon_arrows)
    press("HOME")
    for _ in range(3):
        press("UP")                                      # the top row: M's lines back
    return seen


def mon_keypad(m):
    """The C128's keypad at the monitor: each of its keys (0-9,
    + - .) typed on a clear screen, and the main keys' the same; then
    M 4000 with 4000 and RETURN on the keypad, and by the main keys: the
    screen each time."""
    def pad(text):
        for ch in text:
            m.keys = {C128NAMES[KEYPAD[ch]]}
            m.frames(2)
            m.keys = set()
            m.frames(2)
    got = {}
    for way in ("pad", "main"):
        mclr(m)
        pad("0123456789+-.") if way == "pad" else mon_type(m, "0123456789+-.", settle=0)
        m.frames(10)
        keys = mon_rows(m)
        mclr(m)
        mon_type(m, "M ", settle=0)
        pad("4000\r") if way == "pad" else mon_type(m, "4000\r", settle=0)
        m.frames(40)
        got[way] = (keys, mon_rows(m))
    return got


def mon_keypad_ok(st):
    (pk, pm), (mk, mm) = st["pad"], st["main"]
    return pk == mk and pk[0] == "0123456789+-." and pm == mm and pm[1].startswith(".:4000") and st["held"]


def mon_keypad_say(st):
    (pk, pm), (mk, mm) = st["pad"], st["main"]
    return (f"by the keypad {pk[0]!r} (the main keys {mk[0]!r}); M 4000 by it: {pm[:2]} (the main keys "
            f"{'the same' if pm == mm else mm[:2]}); X with keypad 5 down: the monitor still up {bool(st['held'])}")


def mclr(m):
    """CLR at the monitor: its screen blank, the cursor home."""
    m.keys = {MPOS["HOME"], MPOS["LSHIFT"]}
    m.frames(2)
    m.keys = set()
    m.frames(10)


def mon_after(m, cmd, n=1):
    """The n rows after the last one with cmd (typed at the prompt) on the
    monitor's screen."""
    rows = mon_rows(m)
    at = max((i for i, r in enumerate(rows) if r.lstrip(".") == cmd), default=None)
    return rows[at + 1:at + 1 + n] if at is not None else ["(no " + cmd + ")"]


def mon_cmdout(m, cmd, n=1, settle=40):
    """cmd typed at the monitor, RETURN: the n rows it printed."""
    mon_type(m, cmd + "\r", settle=settle)
    return mon_after(m, cmd, n)


def mon_written(m, cmd, n=1, settle=40):
    """mon_cmdout, and the bank 1 addresses the 8502 wrote meanwhile but
    its bookkeeping (the mailbox's page, ovl, the panel's jobs for rows 13
    and 14: dbeg's and dend's), as a range's (first, last), or a count."""
    sym = sym8502()
    keep = {sym["OVL"], sym["PND"] + 13, sym["PND"] + 14}
    m.writes1 = set()
    out = mon_cmdout(m, cmd, n, settle)
    w = sorted(a for a in m.writes1 if a >> 8 != 0x2F and a not in keep)
    m.writes1 = None
    return out, ((w[0], w[-1]) if w and w[-1] - w[0] == len(w) - 1 else len(w))


def mon_disk(m, st):
    """The monitor's $, W, L and @ on build/zx128.d64's files, in
    the session: what each showed, in st. The 8502's VDC writes meanwhile
    in st["vdc8502"] (none: the monitor is up). An L that didn't put back
    what the check changed (the system variables, the ROM) is put right
    here, so the session goes on (st["fixed"])."""
    log = log8502(m)
    fixed = []
    m.drive = Drive128()
    mclr(m)
    mon_type(m, "$\r", settle=60)
    st["dir"] = dict(rows=mon_rows(m), want=["$"] + dir_lines(m.drive), open=sorted(m.channels))

    # a long one: 50 files more, each line taking the 8502 half a frame
    # (as a drive's would), RUN/STOP once F05's is on the screen
    for i in range(50):
        m.drive.files[b"F%02d" % i] = b"\x00\x40" + bytes(100)
    m.absent_t = FRAME_T // 2
    mclr(m)
    mon_type(m, "$\r", settle=0)
    try:
        m.until(lambda: any('"F05"' in r for r in mon_rows(m)), 300, "the long directory's F05")
        seen = True
    except AssertionError:
        seen = False
    m.keys = {MPOS["RUNSTOP"]}
    m.frames(5)
    m.keys = set()
    m.frames(20)
    rows = mon_rows(m)
    m.absent_t = 0
    for i in range(50):
        m.drive.files.pop(b"F%02d" % i)
    eq = mon_cmdout(m, "=FF")
    st["dirstop"] = dict(seen=seen, rows=rows, open=sorted(m.channels), eq=eq)

    # W, F, L: the bytes back, the file's load address bank 1's
    mclr(m)
    sysv = bytes(m.bank1[0x4000:0x4100])
    w = mon_cmdout(m, 'W "T" 4000 40FF', settle=60)
    t = m.drive.files.get(b"T", b"")
    mon_type(m, "F 4000 40FF 00\r", settle=30)
    zero = bytes(m.bank1[0x4000:0x4100]) == bytes(256)
    m.frames(20)
    l, lw = mon_written(m, 'L "T" 4000', settle=60)
    back = bytes(m.bank1[0x4000:0x4100])
    if back != sysv:
        m.bank1[0x4000:0x4100] = sysv
        fixed.append("system variables")
    m.frames(30)
    st["wl"] = dict(t=t, sysv=sysv, zero=zero, back=back, w=w, l=l, lw=lw, rows=mon_rows(m), vdc=mon_vdc(m))

    # L's refusals, and the ROM's pages 0-2 (the 8502's own zero page and
    # stack are at bank 1's 0 and 1): W "R" first, to put it back
    mclr(m)
    rom = bytes(m.bank1[0:0x300])
    wr = mon_cmdout(m, 'W "R" 0000 02FF', settle=80)
    r = m.drive.files.get(b"R", b"")
    low = bytes(m.bank1[0x4000:0x4080])                  # (the system variables: $3F80-$3FFF are the
    ref1, w1 = mon_written(m, 'L "T" 3F80', 2)          # monitor's own, which it changes itself)
    low2 = bytes(m.bank1[0x4000:0x4080])
    high = bytes(m.bank1[0xBF80:0xC400])
    ref2, w2 = mon_written(m, 'L "T" BF80', 2)
    high2 = bytes(m.bank1[0xBF80:0xC400])
    rom1f = bytes(m.bank1[0x1F80:0x2000])
    ref3, w4 = mon_written(m, 'L "T" 1F80', 2)          # (the ROM's room ends at $2000)
    rom1f2 = bytes(m.bank1[0x1F80:0x2000])
    none, w5 = mon_written(m, 'L "NONE" 4000', 2)
    ok1, w3 = mon_written(m, 'L "T" 0180')               # (pages 0 and 1: the Z80's, from ROM01)
    at180 = bytes(m.bank1[0x0180:0x0280])
    ok0 = mon_cmdout(m, 'L "T" 0000')
    at0 = bytes(m.bank1[0:0x100])
    rb = mon_cmdout(m, 'L "R" 0000', settle=60)
    rom2 = bytes(m.bank1[0:0x300])
    if rom2 != rom:
        m.bank1[0:0x300] = rom
        fixed.append("the ROM")
    st["refuse"] = dict(t=t, rom=rom, r=r, wr=wr, low=low == low2, high=high == high2, ref1=ref1, ref2=ref2,
                        w1=w1, w2=w2, ok1=ok1, w3=w3, at180=at180, ok0=ok0, at0=at0, rb=rb, rom2=rom2,
                        ref3=ref3, w4=w4, rom1f=rom1f == rom1f2, none=none, w5=w5)

    # W "SV": the program, as SAVE ($4009 up to E_LINE), the status after
    answer, answers = sym8502()["answer"], []

    def ans(m):                                          # (the server's answers: A at its answer)
        answers.append(m.cpu.a)
        m._step8502()
    m.traps8502[answer] = ans
    sv = mon_cmdout(m, 'W "SV"', settle=60)
    del m.traps8502[answer]
    st["save"] = dict(sv=sv, file=m.drive.files.get(b"SV", b""), prog=bytes(m.bank1[0x4009:m.peek16(0x4014)]),
                      answers=answers)

    # @: the status; @S:T scratches T, $ lists the rest
    a1 = mon_cmdout(m, "@")
    a2 = mon_cmdout(m, "@S:T")
    gone = b"T" not in m.drive.files
    mclr(m)
    mon_type(m, "$\r", settle=60)
    st["at"] = dict(a1=a1, a2=a2, gone=gone, rows=mon_rows(m), want=["$"] + dir_lines(m.drive))
    m.on_vdc8502 = None
    st["vdc8502"] = len(log)
    st["fixed"] = fixed


def mon_lprog(m, sym, st):
    """After the session's FAST program (BREAK: report D), F5,
    L "SPEED" (CMD_LOAD on the ZX81's stack, as zx64's l_prog), then X:
    to BASIC with the program there, which runs as it does after LOAD."""
    speed = open(os.path.join(ROOT, "build", "obj", "zx128", "speed.p"), "rb").read()
    m.keys = keyset(["SPACE"])
    m.until(lambda: zx_report(m) is not None, 100, "BREAK")
    m.keys = set()
    m.until(lambda: zx_editor(m), 100, "the editor")
    big = bytearray(p_prog('10 PRINT "OK"'))            # (load_too_big's: E_LINE $9000 on 16K)
    big[0x4014 - 0x4009:0x4016 - 0x4009] = (0x9000).to_bytes(2, "little")
    m.drive.files.update({b"SPEED": speed, b"NOTP": b"\x00\x70" + b"\x50" * 32,
                          b"BIG": bytes(big) + bytes(0x9000 - 0x4009 - len(big))})
    log = log8502(m)
    fkey(m, "F5")
    m.until(lambda: m.bank1[sym["mon_up"]], 60, "the monitor")
    m.frames(15)
    prog = bytes(m.bank1[0x4009:m.peek16(0x4014)])
    refused = [mon_cmdout(m, f'L "{n}"', 2, settle=60) for n in ("NOTP", "BIG", "NONE")]
    kept = bytes(m.bank1[0x4009:m.peek16(0x4014)]) == prog
    rows = mon_cmdout(m, 'L "SPEED"', settle=60)
    m.frames(20)
    same = bytes(m.bank1[0x4009:0x4009 + len(speed)]) == speed
    screen = mon_rows(m) == mon_vdc(m)
    eline = m.peek16(0x4014)
    mon_type(m, "X\r", settle=0)
    try:
        m.until(lambda: zx_report(m) is not None and zx_editor(m), 1500, "the program's report")
        rep = zx_report(m)
    except AssertionError:
        rep = None
    m.on_vdc8502 = None
    st["lprog"] = dict(rows=rows, same=same, eline=eline, report=rep, top=m.zx_screen()[0], screen=screen,
                       vdc8502=len(log), panel=panel_ok(m), refused=refused, kept=kept)


@zx128check
def mon_f5_layout():
    # F5 at the K cursor: the monitor's hello and registers at the VDC's
    # columns 32-79 (its own screen, MSCR, as the VDC shows it: set 1's
    # text), the register header "#PC   AF   BC" at column 32 of its row;
    # columns 0-31 the ZX81 at half width (set 1's ZX81 codes), the K
    # cursor at row 23 its inverse K's, $70; 50 frames on, nothing (the
    # IRQ) has drawn over it
    st = mon_session()["layout"]
    check("mon_f5_layout", st["regs"] == "#PC   AF   BC" and st["k"] == bytes([0x70]) and st["half"]
          and st["rows"] == st["vdc"] and st["rows"][0].startswith("#ZX128MON"),
          f"up {st['frames']} frames after F5; row 1 at column 32 {st['regs']!r}; row 23 column 0 "
          f"${st['k'].hex()}; the half picture as D_FILE {st['half']}; the VDC as MSCR {st['rows'] == st['vdc']} "
          f"({st['vdc'][:2]})")


@zx128check
def mon_disk_error():
    # $ and @ with no drive (the kernal's device not present): "#?" for
    # each, nothing hangs, and the monitor goes on (= FF answers)
    st = mon_session()["disk"]
    rows = [r.lstrip(".") for r in st["rows"] if r]
    i = rows.index("$") if "$" in rows else len(rows)
    check("mon_disk_error", rows[i:i + 6] == ["$", "#?", "#?", "@", "#?", "=FF"]
          and "= $00FF +255 %11111111" in rows and st["rows"] == st["vdc"], f"{rows[i:i + 7]}")


@zx128check
def mon_store_shows():
    # ": a 26" into D_FILE's row 2: the half picture shows its "A" (pic_half
    # after the command), and all of it is D_FILE's; pic_half's time
    st = mon_session()["store"]
    check("mon_store_shows", st["df"] == 0x26 and st["vdc"] == bytes([0x26]) and st["half"],
          f"D_FILE ${st['df']:02X}, VDC ${st['vdc'].hex()}, the half picture as D_FILE {st['half']}; "
          f"pic_half {st['us'] / 1000:.1f} ms")


@zx128check
def mon_step_redraws():
    # a program spinning on a flag, F5 (the monitor in it), the flag set,
    # S until it has put "A" at row 0 column 0: the half picture shows it
    # (pic_half on each entry); the monitor's columns as MSCR (no IRQ drew
    # over them during the steps)
    st = mon_session()["step"]
    check("mon_step_redraws", st["df"] == 0x26 and st["before"] != bytes([0x26]) and st["vdc"] == bytes([0x26])
          and st["half"] and st["mon"],
          f"PC {st['pc0']} at F5, {st['steps']} step(s) to {st['pc']}: D_FILE ${st['df']:02X}, VDC "
          f"${st['before'].hex()} then ${st['vdc'].hex()}; the half picture as D_FILE {st['half']}; the monitor's "
          f"columns as MSCR {st['mon']}")


@zx128check
def mon_bp_go():
    # ":" a routine at $7000, B 7002, G; RAND USR 28672: the
    # monitor at the breakpoint ("#BREAKPOINT", PC 7002, its byte back);
    # G: on past it (gostep), to the end ($7100 = 3, 0/0), the breakpoint
    # armed again; the picture and the panel back
    st = mon_session()["bpgo"]
    check("mon_bp_go", st["hit"] and st["report"] == "0/0" and st["a"] == 3 and st["armed"] == 0xFF and st["same"]
          and st["panel"], f"hit {st['hit']} {st['regs'][:10]!r}; G: {st['report']}, $7100 = {st['a']}, $7002 = "
          f"${st['armed']:02X}; VDC = D_FILE {st['same']}, panel {st['panel']}")


@zx128check
def mon_fast_f5():
    # after the breakpoints and steps above, F5 in a FAST program (no IRQ:
    # BREAK-1's brk_f5, monreq 0): the monitor's F5 entry, not a stale
    # breakpoint's. A later F5's: quiet, only the prompt on the screen the
    # check blanked
    st = mon_session()["fast"]
    check("mon_fast_f5", st["fast"] and st["rows"] == ["."], f"interrupts off {st['fast']}; {st['rows'][:3]}")


@zx128check
def mon_back():
    # X at the K cursor and after the steps, G, and F5 in a FAST program
    # (mon_fast_f5): the whole picture and the
    # panel at once (pic_all, panel_all), the lock found again (a window
    # within RELOCK frames of leaving), VDC = D_FILE, the panel right
    # (vdc_text(9, 64, 16)), no write in a window outside the
    # blank; the program goes on to its report. The monitor's stack: the
    # deepest it went (a D listing and an A line among the commands)
    st = mon_session()
    got, ok = [], True
    for key, how in (("back", "X"), ("back2", "X after S"), ("back3", "G"), ("back4", "F5 in FAST")):
        b = st[key]
        good = (b["relock"] <= RELOCK and b["same"] and b["panel"] and b["f8"].rstrip() == "F8 memory  16K"
                and not b["out"] and not b["lost"])
        ok = ok and good
        got.append(f"{how}: a window {b['relock']} frame(s) after leaving (bound {RELOCK}; FAST: none), VDC = D_FILE after "
                   f"{b['pic']}, panel {b['panel']} {b['f8']!r}, {b['out']} writes outside the blank"
                   + ("" if good else " (WRONG)"))
    ok = ok and st["back2"]["report"] == "0/20" and st["asm"] == bytes([0xDD, 0x77, 0x05])
    check("mon_back", ok, "; ".join(got) + f"; then {st['back2']['report']}; A 7000 {st['asm'].hex()}; the "
          f"monitor's stack {st['stack']} bytes deep")


@zx128check
def mon_arrows():
    # the C128's top-row cursor keys at the monitor (K2's into
    # its kmat, hw128.inc's kscan_more): RIGHT and DOWN as CRSR RIGHT and
    # DOWN, LEFT and UP as those with SHIFT. The same moves made with the
    # C64's keys and with these (mon_arrow_moves: held, with SHIFT, DOWN
    # and UP at the bottom and top rows over M's lines) leave the cursor
    # and the screen the same each time; held, they repeat; UP at the top
    # scrolls M's lines back. With a C64 cursor key (steps 11-12) only the
    # screen: on a C64, SHIFT, CRSR DOWN and CRSR RIGHT are three corners
    # of a rectangle in the matrix (GHOSTY: no key taken), the C128's UP
    # is off it, so UP held and CRSR RIGHT go up, then left (UP's SHIFT);
    # CRSR RIGHT held and DOWN: right, then down. X with DOWN still down:
    # the monitor waits for it (kup), then leaves
    st = mon_session()["arrows"]
    c64, c128 = st["C64"], st["C128"]
    combo = (11, 12)
    apart = [i for i, (a, b) in enumerate(zip(c64, c128)) if a[1] != b[1] or (a[0] != b[0] and i not in combo)]
    (r0, c0), (r1, c1) = c64[6][0], c64[7][0]           # before and after RIGHT held
    rep = c1 - c0
    (ra, ca), (rb, cb), (rc, cc) = (c128[i][0] for i in (10, 11, 12))
    mix = (rb, cb) == (ra - 1, ca - 1) and (rc, cc) == (rb + 1, cb + 1)
    top = c64[-1][1][:2]
    ok = not apart and len(c64) == len(c128) == 17 and rep >= 3 and c64[8][0][0] <= r1 - 3 and mix \
        and all(r.startswith(".:3F") for r in top) and st["held"]
    check("mon_arrows", ok, f"C128's keys as the C64's: {'all' if not apart else f'not at steps {apart}'} "
          f"({len(c64)} steps; first apart: {(c64[apart[0]][0], c128[apart[0]][0]) if apart else '-'}); RIGHT "
          f"held: {rep} columns, UP held: rows {r1} to {c64[8][0][0]}; UP held and CRSR RIGHT, CRSR RIGHT held "
          f"and DOWN: {(ra, ca)} {(rb, cb)} {(rc, cc)} ({mix}); UP at the top: {top}; X with DOWN down: the "
          f"monitor still up {bool(st['held'])}")


@zx128check
def mon_keypad_keys():
    # the C128's numeric keypad at the monitor as the main keys
    # (k2mon.inc: k2scan.inc's keys taken into its kmat): what each types, M 4000
    # with it lists as with them; kup waits for it (X with keypad 5 down)
    st = mon_session()["keypad"]
    check("mon_keypad_keys", mon_keypad_ok(st), mon_keypad_say(st))


def mon_span(w):
    return f"${w[0]:04X}-${w[1]:04X}" if isinstance(w, tuple) else f"{w} byte(s)"


def mon_disk_st(key):
    """mon_session's st[key] for the disk's checks."""
    st = mon_session()
    if key not in st:
        raise AssertionError(f"the session has no {key}")
    return st[key]


@zx128check
def mon_dir():
    # $: build/zx128.d64's directory as the drive sends it, a
    # line at a time (the header, each file's blocks and name, the blocks
    # free), the file closed after; 50 files more, RUN/STOP partway: the
    # directory closed early (CMD_DIRC), the monitor goes on (= FF)
    d, s = mon_disk_st("dir"), mon_disk_st("dirstop")
    got = [r for r in d["rows"] if r][:len(d["want"])]
    tail = [r for r in s["rows"] if r]
    stopped = s["seen"] and not any("BLOCKS FREE" in r or '"F49"' in r for r in tail)
    check("mon_dir", got == d["want"] and not d["open"] and stopped and not s["open"]
          and s["eq"] == ["= $00FF +255 %11111111"],
          f"{len(got)} lines of {len(d['want'])} as the drive's{'' if got == d['want'] else f' (got {got[:3]})'}; "
          f"open after {d['open']}; RUN/STOP: F05 seen {s['seen']}, stopped {stopped} at {tail[-3:]}, open "
          f"{s['open']}, then {s['eq']}")


@zx128check
def mon_w_l():
    # W "T" 4000 40FF: a PRG of the 256 bytes, its load address
    # $4000 (bank 1's own, 0 added); F 4000 40FF 00; L "T" 4000: the
    # bytes back, "#LOADED 4000-40FF"
    st = mon_disk_st("wl")
    t = st["t"]
    check("mon_w_l", t == b"\x00\x40" + st["sysv"] and st["w"] == ["00, OK,00,00"] and st["zero"]
          and st["back"] == st["sysv"] and st["l"] == ["#LOADED 4000-40FF"] and st["lw"] == (0x4000, 0x40FF),
          f"T {len(t)} bytes, load address ${(t[0] | t[1] << 8) if len(t) > 1 else 0:04X}, W then {st['w']}; "
          f"F zeroed {st['zero']}; L: the bytes back {st['back'] == st['sysv']}, {st['l']}, the 8502 wrote "
          f"bank 1 {mon_span(st['lw'])}")


@zx128check
def mon_l_refuse():
    # L "NAME" a only into $0000-$1FFF (the ROM) and
    # $4000-$BFFF: T (256 bytes) at 3F80 (into the core's) and at BF80
    # (into $C000) and at 1F80 (past the ROM's $1FFF) refused, "#?" and
    # the drive's status, nothing written; L "NONE" 4000: "#?" and the
    # drive's 62;
    # at 0180 (across bank 1's pages 1 and 2, the first the 8502's own
    # stack's) and 0000 it loads; W "R" 0000 02FF, L "R" 0000 put it back
    st = mon_disk_st("refuse")
    body = st["t"][2:]
    ok = (st["ref1"] == ["#?", "00, OK,00,00"] and st["ref2"] == ["#?", "00, OK,00,00"] and st["low"] and st["high"]
          and st["w1"] == 0 and st["w2"] == 0 and st["w3"] == (0x200, 0x27F)
          and st["ref3"] == ["#?", "00, OK,00,00"] and st["w4"] == 0 and st["rom1f"]
          and st["none"] == ["#?", "62,FILE NOT FOUND,00,00"] and st["w5"] == 0
          and st["ok1"] == ["#LOADED 0180-027F"] and st["at180"] == body and st["ok0"] == ["#LOADED 0000-00FF"]
          and st["at0"] == body and st["r"] == b"\x00\x00" + st["rom"] and st["rb"] == ["#LOADED 0000-02FF"]
          and st["rom2"] == st["rom"] and len(body) == 256)
    check("mon_l_refuse", ok, f"3F80: {st['ref1']}, the 8502 wrote {mon_span(st['w1'])}, $4000-$407F unchanged "
          f"{st['low']}; BF80: {st['ref2']}, wrote {mon_span(st['w2'])}, $BF80-$C3FF unchanged {st['high']}; 1F80: "
          f"{st['ref3']}, wrote {mon_span(st['w4'])}, $1F80-$1FFF unchanged {st['rom1f']}; NONE 4000: {st['none']}, "
          f"wrote {mon_span(st['w5'])}; 0180: "
          f"{st['ok1']}, {st['at180'] == body}, wrote {mon_span(st['w3'])}; 0000: {st['ok0']}, {st['at0'] == body}; "
          f"W \"R\" {len(st['r'])} bytes as the ROM {st['r'][2:] == st['rom']}, L \"R\" 0000 {st['rb']}, the "
          f"ROM back {st['rom2'] == st['rom']}")


@zx128check
def mon_w_save():
    # W "SV": the program as SAVE ($4009 up to E_LINE), the
    # server's answer ok (SAVE's, then @'s), the drive's status after it
    st = mon_disk_st("save")
    check("mon_w_save", st["file"] == st["prog"] and st["sv"] == ["00, OK,00,00"] and st["answers"] == [0, 0],
          f"{len(st['file'])} bytes, the program ($4009-E_LINE) {st['file'] == st['prog']}; the server answered "
          f"{st['answers']}; {st['sv']}")


@zx128check
def mon_at():
    # @: the drive's status line; @S:T (T from W above)
    # scratches it, and $ no longer lists it
    st = mon_disk_st("at")
    rows = [r for r in st["rows"] if r]
    if rows[-1:] == ["."]:                               # the prompt under it
        rows = rows[:-1]
    same = bool(rows) and rows == st["want"][-len(rows):]    # a listing longer than the
    check("mon_at", st["a1"] == ["00, OK,00,00"] and st["a2"] == ["01, FILES SCRATCHED,01,00"] and st["gone"]
          and same and not any('"T"' in r for r in rows),    # screen scrolls: its end
          f"@ {st['a1']}, @S:T {st['a2']}, T gone {st['gone']}, $ as the drive's {same} "
          f"({len(rows)} of {len(st['want'])} lines shown)")


@zx128check
def mon_disk_screen():
    # the monitor's disk commands draw nothing on the VDC from
    # the 8502 (no loading row, no bar, no message: rows 13-14, columns
    # 64-79 are the monitor's), W "SV" (SAVE) among them, and L "SPEED"
    # (LOAD: mon_l_prog); after an L the VDC's columns 32-79 are
    # MSCR; nothing put right by the check (st["fixed"])
    st, wl = mon_session(), mon_disk_st("wl")
    check("mon_disk_screen", mon_disk_st("vdc8502") == 0 and wl["rows"] == wl["vdc"] and not st.get("fixed"),
          f"the 8502's VDC writes {st.get('vdc8502')}; after L the VDC as MSCR {wl['rows'] == wl['vdc']}; put "
          f"right by the check: {st.get('fixed')}")


@zx128check
def mon_l_prog():
    # L "NAME" from the monitor, CMD_LOAD on the ZX81's own
    # stack, as zx64's: a PRG of code "#? NOT A PROGRAM", a program too
    # big for 16K "#? TOO BIG", a missing one "#?" and the drive's
    # "62,FILE NOT FOUND", the program kept; L "SPEED": "#LOADED 4009-"
    # E_LINE - 1, the program as the file; nothing drawn by the 8502; X:
    # to BASIC with it (leave_q), where it runs as after LOAD ("ZX128 SPEED
    # TEST"), and the picture and the panel are back
    st = mon_disk_st("lprog")
    want = [f"#LOADED 4009-{st['eline'] - 1:04X}"]
    no = [["#? NOT A PROGRAM", "."], ["#? TOO BIG", "."], ["#?", "62,FILE NOT FOUND,00,00"]]
    check("mon_l_prog", st["refused"] == no and st["kept"] and st["rows"] == want and st["same"] and st["screen"]
          and not st["vdc8502"] and st["report"] is not None and st["report"].startswith("0/")
          and st["top"] == "ZX128 SPEED TEST" and st["panel"],
          f"{[r[0] if r[0] != '#?' else ' '.join(r) for r in st['refused']]}, the program kept {st['kept']}; "
          f"{st['rows']} (want {want}), the program as the file {st['same']}, the VDC as MSCR {st['screen']}, the "
          f"8502's VDC writes {st['vdc8502']}; X: {st['report']}, {st['top']!r}, panel {st['panel']}")


# ---------------------------------------------------------------- the quiet F5
# The quiet F5 (a later F5: the screen as it was left, a prompt on the
# line after the last one used), ?'s title line, and the screen as the
# VDC shows it while F5 and X change the layout. A machine of its own
# (mon_quiet), its frames watched as the VDC shows them (Seen).
QUIET = {}
SEEN_N = 34                     # frames a layout is watched for (the monitor's cursor blinks every 16)
SEEN_AT = [0] + [VDC_BLANK + (r * 8 + 4) * VDC_LINE for r in range(25)]   # a frame's start, each row's middle


def look_row(m, r, regs):
    """Row r as the VDC shows it, from regs (the screen's and the
    attributes' start, the fonts', the background): each cell's look, its
    glyph as shown (8 lines, reversed if the attribute says), foreground,
    background and underline/blink; a cell all of one colour that colour
    alone (a space and a solid block of the background look the same)."""
    scr, att, font, bg = regs
    vram, n = m.vram, len(m.vram)
    out = []
    for c in range(80):
        code, a = vram[(scr + r * 80 + c) % n], vram[(att + r * 80 + c) % n]
        g0, x = font + (0x1000 if a & 0x80 else 0) + code * 16, 0xFF if a & 0x40 else 0
        g = bytes(vram[(g0 + i) % n] ^ x for i in range(8))
        fg = a & 15
        out.append(bg if fg == bg or g == bytes(8) else 0x100 | fg if g == b"\xff" * 8 else (g, fg, bg, a & 0x30))
    return tuple(out)


class Seen:
    """The frames the VDC shows while it's on: each row as the beam passes
    its middle (SEEN_AT), from the registers the frame began with (the 8563
    takes R12/R13 and R20/R21 at its start), 25 rows of looks (look_row),
    with the phase they began in (a frame begun in phase "" isn't kept).
    The Z80 runs in short steps meanwhile: m.step is taken over, off()
    gives it back (a step ends where the model's would: at the raster
    compare, or a frame's end)."""

    def __init__(self, m):
        self.m, self.phase, self.frames, self.cur = m, "", [], None
        self.pos = m.vdc_pos()
        m.step = self.step

    def off(self):
        del self.m.step

    def step(self, ticks):
        m = self.m
        irq, f0 = m.next_irq_t, m.nframes
        while ticks > 0 and m.z80_on and m.nframes == f0 and not (m.timed and m.t >= irq):
            dc = min((s - self.pos) % VDC_FRAME or VDC_FRAME for s in SEEN_AT)
            n = max(1, int(min(ticks, dc * 2 / (1 + CPU_SLOW) + 1)))
            t0 = m.t
            C128.step(m, n)
            ticks -= max(1, m.t - t0)
            p0, self.pos = self.pos, m.vdc_pos()
            span = (self.pos - p0) % VDC_FRAME
            for d, i in sorted(((s - p0) % VDC_FRAME, i) for i, s in enumerate(SEEN_AT)):
                if 0 < d <= span:
                    self.seen(i)

    def seen(self, i):
        m, cur = self.m, self.cur
        if i == 0:
            if cur and cur[0] and None not in cur[1]:
                self.frames.append(cur)
            v = m.vdc
            self.cur = (self.phase, [None] * 25, (v[12] << 8 | v[13], v[20] << 8 | v[21], (v[28] & 0xE0) << 8,
                                                  v[26] & 15))
        elif cur and cur[0]:
            cur[1][i - 1] = look_row(m, i - 1, cur[2])

    def bad(self, k):
        """Switch k's frames (phase k): the cells that look like neither the
        layout before it (phase k + "<") nor the one after (k + ">"):
        (frames, frames with such a cell, the most in one, the first one's
        (frame, row, column), the cells that differ before and after)."""
        def looks(ph):
            s = [[set() for _ in range(80)] for _ in range(25)]
            for p, rows, _ in self.frames:
                if p == ph:
                    for r in range(25):
                        for c in range(80):
                            s[r][c].add(rows[r][c])
            return s
        old, new = looks(k + "<"), looks(k + ">")
        frames = [rows for p, rows, _ in self.frames if p == k]
        nbad, most, first = 0, 0, None
        for f, rows in enumerate(frames):
            cells = [(r, c) for r in range(25) for c in range(80) if rows[r][c] not in old[r][c] | new[r][c]]
            if cells:
                nbad += 1
                most = max(most, len(cells))
                first = first or (f, *cells[0])
        differ = sum(not (old[r][c] & new[r][c]) for r in range(25) for c in range(80))
        return len(frames), nbad, most, first, differ


def mon_lbl():
    """The monitor's own labels (build/obj/mon128/zx128mon.lbl)."""
    import build
    return build.labels(os.path.join(ROOT, "build", "obj", "mon128", "zx128mon.lbl"))


def quiet_run(st):
    sym = sym128()
    m = zx128()
    d = m.peek16(0x400C) + 1                             # the ZX81's rows 0-21 full (most cells change)
    for r in range(22):
        m.bank1[d + 33 * r:d + 33 * r + 32] = bytes((r + c) % 64 | (c & 1) << 7 for c in range(32))
    m.until(lambda: pic_same(m), 100, "the ZX81's rows")
    sn = Seen(m)
    m.frames(20)
    swaps = []

    def up(m):                                           # the monitor's screen shown (its own: $1000, $1800)
        return m.bank1[sym["mon_up"]] and mon_rows(m) == mon_vdc(m) and m.vdc[12] == 0x10 and m.vdc[20] == 0x18

    def back(m):                                         # the ZX81's ($0000, $0800)
        return not m.bank1[sym["mon_up"]] and pic_same(m) and not panel_busy(m) and m.vdc[12] == 0 \
            and m.vdc[20] == 8

    def swap(k, act, done):
        sn.phase = k + "<"
        m.frames(SEEN_N)
        sn.phase = k
        act()
        m.until(lambda: done(m), 300, f"{k}'s layout")
        m.frames(10)
        sn.phase = k + ">"
        m.frames(SEEN_N)
        sn.phase = ""
        swaps.append(k)

    def ret():
        m.keys = set(MKEY["\r"])
        m.frames(2)
        m.keys = set()

    swap("F5", lambda: fkey(m, "F5"), up)               # the first F5: the title, the registers
    st["first"] = mon_rows(m)
    mon_type(m, "=FF\r")
    mon_type(m, "X")
    st["leftx"] = mon_vdc(m)                             # (each time the screen as it was shown)
    swap("X", ret, back)
    swap("F5 later", lambda: fkey(m, "F5"), up)         # quiet: the prompt under the X line
    st["quiet"] = mon_rows(m)
    st["leftk"] = mon_vdc(m)
    swap("F5 key", lambda: fkey(m, "F5"), back)         # F5 at the prompt: the next line's
    fkey(m, "F5")
    m.until(lambda: up(m), 300, "the monitor")
    m.frames(10)
    st["quiet2"] = mon_rows(m)
    mon_type(m, "?\r", settle=40)
    st["help"] = mon_after(m, "?", 2)
    mon_type(m, "=1")                                    # (the help scrolled: the prompt at the bottom row)
    st["crow"] = m.bank1[mon_lbl()["crow"]]
    st["leftb"] = mon_vdc(m)
    swap("F5 key, the bottom row", lambda: fkey(m, "F5"), back)   # F5 there: the prompt below it
    swap("F5 later, scrolled", lambda: fkey(m, "F5"), up)          # scrolls the screen
    st["quiet3"] = mon_rows(m)
    sn.off()
    st["seen"] = {k: sn.bad(k) for k in swaps}


def quiet_st():
    if not QUIET:
        try:
            quiet_run(QUIET)
        except (AssertionError, KeyError, OSError) as e:
            QUIET["error"] = str(e).splitlines()[0] if str(e) else type(e).__name__
    if "error" in QUIET:
        raise AssertionError(QUIET["error"])
    return QUIET


def prompt_after(rows, i):
    """rows with row i + 1 the prompt alone (".")."""
    return rows[:i + 1] + ["."] + rows[i + 2:]


@zx128check
def mon_quiet_f5():
    # the first F5 after zx128 starts: the title and the registers; X (typed
    # under "=FF"), then F5: the screen as it was left (as shown before X),
    # the prompt alone on the line under ".X" (no title, no registers); F5
    # (the key) at that prompt and F5 again: the prompt on the next line; at
    # the bottom row (".=1" there, the help having scrolled the screen) the
    # same scrolls the screen up a line
    st = quiet_st()
    title = st["first"][0].startswith("#ZX128MON") and st["first"][1].startswith("#PC   AF   BC")
    x = max(i for i, r in enumerate(st["leftx"]) if r == ".X")
    q1 = st["quiet"] == prompt_after(st["leftx"], x)
    p = max(i for i, r in enumerate(st["quiet"]) if r == ".")
    q2 = st["quiet2"] == prompt_after(st["leftk"], p) and st["leftk"] == st["quiet"]
    q3 = st["crow"] == 24 and st["leftb"][24] == ".=1" and st["quiet3"] == st["leftb"][1:] + ["."]
    hello = sum(r.startswith("#ZX128MON") for r in st["quiet"])
    check("mon_quiet_f5", title and q1 and q2 and q3 and hello == 1,
          f"first {st['first'][:2]}; after X at row {x}: {st['quiet'][x:x + 3]} (as left, the prompt under it "
          f"{q1}); F5 at the prompt (row {p}) and back: {st['quiet2'][p:p + 3]} ({q2}); at the bottom row "
          f"({st['crow']}): {st['quiet3'][22:]} (scrolled {q3}); title lines {hello}")


@zx128check
def mon_help_title():
    # ? starts with the title line, as the first F5 shows it, then the help;
    # zx128's monitor's own name, ZX128MON, and the C128 builds'
    # version (build.py's VERSION)
    import build
    st = quiet_st()
    want = f"#ZX128MON {build.VERSION}   ? HELP   X OR F5: BACK"
    check("mon_help_title", st["help"][0] == want and st["help"][1] == simulate.mon_help(True)[0], f"{st['help']}")


# ---------------------------------------------------------------- V
V_VARS = (("D_FILE", 0x400C), ("DF_CC", 0x400E), ("VARS", 0x4010), ("E_LINE", 0x4014), ("STKEND", 0x401C),
          ("RAMTOP", 0x4004), ("PPC", 0x4007), ("FRAMES", 0x4034))
V_HELP = "V            SYSTEM VARIABLES"
V_PROG = "10 LET A=5\n20 DIM B(9)\n30 PRINT A"   # (variables, so VARS..E_LINE has some; PPC 30 at the end)
V_STATE = {}                                     # v_session's, per build


def v_want(m):
    """V's three lines as the model's bank 1 holds the ZX81's variables now:
    three a line, each its name (to 6 columns) and its word in hex, the
    first after a "#", two spaces between them."""
    cells = [f"{n:<6} {m.peek16(a):04X}" for n, a in V_VARS]
    return ["#" + "  ".join(cells[i:i + 3]) for i in range(0, len(cells), 3)]


def v_part3(m, odir):
    """The monitor's part 3 in common RAM (as the Z80 sees it) as the build
    made it: odir's zx128mon3.bin at the monitor's part3 (False without
    them)."""
    try:
        want = open(os.path.join(odir, "zx128mon3.bin"), "rb").read()
        a = mon_lbl()["part3"]
    except (OSError, KeyError):
        return False
    return len(want) > 0 and bytes(m.bank1[a:a + len(want)]) == want


def v_enter(m):
    """F5 at the ZX81's editor: the monitor up, its screen cleared."""
    fkey(m, "F5")
    m.until(lambda: m.bank1[sym128()["mon_up"]], 300, "the monitor")
    m.frames(40)
    mclr(m)


def v_leave(m):
    """X: the ZX81's editor again."""
    mon_type(m, "X\r", settle=0)
    m.until(lambda: not m.bank1[sym128()["mon_up"]] and zx_editor(m), 300, "the editor after X")
    m.frames(20)


def v_run(st, m, odir, rom, cls):
    """V on machine m (zx128's or zx128vic's, booted from the disk), what it
    showed in st: a program loaded and run (V_PROG), F5, V (lines); ":"
    RAMTOP to $7000, V (store); RETURN on V's first line (ret); RAMTOP
    back, ? (help); X, F7, F5, V (f7). Then the function ROM (rom, cls:
    the machine) from a reset, $FF05-$FFED garbage before: F5, V (reset)."""
    load_p(m, p_prog(V_PROG))
    m.until(lambda: zx_report(m) == "0/30" and zx_editor(m), 900, "the program's report")
    v_enter(m)
    st["lines"] = dict(rows=mon_cmdout(m, "V", 4), want=v_want(m) + ["."], part3=v_part3(m, odir))
    s, at = sym128(), max(i for i, r in enumerate(mon_rows(m)) if r.lstrip(".") == "V")
    st["lines"]["raw"] = bytes(m.bank1[s["mscr"] + s["mcols"] * (at + 1):s["mscr"] + s["mcols"] * (at + 2)])
    mon_type(m, ":4004 00 70\r", settle=20)
    st["store"] = dict(rows=mon_cmdout(m, "V", 3), want=v_want(m), ramtop=m.peek16(0x4004))
    crow = mon_lbl()["crow"]
    rows = mon_rows(m)
    first = max((i for i, r in enumerate(rows) if r.startswith(("#D_FILE", "#D#FILE"))), default=m.bank1[crow])
    for _ in range(m.bank1[crow] - first):
        m.keys = {C128NAMES["UP"]}
        m.frames(2)
        m.keys = set()
        m.frames(8)
    at, before = m.bank1[crow], mon_rows(m)
    m.keys = set(MKEY["\r"])
    m.frames(2)
    m.keys = set()
    m.frames(40)
    st["ret"] = dict(at=at, first=first, same=mon_rows(m) == before, crow=m.bank1[crow], rows=mon_rows(m)[first:first + 4])
    mon_type(m, ":4004 00 80\r", settle=20)
    mclr(m)
    mon_type(m, "?\r", settle=60)
    st["help"] = mon_rows(m)
    v_leave(m)
    f7_k(m)
    v_enter(m)
    st["f7"] = dict(rows=mon_cmdout(m, "V", 3), want=v_want(m), part3=v_part3(m, odir))
    m = rom_start(True, rom=open(rom, "rb").read(), cls=cls)
    m.poke(0xFF05, bytes((0x5A + i) & 0xFF for i in range(0xFFEE - 0xFF05)))
    m.run_8502()
    m.until(lambda: m.zx_screen()[23].startswith("k") and zx_editor(m), 900, "the K cursor from the ROM")
    v_enter(m)
    st["reset"] = dict(rows=mon_cmdout(m, "V", 3), want=v_want(m), part3=v_part3(m, odir))


def v_session(key, make, odir, rom, cls=None):
    """v_run's, once for each build (key)."""
    st = V_STATE.setdefault(key, {})
    if not st:
        try:
            v_run(st, make(), odir, rom, cls)
        except (AssertionError, KeyError, OSError, SystemExit, ValueError) as e:
            st["error"] = str(e).splitlines()[0] if str(e) else type(e).__name__
    if "error" in st:
        raise AssertionError(st["error"])
    return st


def v_checks(prefix, st, title, under=0x1F):
    """The V checks' verdicts on v_session's st: (name, ok, text) each.
    under: the screen code the names' "_" is shown as (zx128's VDC font
    has it at $1F; the VIC's, the C128's character ROM, has a left arrow
    there: zx128vic's V shows its $64, a line along the bottom), which
    mon_rows reads as "_" ($1F) or "#" (a graphic)."""
    out = []
    show = "_" if under == 0x1F else "#"
    want = lambda w: [x.replace("_", show) for x in w]
    a = st["lines"]
    out.append((prefix + "_lines", a["rows"] == want(a["want"]) and a["raw"][2:3] == bytes([under]) and a["part3"],
                f"{a['rows']} (want {want(a['want'])}); D_FILE's _ ${a['raw'][2]:02X} (want ${under:02X}); part 3 in "
                f"place {a['part3']}"))
    a = st["store"]
    out.append((prefix + "_store", a["rows"] == want(a["want"]) and a["ramtop"] == 0x7000 and "RAMTOP 7000" in a["rows"][1],
                f"after : 4004 00 70: {a['rows']} (want {want(a['want'])})"))
    a = st["ret"]
    out.append((prefix + "_return", a["at"] == a["first"] and a["same"] and a["crow"] == a["first"] + 1
                and a["rows"][0].startswith("#D"),
                f"RETURN at row {a['at']} (V's first {a['first']}): the screen as it was {a['same']}, the cursor to "
                f"row {a['crow']}; {a['rows']}"))
    h = st["help"]
    t = next((i for i, r in enumerate(h) if r.startswith(title)), None)
    body = h[t + 1:] if t is not None else []
    while body and not body[-1]:
        body.pop()
    r = next((i for i, x in enumerate(body) if x.startswith("R ")), None)
    shared = simulate.mon_help(True)             # the text zx64 shows too, V's line its own
    ok = (t == 1 and h[0].lstrip(".") == "?" and r is not None and body[r + 1:r + 2] == [V_HELP]
          and body == shared + ["."])
    wrong = next(((i, a, b) for i, (a, b) in enumerate(zip(body, shared)) if a != b), None)
    out.append((prefix + "_help", ok, f"title at row {t}, {len(body)} rows after it: R then "
                f"{body[r + 1:r + 2] if r is not None else '(no R)'}, last {body[-2:]}; the shared help's "
                f"{len(shared)} lines, first wrong {wrong}"))
    f, z = st["f7"], st["reset"]
    out.append((prefix + "_reset", f["rows"] == want(f["want"]) and f["part3"] and z["rows"] == want(z["want"])
                and z["part3"], f"after F7: {f['rows']} (want {want(f['want'])}), part 3 {f['part3']}; from the ROM "
                f"after a reset: {z['rows']} (want {want(z['want'])}), part 3 {z['part3']}"))
    return out


def v_zx128():
    import build
    return v_checks("mon_v", v_session("zx128", zx128, os.path.join(ROOT, "build", "obj"), ROM),
                    f"#ZX128MON {build.VERSION}")


@zx128check
def mon_v_lines():
    # a program loaded and run, F5, V: three lines, D_FILE DF_CC
    # VARS, E_LINE STKEND RAMTOP, PPC FRAMES, each its word as bank 1 has
    # it (the names to 6 columns, "#" first: lines to read), the prompt
    # after; the monitor's part 3 ($FF05 on) in common RAM as built
    check(*v_zx128()[0])


@zx128check
def mon_v_store():
    # ": 4004 00 70" (RAMTOP $7000), then V: RAMTOP 7000
    check(*v_zx128()[1])


@zx128check
def mon_v_return():
    # RETURN on V's first line ("#D_FILE ...", whose D would be a
    # command): nothing printed, nothing run, the cursor on the next line
    check(*v_zx128()[2])


@zx128check
def mon_v_help():
    # ? on the top row (after CLR): the title under it, then the
    # help with V's line after R's, to the last (@) and the prompt, none
    # scrolled away (25 rows)
    check(*v_zx128()[3])


@zx128check
def mon_v_reset():
    # V after F7 (the ZX81 started again) and from the function
    # ROM after a reset ($FF05-$FFED garbage before it): the right values,
    # part 3 in place
    check(*v_zx128()[4])


@zx128check
def mon_switch_seen():
    # F5 (the first, and later ones) and X, F5 (the key) back, at the bottom
    # row too (its scroll): no frame, as the VDC shows it (each row as the
    # beam passes it, from the registers the frame began with), has a cell
    # that looks like neither the layout before the switch nor the one
    # after it (the half-done screen: a cell's character from one and its
    # attribute from the other); the ZX81's rows 0-21 full, so most cells
    # change
    st = quiet_st()["seen"]
    ok = all(not nb and differ > 1000 for _, nb, _, _, differ in st.values())
    check("mon_switch_seen", ok, "; ".join(
        f"{k}: {nb} of {n} frames with cells neither layout's (most {most}, first {first}; {differ} cells change)"
        for k, (n, nb, most, first, differ) in st.items()))


@zx128check
def pic_hi_area():
    # zx128's own code area: in bank 1 at $C900 as built, ending before $DFFE,
    # but for blk_cfg, which boot128's vblk fills in: the
    # VDC's block operations as the model does them
    sym = sym128()
    hi = bytearray(open(os.path.join(ROOT, "build", "obj", "zx128hi.bin"), "rb").read())
    m = zx128(frames=1)
    c = sym["blk_cfg"] - 0xC900
    cfg = bytes(m.bank1[sym["blk_cfg"]:sym["blk_cfg"] + 5])
    want = bytes([sym["blk_copyn"] - VDC_BLK_COPYX, sym["blk_filln"] - VDC_BLK_FILLX, m.vdc[24] & 0x7F,
                  8 + VDC_BLK_COPYX, 13 + VDC_BLK_FILLX])
    hi[c:c + 5] = cfg
    end = sym["hiend"]
    check("pic_hi_area", sym["hicode"] == 0xC900 and sym["hiend"] == 0xC900 + len(hi) and end <= 0xDFFE
          and bytes(m.bank1[0xC900:0xC900 + len(hi)]) == hi and sym["pic_step"] >= 0xC900 and cfg == want,
          f"${sym['hicode']:04X}-${sym['hiend'] - 1:04X}, {len(hi)} bytes ({0xDFFE - end} to spare); "
          f"blk_cfg {cfg.hex()} (want {want.hex()})")


@zx128check
def pic_mvd_slots():
    # pic_mvd finds where the ROM was 6 or 8 bytes up the stack (pic_irq
    # jumping to pic_step, with no window, or calling it): every time it
    # ran from the IRQ in pic_t's frames (pic_time's, pic_blk_nowin's ...),
    # one of the two held irq_early's return. A push added on the way would
    # make it miss them, and the table would no longer wait for the ROM's
    # moves. (pic_t's frames all call pic_step; the jump's 6 was seen with
    # lk_sync made to find no window.)
    n = sum(MVD_SLOTS.values())
    check("pic_mvd_slots", n > 0 and not MVD_SLOTS[None],
          f"{n} times from the IRQ: 8 bytes up {MVD_SLOTS[8]}, 6 up {MVD_SLOTS[6]}, neither {MVD_SLOTS[None]}")


# ---- the function ROM: build/zx128.rom, c128/from.asm's copier
# and zx128.prg's bytes behind it, started as the kernal starts it
ROM = os.path.join(ROOT, "build", "zx128.rom")
CRT, CRT_VICE = os.path.join(ROOT, "build", "zx128.crt"), os.path.join(ROOT, "build", "obj", "zx128-vice.crt")
ROM_CR = {True: 0x2A, False: 0x16}   # $FF00 as the kernal enters an external (a cartridge), internal function
                                     # ROM: its bank 8, 4 (JSRFAR; VICE's kernal 318020-05, $F7F0)
ROM_SLOT = {True: 3, False: 1}       # the poll's slot for the ROM at $8000 ($0AC0, counting down: 3-0 external
                                     # $8000, $C000, internal $8000, $C000; VICE) and its ID's place ($0AC1 + slot)
ROM_BACK = 0x02D0                    # where the copier's RTS goes (the kernal's JSRFAR, $02CD)
ROM_KERNAL = [0xFF84, 0xFF87, 0xFF8A, 0xFF81]   # IOINIT RAMTAS RESTOR CINT, in that order
ROM_RUNS = {}                        # (ext, rom) -> (the C128 once at the K cursor, what rom_start saw)


def crt_chips(path):
    """A C128 .crt's header (as VICE's cartconv and the Ultimate take it:
    "C128 CARTRIDGE  ", header $40, version 2.0, type 0, EXROM and GAME 0)
    and its CHIP packets: (header ok, name, [(load, size, bytes)])."""
    d = open(path, "rb").read()
    ok = (d[:16] == b"C128 CARTRIDGE  " and int.from_bytes(d[16:20], "big") == 0x40 and d[20:22] == b"\x02\x00"
          and d[22:24] == b"\0\0" and d[24:26] == b"\0\0")
    chips, o = [], 0x40
    while o < len(d):
        n = int.from_bytes(d[o + 4:o + 8], "big")
        ok &= d[o:o + 4] == b"CHIP" and d[o + 8:o + 12] == b"\0\0\0\0" and n >= 16 and o + n <= len(d)
        load, size = int.from_bytes(d[o + 12:o + 14], "big"), int.from_bytes(d[o + 14:o + 16], "big")
        ok &= n == 16 + size
        chips.append((load, size, d[o + 16:o + 16 + size]))
        o += max(n, 16)
    return ok, d[0x20:0x40].rstrip(b"\0"), chips


def rom_start(ext=True, key=None, joy=0, irq=False, rom=None, cls=None):
    """A C128 as the kernal has it when it starts a function ROM with ID 1,
    at reset, before its own init (VICE's kernal):
    build/zx128.rom external or internal, $FF00 its bank's ($2A, $16),
    the MMU's other registers as the kernal's reset sets them, CIA 1 as a
    reset leaves it (all zero, its data directions modelled), the poll's
    slot and the ROM's ID in $0AC0/$0AC1+, and the 8502 at $8000 with
    ROM_BACK to return to, the decimal flag set and interrupts on (JSRFAR's
    RTI takes the flags from zero page nobody has set). key: a key held
    (CTRL skips); joy: joystick 1's lines held ($04 left, as CTRL; $10
    fire, as SPACE); irq: the 8502's IRQ line held low from
    the start (the VIC's raster IRQ, still enabled and not acknowledged
    after the reset button: the VIC has no reset). rom: another
    function ROM's 32K than build/zx128.rom's; cls: another machine than
    C128 (sim128vic's C128VIC, for zx128vic's ROM)."""
    m = (cls or C128)()
    m.fnrom, m.fnrom_ext = rom or open(ROM, "rb").read(), ext
    m.mmu[5], m.mmu[6], m.mmu[9] = 0xBF, 0x04, 0x01  # (the kernal's $E04B table: $D505 $BF, $D506 $04, P1L 1)
    m.set_cr(ROM_CR[ext])
    m.cia_ddr = True
    m.cia[0:4] = bytes(4)
    m.pa = 0xFF
    m.keys = keyset([key]) if key else set()
    m.joy1, m.irq8502 = joy, irq
    m.bank0[0x0AC0] = ROM_SLOT[ext]
    m.bank0[0x0AC1 + ROM_SLOT[ext]] = 1
    sp = 0xF9
    m.bank0[0x100 + sp + 1:0x100 + sp + 3] = (ROM_BACK - 1).to_bytes(2, "little")
    cpu = m.cpu
    cpu.pc, cpu.sp, cpu.p = 0x8000, sp, cpu.BREAK | cpu.UNUSED | cpu.DECIMAL
    return m


def rom_boot(ext, path=None, cls=None):
    """rom_start's C128 run until zx128's K cursor, once for each ext and
    ROM (ROM_RUNS; path: another ROM file than build/zx128.rom, cls as
    rom_start's, PRG the image's program): what it saw on the way, a
    dict: calls, the kernal calls
    (address, $FF00 then); at, at the copier's JMP $1300 ($FF00, the
    flags, bank 0 from $1300 as far as zx128.prg's bytes go and a page
    past them); rom_reads, the ROM bytes read the model hasn't (the
    kernal's, BASIC's); irqs, IRQs taken before $1300; cycles, the 8502's
    from $8000 to $1300 (the kernal's calls take none: traps); zp, zero
    page after the kernal's last call (CINT), zp1300 and sp at $1300.
    Entered with an IRQ pending (rom_start's irq), the line let go at
    $1300."""
    key = (ext, path or ROM)
    if key in ROM_RUNS:
        return ROM_RUNS[key]
    m = rom_start(ext, irq=True, rom=open(key[1], "rb").read(), cls=cls)
    n = len(open(PRG, "rb").read()) - 2
    seen = dict(calls=[], at=None)
    c0 = m.cpu.processorCycles

    def kcall(m):
        if m.fnrom_byte(m.cpu.pc) is not None:          # (the ROM's own code there: its unpacker)
            m._step8502()
            return
        seen["calls"].append((m.cpu.pc, m.cr))
        m._step8502()
        seen["zp"] = bytes(m.bank0[0:0x100])            # (after the last, CINT: zero page as the kernal leaves it)

    def at1300(m):
        seen["at"] = (m.cr, m.cpu.p, bytes(m.bank0[0x1300:0x1300 + n + 0x100]))
        seen["irqs"], m.irq8502 = m.irqs8502, False
        seen["cycles"], seen["sp"], seen["zp1300"] = m.cpu.processorCycles - c0, m.cpu.sp, bytes(m.bank0[0:0x100])
        del m.traps8502[0x1300]
    for a in ROM_KERNAL:
        m.traps8502[a] = kcall
    m.traps8502[0x1300] = at1300
    m.run_8502()
    for a in ROM_KERNAL:
        del m.traps8502[a]
    seen["rom_reads"] = list(m.rom_reads)
    m.frames(200)
    ROM_RUNS[key] = m, seen
    return ROM_RUNS[key]


ROM_BIG = []                         # big_rom's, once
COPIER_CYCLES = {"zx128": 547_360, "zx128vic": 418_840}   # a plain copier's (the image not
                                     # packed): the 8502's cycles from $8000 to $1300 in the model
SECOND = 985_248                     # the 8502's cycles a second at 1 MHz (PAL)


def from_sym(path):
    """A from.sym's symbols (acme --symbollist): {name: value}."""
    import re
    return {mm.group(1): int(mm.group(2), 16) for mm in re.finditer(r"^\s*(\w+)\s*=\s*\$([0-9a-fA-F]+)",
            open(path).read(), re.M)}


def big_rom():
    """A function ROM from an image 200 bytes bigger than zx128.prg's (its
    bytes, then 200 of a pattern that repeats only every 256), built as
    build.py builds zx128.rom (its files in a directory of their own):
    (the ROM, the image, the bytes spare zx128.prg's own build reports,
    what an image too big for the ROM stopped with: zx128.prg's and bytes
    that don't pack, to 100 below $C000: 11,437, more than the ROM's
    spare). A SystemExit (it doesn't fit) goes on to the check."""
    if ROM_BIG:
        return ROM_BIG[0]
    import build
    import random
    import tempfile
    prg = open(PRG, "rb").read()
    big = prg + bytes((i * 7 + 3) & 0xFF for i in range(200))
    r = random.Random(8)
    keep = build.BUILD, build.OBJ
    with tempfile.TemporaryDirectory(prefix="zx128rom") as tmp:
        build.BUILD = build.OBJ = tmp
        try:
            spare = build.build_rom128(prg)
            try:
                n = 0xC000 - 0x1300 - (len(prg) - 2) - 100
                build.build_rom128(prg + bytes(r.randrange(256) for _ in range(n)))
                over = "fits"
            except SystemExit as e:
                over = str(e)
            build.build_rom128(big)
            rom = open(os.path.join(tmp, "zx128.rom"), "rb").read()
        finally:
            build.BUILD, build.OBJ = keep
    ROM_BIG.append((rom, big[2:], spare, over))
    return ROM_BIG[0]


def rom_vectors(rom):
    """rom's vectors at $FFFA-$FFFF (NMI, reset, IRQ) and whether they are
    on from.asm's RTIs in the ROM's $C000 half below the MMU (there
    whenever the vectors are: the unpack has RAM at $8000-$BFFF for a
    while): NMI and reset on an RTI, the IRQ on PLA, ORA #$04,
    PHA, RTI."""
    vec = [int.from_bytes(rom[o:o + 2], "little") for o in (0x7FFA, 0x7FFC, 0x7FFE)] if len(rom) == 0x8000 else []
    code = [b"\x40", b"\x40", b"\x68\x09\x04\x48\x40"]
    return vec, len(vec) == 3 and all(0xC000 <= v < 0xFF00 and rom[v - 0x8000:v - 0x8000 + len(c)] == c
                                      for v, c in zip(vec, code))


def packed_rom(rom, fsym, prg, repack=True):
    """A function ROM (rom's 32K, its from.sym's symbols fsym)
    against its program (prg, with its load address): (it holds, what it
    shows, the bytes spare). The image packed (extras/zx0/zx0.py) from
    from.asm's STREAM, STREAMLEN bytes, right against the unpacker's part
    below the MMU (PARTB to partb_end; a byte of $FF between when "CBM"
    moved it down), which unpacks to prg's bytes but its
    load address, exactly, and is what build.py packs (ZX0_WEIGHT; not
    looked at without repack); from.asm's
    code at $8000 before it (to codeend), $FF from there to STREAM (the
    bytes spare), $FF00-$FF04 $FF; the unpacker (unpack) and its other
    part (from $FF05, before the vectors) in the $C000 half; and no copy
    the unpacker makes while the stream is below $C000 (this ROM at $8000
    then) reads at $8000 or above (zx0.phase1_reads)."""
    import build
    import zx0
    img = prg[2:]
    st, pb, pe, ce = fsym["STREAM"], fsym["PARTB"], fsym["partb_end"], fsym["codeend"]
    packed = bytes(rom[st - 0x8000:st - 0x8000 + fsym["STREAMLEN"]])
    after = rom[st - 0x8000 + len(packed):pb - 0x8000]
    try:
        out = zx0.unpack(packed)
    except (IndexError, ValueError) as e:
        out = repr(e).encode()
    same = out == img
    want = zx0.pack(img, build.ZX0_WEIGHT) if repack else packed
    gaps = (rom[ce - 0x8000:st - 0x8000] == b"\xff" * (st - ce) and rom[0x7F00:0x7F05] == b"\xff" * 5
            and after == b"\xff" * len(after) and len(after) <= 1)
    places = (ce <= st < pb < pe <= 0xFF00 and 0xC000 <= pb and 0xC000 <= fsym["unpack"] < 0xFFFA
              and 0xFF05 <= fsym["parta"] < fsym["parta_end"] <= 0xFFFA)
    reads = zx0.phase1_reads(packed, st)
    ok = same and packed == want and gaps and places and not reads
    return ok, (f"stream ${st:04X}-${pb - 1:04X} ({len(packed)} bytes, {len(packed) / len(img):.3f} of the image's "
                f"{len(img)}): unpacks to the image {same}, as build.py packs it {packed == want}; code to ${ce:04X}, $FF to the stream and at $FF00-$FF04 {gaps}; the unpacker "
                f"${pb:04X}-${pe - 1:04X} and ${fsym['parta']:04X}-${fsym['parta_end'] - 1:04X}, unpack ${fsym['unpack']:04X} "
                f"{places}; copies reading the ROM before the stream's $C000 {reads[:2]}"), st - ce


@zx128check
def rom_header():
    # build/zx128.rom: 32K, the kernal's ID 1 and "CBM" at $8006, the NMI
    # and reset vectors at $FFFA-$FFFD on an RTI in the ROM's $C000 half
    # below the MMU ($FF00), the IRQ's at $FFFE on one that sets I in the
    # flags it pulls (PLA, ORA #$04, PHA, RTI), no "CBM" at $C007 (the
    # kernal would start that half); build/zx128.crt one CHIP of 32K at
    # $8000 (the Ultimate's), build/obj/zx128-vice.crt two of 16K at $8000
    # and $C000 (VICE's), both the ROM's bytes, named ZX128. big_rom's (an
    # image 200 bytes more than zx128.prg's) has its vectors as zx128.rom's;
    # an image that doesn't fit (zx128.prg's and bytes that don't pack, to 100 below $C000)
    # stops the build, with its packed size and the bytes over
    rom = open(ROM, "rb").read()
    big, image, spare, over = big_rom()
    vec, rti = rom_vectors(rom)
    bvec, brti = rom_vectors(big)
    one, vice = crt_chips(CRT), crt_chips(CRT_VICE)
    check("rom_header", len(rom) == 0x8000 and rom[6:10] == b"\x01CBM" and rti and rom[0x4007:0x400A] != b"CBM"
          and brti and bvec == vec
          and over.startswith("the function ROM doesn't fit") and "packed" in over and "more than" in over
          and one == (True, b"ZX128", [(0x8000, 0x8000, rom)])
          and vice == (True, b"ZX128", [(0x8000, 0x4000, rom[:0x4000]), (0xC000, 0x4000, rom[0x4000:])]),
          f"{len(rom)} bytes, $8006 {rom[6:10].hex(' ')}, vectors {' '.join(f'${v:04X}' for v in vec)} on RTI {rti}; "
          f"zx128.crt {one[0]} {one[1]} {[(hex(a), hex(b), c == rom[:b] or c == rom[0x4000:]) for a, b, c in one[2]]}; "
          f"zx128-vice.crt {vice[0]} {vice[1]} {[(hex(a), hex(b)) for a, b, c in vice[2]]}; an image of "
          f"{len(image)} bytes: vectors {' '.join(f'${v:04X}' for v in bvec)} on RTI {brti}; too big: {over!r}")


@zx128check
def rom_packed():
    # build/zx128.rom holds zx128.prg's image packed (packed_rom:
    # the stream, under 0.9 of it, unpacks to it, right against the unpacker in the $C000
    # half, no copy reading the ROM while it is at $8000), its bytes spare
    # as build.py says (SPARE["rom"] when this process built it, else
    # from from.sym); and from the ROM, external and internal: zero page
    # at $1300 as the kernal left it but $FA-$FE (the user's: the
    # unpacker's $F3-$F9 kept and put back), the stack as it came (SP $F9),
    # and the 8502's time from $8000 to $1300 at most a second (at 1 MHz)
    # more than a plain copier's (COPIER_CYCLES)
    # The same ROM with its stream a byte lower and $FF
    # after it (build.py's retry when "CBM" lands at $C007) as packed_rom
    # wants it too. And an NMI (RESTORE) while the unpack is in its second
    # phase (RAM at $8000-$BFFF): its handler there, in the $C000 half,
    # and the image at $1300 still exactly
    got = []
    fsym = from_sym(os.path.join(ROOT, "build", "obj", "from.sym"))
    prg = open(PRG, "rb").read()
    rom = open(ROM, "rb").read()
    ok, text, spare = packed_rom(rom, fsym, prg)
    got.append((ok and fsym["PARTB"] - fsym["STREAM"] - fsym["STREAMLEN"] in (0, 1)  # (1: "CBM"'s retry)
                and fsym["STREAMLEN"] < 0.9 * (len(prg) - 2), text + f"; {spare} bytes spare"))
    st, n = fsym["STREAM"] - 0x8000, fsym["STREAMLEN"]
    low = rom[:st - 1] + rom[st:st + n] + b"\xff" + rom[st + n:]
    ok, text, _ = packed_rom(low, dict(fsym, STREAM=fsym["STREAM"] - 1), prg)
    got.append((ok, f"a byte lower: {text if not ok else 'packed ok'}"))
    m = rom_start(True)
    for _ in range(2_000_000):                  # (into the second phase: $2F)
        if m.cr == ROM_CR[True] | 0x0F or m.cpu.pc == 0x1300:
            break
        m._step8502()
    for _ in range(5000):
        m._step8502()
    at = m.cpu.pc
    m.nmi8502 = True
    for _ in range(2_000_000):
        if m.cpu.pc == 0x1300:
            break
        m._step8502()
    img = prg[2:]
    same = bytes(m.bank0[0x1300:0x1300 + len(img)]) == img
    got.append((bool(m.nmis8502) and m.nmis8502[0][2] == 0x2F and m.cpu.pc == 0x1300 and same,
                f"an NMI at ${at:04X} in the second phase: taken {[(hex(a), hex(c)) for a, _, c, _ in m.nmis8502]}, "
                f"at ${m.cpu.pc:04X}, the image at $1300 {same}"))
    for ext in (True, False):
        got.append(rom_unpacked(rom_boot(ext)[1], ext, "zx128"))
    check("rom_packed", all(g for g, _ in got), "; ".join(t for _, t in got))


def rom_unpacked(seen, ext, name):
    """rom_boot's seen (ext, the build's name): zero page at $1300 as after
    CINT but $FA-$FE, SP $F9 (as the kernal called $8000), and the
    cycles to $1300 at most SECOND more than COPIER_CYCLES[name]."""
    zp, zp1 = seen.get("zp", b""), seen.get("zp1300", b"")
    diff = [hex(a) for a in range(0x100) if zp[a:a + 1] != zp1[a:a + 1] and not 0xFA <= a <= 0xFE]
    c = seen.get("cycles", 0)
    more = c - COPIER_CYCLES[name]
    return (not diff and seen.get("sp") == 0xF9 and 0 < c and more <= SECOND,
            f"{'external' if ext else 'internal'}: zero page changed at {diff[:4]}, SP ${seen.get('sp', 0):02X}, "
            f"$8000 to $1300 {c} cycles ({c / SECOND:.3f} s at 1 MHz; {more / SECOND:+.3f} s on the copier's)")


ROM_EDGES = []                       # rom_unpack_edges' images, once


def edge_images():
    """Images for rom_unpack_edges, as (name, PRG bytes with $1300 first):
    all one byte (past $8000, one long copy at offset 1; the stream so
    short it is all above $C000), random bytes (literals, runs of 256 and
    more), a stretch reaching past $8000 (random to just below it, a run
    across it, then a piece of it again: a copy reading above $8000, the
    image's last), a far offset (a block 32,000 bytes back), one byte."""
    if ROM_EDGES:
        return ROM_EDGES
    import random
    r = random.Random(8128)
    rnd = lambda n: bytes(r.randrange(256) for _ in range(n))
    below = 0x8000 - 0x1300 - 40
    run = bytes([0x77]) * 600
    tail = rnd(300)
    past = rnd(below) + run + tail + tail[100:260]
    far = rnd(32_000)
    far += far[:400]
    imgs = [("one byte $AA", b"\xaa" * 30_000), ("random", rnd(20_000)), ("past $8000", past),
            ("far offset", far), ("one byte", b"\x42")]
    ROM_EDGES.extend((n, b"\x00\x13" + d) for n, d in imgs)
    return ROM_EDGES


@zx128check
def rom_unpack_edges():
    # the unpacker (from.asm, from the ROM as build.py builds it
    # for an image) on edge_images', from rom_start, external ($FF00 $2B,
    # then $2F) and internal ($17, then $1F): bank 0 from
    # $1300 the image exactly at the JMP $1300, the page after it
    # untouched, $FF00 the kernal's; each ROM as packed_rom wants it. And
    # two images stop the build: one whose copy would read the ROM (a run
    # from $1300 past $8000 while the stream is still below $C000), and
    # one that runs past $C000 (the ROM stays at $C000 in both phases, so
    # a copy from output up there would read it: 30,000 random bytes and
    # 15,000 zeros)
    import build
    import random
    import tempfile
    got = []
    keep = build.BUILD, build.OBJ
    with tempfile.TemporaryDirectory(prefix="zx128edge") as tmp:
        build.BUILD = build.OBJ = tmp
        try:
            for name, prg in edge_images():
                build.build_rom128(prg)
                rom = open(os.path.join(tmp, "zx128.rom"), "rb").read()
                ok, text, _ = packed_rom(rom, from_sym(os.path.join(tmp, "from.sym")), prg, repack=False)
                img = prg[2:]
                for ext in (True, False):
                    m = rom_start(ext, rom=rom)
                    for _ in range(20_000_000):
                        if m.cpu.pc == 0x1300:
                            break
                        m._step8502()
                    mem = bytes(m.bank0[0x1300:0x1300 + len(img) + 0x100])
                    bad = [i for i in range(len(img)) if mem[i] != img[i]]
                    got.append((ok and m.cpu.pc == 0x1300 and not bad and mem[len(img):] == bytes(0x100)
                                and m.cr == ROM_CR[ext] & 0xCF,
                                f"{name} ({len(img)} bytes, {'external' if ext else 'internal'}): at "
                                f"${m.cpu.pc:04X}, {len(bad)} not the image's (from "
                                f"{bad[:1] and f'${0x1300 + bad[0]:04X}'}), past it untouched "
                                f"{mem[len(img):] == bytes(0x100)}, $FF00 ${m.cr:02X}; "
                                f"{text if not ok else 'packed ok'}"))
            refused = []
            r = random.Random(81)
            for img in (bytes(28_000) + bytes(r.randrange(256) for _ in range(16_200)),
                        bytes(r.randrange(256) for _ in range(30_000)) + bytes(15_000)):
                try:
                    build.build_rom128(b"\x00\x13" + img)
                    refused.append("built")
                except SystemExit as e:
                    refused.append(str(e))
        finally:
            build.BUILD, build.OBJ = keep
    got.append(("would read the ROM" in refused[0], f"a run past $8000 with the stream below $C000: {refused[0]!r}"))
    got.append(("$C000" in refused[1] and refused[1] != "built", f"an image past $C000: {refused[1]!r}"))
    check("rom_unpack_edges", all(g for g, _ in got), "; ".join(t for _, t in got))


@zx128check
def rom_zx0():
    # extras/zx0/zx0.py: pack, then unpack, gives the bytes back, for
    # edge_images' and two bytes (both C128 images: rom_packed,
    # vic_rom_packed); packing again gives the same bytes; a copy from
    # before the start is refused by unpack; phase1_reads finds a copy
    # reading $8000 or above with the stream below $C000 (a run of zeros
    # from $7800 past $8000, the stream at $B000), none with it at $C000, and one
    # reading $C000 or above whatever the phase (the ROM is
    # there in both); build.rom_more's room in the PRG stops at $C000
    import build
    import time
    import zx0
    got = []
    t0 = time.time()
    for name, d in [(n, p[2:]) for n, p in edge_images()] + [("two bytes", b"\x01\x02")]:
        s = zx0.pack(d, build.ZX0_WEIGHT)
        got.append((zx0.unpack(s) == d, f"{name}: {len(d)} -> {len(s)}"))
    d = edge_images()[2][1][2:]
    again = zx0.pack(d, build.ZX0_WEIGHT) == zx0.pack(d, build.ZX0_WEIGHT)
    t = time.time() - t0
    w = zx0.Bits()                                  # a byte, then a copy from 2 back: before the start
    w.elias(1)
    w.byte(0x42)
    w.bit(1)
    w.elias(1, invert=True)
    w.byte((127 - 1) << 1)
    w.back = True
    w.elias(1)
    w.bit(1)
    w.elias(256, invert=True)
    try:
        zx0.unpack(bytes(w.out))
        bad = "unpacked"
    except (ValueError, IndexError) as e:
        bad = type(e).__name__
    zeros = zx0.pack(bytes(0x1000))                                 # (from $7800 to $8800)
    hit = zx0.phase1_reads(zeros, 0xB000, out=0x7800)
    miss = zx0.phase1_reads(zeros, 0xC000, out=0x7800)
    high = zx0.phase1_reads(zx0.pack(bytes(0x3100)), 0xF000, out=0x9000)   # (to $C100, phase 2)
    more = build.rom_more(20_000, 20_000, 24_716)                   # (room only to $C000)
    got.append((again and bad != "unpacked" and hit and not miss and bool(high) and high[-1][1] >= 0xC000
                and more == 0xC000 - 0x1300 - 24_716,
                f"packed again the same {again}; a copy from before the start: {bad}; phase1_reads at $B000 "
                f"{hit[:1]}, at $C000 {miss[:1]}, a copy reading $C000 or above in phase 2 {high[-1:]}; rom_more "
                f"capped at $C000 {more}; {t:.1f} s"))
    check("rom_zx0", all(g for g, _ in got), "; ".join(t for g, t in got if not g) or "; ".join(t for _, t in got))


@zx128check
def rom_boots():
    # from the ROM, external ($FF00 $2A) and internal ($16), no disk, entered
    # with interrupts on and an IRQ pending (taken once: the ROM's IRQ
    # vector returns with I set, not into the same IRQ again): the
    # kernal's IOINIT, RAMTAS, RESTOR, CINT (in that order) with its ROM at
    # $C000 ($FF00 the entry's AND $CF: $0A, $06), then zx128 as from the
    # disk: the K cursor, the panel; no ROM byte read that the model hasn't
    # (the kernal's, BASIC's: only this ROM's), nothing it has no chip for
    got = []
    for ext in (True, False):
        m, seen = rom_boot(ext)
        want = [(a, ROM_CR[ext] & 0xCF) for a in ROM_KERNAL]
        got.append((seen["calls"] == want and not seen["rom_reads"] and m.zx_screen()[23].startswith("k")
                    and panel_ok(m) and not m.stray_io and not m.map_errors and seen.get("irqs") == 1,
                    f"{'external' if ext else 'internal'}: IRQs taken {seen.get('irqs')}, kernal calls "
                    f"{' '.join(f'${a:04X}/${c:02X}' for a, c in seen['calls'])}, other ROMs read "
                    f"{seen['rom_reads'][:2]}, row 23 {m.zx_screen()[23]!r}, stray {m.stray_io[:2]}"))
    check("rom_boots", all(g for g, _ in got), "; ".join(t for _, t in got))


@zx128check
def rom_bytes():
    # at the copier's JMP $1300: bank 0 from $1300 holds zx128.prg's bytes
    # (but its load address) exactly, the page after them untouched, $FF00
    # the kernal's (the entry's AND $CF) and interrupts off; external and
    # internal. Then F7 (external), its ROM written over in bank 1: put
    # back from bank 0's copy (prom), no disk. And big_rom's, 200 bytes
    # more (packed): bank 0 from $1300 the image's bytes in order
    # at the JMP $1300, the page after them untouched; external and
    # internal
    prg = open(PRG, "rb").read()[2:]
    got = []
    big, image, _, _ = big_rom()
    for ext in (True, False):
        m = rom_start(ext, rom=big)
        for _ in range(2_000_000):
            if m.cpu.pc == 0x1300:
                break
            m._step8502()
        mem = bytes(m.bank0[0x1300:0x1300 + len(image) + 0x100])
        bad = [i for i in range(len(image)) if mem[i] != image[i]]
        got.append((m.cpu.pc == 0x1300 and not bad and mem[len(image):] == bytes(0x100)
                    and m.cr == ROM_CR[ext] & 0xCF,
                    f"{'external' if ext else 'internal'}, {len(image)} bytes: at ${m.cpu.pc:04X}, "
                    f"{len(bad)} not the image's (from {bad[:1] and f'${0x1300 + bad[0]:04X}'}), past them untouched "
                    f"{mem[len(image):] == bytes(0x100)}, $FF00 ${m.cr:02X}"))
    for ext in (True, False):
        m, seen = rom_boot(ext)
        cr, p, mem = seen["at"] or (None, 0, b"")
        same = mem[:len(prg)] == prg
        got.append((same and mem[len(prg):] == bytes(0x100) and cr == ROM_CR[ext] & 0xCF and p & m.cpu.INTERRUPT
                    and not p & m.cpu.DECIMAL,
                    f"{'external' if ext else 'internal'}: {len(prg)} bytes the same {same}, past them untouched "
                    f"{mem[len(prg):] == bytes(0x100)}, $FF00 {cr if cr is None else f'${cr:02X}'}, flags "
                    f"${p:02X}"))
    m, _ = rom_boot(True)
    m.bank1[0x1234:0x1235] = bytes([m.bank1[0x1234] ^ 0x55])
    opens = m.drive.opens
    f7_k(m)
    f7 = rom_now(m) == rom_want() and m.drive.opens == opens
    check("rom_bytes", all(g for g, _ in got) and f7, "; ".join(t for _, t in got) + f"; F7 puts the ROM back, no "
          f"disk: {f7}")


@zx128check
def rom_skip():
    # CTRL held: the copier returns to the kernal (ROM_BACK) with its
    # stack as it came, $FF00 and CIA 1 (its data directions, port A's
    # lines) as they were, its slot's ID cleared (BASIC's PHOENIX calls
    # every ROM still there: it would start zx128 then), no kernal call,
    # nothing copied; external and internal. Joystick 1 held left instead
    # (PB2 low in every column, as CTRL's in column 7, but with none
    # selected too), SPACE, or joystick 1's fire: no skip, on to the
    # kernal's IOINIT, CIA 1 put back.
    # And a kernal whose $0AC0 isn't the poll's slot ($80 there): no byte
    # of bank 0 cleared
    got = []
    m = rom_start(True, key="CTRL")
    m.bank0[0x0AC0] = 0x80
    m.bank0[0x0AC1 + 0x80] = 0x5A                        # (a byte the guard keeps)
    before = bytes(m.bank0)
    for _ in range(5000):
        if m.cpu.pc in KERNAL128 or m.cpu.pc == ROM_BACK:
            break
        m._step8502()
    changed = [a for a in range(0x10000) if m.bank0[a] != before[a] and not 0x100 <= a < 0x200]
    got.append((m.cpu.pc == ROM_BACK and not changed, f"$0AC0 $80: at ${m.cpu.pc:04X}, bank 0 changed at "
                f"{[hex(a) for a in changed[:4]]}"))
    for what, kw in (("joystick 1 left", dict(joy=0x04)), ("SPACE", dict(key="SPACE")),
                     ("joystick 1's fire", dict(joy=0x10))):
        m = rom_start(True, **kw)
        cia, pa = bytes(m.cia[2:4]), m.pa
        for _ in range(5000):
            if m.cpu.pc in KERNAL128 or m.cpu.pc == ROM_BACK:
                break
            m._step8502()
        got.append((m.cpu.pc == ROM_KERNAL[0] and bytes(m.cia[2:4]) == cia and m.pa == pa,
                    f"{what}: at ${m.cpu.pc:04X} (want ${ROM_KERNAL[0]:04X}), CIA 1's directions "
                    f"{bytes(m.cia[2:4]).hex(' ')}, port A ${m.pa:02X}"))
    for ext in (True, False):
        got.append(ctrl_skip(rom_start(ext, key="CTRL"), ext))
    check("rom_skip", all(g for g, _ in got), "; ".join(t for _, t in got))


def ctrl_skip(m, ext):
    """rom_start's m (CTRL held) run until the copier is back in the
    kernal: (as rom_skip wants it, what it saw): at ROM_BACK with the
    stack as it came, $FF00 and CIA 1 as they were, no kernal call, bank 0
    as it was but the slot's ID (cleared) and the stack's page."""
    before = bytearray(m.bank0)
    cia, pa = bytes(m.cia[0:4]), m.pa
    calls, sp = [], m.cpu.sp
    for _ in range(5000):
        if m.cpu.pc == ROM_BACK:
            break
        if m.cpu.pc in KERNAL128:
            calls.append(m.cpu.pc)
        m._step8502()
    before[0x0AC1 + ROM_SLOT[ext]] = 0
    changed = [a for a in range(0x10000) if m.bank0[a] != before[a] and not 0x100 <= a < 0x200]
    return (m.cr == ROM_CR[ext] and m.cia[2:4] == cia[2:4] and m.pa == pa and not changed and not calls
            and m.cpu.pc == ROM_BACK and m.cpu.sp == sp + 2,
            f"{'external' if ext else 'internal'}: $FF00 ${m.cr:02X}, CIA 1 {bytes(m.cia[0:4]).hex(' ')} "
            f"(was {cia.hex(' ')}), port A ${m.pa:02X} (was ${pa:02X}), bank 0 changed at "
            f"{[hex(a) for a in changed[:4]]} (the slot's ID cleared: {m.bank0[0x0AC1 + ROM_SLOT[ext]] == 0}), "
            f"kernal calls {calls}, at ${m.cpu.pc:04X} SP ${m.cpu.sp:02X} (want ${ROM_BACK:04X} ${sp + 2:02X})")


OWN_FLOOR = 128                 # bytes zx128 keeps spare in the own area


@zx128check
def zx128_room():
    # zx128 fits (build.py stops if it doesn't), with OWN_FLOOR bytes spare
    # in the own area, and zx128.prg fits the function ROM (packed, from
    # from.asm's STREAM to its unpacker; build.py stops if not). Its room
    # left is shown: own area, core, common RAM, the monitor's three parts,
    # its code in common RAM, its buffers; and the PRG's page cliffs
    # (build.page_room: the bytes before it takes a page more at
    # phi..phi_tail or before prom, which the function ROM may not have
    # room for).
    import build
    lbl = build.labels(os.path.join(ROOT, "build", "obj", "zx128.lbl"))
    mlb = build.labels(os.path.join(ROOT, "build", "obj", "mon128", "zx128mon.lbl"))
    g = dict(own=0xDFFE - lbl["hiend"], core=0x2E00 - lbl["coreend"], com=0xF7FE - lbl["zcomend"],
             mhi=0xFBFE - lbl["monend"], mon1=0x4000 - mlb["part1end"], mon2=0xEFFE - mlb["monend"],
             mon3=0xFFEE - mlb["part3end"], mbuf=0xFDFE - mlb["kprev"] - 8, **build.page_room(sym8502()))
    prg = len(open(PRG, "rb").read())
    fsym = from_sym(os.path.join(ROOT, "build", "obj", "from.sym"))
    rspare = fsym["STREAM"] - fsym["codeend"]     # (the image packed, from STREAM to the unpacker)
    bad = []
    if g["own"] < OWN_FLOOR:
        bad.append(f"{g['own']} bytes spare in the own area (at least {OWN_FLOOR})")
    if rspare < 0:
        bad.append(f"zx128.prg is {prg} bytes: packed, {-rspare} past the function ROM's room")
    check("zx128_room", not bad, "; ".join(bad) if bad else
          f"own area {g['own']}, core {g['core']}, common RAM (the panel) {g['com']}; the monitor: part 1 "
          f"{g['mon1']}, part 2 {g['mon2']}, part 3 {g['mon3']}, its code in common RAM {g['mhi']}, its buffers "
          f"{g['mbuf']}; zx128.prg's pages: {build.page_say(g)}; zx128.prg {prg} bytes, the function ROM {rspare} "
          "spare (packed)")


@selfcheck
def pic_left_down():
    # every pic_ check above ran with watch_left: the budget left never
    # went up within a pic_step (but where a frame starts and where the
    # sweep gets its share back)
    ups = [(n, u[:2]) for n, u in LEFT_SEEN if u]
    check("pic_left_down", LEFT_SEEN and not ups and LEFT_STORES[0] > 0,
          f"{len(LEFT_SEEN)} checks, {LEFT_STORES[0]} stores watched; up in {ups[:3]}")


def main():
    for fn in CHECKS:
        fn()
    print(f"\n{simulate.summary()}")
    sys.exit(1 if simulate.failures else 0)


if __name__ == "__main__":
    main()
