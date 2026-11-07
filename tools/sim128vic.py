#!/usr/bin/env python3
"""Run zx128vic without a C128: its part of make test.

zx128vic (z80/zx128vic.asm, c128/boot128.asm built with VDC=0) is zx64's
picture on the C128's VIC: the ZX81's screen and font in RAM bank 1 at
$C000 and $C800, which the VIC reads by $D506 bit 6 (its RAM bank),
$DD00 (its 16K at $C000) and $D018 (VICE and the real C128 agree). The
machine is tools/sim128.py's C128, with one thing more (C128VIC): the
Z80's colour RAM at $1000-$13FF while $FF00 has the I/O on ($7E), as the
C128 has it; there with $FF00 = $7F a write is the ROM's byte changed,
and is logged (rom_writes).

    python3 tools/sim128vic.py         (make test runs it after sim128.py)

sim128's helpers (load_p, cmd128, to_1k, fkey, frames_until ...) are
used as they are: they read the build's labels through sim128's LBL and
sym8502, pointed here at zx128vic's (build/obj/zx128vic.lbl,
build/obj/zx128vic/boot128.sym). Needs make's build/obj/zx128vic.prg;
each check fails without it.
"""
import os
import re
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import sim128  # noqa: E402  (exits with a hint if the z80 or py65 package is missing)
import build  # noqa: E402
import simulate  # noqa: E402
from sim128 import C128, CR, cmd128, df_codes, fkey, keyset, to_1k, zx_report  # noqa: E402
from simulate import FRAME_T, MPOS, ZX, check  # noqa: E402

ROOT = sim128.ROOT
OBJ = os.path.join(ROOT, "build", "obj")
PRG = os.path.join(OBJ, "zx128vic.prg")
LBL = os.path.join(OBJ, "zx128vic.lbl")
SYM8502 = os.path.join(OBJ, "zx128vic", "boot128.sym")
PDIR = os.path.join(OBJ, "zx128vic")            # its test programs (speed.p, mem.p)
CR_IO = 0x7E                                    # $FF00 with the I/O on: colour RAM at $1000-$13FF
COLRAM = 0x1000
PICTURE = [i for i in range(960) if 4 <= i % 40 < 36]         # the ZX81's 32x24 cells, from column 4 (blit's)
FRAME = [i for i in range(1000) if i >= 960 or not 4 <= i % 40 < 36]   # round them: columns 0-3 and 36-39
                                                # of rows 0-23, all of row 24
FRAME_SET = frozenset(FRAME)
FRAME_ADDRS = frozenset(0xC000 + i for i in FRAME)
SOLID = 0x80                                    # the frame's character: the ZX81 font's inverse space, all set
SPEED_MAX = 32                                  # SPEED's 50 loops, frames at most (zx64 on the C64: 30)


def sym8502():
    """zx128vic's boot128 labels (acme's symbol list), names as written."""
    text = open(SYM8502).read()
    return {mm.group(1): int(mm.group(2), 16) for mm in re.finditer(r"^\s*(\w+)\s*=\s*\$([0-9a-fA-F]+)", text, re.M)}


sim128.PRG, sim128.LBL, sim128.sym8502 = PRG, LBL, sym8502   # sim128's helpers: zx128vic's build


class C128VIC(C128):
    """sim128's C128, and the Z80's colour RAM: a write to $1000-$13FF goes
    to colour RAM while $FF00 (as the Z80 stored it) has the I/O on (bit 0
    clear), else to the RAM there, the ZX81 ROM's: logged in rom_writes
    (pc past the store, address). Colour RAM is two banks of 1K, as the
    C128's: the 8502's I/O port, $01, picks the one the CPUs write (bit 0:
    the 8502's at $D800 and the Z80's, whichever) and the one the VIC shows
    (bit 1), as VICE's x128 has it (with bit 0 clear the Z80's writes go
    where the VIC doesn't show them, unless bit 1 is cleared too). colour
    is the VIC's bank; the C128's kernal leaves $01 = $73. And $D030
    (d030; bit 0: the 8502 at 2 MHz), the function ROM's copier's: its
    writes logged in d030_log (pc, value), the 8502's stores made at 2 MHz
    counted in fast_writes."""

    def __init__(self, **kw):
        super().__init__(**kw)
        self.rom_writes = []
        self.col_writes = 0
        self.z.set_write_callback(self._zwrite)
        self.z.mark_addrs(COLRAM, 0x400, self.z.WRITE_MARK)
        self.top_log = None                     # a list: the 8502's writes to bank 1 $C000-$D7FF, (address, value)
        self.frame_log = None                   # a list: the Z80's writes to the frame's cells (watch_frame), (pc, address, value)
        self.cpu.memory = VicBus8502(self)
        self.d030, self.d030_log, self.fast_writes = 0xFC, [], 0   # (bits 2-7 unused: they read 1)

    @property
    def colour(self):
        return self.colbank[self.port8502[1] >> 1 & 1]

    @colour.setter
    def colour(self, v):                        # (C128's __init__: both banks)
        self.colbank = [bytearray(v), bytearray(v)]

    def cpu_colour(self):
        return self.colbank[self.port8502[1] & 1]

    def io_write(self, port, v, pc):
        if 0xD800 <= port <= 0xDBFF:
            self.cpu_colour()[port & 0x3FF] = v & 0x0F
            return
        if port == 0xD030:
            self.d030 = v | 0xFC
            self.d030_log.append((pc, v))
            return
        super().io_write(port, v, pc)

    def io_read(self, port, pc):
        if 0xD800 <= port <= 0xDBFF:
            return self.cpu_colour()[port & 0x3FF] | 0xF0
        if port == 0xD030:
            return self.d030
        return super().io_read(port, pc)

    def _zwrite(self, a, v):
        if COLRAM <= a < COLRAM + 0x400:
            if not self.bank1[CR] & 1:
                self.cpu_colour()[a & 0x3FF] = v & 0x0F
                self.col_writes += 1
                return
            self.rom_writes.append((self.z.pc, a))
        elif self.frame_log is not None and a in FRAME_ADDRS:
            self.frame_log.append((self.z.pc, a, v))
        self.bank1[a] = v

    def watch_frame(self):
        """The Z80's writes to the frame's cells logged in frame_log from now."""
        for a in sorted(FRAME_ADDRS):
            self.z.mark_addrs(a, 1, self.z.WRITE_MARK)
        self.frame_log = []


class VicBus8502(sim128.Bus8502):
    """sim128's 8502 memory, its writes to bank 1's $C000-$D7FF (the VIC's
    screens and fonts) logged in top_log while it is a list."""

    def __setitem__(self, a, v):
        m = self.m
        m.fast_writes += m.d030 & 1
        if m.top_log is not None and a not in (CR, 0, 1):
            p = m.phys8502(a)
            if p is not None and p[0] and 0xC000 <= p[1] < 0xD800:
                m.top_log.append((p[1], v))
        super().__setitem__(a, v)


def zx128vic(frames=200, ntsc=False, down=False, before=None):
    """A C128 with zx128vic.prg where the boot sector's LOAD puts it (bank
    0, its load address), started at boot128's entry, then frames frames
    (the K cursor comes after ~160). ntsc: the VIC an NTSC one
    (sim128.ntsc_vic) from the start; down: the 40/80 key down (the
    80-column screen in use; up by default here: zx128vic is the 40
    columns'). before: called with the C128 before boot128 starts."""
    m = C128VIC()
    m.key4080_down = down
    prg = open(PRG, "rb").read()
    load = prg[0] | prg[1] << 8
    m.poke(load, prg[2:])
    if ntsc:
        ntsc_vic(m)
    if before:
        before(m)
    m.start_8502(load)
    m.frames(frames)
    return m


def sym():
    return sim128.sym128()


def vic_mem(m):
    """(the bank the VIC reads, its screen's address, its font's), as the
    VIC finds them: $D506 bit 6 the RAM bank; $DD00's bits 0-1 (outputs
    by $DD02, an input reads 1) the 16K, 3 - them; $D018 the screen (bits
    4-7, 1K each) and the font (bits 1-3, 2K each) in it."""
    bank = m.bank1 if m.mmu[6] & 0x40 else m.bank0
    dd = (m.cia2[0] & m.cia2[2] | ~m.cia2[2]) & 3
    base = (3 - dd) * 0x4000
    d018 = m.vic[0x18]
    return bank, base + (d018 >> 4) * 0x400, base + (d018 >> 1 & 7) * 0x800


def glyphs(m):
    """The ROM's 64 glyphs (bank 1 $1E00) as the ZX81's characters, and
    inverted as the inverse ones (lower case): glyph bytes -> character."""
    out = {}
    for z in range(64):
        g = bytes(m.bank1[0x1E00 + 8 * z:0x1E08 + 8 * z])
        out.setdefault(g, ZX[z])
        out.setdefault(bytes(b ^ 0xFF for b in g), ZX[z].lower())
    return out


def vic_text(m, row):
    """The VIC's screen row (0-24) as text, 40 characters: each cell's code
    looked up in the font the VIC reads (vic_mem), its glyph matched with
    the ROM's (glyphs: inverse in lower case); '~' for a glyph that is
    none of them."""
    bank, scr, font = vic_mem(m)
    g = glyphs(m)
    out = []
    for c in range(40):
        code = bank[scr + row * 40 + c]
        out.append(g.get(bytes(bank[font + 8 * code:font + 8 * code + 8]), "~"))
    return "".join(out)


def vic_codes(m):
    """The VIC's screen codes, rows 0-23, columns 4-35: the ZX81's picture
    (24 rows of 32)."""
    bank, scr, _ = vic_mem(m)
    return [list(bank[scr + r * 40 + 4:scr + r * 40 + 36]) for r in range(24)]


def vic_msg_text(m):
    """The top row's message: the VIC's row 0, its columns 4-35 (the
    picture's), as text in upper case, spaces off at both ends, when every
    cell is inverse, as a setting's message is (msgx.inc); else None."""
    bank, scr, _ = vic_mem(m)
    if not all(c & 0x80 for c in bank[scr + 4:scr + 36]):
        return None
    return vic_text(m, 0)[4:36].upper().strip()


def k_cursor(m):
    return m.zx_screen()[23].startswith("k") and m.bank1[0x4027] == 0


def ovl_gone(m, frames=300):
    """Until no setting's message is over the top row (ovl 0)."""
    a = sym()["ovl"]
    m.until(lambda: m.bank1[a] == 0, frames, "the top row's message gone")


# ---- the checks
CHECKS = []


def viccheck(fn):
    """A check that needs zx128vic's build: FAIL, not a crash, without it."""
    def run():
        try:
            fn()
        except (AssertionError, OSError, SystemExit, KeyError, AttributeError, ImportError) as e:
            check(fn.__name__, False, str(e).splitlines()[0] if str(e) else type(e).__name__)
    run.__name__ = fn.__name__
    CHECKS.append(run)
    return run


@viccheck
def vic_boot_k():
    # boot128's VDC=0 path, then the ROM's start: the VIC on bank 1's
    # $C000 (screen) and $C800 (font), and the K cursor there, row 23,
    # column 4 (the 32 columns from column 4, as zx64's); the font as
    # zx64's boot makes it; the frame round the picture (frame_look)
    # in scheme 0; nothing written into the ROM
    check("vic_boot_k", *boot_state(zx128vic()))


