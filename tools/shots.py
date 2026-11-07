#!/usr/bin/env python3
"""Screenshots for the docs, from make test's emulators.

    .venv/bin/python tools/shots.py [scene ...]

Runs zx64 in tools/simulate.py's machine, types what each scene needs and
draws the VIC's screen as it is in memory (its own character set, or the
C64's character ROM for the monitor) into docs/img/shot-*.png, and the
loading bar into docs/img/loading-bar.gif. The zx128 and zx128vic scenes
do the same in tools/sim128.py's C128: zx128's VDC screen from the VDC's
RAM, zx128vic's VIC screen from bank 1. Needs a build (make), the C64
character ROM (VICE's chargen-901225-01.bin, found in the usual places or
given as CHARGEN=), ffmpeg for the GIF, and the games in games/ for the
scenes that load them.
"""
import glob
import os
import struct
import sys
import zlib

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import simulate as S  # noqa: E402

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OUT = os.path.join(ROOT, "docs", "img")

# VICE's "colodore" palette
PALETTE = [(0x00, 0x00, 0x00), (0xFF, 0xFF, 0xFF), (0x96, 0x28, 0x2E), (0x5B, 0xD6, 0xCE),
           (0x9F, 0x2D, 0xAD), (0x41, 0xB9, 0x36), (0x27, 0x24, 0xC4), (0xEF, 0xF3, 0x47),
           (0x9F, 0x48, 0x15), (0x5E, 0x35, 0x00), (0xDA, 0x5F, 0x66), (0x47, 0x47, 0x47),
           (0x78, 0x78, 0x78), (0x91, 0xFF, 0x84), (0x68, 0x64, 0xFF), (0xAE, 0xAE, 0xAE)]
BORDER_X, BORDER_Y = 32, 35                     # VICE's normal borders, PAL


def chargen():
    paths = [os.environ.get("CHARGEN", "")] + glob.glob("/opt/homebrew/share/vice/C64/chargen-901225-01.bin") \
        + glob.glob("/usr/local/share/vice/C64/chargen-901225-01.bin") \
        + glob.glob("/usr/share/vice/C64/chargen-901225-01.bin") \
        + glob.glob("/usr/lib/vice/C64/chargen-901225-01.bin")
    for p in paths:
        if p and os.path.exists(p):
            return open(p, "rb").read()
    sys.exit("the C64 character ROM isn't found: give it as CHARGEN=path/chargen-901225-01.bin")


def png(path, w, h, rows):
    def chunk(t, d):
        return struct.pack(">I", len(d)) + t + d + struct.pack(">I", zlib.crc32(t + d) & 0xFFFFFFFF)
    raw = b"".join(b"\0" + bytes(r) for r in rows)
    open(path, "wb").write(b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", struct.pack(">IIBBBBB", w, h, 8, 2, 0, 0, 0))
                           + chunk(b"IDAT", zlib.compress(raw, 9)) + chunk(b"IEND", b""))


def draw(peek, path, rom, scale=2, row=None, io=None):
    """The VIC's text screen as peek(C64 address) shows it; with row, only
    that character row of the ZX81's 32 columns, and a margin. io(address):
    the VIC's and CIA 2's registers and colour RAM, if not peek's (the
    C128's, where the VIC's memory has other bytes at $D000-$DFFF)."""
    io = io or peek
    d011, d018 = io(0xD011), io(0xD018)
    bank = (3 - (io(0xDD00) & 3)) * 0x4000
    screen = bank + (d018 >> 4) * 0x400
    chars = bank + ((d018 >> 1) & 7) * 0x800
    from_rom = bank in (0, 0x8000) and 0x1000 <= chars - bank < 0x2000
    glyph = (lambda c, y: rom[(chars - bank - 0x1000) + c * 8 + y]) if from_rom else \
        (lambda c, y: peek(chars + c * 8 + y))
    rows = 25 if d011 & 8 else 24
    top = BORDER_Y + (d011 & 7) - 3            # where character row 0 starts
    win0, win1 = (BORDER_Y, BORDER_Y + 200) if rows == 25 else (BORDER_Y + 4, BORDER_Y + 196)
    border, back = PALETTE[io(0xD020) & 15], PALETTE[io(0xD021) & 15]
    w, h = 320 + 2 * BORDER_X, 200 + 2 * BORDER_Y
    ys, xs = range(h), range(w)
    if row is not None:
        ys = range(top + row * 8 - 4, top + row * 8 + 12)
        xs = range(BORDER_X + 28, BORDER_X + 292)
    img = []
    for y in ys:
        line = []
        for x in xs:
            px = border
            if win0 <= y < win1 and BORDER_X <= x < BORDER_X + 320:
                cx, cy = (x - BORDER_X) // 8, (y - top) // 8
                px = back
                if 0 <= cy < 25:
                    c = peek(screen + cy * 40 + cx)
                    if glyph(c, (y - top) % 8) & (0x80 >> ((x - BORDER_X) % 8)):
                        px = PALETTE[io(0xD800 + cy * 40 + cx) & 15]
            line.extend(px * scale)
        img.extend([b"".join(bytes(p) for p in zip(*[iter(line)] * 3))] * scale)
    png(path, len(xs) * scale, len(ys) * scale, img)
    print("wrote", os.path.relpath(path, ROOT))


