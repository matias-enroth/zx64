# Testing

zx64: DL2DW's cartridge replica with the `/INT` wire. Drive: SD2IEC.
Emulator: VICE (`x64sc -cpmcart`, 3.7.1 and 3.10).

zx128 and zx128vic: an Ultimate-II+ as the drive (a 1571, burst) and as
the cartridge for the function ROM; a real 1571 too. Emulator: VICE
(`x128`, 3.10).

| C64 | Result |
|---|---|
| C64 Reloaded MK2 | works: everything below |
| C64 Reloaded (the first) | crashes seconds after the Z80 starts |
| Breadbin #1, 250407 rev B | crashes after a few minutes, in Mazogs (CP/M too) |

| C128 | Result |
|---|---|
| Flat PAL C128, the VDC's 64K mod | zx128 and zx128vic work: everything below |

## make test

`make` and `make test` pass on macOS, on Fedora on a ThinkPad, and in
clean containers of Debian 13, Ubuntu 24.04 and Fedora 42.

A few C128 checks load games: `mazogs.p`, `BoulderL.p` and
`games/test/aydemo.p`. Without them those checks are skipped, and the
last line says so.

`tools/simulate.py` runs the patched ROM and zx64 on a Z80 emulator and
the 6510 loader on a 6502 emulator, switching as the cartridge does,
with a fake VIC, CIA, colour RAM, kernal and drive (and a JiffyDOS
drive on the serial bus, timed to the cycle). It types and reads the
screen. It needs the z80 and py65 packages (`python3 -m venv .venv &&
.venv/bin/pip install z80 py65`). 187 checks, with and without `/INT`,
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
- the quiet F5: the title once, then the screen as it was left, and the
  title again when the monitor was read from the disk again; the help;
  a monitor from another build refused
- the frame round the picture in the border's colour, in all six
  schemes, after F5, a `LOAD`, a `SAVE`, F7 and F8
- zx64's second code area: in place after the boot, a `LOAD` and F7;
  the monitor's deepest stack use 64 bytes clear of it
- typing fast with type-ahead: a queued key and an interrupt before the
  ROM reads it don't hang the editor
- pcheck on a program made to trip each warning
- the loading bar and spinner, the version banner

The hardware's glitches are modelled, and the check of each one's handling fails without it:

- CIA1: one wrong keyboard or joystick read (`$D0`) in 211
- port 2: the stick's lines are the keyboard's column lines
- colour RAM: one wrong read in 97
- `$D019`: the raster flag reads as set on the line after a bad line
- `$D011`: bit 7 reads as raster bit 8
- the keyboard matrix: no diodes, so three keys down at the corners of
  a rectangle make the fourth read as down

`tools/sim128.py` does the same for zx128: the ZX81 and zx128 on a Z80
emulator in RAM bank 1, the 8502's side on a 6502 emulator in bank 0,
taking turns through the MMU's `$D505`, with the top 8K common to both.
Around them: the VIC's raster interrupt, the keyboard with the C128's
extra columns, CIA 2's timers, a VDC with its 16K and its block fill and
copy, the C128 kernal's disk calls, and a function ROM. 110 checks:

- the model itself: the VDC's address counting, block operations and
  ready flag, the `IN` mirror, the CPU switch
- the boot: the K cursor, the system variables, the 40/80 key
- the keys: typing, the Y-P row, the keypad and cursor keys, keys held,
  a wrong CIA read, the LAST_K hold
- the picture: the fonts, typing, `PRINT AT`, `POKE`, the collapsed 1K
  display, FAST, the time it takes (quiet, busy, big redraws), the
  writes in the VDC's blank and what happens when the blank is missed
  or short, `CLS` and `SCROLL` by the VDC's block operations
- the panel: its text, the CPU row, F8, SLOW and FAST, messages, F2,
  the joystick, a repaint
- the disk: `LOAD` (PAL and NTSC), `SAVE` and back, a missing file, a
  file too big, the bar, F7 from the copy in memory and from the disk,
  the patches at `LOAD`, 32K, error statuses
- the monitor: F5's layout, the half picture redrawn after a command and
  each step, breakpoints, F5 in FAST, the cursor keys and keypad, the
  disk commands, the quiet F5, the help, `V`
- the function ROM: its header, the packed image, the unpacker's edge
  cases, ZX0 both ways, the boot from both sockets, CTRL's skip
- the room left in each part of memory