def boot_state(m):
    """vic_boot_k's state: (it holds, what m shows)."""
    row = vic_text(m, 23)
    bank, scr, font = vic_mem(m)
    rom = bytes(m.bank1[0x1E00:0x2000])
    inv = bytes(b ^ 0xFF for b in rom)
    want = rom + bytes(0x200) + inv + b"\xff" * 0x200
    ok = (row[4] == "k" and row[:4] == "    " and m.mmu[6] & 0x40 and (m.cia2[0] & 3, m.cia2[2] & 3) == (0, 3)
          and m.vic[0x18] == 0x02 and m.vic[0x11] == 0x17 and bank is m.bank1 and (scr, font) == (0xC000, 0xC800)
          and bytes(m.bank1[0xC800:0xD000]) == want and not m.map_errors and not m.rom_writes and not m.stray_io
          and m.port8502[1] & 3 == 3 and frame_look(m, 0)[0])
    return bool(ok), (f"{frame_look(m, 0)[1]}; row 23 {row[:12]!r}; $D506 ${m.mmu[6]:02X} $DD00 ${m.cia2[0]:02X}/$DD02 "
                      f"${m.cia2[2]:02X} $D018 ${m.vic[0x18]:02X} $D011 ${m.vic[0x11]:02X}; screen ${scr:04X} font "
                      f"${font:04X} (zx64's {bytes(m.bank1[0xC800:0xD000]) == want}); map {m.map_errors[:2]} rom "
                      f"{m.rom_writes[:2]} stray {m.stray_io[:2]}; $01 ${m.port8502[1]:02X} (colour RAM's banks: the "
                      f"CPUs' {m.port8502[1] & 1}, the VIC's {m.port8502[1] >> 1 & 1}: one)")


@viccheck
def vic_setcol():
    # setcol (vicpic.inc's, F2's) with scheme 2, from the editor's state
    # (interrupts on) and from the IRQ's (off): colour RAM's picture cells
    # 13, the frame's round them 0 (the border's), through
    # hwvic128.inc's window (col_ptr to col_end: $FF00 $7E, from
    # common RAM), $D021 and $D020 0; $FF00 back to $7F, the ROM not
    # written, the interrupts as they were
    m = zx128vic()
    s = sym()
    got = []
    for iff in (True, False):
        m.colour[:] = bytes(1024)
        m.bank1[s["scheme"]] = 2
        z = m.z
        pc, sp, i1, i2 = z.pc, z.sp, z.iff1, z.iff2
        z.sp = 0x7EFE
        z.memory[0x7EFE], z.memory[0x7EFF] = 0x00, 0x7E          # its return: to $7E00
        z.pc, z.iff1, z.iff2 = s["setcol"], iff, iff
        enable, m.enable = m.enable, 0                            # (no IRQ meanwhile: the check is the state)
        end = m.nframes + 20
        while z.pc != 0x7E00 and m.nframes < end:
            m.step(1)
        got.append((z.pc == 0x7E00, zx_cram(m), m.vic[0x21], m.vic[0x20], m.bank1[CR], z.iff1 == iff))
        m.enable = enable
        z.pc, z.sp, z.iff1, z.iff2 = pc, sp, i1, i2
    ok = all(g == (True, ([13], [0]), 0, 0, 0x7F, True) for g in got) and not m.rom_writes and not m.map_errors
    check("vic_setcol", ok, f"{got}; colour writes {m.col_writes}; rom {m.rom_writes[:2]} map {m.map_errors[:2]}")


@viccheck
def vic_print():
    # PRINT "ZX128VIC": in D_FILE, then on the VIC's row 0 within 2 frames
    # (zx64's blit every other frame); the report's row too, 2 frames after
    m = zx128vic()
    ovl_gone(m)
    m.type("P SHIFT+P Z X 1 2 8 V I C SHIFT+P NEWLINE")
    m.until(lambda: m.zx_screen()[0] == "ZX128VIC", 100, "ZX128VIC in D_FILE")
    n = sim128.frames_until(m, lambda: vic_text(m, 0)[4:12] == "ZX128VIC", 10, "ZX128VIC on the VIC")
    m.until(lambda: zx_report(m) == "0/0", 100, "the report")
    m.frames(2)                                         # (the report too, by the next blit)
    rows = vic_codes(m)
    same = rows == df_codes(m)
    check("vic_print", n <= 2 and same, f"{n} frame(s); the VIC's picture as D_FILE {same}; {vic_text(m, 0)!r}")


@viccheck
def vic_1k():
    # F8 twice: 32K, then 1K, where the ROM keeps the display collapsed;
    # each row on the VIC padded with spaces as zx64's blit_c pads it
    m = zx128vic()
    to_1k(m)
    ovl_gone(m)
    m.type("P SHIFT+P X SHIFT+P NEWLINE")
    m.until(lambda: m.zx_screen()[0] == "X", 100, "X in D_FILE")
    m.frames(3)
    collapsed = m.peek16(0x4010) - m.peek16(0x400C) != 24 * 33 + 1
    rows = vic_codes(m)
    same = rows == df_codes(m)
    check("vic_1k", collapsed and same and rows[0][:2] == [0x3D, 0] and vic_text(m, 0)[3:6] == " X ",
          f"collapsed {collapsed}, the VIC's picture as D_FILE padded {same}, row 0 {vic_text(m, 0)!r}")


def mem_lines(scr):
    """MEM's report (progs/mem.bas) in screen rows: (RAM's line, FREE's, the
    range's, OK's)."""
    pick = lambda p: next((x for x in scr if x.lstrip().startswith(p)), None)
    return pick("RAM "), pick("FREE "), next((x for x in scr if " TO " in x), None), pick("MEMORY OK")


def zx64_mem32(size):
    """MEM in 32K on zx64 (simulate.py's model of the C64 and the
    cartridge, build/obj's zx64 and mem.p): its report's lines, mem_lines',
    as zx128vic's mem.p of size bytes would give them (its title names the
    build: the free bytes fewer, the first free byte later, by the
    difference)."""
    z = simulate.Machine(int_wired=True)
    z.boot()
    z.tap("F8")
    z.until(lambda: z.cursor() and z.ready(), 600, "zx64's K cursor after F8")
    z.drive.files[b"MEM"] = open(os.path.join(OBJ, "mem.p"), "rb").read()
    d = size - len(z.drive.files[b"MEM"])
    simulate.enter(z, "J SHIFT+P M E M SHIFT+P")
    out = []
    for line in mem_lines(z.screen()):
        f = re.fullmatch(r"FREE( +)(\d+) BYTES", line or "")
        t = re.fullmatch(r"( +)(\d+) TO (\d+)", line or "")
        if f:
            line = f"FREE{f.group(1)}{int(f.group(2)) - d} BYTES"
        elif t:
            line = f"{t.group(1)}{int(t.group(2)) + d} TO {t.group(3)}"
        out.append(line)
    return tuple(out)


def unblit(m):
    """Bank 1's $C000-$D7FF but the cells blit writes (the picture: rows
    0-23, columns 4-35 of $C000): the screen's other cells, the monitor's
    screen, both fonts."""
    pic = {0xC000 + r * 40 + c for r in range(24) for c in range(4, 36)}
    return bytes(m.bank1[a] for a in range(0xC000, 0xD800) if a not in pic)


@viccheck
def vic_32k():
    # F8: 32K, RAMTOP $C000 (bank 1's RAM goes on past $BFFF: the VIC's);
    # NEW's RAM test and MEM's (every free byte, twice) stop below $C000:
    # every byte of $C000-$D7FF that blit doesn't write (the screen's
    # columns 0-3 and 36-39 and the rest past row 23, the frame's solid
    # character, the monitor's screen, both fonts) as the boot left it, the
    # picture as D_FILE; MEM's report
    # as zx64's in 32K (simulate.py's model): the same free RAM, to the byte
    m = zx128vic()
    keep = unblit(m)
    frame = sorted({m.bank1[a] for a in FRAME_ADDRS})
    m.keys = keyset(["LSHIFT", "F7"])
    m.frames(3)
    m.keys = set()
    m.until(lambda: m.peek16(0x4004) == 0xC000, 300, "RAMTOP $C000")
    m.until(lambda: k_cursor(m), 600, "the K cursor in 32K")
    m.type("A NEWLINE")                                     # NEW
    m.frames(100)
    m.until(lambda: k_cursor(m), 600, "the K cursor after NEW")
    top = m.peek16(0x4004)
    kept_new = unblit(m) == keep
    m.drive.files[b"MEM"] = open(os.path.join(PDIR, "mem.p"), "rb").read()
    r = cmd128(m, "J SHIFT+P M E M SHIFT+P", 3000)
    got = mem_lines(m.zx_screen())
    want = zx64_mem32(len(m.drive.files[b"MEM"]))
    m.frames(3)
    kept = unblit(m) == keep
    same = vic_codes(m) == df_codes(m)
    check("vic_32k", top == 0xC000 and got == want and None not in got and got[0].endswith("32K") and kept_new
          and kept and same and r.startswith("0/") and not m.rom_writes and frame == [SOLID],
          f"RAMTOP after NEW ${top:04X}; MEM {got} {r}, zx64's {want}; the frame at boot {frame}; $C000-$D7FF but "
          f"the picture kept after "
          f"NEW {kept_new}, after MEM {kept}; the picture as D_FILE {same}")


@viccheck
def vic_speed():
    # LOAD "SPEED": 50 loops in SPEED_MAX frames at most (zx64 on the C64:
    # 30; zx128 on the VDC: 37). zx128vic's own title, the VIC's
    # PAL (the model's) as the Z80 measured it at the start, no /INT line
    m = zx128vic()
    m.drive.files[b"SPEED"] = open(os.path.join(PDIR, "speed.p"), "rb").read()
    r = cmd128(m, "J SHIFT+P S P E E D SHIFT+P", 1500)
    scr = m.zx_screen()
    frames = next((int(x.split()[0]) for x in scr if x.endswith(" FRAMES")), None)
    title = "ZX128VIC SPEED TEST"
    check("vic_speed", scr[0] == title and r.startswith("0/") and frames is not None
          and frames <= SPEED_MAX and vic_text(m, 0)[4:4 + len(title)] == title
          and sim128.speed_video(scr) == "PAL",
          f"{frames} frames for 50 loops (at most {SPEED_MAX}), {r}; VIC row 0 {vic_text(m, 0)[4:24]!r}; video "
          f"{sim128.speed_video(scr)!r}")


@viccheck
def vic_speed_ntsc():
    # SPEED on an NTSC VIC (263 lines, ntsc_vic): "VIC VIDEO:   NTSC"
    m = zx128vic(ntsc=True)
    m.drive.files[b"SPEED"] = open(os.path.join(PDIR, "speed.p"), "rb").read()
    r = cmd128(m, "J SHIFT+P S P E E D SHIFT+P", 1500)
    scr = m.zx_screen()
    check("vic_speed_ntsc", r.startswith("0/") and sim128.speed_video(scr) == "NTSC",
          f"{r}; video {sim128.speed_video(scr)!r}; {scr[:4]}")


@viccheck
def vic_vdc_note():
    # the 40/80 key down (the 80-column screen in use): boot128
    # says on the VDC's screen to use the 40 columns, as zx128 says the
    # other way on the VIC's (sim128's boot_4080_up): its first row, the
    # rest of the screen blank, its attributes left as the kernal had them
    # (a pattern put there first), the kernal's cursor off (R10's blink
    # bits 01, from the kernal's $60); zx128vic runs on the VIC all the
    # same. Up: the VDC not touched
    def kernal(m):
        m.vram[0x800:0x1000] = bytes((i * 7 + 3) & 0xFF for i in range(0x800))
        m.vdc[10] = 0x60
    seeded = bytes((i * 7 + 3) & 0xFF for i in range(0x800))
    m = zx128vic(down=True, before=kernal)
    scr = bytes(m.vram[0:2000])
    row = "".join(chr(c + 64) if 1 <= c <= 26 else chr(c) for c in scr[:80]).rstrip()
    rest = set(scr[len(row):])
    attrs = bytes(m.vram[0x800:0x1000]) == seeded
    cursor = m.vdc[10] & 0x60 == 0x20
    up = zx128vic(before=kernal)
    upok = not any(up.vram[:0x800]) and bytes(up.vram[0x800:0x1000]) == seeded and up.vdc[10] == 0x60
    check("vic_vdc_note", row == "ZX128VIC: THE 40-COLUMN SCREEN, PLEASE" and rest == {0x20} and attrs and cursor
          and boot_state(m)[0] and upok,
          f"row 0 {row!r}, the rest {sorted(rest)[:4]}, attributes as the kernal's {attrs}, R10 ${m.vdc[10]:02X} "
          f"(cursor off {cursor}); on the VIC as ever {boot_state(m)[0]}; up: VDC untouched {upok}")