class Shot(S.Machine):
    """The machine, with a hook while the 6510 runs (the loading bar)."""
    on_6510 = None

    def run_6510(self, limit=2_000_000):
        cpu = self.cpu
        for i in range(limit):
            if self.z80_on:
                self.z.memory[0x0000:0xF000] = self.ram[0x1000:0x10000]
                self.z.memory[0xF000:0x10000] = self.ram[0x0000:0x1000]
                return
            if self.on_6510 and i % 4000 == 0:
                self.on_6510(self)
            self.step_6510()
        raise AssertionError(f"the 6510 never handed back (pc ${cpu.pc:04X})")


ROM = None


def shot(m, name):
    """The screen as the Z80 sees it (C64 address - $1000)."""
    draw(lambda a: m.z.memory[(a - 0x1000) & 0xFFFF], os.path.join(OUT, f"shot-{name}.png"), ROM)


def machine():
    m = Shot(int_wired=True)
    m.ram[0x02A6] = 1                                     # the kernal's PAL flag
    for f in glob.glob(os.path.join(ROOT, "build", "obj", "*.p")) + glob.glob(os.path.join(ROOT, "games", "*.p")):
        m.drive.files[os.path.basename(f)[:-2].upper().encode()] = open(f, "rb").read()
    for f in ("zx64mon", "zx64mon2", "zx81"):
        m.drive.files[f.upper().encode()] = open(os.path.join(ROOT, "build", "obj", f + ".prg"), "rb").read()
    return m


def load(m, name, frames):
    try:
        m.type("J SHIFT+P " + " ".join(name) + " SHIFT+P NEWLINE")
    except AssertionError:
        pass                                             # it runs as it loads
    m.run(frames)


def key(m, k, frames=200):
    m.keys = {S.C64KEY[S.ZXKEY[k]]}
    m.run(6)
    m.keys = set()
    m.run(frames)


def f2(m, times):
    for _ in range(times):
        m.keys = {S.C64NAMES["LSHIFT"], S.C64NAMES["F1"]}
        m.run(4)
        m.keys = set()
        m.run(10)
    m.run(120)                                           # the scheme's name gone


def mon(m, *lines):
    for line in lines:
        m.mtype(line + "\r", settle=60)


def sc_bar():
    """LOAD "MAZOGS": the top row as the bar fills, as a GIF (needs ffmpeg)."""
    import shutil
    import subprocess
    import tempfile
    m = machine()
    m.boot()
    tmp = tempfile.mkdtemp()
    n = [0]

    def at(mm):
        n[0] += 1
        if n[0] % 2 == 0:
            draw(lambda a: mm.ram[a], os.path.join(tmp, f"f{n[0] // 2:04d}.png"), ROM, scale=3, row=0)
    m.on_6510 = at
    load(m, "MAZOGS", 10)
    out = os.path.join(OUT, "loading-bar.gif")
    subprocess.run(["ffmpeg", "-v", "error", "-y", "-framerate", "12", "-i", os.path.join(tmp, "f%04d.png"),
                    "-vf", "split[a][b];[a]palettegen=max_colors=4[p];[b][p]paletteuse", "-loop", "0", out],
                   check=True)
    shutil.rmtree(tmp)
    print("wrote", os.path.relpath(out, ROOT))


def sc_games():
    """3D Monster Maze in green; 1K ZX Chess; Fungaloids in amber."""
    m = machine()
    m.boot()
    f2(m, 2)
    load(m, "MONSTERMAZE", 300)
    key(m, "NEWLINE", 400)
    shot(m, "monstermaze")
    m = machine()
    m.boot()
    load(m, "1KCHESS", 300)
    shot(m, "1kchess")
    m = machine()
    m.boot()
    f2(m, 3)
    load(m, "FUNGALOIDS", 300)
    shot(m, "fungaloids")


