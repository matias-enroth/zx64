# memtest128: a C128 memory test for the VDC's RAM and the REU

A memory test for the two kinds of RAM a Commodore 128 has beyond its
own 128K: the 80-column chip's video RAM (the VDC, 16K or 64K) and a RAM
Expansion Unit (a 1700, 1750 or 1764, or an Ultimate's REU, up to 16
MB). It finds their sizes, then tests them pass after pass, and shows
every bad byte's address, what was written and what came back.

## Running it

Load `memtest128.d64` in C128 mode and:

    RUN"MEMTEST128"

It runs until you hold any key; then it stops at the next safe point,
puts both screens back and returns to `READY.`. The 40-column screen
shows the test all the time. The 80-column screen shows the same, except
while the VDC is being tested, when it shows the test patterns.

What you see:

- the pass, and the time since the start (CIA 1's clock)
- **errors**, for the VDC and the REU, each with the first and the last
  bad byte: its address, what was written, what came back. `$BB:PPOO`
  is an REU address: bank, page, offset
- **reu compare failed, data ok**: the REU's own compare said
  "different", but the bytes fetched were right. It should stay 0;
  anything else points at the REU's verify, not at its RAM
- **vdc not ready (2 ms)**: how often the VDC didn't answer within 2 ms.
  It should stay 0
- **passes with errors**, and the last pass's result

## What it does

The sizes, once at the start:

- **The VDC:** a tag in every page of its memory, written from the top
  down and read back from the bottom up. A 16K chip can't keep them
  all, so a tag goes missing. A 64K chip is tested in its 64K mode, and
  put back in the 16K mode the kernal leaves it in.
- **The REU:** a marker at the start of every bank, read back the same
  way: where they repeat is the size. "not found": no REU. "bank 0
  fails": an REU, but no RAM behind it.

Each pass:

1. **The VDC:** all of its RAM written and read back twice, a pattern
   and then its complement. The character set is put back afterwards.
2. **The REU**, twice, a pattern and then its complement, the pattern
   changing every pass:
   - **write** every 64K bank by DMA
   - **verify** every bank with the REU's own compare; a block that
     fails is fetched and compared byte by byte, so the bad bytes are
     counted and shown
   - **fetch** one bank, a different one each time, and compare it with
     the CPU, to test the other direction too

Every 256-byte page starts with its bank and page number, so address
faults, banks or pages that answer twice, show up as errors.

The REU's DMA sets the pace: a pass takes about two minutes with a 16 MB
REU, and a few seconds with 512K.

## Seen working

- VICE `x128` 3.10: no REU, 128K, 512K and 16 MB; a 16K and a 64K VDC
  (`-VDC16KB`, `-VDC64KB`). No errors from the normal build; the planted
  ones (below) found at the right addresses.
- A flat PAL C128 with the VDC's 64K mod and an Ultimate-II+'s 16 MB REU:
  "vdc 64k", "reu 16384k", passes without errors, no "reu compare
  failed, data ok", no "vdc not ready".

## Building

With [ACME](https://sourceforge.net/projects/acme-crossass/) and VICE's
`c1541`:

    acme -f cbm -o memtest128.prg memtest128.asm
    c1541 -format "memtest128,mt" d64 memtest128.d64 -write memtest128.prg memtest128

`-DFAULT=1` builds a version that plants one bad byte in the VDC
(`$1234`) and one in the REU (bank 1, `$4123`) every round, to see that
errors are found. From the repository's top, `make memtest128` builds
both, as `build/memtest128.d64` and `build/memtest128f.d64`.

## On a C128 nobody sits at

With an Ultimate-II+ and [ultimate.py](../ultimate/):

    extras/ultimate/ultimate.py mount build/memtest128.d64
    extras/ultimate/ultimate.py type 'RUN"MEMTEST128"\n'

`extras/ultimate/ultimate.py readmem 0400 1000` then reads the 40-column
screen (as screen codes). memtest128 runs on the 8502, so the
Ultimate's DMA doesn't disturb it.

## About

memtest128 is part of [zx64](../../README.md), a ZX81 on the C64's
CP/M cartridge and on the C128's own Z80. MIT licence, see [LICENSE](../../LICENSE).