The VDC is modelled as measured on the C128: its frame of 19,674
cycles and its vertical blank of about 7 ms; outside the blank a data
access while it's busy is lost; block operations take their measured
time, and the checks count any access made while one runs. The Y-P
row's `IN` reads
I/O 2's open bus, as on the C128.

`tools/sim128vic.py` runs zx128vic in the same machine, with colour RAM
mapped in over the ROM's `$1000-$13FF` when the Z80 turns the I/O on. 41
checks: the boot, the colours (with an interrupt during F2), 32K stopping
below the VIC's screens, `SPEED` (PAL and NTSC), the 80-column screen's
note, the frame, the keys and the LAST_K hold, F7's fonts, the bar, the
monitor (F5, back, quiet, breakpoints, FAST, the disk, the cursor keys
and keypad, NTSC, `V`), and the function ROM.

`extras/ultimate/test_ultimate.py`: 24 tests of `ultimate.py` against a
stub of the Ultimate's REST API.

## On hardware

Seen on the C64:

- [x] Boot from the SD2IEC, typing, type-ahead, the top-row messages;
      F1, F2, F3 the joystick (a tap switches, held a second teaches),
      F7 a reset, F8 (SHIFT+F7) the memory size, SHIFT+F5 the monitor
      as F5
- [x] Power-on, then F2 through every scheme: the frame in each
- [x] Without `/INT`: picture only in the key wait (the replica doesn't
      wire it). With it: SLOW mode runs, `PAUSE 500` = 10.04 s, no stray
      IRQs
