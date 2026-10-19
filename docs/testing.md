# Testing

Hardware: C64 Reloaded MK2, DL2DW's replica cartridge with the `/INT`
wire, SD2IEC. Emulator: VICE (`x64sc -cpmcart`, 3.7.1 and 3.10).

## make test

`tools/simulate.py` runs the patched ROM and zx64 on a Z80 emulator and
the 6510 loader on a 6502 emulator, switching as the cartridge does,
with a fake VIC, CIA, colour RAM, kernal and drive. It types and reads
the screen. 116 checks, with and without `/INT`, covering:

- boot, typing, type-ahead and F1 (TEST typed fast: no ghost F), the
  cursor keys, F2/F3/F5/F7; no cartridge: a message and back to BASIC
- F7 after the ROM was written over: read again from the boot file; a
  plain F7 doesn't touch the disk
- `SAVE`/`LOAD`/`RUN`, `NAME.P`, report D (missing file, write-protected
  disk), report 4 (too big), junk after a program, a stray `$DE00` write
- `FAST`/`SLOW`, `FRAMES`, the collapsed 1K display, 16K/32K/1K
- without `/INT`: polling the raster flag, also after `USR 8192` calls the
  IRQ handler; with it, never falling back
- `IN A,($FE)`: the rows where games read them; no `IN`/`OUT` by zx64
- interrupt cost: ~1,200 T-states idle, ~7,200 with a key, ~13,900 with
  the picture copy (a PAL frame is 39,312)
- the test programs (`SPEED`, `PAUSE`, `MEM`, `FAST`: the picture
  held, `FRAMES` still, SPACE and RUN/STOP breaking a FAST loop)
- the monitor: every command (`=` in all three bases, and `?` past
  $FFFF); D over 123 instructions and the whole ROM;
  A assembling everything D shows; S's next-PC for 16 kinds of branch;
  breakpoints with and without `/INT`; the disk commands
- pcheck on a program made to trip each warning
- the loading bar and spinner, the version banner

The hardware's glitches are modelled, and each fix failed without it:

- CIA1: one wrong keyboard read (`$D0`) in 211
- colour RAM: one wrong read in 97
- `$D019`: the raster flag reads as set on the line after a bad line
- `$D011`: bit 7 reads as raster bit 8
- the keyboard matrix: no diodes, so three keys down at the corners of
  a rectangle make the fourth read as down

## On hardware

Done (2026-10-13 to 2026-10-16):

- [x] Boot from the SD2IEC, typing, type-ahead, F1/F2/F3/F7, the top-row
      messages
- [x] Without `/INT`: picture only in the key wait (the replica doesn't
      wire it). With it: SLOW mode runs, `PAUSE 500` = 10.04 s, no stray
      IRQs
- [x] `SPEED`: 50 loops in 30 frames (~1.8 T-states per C64 cycle); a UK
      ZX81 takes 56-58 (58 every time on 2026-10-16, with a ZXpand+,
      whose ROM SPEED also recognises as a real ZX81's)
- [x] `MEM` in 16K and 32K; 32K `DIM A(4000)` saved and loaded back
- [x] `LOAD "MAZOGS"` plays through; `LOAD "BOULDERL"` with redefined
      keys; SPACE is BREAK; report D for a missing file
- [x] The loading bar and spinner, `SAVE` and `LOAD`
- [x] The monitor: M, D, A, R, G/X, B/S, `$`, L, W, `@`, in and out of
      Mazogs repeatedly
- [x] The LED mod (docs/cpm-cart.md)
- [x] Games: `tetris.p` (polls `LAST_K`), `tetris1k.p`, `mine81.p`, 3D
      Monster Maze, Fungaloids, 1K ZX Chess play; `tetrishr.p` (hi-res)
      refuses to start with a warning of its own; `aydemo.p` starts (no
      AY, so no sound)
- [x] No cartridge: the message, then `READY.`. With the wire, nothing
      changed by the `irqseen` fallback
- [x] `LOAD "FAST"`: the picture holds while it counts, comes back at
      SLOW, `FRAMES` 0; SPACE and RUN/STOP break the FAST loop (D/230)
- [x] `aydemo.p`, then F7: " LOADING ZX81 ROM", then the `K` cursor; a
      plain F7 is still instant
- [x] `LOAD "MAZOGS"` finding `MAZOGS.P` (renamed with the monitor's
      `@R:`); `SAVE` over an existing name
- [x] `SAVE` to a full disk (`@CD:` to a d64 with 0 blocks free): report D
- [x] Typing `TEST` fast: no ghost F, in the editor and the monitor
- [x] `rom/romdump.p` on a ZX81 with a ZXpand+: the dump (`ZX81ROM.P`)
      has the standard ROM's md5

Done after 1.0 (2026-10-18):

- [x] The monitor's `=` (base conversion)
- [x] An `M` line's characters changed and entered
- [x] Text with `:` and `'`, the offered next line
- [x] `L "NAME"` of a program in the monitor
- [x] Scrolling `M` and `D` listings with CRSR UP/DOWN at the screen's edges
- [x] A C64 reset with the monitor in RAM, then zx64 and F5: the monitor
      loaded again, on a clear screen
- [x] CRSR DOWN under a short listing: the rows to the bottom filled, the
      cursor staying there; a `D` then an `M` listing scroll up and down
      each from its own edge
- [x] RETURN on an `M` line: the line drawn again (then, a changed
      character over an inverse one stayed inverse; no longer so)

Not yet tried there:

- [ ] The manual's hello world, both ways, and its breakpoint on `RST $10`
- [ ] `W "HELLO"` in the monitor, `X` to BASIC after `L`; `L` and `LOAD`
      of a PRG of code: refused
- [ ] RVS ON (CTRL+9) and OFF (CTRL+0) in the monitor; an `M` line's
      characters stored as they show, reversed or not; `:` text with RVS ON
- [ ] `Z 10` with no program, `Z 17` growing it, the hello world with an
      inverse `WORLD`; `Z` before a program without a line 1; `X` after `Z`
- [ ] CTRL+HOME in the monitor: the bottom row

## pcheck on real programs

Checked against source or a disassembly (2026-10-14):

- `BoulderL.p`: 22 keyboard `IN`s, rows from its key table; nothing zx64
  can't do. `DB`/`D3` bytes in its data aren't counted as code
- `mazogs.p`: no `IN`/`OUT`; `USR 8192` (its ZXpand SAVE)
- programs for the ZXpand and an AY chip (from the author's zedwire
  project): their ports (`$07`, `$17`; `$CF`, `$0F`), with where each
  write lands
- sz81's `tetrishr.p`: `LD I,A` (hi-res); `aydemo.p`: the AY port and two
  `OUT`s with A unknown. `tetris.p`, `tetris1k.p`, `mine81.p`, Monster
  Maze: clean. 1K ZX Chess (`RAND USR X`) and Fungaloids (code built at
  run time) can't be followed

## After a hang

The MK2's USB serial link (19200 8N1) has a debug menu that reads
memory; use `build/zx64.lbl` and `build/zx64mon.lbl` (Z80 address +
`$1000`). A read halts the C64 and may not resume, so only after a hang,
and power-cycle afterwards. Or reset (not power off) and `PEEK` from
C64 BASIC.