SCHEMES_VIC = [(0, 1, 1), (1, 0, 0), (13, 0, 0), (8, 0, 0), (0, 13, 13), (14, 6, 14)]   # zx64's: characters,
                                                # background, border (C64 colours)
OVL_FRAMES = 100                                # a setting's message: 2 s (ovl)


def msg_names():
    """zx64's F2 names, msg_col0-5 (tools/build.py's MESSAGES)."""
    import build
    return [t for lb, t, k in build.MESSAGES if lb.startswith("msg_col")]


@viccheck
def vic_msg():
    # the greeting at the first key wait: " ZX128VIC 1.2" (the
    # C128 builds' version, build.py's VERSION) on the top row; gone after its 2 s, row 0 the picture's again. F1 (the
    # type-ahead off): zx128's text, "TYPE-AHEAD OFF" (TEXT128: no ", AS A
    # ZX81"), F1 at its end, on the top row for 2 s (OVL_FRAMES), then
    # the picture's row 0 back
    m = zx128vic(frames=1)
    m.until(lambda: k_cursor(m), 400, "the K cursor")
    sim128.frames_until(m, lambda: vic_msg_text(m) is not None, 10, "the greeting")
    hello = vic_msg_text(m)
    ovl_gone(m)
    m.frames(3)
    back0 = vic_codes(m)[0] == df_codes(m)[0]
    fkey(m, "F1")
    t0 = m.nframes - 8                                  # (fkey's 5 frames held, 3 up: F1 acts as it goes down)
    f1 = vic_msg_text(m)
    while vic_msg_text(m) is not None and m.nframes - t0 < 300:
        m.frames(1)                                     # (each frame's end: the IRQ, blit, not begun)
    gone = m.nframes - t0
    m.frames(3)
    back1 = vic_codes(m)[0] == df_codes(m)[0]
    kboff = m.bank1[sym()["kbuf"]] == 0
    check("vic_msg", hello == f"ZX128VIC {build.VERSION}" and back0 and f1 is not None and f1.startswith("TYPE-AHEAD OFF ")
          and f1.endswith(" F1") and "ZX81" not in f1 and abs(gone - OVL_FRAMES) <= 10 and back1 and kboff,
          f"at the K cursor {hello!r}, then row 0 the picture's {back0}; F1: {f1!r}, gone "
          f"{gone} frames after (about {OVL_FRAMES}), row 0 the picture's again {back1}; type-ahead off {kboff}")


def scheme_state(m):
    """(scheme, the VIC's colour RAM's colours (zx_cram: the picture's, the
    frame's), $D021, $D020)."""
    return m.bank1[sym()["scheme"]], zx_cram(m), m.vic[0x21] & 15, m.vic[0x20] & 15


@viccheck
def vic_f2():
    # F2 (SHIFT+F1) six times round: each time the next of zx64's schemes,
    # colour RAM (the bank the VIC shows) its characters' colour in the
    # picture's cells, its border's in the frame's, $D021
    # and $D020 its background and border, its name (zx64's) on the top
    # row; back to black on white. Then F2 once more, F7 and F8: the ZX81
    # starts again in that scheme each time
    m = zx128vic()
    names = msg_names()
    got, ok = [], True
    for i in range(6):
        fkey(m, "LSHIFT", "F1")
        s, cols, back, border = scheme_state(m)
        want = SCHEMES_VIC[(i + 1) % 6]
        msg = vic_msg_text(m) or ""
        good = s == (i + 1) % 6 and cols == ([want[0]], [want[2]]) and (back, border) == want[1:] \
            and msg.startswith(names[s])
        got.append(f"{s}: {cols} ${back:X} ${border:X} {msg[:16]!r}{'' if good else ' (WRONG)'}")
        ok = ok and good
    fkey(m, "LSHIFT", "F1")
    ovl_gone(m)
    fkey(m, "F7", frames=3)
    m.until(lambda: not sim128.zx_editor(m), 100, "the ZX81 starting again")
    m.until(lambda: k_cursor(m) and sim128.zx_editor(m), 600, "the K cursor after F7")
    f7 = scheme_state(m)
    fkey(m, "LSHIFT", "F7", frames=3)
    m.until(lambda: m.peek16(0x4004) == 0xC000, 300, "RAMTOP $C000 after F8")
    m.until(lambda: k_cursor(m) and sim128.zx_editor(m), 600, "the K cursor after F8")
    f8 = scheme_state(m)
    kept = f7 == f8 == (1, ([1], [0]), 0, 0)
    check("vic_f2", ok and kept and not m.rom_writes and m.bank1[CR] == 0x7F,
          f"{'; '.join(got)}; F7 in scheme 1: {f7}, F8: {f8}; rom {m.rom_writes[:2]}")


@viccheck
def vic_f2_irq():
    # setcol with the interrupts on (F2's from the editor,
    # the monitor's colours) and the raster IRQ due just after its first
    # colour RAM write: no IRQ taken while $FF00 = $7E (colour RAM over the
    # ROM's $1000-$13FF), the IRQ taken once it is $7F again, colour RAM
    # the scheme's (the picture's cells and the frame's). And F2 while a program runs (setcol inside the
    # IRQ, scan's): no frame's IRQ lost over it (setcol under a frame)
    s = sym()
    m = zx128vic()
    log = []
    m.on_irq = lambda m: log.append((m.bank1[CR], m.z.pc))
    m.colour[:] = bytes(1024)
    m.bank1[s["scheme"]] = 3
    z = m.z
    pc, sp, i1, i2 = z.pc, z.sp, z.iff1, z.iff2
    z.sp = 0x7EFE
    z.memory[0x7EFE], z.memory[0x7EFF] = 0x00, 0x7E          # its return: to $7E00
    z.pc, z.iff1, z.iff2 = s["setcol"], True, True
    end, due = m.nframes + 20, None
    while z.pc != 0x7E00 and m.nframes < end:
        if due is None and m.col_writes:
            m.latch |= 1                                      # the IRQ due, mid-write
            due = (m.t, m.bank1[CR])
        m.step(1)
    done = z.pc == 0x7E00
    mid = list(log)
    z.pc, z.sp, z.iff1, z.iff2 = pc, sp, i1, i2
    ok_mid = done and due is not None and due[1] == 0x7E and mid and all(cr == 0x7F for cr, _ in mid) \
        and zx_cram(m) == ([8], [0]) and m.bank1[CR] == 0x7F and not m.rom_writes
    m.on_irq = None
    sim128.load_p(m, sim128.p_prog("10 GOTO 10"))
    m.frames(20)
    f0, n0 = m.nframes, m.irqs
    fkey(m, "LSHIFT", "F1")
    m.frames(20)
    lost = (m.nframes - f0) - (m.irqs - n0)
    check("vic_f2_irq", ok_mid and lost <= 0 and m.bank1[CR] == 0x7F,
          f"from the editor: done {done}, the IRQ due at $FF00 ${due[1] if due else 0:02X}, taken {len(mid)} "
          f"time(s), $FF00 then {[f'${cr:02X}' for cr, _ in mid]}; colour RAM {zx_cram(m)}; "
          f"F2 in a program: {lost} frame IRQ(s) lost")


def zx_cram(m):
    """The colour RAM the VIC shows, as the ZX81's screen has it: (its
    picture's 32x24 cells' colours, the frame's round them), each sorted."""
    c = m.colour
    return sorted({c[i] for i in PICTURE}), sorted({c[i] for i in FRAME})


def frame_look(m, scheme):
    """(it holds, what m shows): the ZX81's screen with the frame in
    scheme: the frame's cells the solid character (its glyph all set in the
    font the VIC reads) in the border's colour, the picture's cells the
    characters' colour, $D021 and $D020 the scheme's."""
    text, back, border = SCHEMES_VIC[scheme]
    bank, scr, font = vic_mem(m)
    codes = sorted({bank[scr + i] for i in FRAME})
    solid = bytes(bank[font + 8 * SOLID:font + 8 * SOLID + 8]) == b"\xff" * 8
    pic, frm = zx_cram(m)
    regs = m.vic[0x21] & 15, m.vic[0x20] & 15
    ok = scr == 0xC000 and codes == [SOLID] and solid and pic == [text] and frm == [border] and regs == (back, border)
    return ok, (f"frame {[f'${c:02X}' for c in codes]}{'' if solid else ' (not solid)'}, colours: picture {pic} "
                f"frame {frm}, $D021/$D020 {regs}{'' if ok else f' (WRONG: scheme {scheme} {SCHEMES_VIC[scheme]})'}")


@viccheck
def vic_frame():
    # the ZX81's screen round its 32x24 picture (columns 0-3 and
    # 36-39 of rows 0-23, all of row 24): the font's inverse space ($80,
    # solid) in the border's colour, so only the picture shows the
    # background, and the picture's cells the characters' colour: at boot
    # (scheme 0), after F2 through all six schemes (each its message on
    # the top row meanwhile), after F5 then X (the monitor's own colours
    # over all of colour RAM while it is up), after F7 with a program's
    # POKEs over the frame (made again, as at boot). The Z80 never writes
    # the frame (blit, blit_c, the top row's messages); the 8502 only as
    # F7 makes the screen again, the solid character
    m = zx128vic()
    m.until(lambda: k_cursor(m), 400, "the K cursor")
    m.watch_frame()
    got, ok = [], True

    def look(what, scheme):
        nonlocal ok
        good, txt = frame_look(m, scheme)
        ok = ok and good
        got.append(f"{what}: {txt}")

    look("boot", 0)
    for i in range(6):
        fkey(m, "LSHIFT", "F1")
        look(f"F2 {(i + 1) % 6}", (i + 1) % 6)
    ovl_gone(m)
    fkey(m, "F5")
    m.until(lambda: m.bank1[sym()["mon_up"]] and m.vic[0x18] == 0x14, 300, "the monitor")
    m.frames(10)
    mon = sorted(set(m.colour[:1000])), m.vic[0x21] & 15, m.vic[0x20] & 15
    sim128.mon_type(m, "X\r", settle=0)
    m.until(lambda: not m.bank1[sym()["mon_up"]] and m.vic[0x18] == 0x02, 300, "the ZX81's screen after X")
    m.frames(4)
    look("F5, X", 0)
    for r in (0, 12, 23, 24):
        m.bank1[0xC000 + 40 * r:0xC000 + 40 * r + 4] = b"\x55\x66\x77\x88"
        m.bank1[0xC000 + 40 * r + 36:0xC000 + 40 * r + 40] = b"\x55\x66\x77\x88"
    m.top_log = []
    sim128.f7_k(m)
    m.frames(3)
    look("F7", 0)
    by8502 = sorted({v for a, v in m.top_log if a in FRAME_ADDRS})
    m.top_log = None
    k = vic_text(m, 23)[4] == "k"
    z80 = m.frame_log
    check("vic_frame", ok and mon == ([MON_LOOK[3]], MON_LOOK[2], MON_LOOK[4]) and not z80 and by8502 == [SOLID] and k
          and not m.rom_writes,
          f"{'; '.join(got)}; the monitor's colours {mon}; the Z80's writes to the frame {len(z80)} {z80[:3]}, the "
          f"8502's on F7 {[f'${v:02X}' for v in by8502]}; the K cursor at row 23, column 4 {k}")


