# Testing

Cartridge: DL2DW's replica with the `/INT` wire. Drive: SD2IEC.
Emulator: VICE (`x64sc -cpmcart`, 3.7.1 and 3.10).

| C64 | Result |
|---|---|
| C64 Reloaded MK2 | works: everything below |
| C64 Reloaded (the first) | crashes seconds after the Z80 starts |
| Breadbin #1, 250407 rev B | crashes after a few minutes, in Mazogs (CP/M too) |

## make test

`tools/simulate.py` runs the patched ROM and zx64 on a Z80 emulator and
the 6510 loader on a 6502 emulator, switching as the cartridge does,
with a fake VIC, CIA, colour RAM, kernal and drive (and a JiffyDOS
drive on the serial bus, timed to the cycle). It types and reads the
screen. It needs the z80 and py65 packages (`python3 -m venv .venv &&
.venv/bin/pip install z80 py65`). 169 checks, with and without `/INT`,
covering:

- boot, typing, type-ahead and F1 (TEST typed fast: no ghost F; a key
  down while DEL or a cursor key is still down: no SHIFT from them), the
  cursor keys, F2/F3/F5/F7/F8 (F8 in a FAST program too, SHIFT+F5 the
  monitor as F5); no cartridge: a message and back to BASIC
- the boot file (`ZX81`, a stub): `ZX64` and both monitor files by
  JiffyDOS, so F5 needs no disk; on a plain drive `ZX64` the kernal's
  way, the monitor left for F5; no `ZX64`: said, back to BASIC; no
  monitor on the disk: zx64 starts all the same
- F7 after the ROM was written over: read again from `ZX64`, the
  charset made again from it, a second F7 no disk access (in 1K too,
  where the Z80's stack is in the first buffer); no `ZX64`, or
  another build's: the ROM left as it was, said on the top row; zx64's
  own copy of the sum changed: said too; a plain F7 doesn't touch the
  disk
- JiffyDOS: the reader in place after the boot; a JiffyDOS drive says
  yes and every byte comes as sent, the last marked, each clear of the
  bad lines; a plain drive or none: no. `LOAD` (NAME.P, a missing file),
  F7's ROM, F5's monitor, and the monitor's L (on its own screen: the VIC
  bank kept, the guard on y-scroll 3) and `$` by JiffyDOS; everything
  else in this list with a plain drive, the kernal's way
- `SAVE`/`LOAD`/`RUN`, `NAME.P`, every ZX81 character in a file name,
  report D (missing file, write-protected disk), report 4 (too big), junk
  after a program, a stray `$DE00` write
- `FAST`/`SLOW`, `FRAMES`, the collapsed 1K display, 16K/32K/1K
- without `/INT`: polling the raster flag, also after `USR 8192` calls the
  IRQ handler; with it, never falling back
- `IN A,($FE)`: the rows where games read them; no `IN`/`OUT` by zx64
- the joystick:
  - each direction as its key; a diagonal (`INKEY$` gets the newest,
    `IN A,($FE)` both); held in the editor (one key); a diagonal onto,
    or let go from, a direction the layout leaves out
  - F3 switching: no SHIFT for the program, not the monitor (in BREAK-1
    neither, nor coming again while held), not stopping it, kept by F7
    and F8
  - the stick held with F1, or with a key in its column, up diagonals
    too: no ghost F-key or reset, no BREAK, also with the key let go
    between BREAK-1's reads
  - hold F3: the program frozen, keys taught, a cursor key, SHIFT alone,
    F1 none, F5 giving up, F7 and the stick ignored, nothing left for
    the program or the edit line; without `/INT`, F5 in a running
    program more than once
- interrupt cost: ~1,200 T-states idle, ~7,400 with a key, ~5,400 with
  the stick held, ~14,100 with the picture copy (a PAL frame is 39,312
  at 2 T-states a cycle)
- the test programs (`SPEED`, `PAUSE`, `MEM`, `FAST`: the picture
  held, `FRAMES` still, SPACE and RUN/STOP breaking a FAST loop)
- the monitor: every command (`=` in all three bases, and `?` past
  $FFFF); D over 123 instructions and the whole ROM;
  A assembling everything D shows; S's next-PC for 16 kinds of branch;
  breakpoints with and without `/INT`; the disk commands; RETURN on
  the `#` title and headings (nothing), SHIFT+RETURN (the next line)
- pcheck on a program made to trip each warning
- the loading bar and spinner, the version banner

The hardware's glitches are modelled, and each fix failed without it:

- CIA1: one wrong keyboard or joystick read (`$D0`) in 211
- port 2: the stick's lines are the keyboard's column lines
- colour RAM: one wrong read in 97
- `$D019`: the raster flag reads as set on the line after a bad line
- `$D011`: bit 7 reads as raster bit 8
- the keyboard matrix: no diodes, so three keys down at the corners of
  a rectangle make the fourth read as down

