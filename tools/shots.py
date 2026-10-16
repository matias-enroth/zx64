#!/usr/bin/env python3
"""Screenshots for the docs, from make test's emulators.

    .venv/bin/python tools/shots.py [scene ...]

Runs zx64 in tools/simulate.py's machine, types what each scene needs and
draws the VIC's screen as it is in memory (its own character set, or the
C64's character ROM for the monitor) into docs/img/shot-*.png, and the
loading bar into docs/img/loading-bar.gif. Needs a build (make), the C64
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


def draw(peek, path, rom, scale=2, row=None):
    """The VIC's text screen as peek(C64 address) shows it; with row, only
    that character row of the ZX81's 32 columns, and a margin."""
    d011, d018 = peek(0xD011), peek(0xD018)
    bank = (3 - (peek(0xDD00) & 3)) * 0x4000
    screen = bank + (d018 >> 4) * 0x400
    chars = bank + ((d018 >> 1) & 7) * 0x800
    from_rom = bank in (0, 0x8000) and 0x1000 <= chars - bank < 0x2000
    glyph = (lambda c, y: rom[(chars - bank - 0x1000) + c * 8 + y]) if from_rom else \
        (lambda c, y: peek(chars + c * 8 + y))
    rows = 25 if d011 & 8 else 24
    top = BORDER_Y + (d011 & 7) - 3            # where character row 0 starts
    win0, win1 = (BORDER_Y, BORDER_Y + 200) if rows == 25 else (BORDER_Y + 4, BORDER_Y + 196)
    border, back = PALETTE[peek(0xD020) & 15], PALETTE[peek(0xD021) & 15]
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
                        px = PALETTE[peek(0xD800 + cy * 40 + cx) & 15]
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
            if cpu.pc in S.KERNAL:
                getattr(self, "k_" + S.KERNAL[cpu.pc])()
                lo = self.ram[0x100 + ((cpu.sp + 1) & 0xFF)]
                hi = self.ram[0x100 + ((cpu.sp + 2) & 0xFF)]
                cpu.sp = (cpu.sp + 2) & 0xFF
                cpu.pc = ((hi << 8) | lo) + 1
            else:
                cpu.step()
        raise AssertionError("the 6510 never handed back")


ROM = None


def shot(m, name):
    """The screen as the Z80 sees it (C64 address - $1000)."""
    draw(lambda a: m.z.memory[(a - 0x1000) & 0xFFFF], os.path.join(OUT, f"shot-{name}.png"), ROM)


def machine():
    m = Shot(int_wired=True)
    m.ram[0x02A6] = 1                                     # the kernal's PAL flag
    for f in glob.glob(os.path.join(ROOT, "build", "*.p")) + glob.glob(os.path.join(ROOT, "games", "*.p")):
        m.drive.files[os.path.basename(f)[:-2].upper().encode()] = open(f, "rb").read()
    for f in ("zx64mon", "zx64mon2", "zx81"):
        m.drive.files[f.upper().encode()] = open(os.path.join(ROOT, "build", f + ".prg"), "rb").read()
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
    m = machine()
    m.boot()
    load(m, "MAZOGS", 300)
    m.tap("F5")
    m.run(60)
    pc = m.mscreen()[2][1:5]
    mon(m, f"D {pc}")
    shot(m, "mon-mazogs")
    mon(m, "D 0000 0008", "D 0038 003A", "D 0277 027D")
    shot(m, "mon-rom")


def sc_asm():
    """1 REM with room for code; A assembles; RUN; M and PEEK."""
    m = machine()
    m.boot()
    m.type("1 E " + " ".join("012345678901234567890123") + " NEWLINE")
    m.type("1 0 P SHIFT+NEWLINE L 1 6 5 1 4 NEWLINE")              # 10 PRINT USR 16514
    m.type("2 0 P SHIFT+NEWLINE O 1 6 5 3 4 SHIFT+K 2 5 6 SHIFT+B "
           "SHIFT+NEWLINE O 1 6 5 3 5 NEWLINE")                      # 20 PRINT PEEK ...
    m.run(5)
    m.tap("F5")
    m.run(60)
    mon(m, "A 4082 LD HL,$0000", "LD B,$64", "LD E,B", "LD D,$00", "ADD HL,DE", "DJNZ $4087",
        "LD ($4096),HL", "LD B,H", "LD C,L", "RET", "")
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
SCENES = {k[3:]: v for k, v in dict(globals()).items() if k.startswith("sc_")}


def main():
    global ROM
    ROM = chargen()
    for name in sys.argv[1:] or SCENES:
        SCENES[name]()


if __name__ == "__main__":
    main()