@viccheck
def vic_keys():
    # the C128's cursor keys as zx128's k2scan has them (LEFT as SHIFT 5,
    # RIGHT as SHIFT 8, UP as SHIFT 7, DOWN as SHIFT 6); the joystick in
    # port 2 as zx64's (5678+0: right is 8, fire 0, in the IN mirror's $EF
    # row); BoulderL's $DF row patched at LOAD (build.py's patches_load128):
    # with P held its menu's, game's and REDEFINE KEYS' reads see P
    import build
    e_line = sim128.e_line
    m = zx128vic()
    m.type("P 1 2")
    end = e_line(m)
    m.type("LEFT")
    left = e_line(m)
    m.type("RIGHT")
    right = e_line(m)
    m.type("SHIFT+8 SHIFT+0 SHIFT+0 SHIFT+0 SHIFT+0")
    m.type("1 0 P NEWLINE 2 0 P NEWLINE")
    ppc = [m.peek16(0x400A)]
    for k in ("UP", "DOWN"):
        m.type(k)
        ppc.append(m.peek16(0x400A))
    arrows = left != end and right == end and ppc == [20, 10, 20]
    m.joy = {"right", "fire"}
    m.frames(8)
    stick = m.bank1[0xEFFE]
    m.joy = set()
    m.frames(8)
    stick_up = m.bank1[0xEFFE]
    boulder = simulate.game("BoulderL.p", "vic_keys")
    if boulder is None:
        return
    tab = dict((w.split(":")[0], e) for w, e in build.patches_load128(sym()))
    m = zx128vic()
    m.drive.files[b"BL"] = boulder
    sim128.load128(m, "BL")
    m.frames(20)
    placed = all(bytes(m.bank1[a:a + len(n)]) == bytes(n) for a, o, n in tab["BoulderL"])
    sim128.keyrow_df(m)
    menu = sim128.z80_run(m, 0x75A7, 0x75AB)[0]
    game = sim128.z80_run(m, 0x6085, 0x608D)[0]
    redef = sim128.z80_run(m, 0x7A83, 0x7A93)
    m.keys = set()
    m.joy = {"right", "fire"}
    m.frames(8)
    two = (sim128.z80_run(m, 0x64C0, 0x64C8)[0], sim128.z80_run(m, 0x6513, 0x651B)[0])
    m.joy = set()
    check("vic_keys", arrows and stick & 0x05 == 0 and stick_up & 0x1F == 0x1F and placed and not menu & 1
          and not game & 1 and redef == (0x01, 0xDF) and two == (0, 0),
          f"edit line {end.hex()} LEFT {left.hex()} RIGHT {right.hex()}, E_PPC {ppc}; the stick right and fire: "
          f"$EFFE ${stick:02X} (up ${stick_up:02X}); BoulderL patched {placed}, P held: menu ${menu:02X}, game "
          f"${game:02X}, REDEFINE KEYS {redef}; its 8 and 0 by the stick ${two[0]:02X} ${two[1]:02X}")


@viccheck
def vic_lastk_race():
    # LAST_K from the type-ahead (rompatch.inc's kb_key) until the
    # ROM has read it: an IRQ after any instruction in between (its scan,
    # no key down) must leave the key, or DECODE loops for ever on $FFFF
    # (zx128vic.asm's kb_lkhold, as zx128's: simulate.py's lastk_sweep)
    m = zx128vic()
    m.type("1 E")                                   # 1 REM
    store = simulate.lk_store(m.bank1, sym()["kb_key"])
    n, bad = simulate.lastk_sweep(m, lambda: m.step(1), m.bank1, store, sym()["d1active"],
                                  lambda: sim128.e_line(m), m.until)
    check("vic_lastk_race", n > 0 and not bad, f"an IRQ after each of {n} instructions from kb_key's store to "
          f"the ROM's read: {bad or 'each key in the edit line'}")


@viccheck
def vic_lastk_bursts():
    # typed in bursts of two keys (simulate.py's lastk_bursts): the
    # second is handed from the queue wherever the raster is; LAST_K as
    # the ROM reads it is each key handed
    m = zx128vic()
    m.type("1 E")
    store = simulate.lk_store(m.bank1, sym()["kb_key"])
    handed, inwin, wrong = simulate.lastk_bursts(m, lambda: m.step(1), m.bank1, store, lambda: m.nframes, 60, 1)
    check("vic_lastk_bursts", handed and not wrong, f"{handed} keys handed, {inwin} with an IRQ before the ROM's "
          "read; " + (f"burst {wrong[0]} {wrong[1]}: ${wrong[2]:04X} handed, ${wrong[3]:04X} read" if wrong
                      else "none lost"))


def fonts(m):
    return bytes(m.bank1[0xC800:0xD800])


@viccheck
def vic_f7_fonts():
    # a program's POKEs (or OUTs) over the VIC's fonts and
    # the screen's cells blit never writes: F7 makes both fonts again (the
    # ZX81's as boot128 makes it, the monitor's from the character ROM),
    # those cells as at boot, without the disk; the K cursor. Then the ROM
    # and the boot file's copy of it in bank 0 written over (a glyph of
    # the ROM's font): F7 reads ZX128VIC from the disk (" LOADING
    # ZX128VIC" on the top row) and the ZX81's font is made from the ROM
    # put back. Once more with no ZX128VIC on the disk: why, on the top row
    # as zx64's says it
    b8 = sim128.sym8502()
    m = zx128vic()
    want, keep = fonts(m), unblit(m)
    rnd = __import__("random").Random(3)
    m.bank1[0xC800:0xD800] = bytes(rnd.randrange(256) for _ in range(0x1000))
    for r in range(25):
        m.bank1[0xC000 + 40 * r:0xC000 + 40 * r + 4] = b"\x55\x66\x77\x88"
    hurt = fonts(m) != want
    opens = m.drive.opens
    sim128.f7_k(m)
    m.frames(3)
    same, cells = fonts(m) == want, unblit(m)[:0x400 - 768] == keep[:0x400 - 768]
    k = vic_text(m, 23)[4] == "k"
    prom = b8["prom"]
    m.bank0[prom + 0x1E10] ^= 0x55
    m.bank1[0x1E10:0x1E11] = bytes([m.bank1[0x1E10] ^ 0x55])
    m.drive.files[b"ZX128VIC"] = open(PRG, "rb").read()
    m.top_log = []
    sim128.f7_k(m)
    m.frames(3)
    words = row_written(m.top_log)[:17]
    disk = fonts(m) == want and m.drive.opens == opens + 1
    m.bank0[prom + 0x1E10] ^= 0x55                      # (both again, and no ZX128VIC on the disk: why, zx64's
    m.bank1[0x1E10:0x1E11] = bytes([m.bank1[0x1E10] ^ 0x55])   # way, on the top row)
    del m.drive.files[b"ZX128VIC"]
    fkey(m, "F7")
    sim128.frames_until(m, lambda: vic_msg_text(m) is not None and "ROM" in vic_msg_text(m), 300,
                        "why the ROM wasn't reloaded")
    why = vic_msg_text(m)
    check("vic_f7_fonts", hurt and same and cells and k and words == " loading zx128vic" and disk
          and why == "ROM NOT RELOADED: NO ZX128VIC",
          f"fonts made again {same}, the screen's other cells as at boot {cells}, the K cursor {k}, opens "
          f"{m.drive.opens - opens}; the ROM's glyph and its copy hurt: the top row {words!r}, the font from the "
          f"ROM put back {disk}; no ZX128VIC: {why!r}")


def row_written(log):
    """The top row as the 8502 wrote it whole (wrow: columns 0-31, $C004-
    $C023, one after the other, not as part of a page: vfonts'), as text
    (inverse in lower case, '?' for a code that isn't), or ''."""
    for i in range(len(log) - 31):
        if [a for a, v in log[i:i + 32]] == list(range(0xC004, 0xC024)) and (i == 0 or log[i - 1][0] != 0xC003):
            return "".join(sim128.ZX[v & 0x3F].lower() if v & 0x80 else "?" for a, v in log[i:i + 32])
    return ""


def bar_cells(log):
    """The 8502's writes to the top row's bar (columns 22-29, $C01A-$C021):
    [(cell, code)] in order."""
    return [(a - 0xC01A, v) for a, v in log if 0xC01A <= a < 0xC022]


@viccheck
def vic_load_bar():
    # LOAD "MAZOGS": the 8502 writes the VIC's top row as zx64's lstat and
    # pstep have it: " LOADING MAZOGS" inverse from column 0, the bar's 8
    # cells (columns 22-29) inverse until data has come, then empty (white:
    # 0), then filled a half (5) and then whole ($80) in order, 16 steps;
    # nothing else of $C000-$D7FF; then the game's picture: the VIC as
    # D_FILE. LOAD "NOPE", not there: report D, " LOADING NOPE" and no bar
    # meanwhile, then the drive's status on the top row as a message
    # (its words from column 0: a real drive's begin with a space, the
    # model's don't; its numbers from 16) for 2 s. A setting's message
    # (F2's) still up as LOAD begins doesn't come back over the loaded
    # program (dbeg clears ovl, as zx64's lstat does). SAVE "A": " SAVING
    # A", the bar as LOAD's
    game = simulate.game("mazogs.p", "vic_load_bar")
    if game is None:
        return
    m = zx128vic()
    m.drive.files[b"MAZOGS"] = game
    ovl_gone(m)
    m.top_log = []
    sim128.load128(m, "MAZOGS")
    m.until(lambda: m.peek16(0x4014) == game[11] | game[12] << 8, 200, "the program in")
    log, m.top_log = m.top_log, None
    words = row_written(log)
    cells = bar_cells(log)
    i0 = next((i for i, (c, v) in enumerate(cells) if v == 0), None)
    empty = i0 is not None and cells[i0:i0 + 8] == [(c, 0) for c in range(8)]
    after = cells[i0 + 8:] if empty else []
    want_fill = [(k >> 1, 0x80 if k & 1 else 0x05) for k in range(16)]
    inside = all(0xC004 <= a < 0xC024 for a, v in log)
    m.frames(10)
    pic = sim128.frames_until(m, lambda: vic_codes(m) == df_codes(m), 100, "the VIC as D_FILE")
    m = zx128vic()
    ovl_gone(m)
    m.top_log = []
    r = cmd128(m, "J SHIFT+P N O P E SHIFT+P")
    nope, nobar = row_written(m.top_log), not any(v == 0 for c, v in bar_cells(m.top_log))
    m.top_log = None
    status = vic_msg_text(m)
    t0 = m.nframes
    while vic_msg_text(m) is not None and m.nframes - t0 < 300:
        m.frames(1)
    shown = m.nframes - t0
    missing = (r.startswith("D/") and nope == " loading nope".ljust(32) and nobar
               and status == "FILE NOT FOUND  62,00,00"           # (the model's drive: no space after "62,")
               and abs(shown - OVL_FRAMES) <= 10)
    m = zx128vic()
    m.drive.files[b"MAZOGS"] = game
    ovl_gone(m)
    m.type("J SHIFT+P M A Z O G S SHIFT+P")
    fkey(m, "LSHIFT", "F1")
    name = msg_names()[m.bank1[sym()["scheme"]]]
    up = (vic_msg_text(m) or "").startswith(name) and m.bank1[sym()["ovl"]] > 0
    opens = m.drive.opens
    m.keys = keyset(["NEWLINE"])
    m.until(lambda: m.drive.opens > opens, 100, 'LOAD "MAZOGS"')
    m.keys = set()
    m.until(lambda: m.peek16(0x4014) == game[11] | game[12] << 8, 200, "the program in")
    back = []
    for _ in range(120):
        m.frames(1)
        if (vic_msg_text(m) or "").startswith(name):
            back.append(m.nframes)
    m = zx128vic()
    ovl_gone(m)
    m.top_log = []
    rs = cmd128(m, "S SHIFT+P A SHIFT+P")
    slog, m.top_log = m.top_log, None
    swords, scells = row_written(slog), bar_cells(slog)
    s0 = next((i for i, (c, v) in enumerate(scells) if v == 0), None)
    sbar = s0 is not None and scells[s0:s0 + 8] == [(c, 0) for c in range(8)] and scells[s0 + 8:] == want_fill
    saved = rs == "0/0" and swords == " saving  a".ljust(32) and sbar and b"A" in m.drive.files
    check("vic_load_bar", missing and up and not back and saved and words == " loading mazogs".ljust(32)
          and empty and after == want_fill and inside and pic <= 4,
          f"row 0 {words!r}; the bar: empty {empty}, then {after[:4]}... ({len(after)} steps, "
          f"{'as' if after == want_fill else 'NOT as'} zx64's); only the top row {inside}; the picture as D_FILE "
          f"{pic} frame(s) after; NOPE: {r}, row 0 {nope.rstrip()!r}, no bar {nobar}, then {status!r} for about "
          f"{shown} frames; F2's message up as LOAD began {up}, back over the program {back[:3]}; SAVE: {rs}, "
          f"row 0 {swords.rstrip()!r}, the bar {sbar}")