def sc_monitor():
    """The monitor: F5 in Mazogs; the ROM's start and its patched INT."""
    for wait in range(300, 340, 3):                      # F5 when it stops the game in its
        m = machine()                                    # own code, not in the ROM's
        m.boot()
        load(m, "MAZOGS", wait)
        m.tap("F5")
        m.run(60)
        pc = m.mscreen()[2][1:5]
        if int(pc, 16) >= 0x4000:
            break
    mon(m, f"D {pc}")
    shot(m, "mon-mazogs")
    mon(m, "D 0000 0008", "D 0038 003A", "D 0277 027D")
    shot(m, "mon-rom")


def in_monitor():
    """A fresh zx64, F5 pressed at the K cursor."""
    m = machine()
    m.boot()
    m.run(5)
    m.tap("F5")
    m.run(60)
    return m


def clear(m):
    """SHIFT+CLR HOME: the monitor's screen cleared, for a shot of one example."""
    m.mkey("LSHIFT", "HOME")
    m.run(20)


def hello(m):
    """The manual's hello world: Z 17 makes the REM; A assembles, : the
    text (WORLD with RVS ON)."""
    mon(m, "Z 17", "A 4082 LD HL,$408D", "LD A,(HL)", "INC A", "RET Z", "DEC A", "RST $10", "INC HL",
        "JR $4085", "")
    m.mtype(":408D 'HELLO ")
    m.mkey("CTRL", "9")
    m.mtype("WORLD")
    m.mkey("CTRL", "0")
    m.mtype("' FF\r", settle=60)


def sc_asm():
    """Hello world in a REM; LIST; RUN; M."""
    m = in_monitor()
    hello(m)
    shot(m, "asm")
    mon(m, "X")
    m.run(30)
    S.enter(m, "K")                                                 # LIST
    shot(m, "rem")
    S.enter(m, "R")                                                 # RUN
    m.tap("F5")
    m.run(60)
    mon(m, "M 4082 4099")
    shot(m, "mon-m")


def sc_patch():
    """H finds PRINT in the ROM's keyword table; : makes it WRITE; F7 notices."""
    m = machine()
    m.boot()
    m.type("1 0 P SHIFT+P H E L L O SHIFT+P NEWLINE")              # 10 PRINT "HELLO"
    m.run(5)
    m.tap("F5")
    m.run(60)
    mon(m, "H 0000 1FFF 'PRIN", "M 01C0 01C7", ":01C3 3C 37 2E 39 AA", "M 01C0 01C7")
    shot(m, "hunt")
    mon(m, "X")
    m.run(30)
    S.enter(m, "K")                                                 # LIST
    shot(m, "write")
    m.tap("F7")
    m.until(lambda: m.cursor() and m.ready(), 900, "K after F7")


def sc_break():
    """A breakpoint on hello world's RST $10: RUN stops there with A an H,
    G stops there again with A an E."""
    m = in_monitor()
    hello(m)
    m.mtype("\r", settle=30)                                        # the offered : line ended
    clear(m)
    mon(m, "B 4089", "X")
    m.run(30)
    try:
        S.enter(m, "R")                                             # RUN, which stops at once
    except AssertionError:
        pass
    m.run(60)
    mon(m, "G")
    shot(m, "break")


def sc_regs():
    """ADD HL,DE at 7000; R; PC, DE and HL typed over on its ; line; S: HL 5555."""
    m = in_monitor()
    clear(m)
    mon(m, "A 7000 ADD HL,DE", "", "R")
    for _ in range(3):                                              # up to the ; line
        m.mkey("RSHIFT", "CRSRDOWN")
    m.mtype("7000")                                                 # over PC
    for _ in range(11):
        m.mkey("CRSRRIGHT")
    m.mtype("4321")                                                 # over DE
    m.mkey("CRSRRIGHT")
    m.mtype("1234\r", settle=60)                                    # over HL
    for _ in range(2):                                              # down to the prompt
        m.mkey("CRSRDOWN")
    m.mkey("CRSRRIGHT")
    mon(m, "S")
    shot(m, "regs")


def sc_text():
    """: with text over two lines, M shows it, H finds it."""
    m = in_monitor()
    clear(m)
    mon(m, ":7000 'THE QUICK BROWN FOX JUMPS", " OVER THE LAZY DOG' FF", "", "M 7000 702F", "H 7000 7FFF 'LAZY")
    shot(m, "text")