## On hardware

Seen on the C64 with 1.0:

- [x] Boot from the SD2IEC, typing, type-ahead, F1/F2/F3/F7 (F3 then the
      memory size), the top-row messages
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

Seen on the C64 with 1.1:

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
- [x] RETURN on an `M` line: the line drawn again

- [x] An `M` line's characters stored as they show, reversed or not
- [x] RVS ON (CTRL+9) and OFF (CTRL+0) in the monitor
- [x] `Z`: line 1's `REM` made and resized
- [x] CTRL+HOME in the monitor: the bottom row

- [x] `W "HELLO"` in the monitor, `X` to BASIC after `L`; `L` and `LOAD`
      of a PRG of code: refused
- [x] The hello world with `Z 17` and an inverse `WORLD`; `Z` before a
      program without a line 1
- [x] The manual's hello world, both ways, and its breakpoint on `RST $10`
- [x] `A 7000` alone: `.A 7000` offered; a `D` line changed to an
      instruction of another length: the next address offered
- [x] The joystick (a Hyperkin pad) in port 2: BoulderL played with it,
      smoothly
- [x] Hold F6 (now F3) in Mazogs: its own keys taught, it carries on,
      playable

- [x] F6 (now F3) switching 5678+0 and the taught keys, with the stick
      held too; F7 and F3 (now F8) keep the layout
- [x] Fire held and `0` pressed, right and `8`: no reset
- [x] Mazogs with the keyboard and the stick: no freezes seen any more
- [x] A diagonal in Mazogs where the newer direction is open: it turns
- [x] `G`, DEL, `G` typed fast (each down before the last is up): `G`,
      not `LLIST`; the same with a cursor key
- [x] `@CD:` to a folder or d64 without `ZX81`, then `aydemo.p` and F7:
      `ROM NOT RELOADED: NO ZX81` on the top row, the `K` cursor (the ROM
      was then read from `ZX81`; now `ZX64`, `NO ZX64`)
- [x] `aydemo.p`, then F7: the ROM and the charset read again, the `K`
      cursor; a second F7 no disk access
- [x] `jtest` with its own copy of the JiffyDOS protocol on the SD2IEC:
      "jiffy yes", every read the same as the kernal's, 3,395 B/s
      against 492 (6.9x); the same with zx64's y-scroll and the screen
      off
- [x] By JiffyDOS on the SD2IEC: `LOAD "MAZOGS"` in about 4.5 s
      (27 s the kernal's way; the game plays), a missing file (report D
      in under a second, NAME.P tried too; the bar shows briefly, the
      SD2IEC's LED blinks, `@` says `62,FILE NOT FOUND`), a name found
      only as NAME.P (`tetris1k` renamed `tetris1k.p`), F5's monitor, the
      monitor's `W` then `L` (its screen kept) and `$`, F7 after
      `aydemo.p` (the ROM by JiffyDOS)
- [x] `jtest` with zx64's reader (c64/jcore.asm): "jiffy yes", every
      read ok, 3,402 B/s for zx81 (now `ZX64`: 14,156 bytes in 4.16 s,
      28.77 s the kernal's way), the same with zx64's y-scroll and the
      screen off. In VICE with a 1541: "jiffy no", the kernal's reads ok
- [x] The boot file, a stub: from `RUN`, 7 s to the Z80's LED (`ZX64`
      and both monitor files by JiffyDOS), 10 s to the `K` cursor (the
      rest is the ROM's own start, 2.8 s in the simulator too; about
      31 s before). F5 at once, no disk; `aydemo.p` and F7 read the ROM
      from `ZX64`. A disk with `ZX81` but no `ZX64`: "ZX64 NOT LOADED".
      In VICE with a 1541: `ZX64` the kernal's way, the `K` cursor, the
      monitor not loaded
- [x] With time-outs in the JiffyDOS TALK and the boot file's load
      bounded: the boot and `LOAD` as before
- [x] The F-keys moved: F3 the joystick (a tap switches, held a second
      teaches), F8 (SHIFT+F7) the memory size, SHIFT+F5 the monitor as F5;
      F7 alone still a reset
- [x] The manual's monitor examples: `ADD HL,DE` set up on the `;` line
      and stepped with `S` (HL `5555`), and `:C020 02` (a red border)

Not yet tried there:

- [ ] The boot from the 1571 (no JiffyDOS): `ZX64` the kernal's way, F5
      loading the monitor; `LOAD` and F7 as before

## pcheck on real programs

Checked against source or a disassembly:

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
memory; use `build/obj/zx64.lbl` and `build/obj/zx64mon.lbl` (Z80
address + `$1000`). A read halts the C64 and may not resume, so only after a hang,
and power-cycle afterwards. Or reset (not power off) and `PEEK` from
C64 BASIC.