# ---------------------------------------------------------------- the monitor
# zx64mon on the VIC, resident (z80/monvic.inc): F5 shows its own
# screen, MSCR ($C400, 40 columns, 25 rows), in the C128's character ROM
# copied to $D000 ($D018 $14, $D011 $1B), in its colours (light blue on
# blue), as zx64's does on the C64; the ZX81's screen at $C000 stays as it
# is meanwhile; X, G or F5 back to it ($D018 $02, $D011 $17, the scheme's
# colours). A later F5 is quiet, as zx128's. One booted zx128vic for all
# of them (mon_session_vic), in scheme 2 (green on black), so the scheme
# coming back is seen. The frames the VIC shows across each switch are
# watched (VicSeen).
MON_VIC = {}
MSTACK_N = 254                                  # the monitor's stack: $FE00-$FEFD (hwvic128.inc's MSTACK)
MON_LOOK = (0x14, 0x1B, 11, 13, 13)             # $D018 $D011 $D021, characters, border (the C128's own: monvic.inc)
MON_TITLE = f"#ZX128MON {build.VERSION}   ? HELP   X OR F5: BACK"   # its title line
MON_SCHEME = 2
LINE_T = 126                                    # T-states a raster line (the model's: 2 a cycle)
SEEN_LINES = [30] + [57 + 8 * r for r in range(25)] + [280]   # the top border, each text row, the bottom border
FRAME0_T = (0 - 250) % 312 * LINE_T             # line 0 in the model's frame (which starts at line 250)


def zx_look(scheme):
    """The ZX81's look in a scheme: (MON_LOOK's fields)."""
    text, back, border = SCHEMES_VIC[scheme]
    return 0x02, 0x17, back, text, border


def cram_row(lk, r):
    """A look's colour RAM row r (0-24), its 40 cells: the monitor's all its
    characters' colour (mon_on's fill); the ZX81's (lk's $D018 $02) the
    frame's cells (FRAME) its border's, the picture's its characters'."""
    if lk[0] != 0x02:
        return [lk[3]] * 40
    return [lk[4] if 40 * r + c in FRAME_SET else lk[3] for c in range(40)]


def line_t(line):
    return (line - 250) % 312 * LINE_T