def sc_disk():
    """The disk commands: W and L, the program and a range; @ a command and the status."""
    m = in_monitor()
    hello(m)
    m.mtype("\r", settle=30)                                        # the offered : line ended
    clear(m)
    mon(m, 'W "HELLO"', 'L "HELLO"', 'W "ROM" 0000 1FFF', 'L "ROM" 8000', "@S:ROM", "@")
    shot(m, "disk")


def sc_speed():
    """SPEED's report: the setup, and an empty loop timed."""
    m = machine()
    m.boot()
    load(m, "SPEED", 2000)
    shot(m, "speed")


def rgbi(c):
    """A VDC colour (RGBI, 0-15) as an RGB triple, as a CGA monitor shows it
    (dark yellow as brown)."""
    if c == 12:
        return (0xAA, 0x55, 0x00)
    i = 0x55 if c & 1 else 0
    return tuple((0xAA if c & bit else 0) + i for bit in (8, 4, 2))


def draw_vdc(m, path, margin=16):
    """The VDC's 80x25 text screen as its RAM and registers have it (R12/R13
    the characters, R20/R21 the attributes, R28 the character sets, 16 bytes
    a glyph, attribute bit 7 the second set, bit 6 reverse, R26 the
    background), each line drawn twice for the screen's shape, with a margin
    in the background's colour."""
    v, ram = m.vdc, m.vram
    n = len(ram)
    scr, att, cs = v[12] << 8 | v[13], v[20] << 8 | v[21], (v[28] & 0xE0) << 8
    bg = rgbi(v[26] & 15)
    img = []
    for y in range(-margin, 200 + margin):
        line = []
        for x in range(-margin, 640 + margin):
            px = bg
            if 0 <= y < 200 and 0 <= x < 640:
                i = (y >> 3) * 80 + (x >> 3)
                code, a = ram[(scr + i) % n], ram[(att + i) % n]
                bits = ram[(cs + (0x1000 if a & 0x80 else 0) + code * 16 + (y & 7)) % n]
                if a & 0x40:
                    bits ^= 0xFF
                if bits & 0x80 >> (x & 7):
                    px = rgbi(a & 15)
            line.extend(px)
        img += [bytes(line)] * 2
    png(path, 640 + 2 * margin, 2 * (200 + 2 * margin), img)
    print("wrote", os.path.relpath(path, ROOT))


def mazogs128(sim128, m, wait):
    """Mazogs loaded into a booted C128 build, run for wait frames."""
    sim128.load_p(m, open(os.path.join(ROOT, "games", "mazogs.p"), "rb").read())
    m.frames(wait)


def sc_zx128():
    """zx128: HELLO ZX81 printed till the screen is full. (The monitor
    beside Mazogs is a photo now, mon128.jpg.)"""
    import sim128
    m = sim128.zx128()                                   # a program of the reader's own
    m.type("1 0 P SHIFT+P H E L L O SPACE Z X 8 1 SHIFT+P NEWLINE 2 0 G 1 0 NEWLINE R NEWLINE")
    m.frames(150)
    draw_vdc(m, os.path.join(OUT, "shot-zx128-hello.png"))


def sc_zx128vic():
    """zx128vic: the monitor in the C128's colours, V after F5 in Mazogs.
    (The model has no character ROM: the C64's stands in for the C128's
    upper case and graphics, copied to $D000 for the monitor.)"""
    import sim128
    saved = sim128.PRG, sim128.LBL, sim128.sym8502
    import sim128vic                                     # (points sim128's helpers at zx128vic's build)
    try:
        m = sim128vic.zx128vic()
        mazogs128(sim128, m, 300)
        sim128.fkey(m, "F5")
        m.frames(60)
        sim128.mon_type(m, "V\r", settle=60)
    finally:
        sim128.PRG, sim128.LBL, sim128.sym8502 = saved

    def io(a):
        if a == 0xDD00:
            return (m.cia2[0] & m.cia2[2] | ~m.cia2[2]) & 3
        if 0xD800 <= a < 0xDC00:
            return m.colour[a - 0xD800]
        return m.vic[a - 0xD000]
    bank = m.bank1 if m.mmu[6] & 0x40 else m.bank0
    draw(lambda a: ROM[a - 0xD000] if 0xD000 <= a < 0xD800 else bank[a],
         os.path.join(OUT, "shot-zx128vic-mon.png"), ROM, io=io)


SCENES = {k[3:]: v for k, v in dict(globals()).items() if k.startswith("sc_")}


def main():
    global ROM
    ROM = chargen()
    for name in sys.argv[1:] or SCENES:
        SCENES[name]()


if __name__ == "__main__":
    main()