- [x] `SPEED`: PAL, `/INT SEEN: 1`, no stray IRQs; 50 loops in 33
      frames. A UK ZX81 takes 56-58 (58 on one with a ZXpand+, whose ROM
      `SPEED` also recognises as a real ZX81's)
- [x] `MEM` in 16K and 32K; 32K `DIM A(4000)` saved and loaded back
- [x] `LOAD "MAZOGS"` plays through; `LOAD "BOULDERL"` with redefined
      keys; SPACE is BREAK; report D for a missing file
- [x] The loading bar and spinner, `SAVE` and `LOAD`
- [x] A `LOAD`, then F7
- [x] Fast typing; typing `TEST` fast: no ghost F, in the editor and the
      monitor
- [x] The LED mod (docs/cpm-cart.md)
- [x] Games: `tetris.p` (polls `LAST_K`), `tetris1k.p`, `mine81.p`, 3D
      Monster Maze, Fungaloids, 1K ZX Chess play; `tetrishr.p` (hi-res)
      refuses to start with a warning of its own; `aydemo.p` starts (no
      AY, so no sound)
- [x] `.P` files with VERSN not 0: the disk's `INVASION` and `REDANTS`
      load and play
- [x] No cartridge: the message, then `READY.`. With the wire, the
      `irqseen` fallback stays out of the way
- [x] `LOAD "FAST"`: the picture holds while it counts, comes back at
      SLOW, `FRAMES` 0; SPACE and RUN/STOP break the FAST loop (D/230)
- [x] `LOAD "MAZOGS"` finding `MAZOGS.P` (renamed with the monitor's
      `@R:`); `SAVE` over an existing name
- [x] `SAVE` to a full disk (`@CD:` to a d64 with 0 blocks free): report D
- [x] `aydemo.p`, then F7: the ROM and the charset read again, the `K`
      cursor; a second F7 no disk access
- [x] F7 with another disk in the drive: `ROM NOT RELOADED: NO ZX64`
- [x] `rom/romdump.p` on a ZX81 with a ZXpand+: the dump (`ZX81ROM.P`)
      has the standard ROM's md5

The monitor:

- [x] M, D, A, R, G/X, B/S, `$`, L, W, `@`, in and out of Mazogs
      repeatedly
- [x] F5 twice: the second entry quiet; `?`
- [x] `=` (base conversion)
- [x] An `M` line's characters changed and entered, stored as they show,
      reversed or not; RETURN on an `M` line: the line drawn again
- [x] Text with `:` and `'`, the offered next line
- [x] `L "NAME"` of a program
- [x] Scrolling `M` and `D` listings with CRSR UP/DOWN at the screen's
      edges; CRSR DOWN under a short listing: the rows to the bottom
      filled, the cursor staying there; a `D` then an `M` listing scroll
      up and down each from its own edge
- [x] A C64 reset with the monitor in RAM, then zx64 and F5: the monitor
      loaded again, on a clear screen
- [x] RVS ON (CTRL+9) and OFF (CTRL+0); CTRL+HOME: the bottom row
- [x] `Z`: line 1's `REM` made and resized; `Z` before a program without
      a line 1
- [x] `W "HELLO"`, `X` to BASIC after `L`; `L` and `LOAD` of a PRG of
      code: refused
- [x] The hello world with `Z 17` and an inverse `WORLD`; the manual's
      hello world, both ways, and its breakpoint on `RST $10`
- [x] `A 7000` alone: `.A 7000` offered; a `D` line changed to an
      instruction of another length: the next address offered
- [x] The manual's examples: `ADD HL,DE` set up on the `;` line and
      stepped with `S` (HL `5555`), and `:C020 02` (a red border)
- [x] SHIFT+RETURN: the next line, nothing run
- [x] RUN/STOP during `$` (SD2IEC): the listing stops cleanly, `@` and
      `$` fine after it

The joystick (a Hyperkin pad in port 2):

- [x] BoulderL played with it, smoothly
- [x] Hold F3 in Mazogs: its own keys taught, it carries on, playable
- [x] F3 switching 5678+0 and the taught keys, with the stick held too;
      F7 and F8 keep the layout
- [x] Fire held and `0` pressed, right and `8`: no reset
- [x] Mazogs with the keyboard and the stick: no freezes
- [x] A diagonal in Mazogs where the newer direction is open: it turns
- [x] `G`, DEL, `G` typed fast (each down before the last is up): `G`,
      not `LLIST`; the same with a cursor key

The disk:

- [x] By JiffyDOS on the SD2IEC: `LOAD "MAZOGS"` in about 4.5 s
      (27 s the kernal's way; the game plays), a missing file (report D
      in under a second, NAME.P tried too; the bar shows briefly, the
      SD2IEC's LED blinks, `@` says `62,FILE NOT FOUND`), a name found
      only as NAME.P (`tetris1k` renamed `tetris1k.p`), F5's monitor, the
      monitor's `W` then `L` (its screen kept) and `$`, F7 after
      `aydemo.p` (the ROM by JiffyDOS)
- [x] `jtest` with zx64's reader (c64/jcore.asm): "jiffy yes", every
      read ok, 3,402 B/s (14,156 bytes in 4.16 s, 28.77 s the kernal's
      way), the same with zx64's y-scroll and the screen off. In VICE
      with a 1541: "jiffy no", the kernal's reads ok
- [x] The boot file, a stub: from `RUN`, 7 s to the Z80's LED (`ZX64`
      and both monitor files by JiffyDOS), 10 s to the `K` cursor (the
      rest is the ROM's own start, 2.8 s in the simulator too). F5 at
      once, no disk; `aydemo.p` and F7 read the ROM from `ZX64`. A disk
      with `ZX81` but no `ZX64`: "ZX64 NOT LOADED". In VICE with a 1541:
      `ZX64` the kernal's way, the `K` cursor, the monitor not loaded
- [x] The boot from a real 1571 (no JiffyDOS, so the kernal's speed):
      `LOAD "MAZOGS"` about 35 s; the first F5 loads `zx64mon` in about
      22 s, later ones instant; F7 fast, and with the ROM changed
      (`:0100 01`) it reads the ROM again from the 1571

Not tried:

- [ ] F5 with another version's `zx64mon` files on the disk:
      `ZX64MON: OTHER ZX64`

Seen on the C128, zx128 (80 columns):

- [x] The boot from the disk (the Ultimate's 1571), and from the
      function ROM as the Ultimate's cartridge: the ZX81 in under 5 s;
      CTRL held gives C128 BASIC, the Commodore key C64 mode; the C128's
      own reset button
- [x] The picture on the VDC the same as the display file in every
      workload; Mazogs and 3D Monster Maze played. A big redraw from
      Mazogs on the screen in 6 frames, one from Monster Maze in 10; the
      picture 5.1 ms of a quiet frame, 8.7 ms at most; no write lost
- [x] The panel; F1, F2's four schemes, F3 (the stick's keys taught, in
      BoulderL), F7, F8's three sizes
- [x] `SPEED`: 50 loops in 37 frames. `PAUSE 500`: 9.97 s on a
      stopwatch, no stray IRQs
- [x] Typing a program and `RUN`; the Y-P row in the editor; the C128's
      cursor keys in the editor and the listing; the keypad in the ZX81
      (digits, `.`, ENTER) and in the monitor
- [x] `LOAD "MAZOGS"`: 6.9 s by burst (37.0 s without); `SAVE` and
      `LOAD` back, a 32K program too (`SUM OK`); `LOAD "NOPE"`: report
      D; `SAVE` to a full disk: report D with the drive's message
- [x] `LOAD "FAST"` as its text says; `aydemo` in 16K, then F7: the ROM
      put back; BoulderL in 32K; `tetris1k` and 1K ZX Chess in 1K
- [x] The monitor: F5 in Mazogs, `S` with the picture following, `M`,
      `X` back; a breakpoint loop; `$`, `W`, `L`, `@`; the quiet F5 and
      `?`; no garbage as F5 and `X` switch screens
- [x] The function ROM as an EPROM (a 27C256) in the C128's own
      socket, U36, the Ultimate's cartridge off: the ZX81 at power-on
      with no disk; CTRL held gives C128 BASIC; F5, `LOAD` and F7
- [x] A real 1571 as drive 8, zx128 from U36: `LOAD "MAZOGS"` by burst,
      8.6 s from NEWLINE to the game: the drive slower to get going
      than the Ultimate's, then about 7 s for the bar and the game's start
- [x] The boot from zx128.d64 on a real disk in the 1571, CTRL held at
      power-on to pass over U36's ROM, then `BOOT`: zx128 running about
      20 s after RETURN
- [x] The release build: boot, F5, `?`, `X`, F5 again (quiet), F7
- [x] An SD2IEC as drive 8, no burst: the boot from zx128.d64 (CTRL held
      to pass over U36) takes about 70 s with only BOOTING on the
      screen, the kernal loading 129 blocks at its own speed, then
      zx128 runs; BREAK cuts it short, and U36's ROM starts instead.
      `LOAD "MAZOGS"` at the kernal's speed
- [x] `.P` files with VERSN not 0: the disk's `INVASION` and `REDANTS`
      load and play

Seen on the C128, zx128vic (40 columns):

- [x] The boot from the disk and from the cartridge (the ZX81 in under
      5 s); CTRL and the Commodore key as for zx128
- [x] `SPEED`: 50 loops in 34 frames. `PAUSE 500`: 10.04 s, no stray
      IRQs
- [x] Typing, the Y-P row, the cursor keys and the keypad; F1, F2's
      schemes (the colours written by the Z80), F3 with a stick, F7,
      F8 to 32K (`MEM` OK), 1K
- [x] `LOAD "MAZOGS"` with the bar; a 32K program saved and loaded back;
      `LOAD "NOPE"`: report D; `SAVE` to a full disk: report D
- [x] Mazogs, BoulderL (32K, keys redefined, the stick taught),
      `mine81`, `tetris`, `tetris1k` in 1K; `aydemo`, then F7: the ROM
      and the fonts back
- [x] The monitor in the C128's colours: F5 in Mazogs and `X` back, `$`,
      `W`, `L`, `@`, `S`, `B`, the quiet F5, F5 in a FAST program, `?`
- [x] The frame in the C64 colours: four columns on each side
- [x] RESTORE and RUN/STOP+RESTORE do nothing
- [x] A real 1571 as drive 8: `BOOT` from zx128vic.d64 on a real disk,
      zx128vic running about 18 s after RETURN; `LOAD "MAZOGS"` by burst
      in about 7 s
- [x] The release build: boot, F5, `?`, `X`, F5 again (quiet), F7;
      fast typing with type-ahead
- [x] The monitor's disk commands on the real 1571: `@UJ` resets the
      drive; `W "FOO" 7000 70FF` and `L "FOO" 7000`; `L "FOO"`:
      `#? NOT A PROGRAM`; `L "NOPE"`: the drive's DRIVE NOT READY with
      the door open, FILE NOT FOUND with it closed; `W` to a disk with
      its notch taped over: WRITE PROTECT ON; BREAK during `$`, no ill
      effect
- [x] `SAVE` and `LOAD` back from ZX81 BASIC on the real 1571
- [x] BREAK during `LOAD`: no effect, the load runs to its end (zx64,
      zx128vic and zx128 don't watch BREAK while they load)

Not tried:

- [ ] An NTSC C128, a C128D, a 16K VDC

## pcheck on real programs

Checked against source or a disassembly:

- `BoulderL.p`: 22 keyboard `IN`s, rows from its key table; nothing zx64
  can't do. `DB`/`D3` bytes in its data aren't counted as code
- `mazogs.p`: no `IN`/`OUT`; `USR 8192` (its ZXpand SAVE)
- programs for the ZXpand and an AY chip: their ports (`$07`, `$17`; `$CF`, `$0F`), with where each
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