class VicSeen:
    """The frames the VIC shows (line 0 to 311) while it's on: each text
    row's look as the beam passes it (SEEN_LINES: $D018, $D011, $D021 and
    the row's colour RAM, the VIC's bank) and the border's above and below
    the text, matched with looks (name: MON_LOOK's fields); frames, by
    number, each a list of the names each sample matched. The Z80 runs in
    short steps meanwhile: m.step is taken over (sim128's Seen's way),
    off() gives it back."""

    def __init__(self, m, looks):
        self.m, self.looks, self.frames = m, looks, {}
        m.step = self.step

    def off(self):
        del self.m.step
        return self

    def step(self, ticks):
        m, f0 = self.m, self.m.nframes
        while ticks > 0 and m.z80_on and m.nframes == f0:
            pos = m.now_t() % FRAME_T
            d = min((line_t(ln) - pos) % FRAME_T or FRAME_T for ln in SEEN_LINES)
            n = max(1, int(min(ticks, d / (1 + sim128.CPU_SLOW) + 1)))
            t0 = m.now_t()
            C128.step(m, n)
            t1 = m.now_t()
            ticks -= max(1, int(t1 - t0))
            for i, ln in enumerate(SEEN_LINES):
                tl = t0 - t0 % FRAME_T + line_t(ln)
                while tl <= t0:
                    tl += FRAME_T
                while tl <= t1:
                    f = int((tl - FRAME0_T) // FRAME_T)
                    self.frames.setdefault(f, [None] * len(SEEN_LINES))[i] = self.look(i)
                    tl += FRAME_T

    def look(self, i):
        m = self.m
        if i in (0, len(SEEN_LINES) - 1):
            return frozenset(k for k, lk in self.looks.items() if lk[4] == m.vic[0x20] & 15)
        r = i - 1
        row = list(m.colour[40 * r:40 * r + 40])
        return frozenset(k for k, lk in self.looks.items()
                         if (m.vic[0x18], m.vic[0x11] & 0x7F, m.vic[0x21] & 15) == lk[:3] and row == cram_row(lk, r))

    def sum(self):
        """(whole frames, frames no one look explains (half of each), the
        looks in order as the frames had them, the first bad frame's
        samples)."""
        whole = [(f, s) for f, s in sorted(self.frames.items()) if None not in s]
        bad, seq, first = 0, [], None
        for f, s in whole:
            both = frozenset.intersection(*s)
            if not both:
                bad += 1
                first = first or [sorted(x) for x in s]
                continue
            name = "/".join(sorted(both))
            if not seq or seq[-1] != name:
                seq.append(name)
        return len(whole), bad, seq, first


def vic_swap(m, act, done, what, before=8, after=12):
    """The frames seen (VicSeen.sum) from before frames ahead of act() to
    after frames past done(m)."""
    s = sym()
    looks = {"zx": zx_look(m.bank1[s["scheme"]]), "mon": MON_LOOK}
    sn = VicSeen(m, looks)
    try:
        m.frames(before)
        act()
        m.until(lambda: done(m), 300, what)
        m.frames(after)
    finally:
        sn.off()
    return sn.sum()


def mon_shown(m):
    """The screen the VIC shows (vic_mem) as the monitor's rows: sim128's
    mon_rows' text of 25 rows of 40 screen codes."""
    bank, scr, _ = vic_mem(m)
    rows = []
    for r in range(25):
        row = bank[scr + 40 * r:scr + 40 * r + 40]
        rows.append("".join(chr((c & 0x7F) + 0x40) if c & 0x7F < 0x20 else chr(c & 0x7F) if c & 0x7F < 0x40
                            else "#" for c in row).rstrip())
    return rows


def mon_lbl():
    """zx128vic's monitor's own labels (build/obj/zx128vic/mon/)."""
    import build
    return build.labels(os.path.join(OBJ, "zx128vic", "mon", "zx128vicmon.lbl"))


sim128.mon_lbl = mon_lbl                        # (sim128's mon_arrow_moves: this monitor's cursor)


def vic_up(m):
    """The monitor's screen up and shown, its colours in."""
    return (m.bank1[sym()["mon_up"]] and (m.vic[0x18], m.vic[0x11] & 0x7F) == (0x14, 0x1B)
            and set(m.colour[:1000]) == {MON_LOOK[3]})


def vic_back(m):
    """The ZX81's screen shown again, the scheme's colours in (the
    picture's, the frame's: zx_cram)."""
    lk = zx_look(m.bank1[sym()["scheme"]])
    return (not m.bank1[sym()["mon_up"]] and (m.vic[0x18], m.vic[0x11] & 0x7F) == lk[:2]
            and zx_cram(m) == ([lk[3]], [lk[4]]))


def vic_written(m, cmd, n=1, settle=40):
    """sim128's mon_cmdout, and the bank 1 addresses the 8502 wrote
    meanwhile but its bookkeeping (the mailbox's page, ovl), as a range's
    (first, last), or a count."""
    keep = {sym8502()["OVL"]}
    m.writes1 = set()
    out = sim128.mon_cmdout(m, cmd, n, settle)
    w = sorted(a for a in m.writes1 if a >> 8 != 0x2F and a not in keep)
    m.writes1 = None
    return out, ((w[0], w[-1]) if w and w[-1] - w[0] == len(w) - 1 else len(w))


def mon_session_vic():
    if not MON_VIC:
        try:
            mon_run_vic(MON_VIC)
        except (AssertionError, KeyError, OSError, SystemExit) as e:
            MON_VIC["error"] = str(e).splitlines()[0] if str(e) else type(e).__name__
    if "error" in MON_VIC:
        raise AssertionError(MON_VIC["error"])
    return MON_VIC


def mon_run_vic(st):
    s = sym()
    m = zx128vic()
    rows, mon_type, mclr = sim128.mon_rows, sim128.mon_type, sim128.mclr
    stack = s["mstack"]
    m.bank1[stack - MSTACK_N:stack] = b"\xa5" * MSTACK_N
    for _ in range(MON_SCHEME):
        fkey(m, "LSHIFT", "F1")
    ovl_gone(m)
    m.frames(4)
    zx, fnt = bytes(m.bank1[0xC000:0xC400]), fonts(m)

    # F5, the first: the title and the registers
    seen = vic_swap(m, lambda: fkey(m, "F5"), vic_up, "the monitor's screen")
    m.frames(30)
    bank, scr, font = vic_mem(m)
    st["f5"] = dict(seen=seen, mem=(bank is m.bank1, scr, font), rows=rows(m), shown=mon_shown(m) == rows(m),
                    look=(m.vic[0x18], m.vic[0x11] & 0x7F, m.vic[0x21] & 15, sorted(set(m.colour[:1000])),
                          m.vic[0x20] & 15), zx=bytes(m.bank1[0xC000:0xC400]) == zx, fonts=fonts(m) == fnt)

    # the disk: $, W, L, @, and L and W over bank 1's $0000-$01FF (parked
    # at ROM01 meanwhile: mon6510.inc); the 8502 writes nothing of the VIC's
    m.drive = sim128.Drive128(os.path.join(ROOT, "build", "zx128vic.d64"))
    m.top_log = []
    mclr(m)
    mon_type(m, "$\r", settle=60)
    dirr = dict(rows=[r for r in rows(m) if r], want=["$"] + sim128.dir_lines(m.drive))
    mclr(m)
    sysv = bytes(m.bank1[0x4000:0x4100])
    w = sim128.mon_cmdout(m, 'W "T" 4000 40FF', settle=60)
    t = m.drive.files.get(b"T", b"")
    mon_type(m, "F 4000 40FF 00\r", settle=30)
    zero = bytes(m.bank1[0x4000:0x4100]) == bytes(256)
    m.frames(20)
    l, lw = vic_written(m, 'L "T" 4000', settle=60)
    back = bytes(m.bank1[0x4000:0x4100])
    m.bank1[0x4000:0x4100] = sysv
    mclr(m)
    rom = bytes(m.bank1[0:0x200])
    wr = sim128.mon_cmdout(m, 'W "R" 0000 01FF', settle=80)
    r = m.drive.files.get(b"R", b"")
    l1, lw1 = vic_written(m, 'L "T" 0100', settle=60)
    at100 = bytes(m.bank1[0x100:0x200])
    rb = sim128.mon_cmdout(m, 'L "R" 0000', settle=60)
    rom2 = bytes(m.bank1[0:0x200])
    m.bank1[0:0x200] = rom
    at = sim128.mon_cmdout(m, "@")
    prog = bytes(m.bank1[0x4009:m.peek16(0x4014)])
    sv = sim128.mon_cmdout(m, 'W "SV"', settle=60)     # (SAVE's and LOAD's paths: the row and the bar, but quiet)
    m.drive.files[b"OK"] = sim128.p_prog('10 PRINT "OK"')
    lsv = sim128.mon_cmdout(m, 'L "OK"', settle=60)
    m.frames(10)
    st["disk"] = dict(dir=dirr, w=w, t=t, sysv=sysv, zero=zero, l=l, lw=lw, back=back, rom=rom, wr=wr, r=r, l1=l1,
                      lw1=lw1, at100=at100, rb=rb, rom2=rom2, at=at, top=len(m.top_log), shown=mon_shown(m) == rows(m),
                      zx=bytes(m.bank1[0xC000:0xC400]) == zx, d018=m.vic[0x18], sv=sv, svf=m.drive.files.get(b"SV"),
                      prog=prog, lsv=lsv, eline=m.peek16(0x4014))
    m.top_log = None

    # the arrows (zx128's mon_arrows), then X with DOWN (K2) down: kup
    # holds the monitor until it is up too
    st["arrows"] = {n: sim128.mon_arrow_moves(m, way) for n, way in sim128.ARROW_WAYS.items()}
    st["keypad"] = sim128.mon_keypad(m)                 # the keypad (zx128's mon_keypad_keys)
    mclr(m)
    mon_type(m, "=FF\r")
    mon_type(m, "X", settle=0)
    left = rows(m)
    m.keys = {MPOS["RETURN"], sim128.C128NAMES["DOWN"]}
    m.frames(2)
    m.keys = {sim128.C128NAMES["DOWN"]}
    m.frames(30)
    st["arrows"]["held"] = m.bank1[s["mon_up"]]
    m.keys = {sim128.C128NAMES["KP5"]}                  # then keypad 5 for DOWN: kup waits for it
    m.frames(30)                                        # too
    st["keypad"]["held"] = m.bank1[s["mon_up"]]
    seen = vic_swap(m, lambda: setattr(m, "keys", set()), vic_back, "the ZX81's screen after X")
    m.frames(4)
    used = next((i for i in range(MSTACK_N) if m.bank1[stack - MSTACK_N + i] != 0xA5), MSTACK_N)
    st["x"] = dict(seen=seen, pic=vic_codes(m) == df_codes(m), look=(m.vic[0x18], m.vic[0x11] & 0x7F,
                   m.vic[0x21] & 15, zx_cram(m), m.vic[0x20] & 15), stack=MSTACK_N - used)
    m.until(lambda: zx_report(m) is not None and sim128.zx_editor(m), 300, "the report after L \"OK\"")
    st["disk"]["report"] = zx_report(m), m.zx_screen()[0]   # (L "NAME": X goes to BASIC, the program runs
                                                            # as after LOAD)

    # a later F5: quiet, the screen as left, the prompt under ".X"; F5 (the
    # key) at it back, and F5 again: the prompt on the next line
    seen = vic_swap(m, lambda: fkey(m, "F5"), vic_up, "the monitor's screen, quiet")
    m.frames(10)
    quiet = rows(m)
    seen_f5 = vic_swap(m, lambda: fkey(m, "F5"), vic_back, "the ZX81's screen after F5")
    fkey(m, "F5")
    m.until(lambda: vic_up(m), 300, "the monitor again")
    m.frames(10)
    st["quiet"] = dict(seen=seen, seen_f5=seen_f5, left=left, quiet=quiet, quiet2=rows(m))
    mon_type(m, "X\r", settle=0)
    m.until(lambda: vic_back(m), 300, "the ZX81's screen")

    # S: a program spinning on a flag, F5, the flag set, S until it has put
    # "A" at row 0: the monitor's screen up all along; X: the picture shows it
    sim128.load_p(m, sim128.p_prog("10 REM {bin:spin}\n20 RAND USR 16514", blobs={"spin": sim128.SPIN}))
    m.frames(20)
    fkey(m, "F5")
    m.until(lambda: vic_up(m), 60, "the monitor in the program")
    m.frames(10)
    mon_type(m, "R\r", settle=20)
    pc0 = sim128.mon_pc(m)
    d = m.peek16(0x400C) + 1
    m.bank1[0x408F] = 1
    looks = set()
    mon_type(m, "S\r", settle=20)
    steps = 1
    while m.bank1[d] != 0x26 and steps < 12:
        looks.add((m.vic[0x18], m.bank1[s["mon_up"]]))
        mon_type(m, "\r", settle=20)
        steps += 1
    looks.add((m.vic[0x18], m.bank1[s["mon_up"]]))
    mclr(m)
    seen = vic_swap(m, lambda: mon_type(m, "X\r", settle=0), vic_back, "the ZX81's screen after S")
    m.frames(4)
    st["step"] = dict(pc0=pc0, steps=steps, df=m.bank1[d], looks=looks, seen=seen, vic=vic_codes(m)[0][0])
    m.until(lambda: zx_report(m) is not None and sim128.zx_editor(m), 300, "the program's end")
    st["step"]["report"] = zx_report(m)

    # B, then G at it, RAND USR 28672: the breakpoint; G on past it
    fkey(m, "F5")
    m.until(lambda: vic_up(m), 60, "the monitor")
    m.frames(15)
    mon_type(m, ":7000 3E 01 3C 3C 32 00 71 C9\r", settle=20)   # LD A,1; INC A; INC A; LD ($7100),A; RET
    mon_type(m, "B 7002\r")
    seen = vic_swap(m, lambda: mon_type(m, "G\r", settle=0), vic_back, "the ZX81's screen after G")
    m.type("T SHIFT+NEWLINE L 2 8 6 7 2")               # RAND USR 28672
    m.keys = keyset(["NEWLINE"])
    m.until(lambda: m.bank1[s["mon_up"]], 60, "the breakpoint")
    m.keys = set()
    m.frames(15)
    rws = rows(m)
    hit = "#BREAKPOINT" in rws and sim128.mon_pc(m) == "7002" and m.bank1[0x7002] == 0x3C
    mon_type(m, "G\r", settle=0)
    m.until(lambda: zx_report(m) is not None and sim128.zx_editor(m), 300, "the program's end")
    m.frames(10)
    st["bp"] = dict(seen=seen, hit=hit, report=zx_report(m), a=m.bank1[0x7100], armed=m.bank1[0x7002],
                    pic=vic_codes(m) == df_codes(m), up=vic_back(m))

    # F5 in a FAST program (no IRQ: BREAK-1's brk_f5): quiet, the prompt
    # alone on the screen the check blanked; F5 back: the picture at once
    sim128.load_p(m, sim128.p_prog("10 FAST\n20 GOTO 20"))
    m.frames(20)
    a = s["mscr"]
    m.bank1[a:a + 1000] = b"\x20" * 1000
    fast = not m.z.iff1
    fkey(m, "F5")
    m.until(lambda: vic_up(m), 60, "the monitor in a FAST program")
    m.frames(15)
    frows = [x for x in rows(m) if x]
    m.bank1[m.peek16(0x400C) + 1 + 33 * 3] = 0x26      # ("A" at row 3: on the VIC as the monitor leaves)
    seen = vic_swap(m, lambda: fkey(m, "F5"), vic_back, "the ZX81's screen after F5 in FAST")
    st["fast"] = dict(fast=fast, rows=frows, seen=seen, pic=vic_codes(m) == df_codes(m), iff=m.z.iff1)
    m.keys = keyset(["SPACE"])
    m.until(lambda: zx_report(m) is not None, 100, "BREAK")
    m.keys = set()
    m.until(lambda: sim128.zx_editor(m), 100, "the editor")
    st["fast"]["report"] = zx_report(m)
    st["rom"] = list(m.rom_writes)


def seen_ok(sn, want):
    n, bad, seq, first = sn
    return n > 15 and not bad and seq == want


def seen_txt(sn):
    n, bad, seq, first = sn
    return f"{n} frames, {bad} half of each{f' (first {first})' if first else ''}, {' then '.join(seq)}"


@viccheck
def vic_mon_f5():
    # F5 at the K cursor: the monitor's own screen at $C400 ($D018 $14:
    # screen $C400, font $D000, the C128's character ROM as boot128 copied
    # it; $D011 $1B, 25 rows), the title and the registers on it, the VIC
    # showing MSCR (the title zx128's monitor's, MON_TITLE); the
    # monitor's colours (MON_LOOK); the ZX81's
    # screen at $C000 and both fonts as they were; no frame with half of
    # each look
    st = mon_session_vic()["f5"]
    rows = st["rows"]
    ok = (st["mem"] == (True, 0xC400, 0xD000) and rows[0].startswith(MON_TITLE) and rows[1].startswith("#PC   AF")
          and rows[2].startswith(";") and st["shown"] and st["look"] == (0x14, 0x1B, MON_LOOK[2], [MON_LOOK[3]], MON_LOOK[4]) and st["zx"]
          and st["fonts"] and seen_ok(st["seen"], ["zx", "mon"]))
    check("vic_mon_f5", ok, f"VIC: bank 1 {st['mem'][0]}, screen ${st['mem'][1]:04X}, font ${st['mem'][2]:04X}; "
          f"{rows[:2]}; the VIC shows MSCR {st['shown']}; $D018 $D011 $D021 colours border {st['look']}; the "
          f"ZX81's screen kept {st['zx']}, fonts {st['fonts']}; {seen_txt(st['seen'])}")


@viccheck
def vic_mon_back():
    # X (with DOWN, K2, held: the monitor waits), S's X, G, F5 in a FAST
    # program: back to the ZX81's screen ($D018 $02, $D011 $17) in the
    # scheme's colours (2: green on black, the frame round the picture
    # black), no frame with half of each
    # look; the picture as D_FILE (in FAST too: no IRQ to blit it); the
    # monitor's stack (from MSTACK, common RAM: never in $D000-$DFFF or
    # $1000-$13FF, the colour RAM window's) as deep as it went
    st = mon_session_vic()
    want = zx_look(MON_SCHEME)
    x, sx, bp, fast = st["x"], st["step"], st["bp"], st["fast"]
    ok = (x["look"] == (want[0], want[1], want[2], ([want[3]], [want[4]]), want[4]) and x["pic"] and seen_ok(x["seen"], ["mon", "zx"])
          and seen_ok(sx["seen"], ["mon", "zx"]) and seen_ok(bp["seen"], ["mon", "zx"]) and bp["up"] and bp["pic"]
          and seen_ok(fast["seen"], ["mon", "zx"]) and fast["pic"] and 0 < x["stack"] < MSTACK_N and not st["rom"])
    check("vic_mon_back", ok, f"X: {x['look']}, the picture as D_FILE {x['pic']}, {seen_txt(x['seen'])}; after S: "
          f"{seen_txt(sx['seen'])}; G: {seen_txt(bp['seen'])}; F5 in FAST: {seen_txt(fast['seen'])}, the picture "
          f"{fast['pic']}; the stack {x['stack']} bytes deep; ROM writes {st['rom'][:2]}")


@viccheck
def vic_mon_quiet():
    # a later F5: the screen as it was left, the prompt alone on the line
    # under ".X" (no title, no registers); F5 (the key) at that prompt, F5
    # again: the prompt on the next line; both switches without a half
    # frame
    st = mon_session_vic()["quiet"]
    left, quiet = st["left"], st["quiet"]
    x = max((i for i, r in enumerate(left) if r == ".X"), default=None)
    q1 = x is not None and quiet == sim128.prompt_after(left, x)
    p = max((i for i, r in enumerate(quiet) if r == "."), default=None)
    q2 = p is not None and st["quiet2"] == sim128.prompt_after(quiet, p)
    hello = sum(r.startswith("#ZX128MON") for r in quiet)
    check("vic_mon_quiet", q1 and q2 and not hello and seen_ok(st["seen"], ["zx", "mon"])
          and seen_ok(st["seen_f5"], ["mon", "zx"]),
          f"after X at row {x}: {quiet[x:x + 3] if x is not None else left[:3]} ({q1}); F5 at the prompt (row {p}) "
          f"and back: {st['quiet2'][p:p + 3] if p is not None else ''} ({q2}); title lines {hello}; F5: "
          f"{seen_txt(st['seen'])}; F5 back: {seen_txt(st['seen_f5'])}")


@viccheck
def vic_mon_bp():
    # S: a program spinning on a flag, F5 in it, the flag set, S until it
    # has put "A" at D_FILE's row 0: the monitor's screen up through the
    # steps; X: the VIC shows the "A", the program goes on to 0/20. ":" a
    # routine at $7000, B 7002, G; RAND USR 28672: the monitor at the
    # breakpoint ("#BREAKPOINT", PC 7002, its byte back); G: on past it, to
    # the end ($7100 = 3, 0/0), the breakpoint armed again (zx128's
    # mon_bp_go)
    st = mon_session_vic()
    sx, bp = st["step"], st["bp"]
    up = sx["looks"] == {(0x14, 1)}
    ok = (sx["df"] == 0x26 and up and sx["vic"] == 0x26 and sx["report"] == "0/20" and bp["hit"]
          and bp["report"] == "0/0" and bp["a"] == 3 and bp["armed"] == 0xFF)
    check("vic_mon_bp", ok, f"PC {sx['pc0']} at F5, {sx['steps']} step(s): D_FILE ${sx['df']:02X}, the monitor's "
          f"screen through them {sorted(sx['looks'])}, the VIC after X ${sx['vic']:02X}, {sx['report']}; the "
          f"breakpoint hit {bp['hit']}, G: {bp['report']}, $7100 = {bp['a']}, $7002 = ${bp['armed']:02X}")


@viccheck
def vic_mon_fast_f5():
    # F5 in a FAST program (no IRQ: BREAK-1's brk_f5): the monitor's F5
    # entry, quiet: only the prompt on the screen the check blanked; F5
    # back, BREAK: D/20
    st = mon_session_vic()["fast"]
    check("vic_mon_fast_f5", st["fast"] and st["rows"] == ["."] and st["report"] == "D/20",
          f"interrupts off {st['fast']}; {st['rows'][:3]}; then {st['report']}")


@viccheck
def vic_mon_disk():
    # $: the d64's directory as the drive sends it; W "T" 4000 40FF (a PRG
    # of the 256 bytes, its load address bank 1's own: $4000), F 4000 40FF
    # 00, L "T" 4000: the bytes back, "#LOADED 4000-40FF", the 8502 writing
    # just those; W "R" 0000 01FF, L "T" 0100 and L "R" 0000 (bank 1's
    # $0000-$01FF parked at ROM01 meanwhile: mon6510.inc); @: the status;
    # W "SV" (the program, as SAVE) and L "OK" (as LOAD: X then goes to
    # BASIC, where it runs, as after LOAD: OK, 0/10). The 8502 writes nothing of $C000-$D7FF (no loading
    # row, no bar: the monitor is up, boot128's quiet), the VIC shows MSCR
    # after, the ZX81's screen as it was
    st = mon_session_vic()["disk"]
    body = st["t"][2:]
    ok = (st["dir"]["rows"][:len(st["dir"]["want"])] == st["dir"]["want"] and st["t"] == b"\x00\x40" + st["sysv"]
          and st["w"] == ["00, OK,00,00"] and st["zero"] and st["back"] == st["sysv"] and st["l"] == ["#LOADED 4000-40FF"]
          and st["lw"] == (0x4000, 0x40FF) and st["r"] == b"\x00\x00" + st["rom"] and st["l1"] == ["#LOADED 0100-01FF"]
          and st["at100"] == body and st["rb"] == ["#LOADED 0000-01FF"] and st["rom2"] == st["rom"]
          and st["at"] == ["00, OK,00,00"] and st["top"] == 0 and st["shown"] and st["zx"] and st["d018"] == 0x14
          and st["sv"] == ["00, OK,00,00"] and st["svf"] == st["prog"] and st["lsv"] == [f"#LOADED 4009-{st['eline'] - 1:04X}"]
          and st["report"] == ("0/10", "OK"))
    check("vic_mon_disk", ok, f"$ as the drive's {st['dir']['rows'][:len(st['dir']['want'])] == st['dir']['want']} "
          f"({st['dir']['rows'][:2]}); W {st['w']}, T {len(st['t'])} bytes; F zeroed {st['zero']}; L {st['l']}, "
          f"back {st['back'] == st['sysv']}, the 8502 wrote {st['lw']}; W \"R\" {st['wr']} as the ROM "
          f"{st['r'][2:] == st['rom']}; L \"T\" 0100 {st['l1']} ({st['at100'] == body}, wrote {st['lw1']}), L \"R\" "
          f"0000 {st['rb']} ({st['rom2'] == st['rom']}); @ {st['at']}; the 8502's writes to $C000-$D7FF "
          f"{st['top']}; the VIC shows MSCR {st['shown']}, the ZX81's screen kept {st['zx']}; W \"SV\" {st['sv']}, "
          f"the program {st['svf'] == st['prog']}; L \"OK\" {st['lsv']}, X: {st['report']}")


@viccheck
def vic_mon_arrows():
    # the C128's top-row cursor keys at the monitor as the C64's (k2mon.inc,
    # io128.inc's kscan_more), zx128's mon_arrows: the same moves made with
    # either leave the cursor and the screen the same; held, they repeat;
    # UP at the top scrolls M's lines back; X with DOWN still down: the
    # monitor waits for it
    st = mon_session_vic()["arrows"]
    c64, c128 = st["C64"], st["C128"]
    combo = (11, 12)
    apart = [i for i, (a, b) in enumerate(zip(c64, c128)) if a[1] != b[1] or (a[0] != b[0] and i not in combo)]
    (r0, c0), (r1, c1) = c64[6][0], c64[7][0]
    rep = c1 - c0
    (ra, ca), (rb, cb), (rc, cc) = (c128[i][0] for i in (10, 11, 12))
    mix = (rb, cb) == (ra - 1, ca - 1) and (rc, cc) == (rb + 1, cb + 1)
    top = c64[-1][1][:2]
    ok = not apart and len(c64) == len(c128) == 17 and rep >= 3 and c64[8][0][0] <= r1 - 3 and mix \
        and all(r.startswith(".:3F") for r in top) and st["held"]
    check("vic_mon_arrows", ok, f"C128's keys as the C64's: {'all' if not apart else f'not at steps {apart}'}; "
          f"RIGHT held: {rep} columns, UP held: rows {r1} to {c64[8][0][0]}; the mixes {(ra, ca)} {(rb, cb)} "
          f"{(rc, cc)} ({mix}); UP at the top: {top}; X with DOWN down: still up {bool(st['held'])}")


@viccheck
def vic_keypad():
    # the C128's numeric keypad at the ZX81 as the main keys
    # (zx128's kbd_c128_keypad: k2scan.inc, in the own area here)
    st = sim128.keypad_zx(zx128vic())
    check("vic_keypad", sim128.keypad_zx_ok(st), sim128.keypad_zx_say(st))


@viccheck
def vic_keys_map():
    # zx128's kbd_c128_map here (KPFAST's code, its
    # one-key cache: KP7 then RIGHT, the same row)
    bad = sim128.keypad_map(zx128vic)
    check("vic_keys_map", not bad, f"{len(sim128.K128AS)} keys and KP7 then RIGHT: "
          + (f"differ: {bad}" if bad else "each as its C64 key"))


@viccheck
def vic_keys_held():
    # zx128's kbd_c128_held here (k2scan.inc's KPFAST
    # variant): RIGHT and keypad 8 held, against CRSR RIGHT and 8
    sim128.held_check("vic_keys_held", "zx128vic", zx128vic)


@viccheck
def vic_keys_glitch():
    # zx128's kbd_c128_glitch here: keypad digits with the
    # cartridge's misreads on, the line as typed
    got, want = sim128.keypad_glitch(zx128vic)
    check("vic_keys_glitch", got == want, f"{len(want) - 1} keypad digits, misreads on: "
          f"{'as typed' if got == want else f'{got!r}'}")


@viccheck
def vic_mon_keypad():
    # the C128's numeric keypad at the monitor as the main keys
    # (zx128's mon_keypad_keys: k2mon.inc, in the monitor's part 1)
    st = mon_session_vic()["keypad"]
    check("vic_mon_keypad", sim128.mon_keypad_ok(st), sim128.mon_keypad_say(st))


NTSC_LINE_T, NTSC_LINES, ntsc_vic = sim128.NTSC_LINE_T, sim128.NTSC_LINES, sim128.ntsc_vic   # (sim128's)


def run_hide(m, frames=10):
    """monvic.inc's mv_hide called from the K cursor (no IRQ meanwhile): the
    raster line it returns on, or None if it hasn't in frames."""
    s, z = sym(), m.z
    pc, sp, i1, i2 = z.pc, z.sp, z.iff1, z.iff2
    z.sp = 0x7EFE
    z.memory[0x7EFE], z.memory[0x7EFF] = 0x00, 0x7E          # its return: to $7E00
    z.pc, z.iff1, z.iff2 = s["mv_hide"], False, False
    enable, m.enable = m.enable, 0
    end = m.nframes + frames
    while z.pc != 0x7E00 and m.nframes < end:
        m.step(1)
    at = m.line() if z.pc == 0x7E00 else None
    m.enable = enable
    z.pc, z.sp, z.iff1, z.iff2 = pc, sp, i1, i2
    return at


@viccheck
def vic_mon_ntsc():
    # the monitor's switch waits out of sight (mv_hide):
    # on a PAL VIC until line 300, past the text and the border PAL shows;
    # on an NTSC one (263 lines: no line 300) until the wrap to line 0,
    # not for ever (at most a line late: a poll's loop). Both from the K
    # cursor, in the raster's every phase (begun at 8 points of a frame)
    pal, ntsc = [], []
    m = zx128vic()
    for k in range(8):
        m.frames(1)
        m.step(FRAME_T // 8 * k // 2 + 1)
        pal.append(run_hide(m))
    m = zx128vic()
    ntsc_vic(m)
    for k in range(8):
        m.frames(1)
        m.step(NTSC_LINES * NTSC_LINE_T // 8 * k // 2 + 1)
        ntsc.append(run_hide(m))
    check("vic_mon_ntsc", all(a in (300, 301) for a in pal) and all(a in (0, 1) for a in ntsc),
          f"PAL: back at line(s) {sorted(set(pal), key=str)} (300, or 301: a poll's overshoot); NTSC: "
          f"{sorted(set(ntsc), key=str)} (0 or 1; None: it never returned)")


def v_vic():
    """sim128's V session and checks on zx128vic: its machine, its
    part 3 (build/obj/zx128vic/), its function ROM."""
    return sim128.v_checks("vic_mon_v", sim128.v_session("zx128vic", zx128vic, os.path.join(OBJ, "zx128vic"), VROM,
                                                         C128VIC), MON_TITLE, under=0x64)


@viccheck
def vic_mon_v_lines():
    # sim128's mon_v_lines on zx128vic's 40 columns; the names'
    # "_" as the C128 character ROM's line along the bottom ($64: its $1F,
    # what the "_" would be, is a left arrow)
    check(*v_vic()[0])


@viccheck
def vic_mon_v_store():
    # sim128's mon_v_store
    check(*v_vic()[1])


@viccheck
def vic_mon_v_return():
    # sim128's mon_v_return
    check(*v_vic()[2])


@viccheck
def vic_mon_v_help():
    # sim128's mon_v_help: the help and its title on the VIC's 25 rows
    check(*v_vic()[3])


@viccheck
def vic_mon_v_reset():
    # sim128's mon_v_reset: after F7, and from zx128vic's function ROM
    # after a reset
    check(*v_vic()[4])


@viccheck
def vic_editor_idle():
    # keys typed a few frames apart (Q, SHIFT+0 twice):
    # the editor's idle key wait can keep eframes at 1 (keywait clears it
    # before frame sets d1active: an IRQ between counts one), and the
    # helpers' zx_editor still takes it for the editor (eframes < 2, as
    # romkbd.inc's mirror does), so no check waits on it in vain
    m = zx128vic()
    ovl_gone(m)
    s = sym()
    got = []
    for gap in (4, 6, 8):
        for k in ("Q", "SHIFT+0", "Q", "SHIFT+0"):
            m.keys = keyset(k.split("+"))
            m.frames(2)
            m.keys = set()
            m.frames(gap)
        m.frames(30)
        got.append((m.bank1[s["eframes"]], m.bank1[s["edit"]], sim128.zx_editor(m)))
    check("vic_editor_idle", all(ed == 1 and ok for ef, ed, ok in got) and any(ef == 1 for ef, ed, ok in got),
          f"(eframes, edit, zx_editor) after each round: {got}")


# ---- the function ROM: build/zx128vic.rom, c128/from.asm's copier
# and zx128vic.prg's bytes behind it, as build/zx128.rom is zx128's; started
# as sim128's rom_start starts zx128's
VROM = os.path.join(ROOT, "build", "zx128vic.rom")
VCRT, VCRT_VICE = os.path.join(ROOT, "build", "zx128vic.crt"), os.path.join(OBJ, "zx128vic-vice.crt")


def vrom():
    return open(VROM, "rb").read()


@viccheck
def vic_rom_boots():
    # build/zx128vic.rom as sim128's rom_header wants zx128.rom (32K, ID 1
    # and "CBM" at $8006, the vectors on from.asm's RTIs, no "CBM" at
    # $C007), its .crt files as zx128's (build/zx128vic.crt one 32K CHIP at
    # $8000, build/obj/zx128vic-vice.crt two of 16K), named ZX128VIC.
    # Started as the kernal starts it, external ($FF00 $2A) and internal
    # ($16), an IRQ pending (taken once): the kernal's IOINIT, RAMTAS,
    # RESTOR, CINT with its ROM at $C000, zx128vic.prg's bytes at $1300 at
    # the copier's JMP $1300 ($FF00 the kernal's, interrupts off, no
    # decimal), no other ROM read (the kernal's, BASIC's) than boot128's of
    # the character ROM's first 2K (vs_rom's, the monitor's font: the
    # model has none), then vic_boot_k's state: the K cursor on the VIC, as
    # from the disk
    rom = vrom()
    vec, rti = sim128.rom_vectors(rom)
    one, vice = sim128.crt_chips(VCRT), sim128.crt_chips(VCRT_VICE)
    files = (len(rom) == 0x8000 and rom[6:10] == b"\x01CBM" and rti and rom[0x4007:0x400A] != b"CBM"
             and one == (True, b"ZX128VIC", [(0x8000, 0x8000, rom)])
             and vice == (True, b"ZX128VIC", [(0x8000, 0x4000, rom[:0x4000]), (0xC000, 0x4000, rom[0x4000:])]))
    got = [(files, f"{len(rom)} bytes, $8006 {rom[6:10].hex(' ')}, vectors {' '.join(f'${v:04X}' for v in vec)} on "
                   f"RTI {rti}; zx128vic.crt {one[0]} {one[1]} {[(hex(a), hex(b)) for a, b, c in one[2]]}; "
                   f"zx128vic-vice.crt {vice[0]} {vice[1]} {[(hex(a), hex(b)) for a, b, c in vice[2]]}")]
    prg = open(PRG, "rb").read()[2:]
    vr = sym8502()["vr_src"]
    for ext in (True, False):
        m, seen = sim128.rom_boot(ext, VROM, C128VIC)
        chars = {a for pc, a in seen["rom_reads"] if vr <= pc < vr + 3}
        other = [(pc, a) for pc, a in seen["rom_reads"] if not vr <= pc < vr + 3]
        want = [(a, sim128.ROM_CR[ext] & 0xCF) for a in sim128.ROM_KERNAL]
        cr, p, mem = seen["at"] or (None, 0, b"")
        at = (mem[:len(prg)] == prg and mem[len(prg):] == bytes(0x100) and cr == sim128.ROM_CR[ext] & 0xCF
              and p & m.cpu.INTERRUPT and not p & m.cpu.DECIMAL)
        ok, text = boot_state(m)
        got.append((ok and at and seen["calls"] == want and not other and chars == set(range(0xD000, 0xD800))
                    and seen.get("irqs") == 1,
                    f"{'external' if ext else 'internal'}: IRQs taken {seen.get('irqs')}, kernal calls "
                    f"{' '.join(f'${a:04X}/${c:02X}' for a, c in seen['calls'])}, other ROMs read "
                    f"{other[:2]} (the character ROM: {len(chars)} bytes); at $1300 the image {mem[:len(prg)] == prg}, $FF00 "
                    f"{cr if cr is None else f'${cr:02X}'}, flags ${p:02X}; {text}"))
    check("vic_rom_boots", all(g for g, _ in got), "; ".join(t for _, t in got))


@viccheck
def vic_rom_skip():
    # CTRL held: back to the kernal as zx128's ROM goes (sim128's ctrl_skip:
    # $FF00, CIA 1, the stack as they came, the slot's ID cleared, no kernal
    # call, nothing copied), and $D030 as the kernal set it, not written;
    # external and internal
    got = []
    for ext in (True, False):
        m = sim128.rom_start(ext, key="CTRL", rom=vrom(), cls=C128VIC)
        d030 = m.d030
        ok, text = sim128.ctrl_skip(m, ext)
        got.append((ok and not m.d030_log and m.d030 == d030, f"{text}, $D030 writes {m.d030_log}"))
    check("vic_rom_skip", all(g for g, _ in got), "; ".join(t for _, t in got))


@viccheck
def vic_rom_speed():
    # if the copier runs at 2 MHz ($D030 bit 0: the VIC shows garbage then):
    # every store of the copy made at 2 MHz, and $D030 back to 1 MHz, its
    # other bits as the kernal left them, before boot128's entry (all its
    # writes from the ROM, none after); external and internal. (CTRL's
    # skip: vic_rom_skip, $D030 untouched.) A copier at 1 MHz: no write
    prg = os.path.getsize(PRG) - 2
    got = []
    for ext in (True, False):
        m, _ = sim128.rom_boot(ext, VROM, C128VIC)
        log = m.d030_log
        fast = bool(log)
        ok = not log or (all(0x8000 <= pc < 0x10000 for pc, _ in log) and log[0][1] & 1 and not log[-1][1] & 1
                         and log[-1][1] | 0xFC == 0xFC and m.d030 == 0xFC and m.fast_writes >= prg)
        got.append((ok, f"{'external' if ext else 'internal'}: $D030 writes "
                        f"{[(f'${pc:04X}', f'${v:02X}') for pc, v in log]} ({'2 MHz' if fast else '1 MHz'}), "
                        f"stores at 2 MHz {m.fast_writes} (the image {prg}), $D030 now ${m.d030:02X}"))
    check("vic_rom_speed", all(g for g, _ in got), "; ".join(t for _, t in got))


@viccheck
def vic_rom_packed():
    # build/zx128vic.rom as sim128's rom_packed wants zx128.rom:
    # zx128vic.prg's image packed, under 0.9 of it (sim128.packed_rom), and from the ROM,
    # external and internal, zero page at $1300 as the kernal left it but
    # $FA-$FE, SP $F9, and the time from $8000 to $1300 at most a second
    # (at 1 MHz) more than the copier's (sim128.rom_unpacked)
    fsym = sim128.from_sym(os.path.join(OBJ, "zx128vic", "from.sym"))
    prg = open(PRG, "rb").read()
    ok, text, spare = sim128.packed_rom(vrom(), fsym, prg)
    got = [(ok and fsym["STREAMLEN"] < 0.9 * (len(prg) - 2), text + f"; {spare} bytes spare")]
    for ext in (True, False):
        got.append(sim128.rom_unpacked(sim128.rom_boot(ext, VROM, C128VIC)[1], ext, "zx128vic"))
    check("vic_rom_packed", all(g for g, _ in got), "; ".join(t for _, t in got))


OWN_FLOOR = sim128.OWN_FLOOR                    # the own area's spare, at least (as zx128's)
COM_FLOOR = 10                                  # common RAM's (constraints: as zx128's)


@viccheck
def vic_builds():
    # both C128 builds' room left, from their labels: the core (to KPAGE),
    # the own area (zx128 $C900, zx128vic $D800, both to $DFFD), common RAM
    # (to $F7FD); zx128vic keeps OWN_FLOOR in its own area and COM_FLOOR
    # in common RAM. zx128vic's monitor: part 1 to $3FFF, part 2 to $EFFD
    # ($EFFE: an IN copy, the $EF row's), its buffers from MBUF to $FDFD
    # ($FDFE: the $FD row's), its stack from $FEFD down; and both function
    # ROMs' room left (each its own copier: zx128vic's from.asm with FAST),
    # as the build counts it (packed)
    import build
    got = {}
    for name in ("zx128", "zx128vic"):
        lb = build.labels(os.path.join(OBJ, name + ".lbl"))
        got[name] = dict(core=0x2E00 - lb["coreend"], own=0xDFFE - lb["hiend"], com=0xF7FE - lb["zcomend"])
    v = got["zx128vic"]
    ml = mon_lbl()
    mon = dict(p1=0x4000 - ml["part1end"], p2=0xEFFE - ml["monend"], buf=0xFDFE - ml["kprev"] - 8)
    places = ml["mbuf"] == 0xFC00 and ml["mstack"] == 0xFEFE and ml["mscr"] == 0xC400 and ml["mcols"] == 40
    rom = {}                                    # (packed, from from.asm's STREAM to its unpacker)
    for n, d in (("zx128", ()), ("zx128vic", ("zx128vic",))):
        fs = sim128.from_sym(os.path.join(OBJ, *d, "from.sym"))
        rom[n] = fs["STREAM"] - fs["codeend"]
    check("vic_builds", v["own"] >= OWN_FLOOR and v["com"] >= COM_FLOOR and v["core"] >= 0 and places
          and min(mon.values()) >= 0 and min(rom.values()) >= 0,
          "; ".join(f"{n}: core {g['core']}, own area {g['own']}, common RAM {g['com']}" for n, g in got.items())
          + f"; zx128vic's monitor: part 1 {mon['p1']}, part 2 {mon['p2']}, buffers {mon['buf']} spare, "
          f"MBUF ${ml['mbuf']:04X}, MSTACK ${ml['mstack']:04X}; the function ROMs: "
          + ", ".join(f"{n} {r} spare" for n, r in rom.items()))


def main():
    for fn in CHECKS:
        fn()
    print(f"\n{simulate.summary()}")
    sys.exit(1 if simulate.failures else 0)


if __name__ == "__main__":
    main()
