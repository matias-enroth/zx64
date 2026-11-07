# jtest: does my drive speak JiffyDOS, and how fast?

A C64 program that asks the drive for JiffyDOS, the fast serial protocol
of JiffyDOS ROMs and of the SD2IEC, and reads the same files three ways:
by the kernal, by its own JiffyDOS reader with the screen on, and by the
same reader with the screen off. Each read shows its bytes, its time,
the bytes a second and a checksum, so you see at once whether the drive
answered, whether every byte came through, and how much faster it was.
No JiffyDOS ROM is needed in the C64: the reader is in the program.

## Running it

jtest reads three files from the disk it's on: `ZX64`, `ZX64MON` and
`ZX64MON2`, about 14K, 4K and 4K. Put them beside it (any files under
those names will do), then on a C64:

    LOAD "JTEST",8
    RUN

Each file is read three times, and each read gets a line:

| | |
|---|---|
| `k` | the kernal: `OPEN`, `CHKIN`, `CHRIN` |
| `j7` | jtest's JiffyDOS reader, the screen on (y-scroll 7) |
| `j-` | the same, the screen off: no bad lines at all |

"ok" means the same bytes and checksum as the kernal's read. "jiffy no"
means the drive didn't answer, and the `j` reads went through the
kernal after all.

## How it reads

The protocol, worked out from sd2iec's and SJLOAD's source (read, not
copied):

- **Asking:** jtest sends its own TALK, with a short pause before the
  last bit. A JiffyDOS drive notices the pause, answers with a short
  pulse on DATA, and talks JiffyDOS until the next ATN.
- **A byte:** the drive puts it on CLK and DATA two bits at a time, then
  marks whether more are coming. jtest says it got it, and the next one
  follows.

The reads are timed to the cycle, so no bad line may fall among them:
jtest starts a byte only on raster lines that leave room.

## Seen working

- A C64 Reloaded MK2 with an SD2IEC: "jiffy yes", every read ok, about
  seven times as fast as the kernal; the same with the screen off.
- VICE with a 1541: "jiffy no", the kernal's reads ok.

## Building

With [ACME](https://sourceforge.net/projects/acme-crossass/), from the
repository's top (the reader is `c64/jcore.asm`):

    acme -f cbm -I c64 -o jtest.prg extras/jtest/jtest.asm

or `make jtest`, which writes `build/jtest.prg`.

## About

jtest tries the fast loader of [zx64](../../README.md), a ZX81 on the
C64's CP/M cartridge, with zx64's own reader: hence the file names. MIT licence, see [LICENSE](../../LICENSE).
