# zx64 manual

## Contents

- [Background](#background)
- [How it works](#how-it-works)
- [Getting started](#getting-started)
- [Using the ZX81](#using-the-zx81)
- [The games](#the-games)
- [The monitor](#the-monitor)
- [The test programs](#the-test-programs)
- [Troubleshooting](#troubleshooting)
- [The source](#the-source)

## Background

Commodore's CP/M cartridge (1983) is remembered as a flop. It put a Z80
next to the C64's 6510 so the C64 could run CP/M, and C64 CP/M is often
called the worst CP/M port there was: slow, short of memory, little
software, and disks no other CP/M machine of the day could read. The
cartridge is rare now, and notoriously picky about the C64 it's plugged
into. The author built a few replicas of Dirk Wouters's (DL2DW) design
and tried them on about seven C64s from his collection, breadbins and
C64Cs alike. CP/M either wouldn't start at all or crashed after a few
minutes.

On a C64 Reloaded MK2, the same cards turn out to be rock solid. That is
the machine zx64 was developed and tested on: see
[The hardware](#the-hardware).

The cartridge's trick is a single register: a write to `$DE00` stops
the 6510 and hands the whole machine, memory and I/O chips, to the Z80.
But then there is nothing. No kernal, no screen editor, no keyboard
routine: a Z80 in front of 64K of RAM and a VIC, with no idea what to do
with them. Unless you bring your own operating system.

The ZX81's is 8K: BASIC, the editor, the display, the keyboard and tape,
written for a Z80 and almost nothing else. Most of what the ZX81's ULA
did in hardware, a C64 can do with its VIC, its CIA and some help from
the 6510. zx64 runs that ROM, with eleven routines patched, and the C64
becomes a ZX81.

## How it works

### Two CPUs, taking turns

The cartridge's Z80 and the C64's 6510 share the same memory and the
same chips, and take turns: only one of them runs at a time. A write to
`$DE00` hands the machine to the other, and the one that wrote it
freezes where it is until it gets the machine back.

<p align="center">
  <img src="img/turns-flow.svg" width="100%" alt="A timeline: the 6510 boots and sets up the VIC, then hands over with $DE00; the Z80 starts the ZX81, you type LOAD MAZOGS; the 6510 loads it from disk; the Z80 runs Mazogs while the 6510 waits">
</p>

The 6510 starts things. The boot file loads `ZX64`, about 14K holding
the 6510's loader, your patched ROM and zx64, and starts it. `ZX64` sets
up the VIC, makes a character set from the ZX81 ROM's, and hands over.
The Z80 starts at `$0000`, like a ZX81 switched on. From then on the Z80
runs nearly all the time, and the 6510 only wakes up for the disk.

The Z80 sees the C64's memory shifted by 4K: where a ZX81 expects its
ROM, at `$0000`, it finds the C64's `$1000`. The shift is the
cartridge's own: an adder chip adds `$1000` to every Z80 address, so
CP/M got RAM at `$0000` while the 6510 kept its zero page, stack and
screen. It wraps around, so the Z80 still reaches all 64K: its top 4K
is the C64's bottom 4K. Addresses in this manual are the Z80's, as the
monitor shows them.

<p align="center">
  <img src="img/memory-map.svg" width="80%" alt="Memory as the Z80 sees it: 0000 the ZX81 ROM, 2000 zx64, 3000 zx64mon, 4000 the ZX81's 16K, 8000 16K more in 32K mode, C000 the C64's I/O chips, D000 the VIC's screen and the ZX81 font, E000 zx64mon's second part, F000 the 6510's own page; C64 addresses are $1000 higher">
</p>

### The picture

A ZX81 has no video chip. With a little help from the ULA, its Z80 draws
the picture itself, 50 times a second, from the display file, the
screen's contents in RAM. That is why a ZX81 is slow in SLOW mode: most
of its time goes into drawing. In FAST mode it stops drawing to compute,
and the screen goes blank.

The C64's VIC draws a picture on its own; it only needs to be told what
to show. So zx64 keeps the VIC's screen memory up to date instead: it
copies the display file across at the end of every other frame, when
the VIC signals one. The ROM never notices: it writes to its display file
as always. The Z80 spends only the copy on the picture, which is why
zx64 is nearly twice as fast as a real ZX81 in SLOW mode. In FAST mode
zx64 stops copying, so the picture holds still instead of going blank.

<p align="center">
  <img src="img/picture-flow.svg" width="100%" alt="BASIC and the ROM write the display file in the ZX81's RAM; zx64 copies it 25 times a second, when the VIC signals; the VIC draws its screen memory in the ZX81's font">
</p>

The VIC's signal reaches the Z80 through its interrupt line, which the
cartridge leaves unconnected: one wire fixes that, see
[the /INT wire](cpm-cart.md#the-int-wire).

### The keyboard

The ZX81's ROM reads its keyboard as 8 rows of 5 keys. The C64's is a
grid of 8 by 8 keys. 50 times a second zx64 reads the C64's grid, works
out which ZX81 key each pressed key stands for, and writes the result
where the ROM expects its keyboard rows. From there the ROM's own
keyboard code takes over, unchanged.

<p align="center">
  <img src="img/keyboard-flow.svg" width="100%" alt="You press P; the C64 keyboard's 8 by 8 grid is read through the CIA; zx64 turns C64 keys into ZX81 keys 50 times a second; the ZX81's keyboard rows feed the editor and INPUT (through zx64's type-ahead queue), LAST_K and INKEY$, and games that read the keyboard hardware themselves">
</p>

zx64 adds two things on the way. Type-ahead queues keys in the order
you press them, so fast typing isn't lost. And it filters out ghost
keys: some combinations of keys held down make the C64's keyboard report
one that isn't pressed. Typed quickly, `TEST` could come out as `TESFT`;
zx64 gives `TEST`.

A joystick in port 2 goes in at the same place, as the ZX81 keys of its
[layout](#the-joystick). Its lines are the keyboard's column lines, so
with the stick held a key in one of its columns shows in every column:
fire and `0` together would read as F7, the reset. zx64 takes those
ghosts out too; while the stick is held, a second key in the same row
as such a key can't be read.

### The disk

The disk is the 6510's job. For `LOAD` and `SAVE` the Z80 leaves a
command and the name in a mailbox at `$2F00` and writes `$DE00`. The
6510's loader, waiting since `RUN`, does the work, fills the bar on the
top row, and switches back. The monitor's disk commands go the same way.
It reads by JiffyDOS when the drive answers to it, with its own code for
the serial bus: about 3,400 bytes a second, seven times the kernal's
speed. Otherwise, and for writing, it uses the C64's kernal.

### What zx64 changes in the ROM

Only what touched the ZX81's hardware. Eleven places, each checked byte
for byte by `tools/build.py` first, so another ROM is refused rather
than broken. The rest of the ROM runs as Sinclair wrote it.

- **The picture:** the ZX81's interrupt (`$0038`) becomes zx64's, which
  copies the screen; the display routine (`$0277`) waits for it.
- **SLOW and FAST** (`$0207`, `$02E7`, `$04CC`): interrupts on or off
  instead of the display on or off.
- **The keyboard** (`$02BB`) and **BREAK** (`$0F46`): read from the C64's
  keys.
- **LOAD and SAVE** (`$0340`, `$02F6`): the disk instead of the tape.
- **The printer** (`$087B`): skipped. The **reset** (`$0000`): an `OUT`
  that only made sense on the ZX81 is gone.

The monitor's `D` shows them in place: see [Reading the ROM](#reading-the-rom).

### IN and OUT

On a ZX81, `IN` and `OUT` talk to hardware. On the cartridge they don't:
they read and write memory instead, at an address made from the port
number and the A register. zx64 makes good use of that: it puts the
keyboard rows exactly where a game's `IN A,($FE)` will read them, so
games that read the keyboard themselves still work.

The catch is the other way: a game that writes to a sound chip, a
printer, a ZXpand or another add-on the ZX81 may have had writes into
memory instead, possibly into the ROM. `tools/pcheck.py` warns about
such games when they go on the disk, and F7 repairs the ROM afterwards.

## Getting started

### The hardware

zx64 was developed on this setup:

- [C64 Reloaded MK2](https://wiki.icomp.de/wiki/C64_reloaded_mk2)
  (Individual Computers). Its USB serial link reads the C64's memory,
  which helped find several of the bugs.
- DL2DW's [CP/M cartridge replica](https://codeberg.org/diwou/Commodore_CPM_Cartridge):
  schematic, Gerbers and parts list, plus one wire for `/INT`, and if you
  like an [LED](cpm-cart.md#led-while-the-z80-runs) that shows which CPU
  has the machine.
- An [SD2IEC](https://www.tfw8b.com/sd2iec-info/).

Other setups may work; reports are welcome.

<p align="center">
  <img src="img/setup.jpg" width="49%" alt="A C64 Reloaded MK2 in its case, Mazogs's title on the monitor behind it, and the CP/M cartridge replica plugged in at the back with its red LED lit">
  <img src="img/mod-card.jpg" width="49%" alt="The author's replica card with both mods: a red wire from the edge connector's pin 4 to a test hook on the Z80, a red LED in U5's socket, and a plastic standoff beside the card">
</p>

The setup, running Mazogs with the LED lit; and the card as used: the
`/INT` wire soldered at the edge connector and clipped to the Z80, the
LED in U5's socket, and a standoff to keep the card steady in the port.

### Building and booting

You need:

- A C64, the CP/M cartridge with the [/INT wire](cpm-cart.md#the-int-wire),
  and a disk drive.
- Or, without the hardware, VICE: its `x64sc` emulates the cartridge
  (`-cpmcart`), interrupt included, so no wire is needed.
- Your own ZX81 ROM as `rom/zx81.rom` (8192 bytes, the standard
  second version).
- GNU z80asm, acme, c1541 from VICE, and Python 3 to build.

```sh
cp ~/somewhere/zx81.rom rom/
cp ~/somewhere/*.p games/       # any games for the disk
make
```

Put `build/zx64.d64` on a disk for your drive, then on the C64:

    LOAD "ZX81",8
    RUN

`LOAD` takes a second or two; `RUN` loads the rest. On a drive with
JiffyDOS, like an SD2IEC, the ZX81 is ready about 10 seconds after
`RUN`, with the monitor already loaded, so F5 opens it at once. Other
drives load the kernal's way, in about half a minute, and F5 loads the
monitor the first time.

In VICE: `make vice`, and set the keyboard mapping to positional.

## Using the ZX81

The keys are in the same places as on the ZX81's keyboard, with the
ZX81's legends:

<p align="center">
  <img src="img/keyboard.png" width="100%" alt="The C64 keyboard with the ZX81's legends: keywords above, SHIFT symbols in red, functions below, block graphics in the corners; F1, F3, F5, F7 as type-ahead and colours, joystick, monitor, reset and RAM size">
</p>

Printable overlay: [keyboard.pdf](keyboard.pdf). Keyboard viewer, to
open locally: `docs/keyboard.html`.

| Key | |
|---|---|
| SPACE, RUN/STOP | BREAK |
| F1 | type-ahead on or off |
| F2 (SHIFT+F1) | the next colour scheme |
| F3 | the joystick: 5678+0 or your own keys; held, set your own |
| F5, F6 (SHIFT+F5) | the monitor |
| F7 | reset |
| F8 (SHIFT+F7) | memory: 16K, 32K, 1K (resets) |

- **Type-ahead**, on at the start: type at C64 speed.
- **Colour schemes**: black on white, white on black, green screen,
  amber, black on green, C64 blue.
- **Memory**: 16K, the default, as with Sinclair's RAM pack; 32K,
  RAM from `$4000` to `$BFFF`, all for BASIC; 1K, the bare ZX81.
- **Reset**: the settings stay. If a program wrote over the ROM, it is
  read again from the disk first.

## The games

Yes, games. `LOAD "MAZOGS"`, watch the bar fill, and off you go:

<p align="center">
  <img src="img/loading-bar.gif" width="80%" alt="The top row while LOAD MAZOGS runs: LOADING MAZOGS, the bar filling in black, a spinner turning at the right">
</p>

<p align="center">
  <img src="img/shot-monstermaze.png" width="32%" alt="3D Monster Maze's introduction, green on black">
  <img src="img/shot-1kchess.png" width="32%" alt="1K ZX Chess: the board in the collapsed 1K display">
  <img src="img/shot-fungaloids.png" width="32%" alt="Fungaloids's title page, amber">
</p>

Most games should just work: those that draw with the ZX81's own
characters and block graphics, as nearly all do. Every one tried so far
plays, from Mazogs and 3D Monster Maze to 1K ZX Chess. Out of reach:
hi-res and WRX graphics, and anything else that changes how the ZX81
draws its picture.

Put your `.p` files in `games/` and run `make`: they go on zx64's disk,
and `tools/pcheck.py` tells you if one uses something zx64 can't do,
such as add-on hardware or hi-res. Then `LOAD "NAME"`. `SAVE "NAME"`
saves to the same disk.

### The joystick

A joystick in port 2 maps to ZX81 keys. At the start they are the keys
with the arrows on them, the most common: 7 6 5 8 for up, down, left and
right, 0 for fire. ZX81 games read the keyboard, and each picks its own
keys, so you can teach zx64 a game's own. F3 then switches between the
two layouts, each shown on the top row as its keys: `U7 D6 L5 R8 F0`.

**Your own keys:** hold F3 for a second. The program stops where it is
and the top row asks for each key in turn, a `?` at the one it wants:
`U? D- L- R- F-`. Press the game's key for it. F1 gives a direction no
key, F5 gives up and keeps the layout as it was. After the fire key the
program carries on with your layout, which stays until you switch off.

On a diagonal, BASIC games see the direction pressed last;
games that read the keyboard themselves see both. In FAST mode, holding
F3 doesn't teach keys: F3 only switches.

## The monitor

This is zx64's party trick. Press F5 and the ZX81 stops wherever it is,
in BASIC, the editor or the middle of a game, and zx64mon opens: a
machine code monitor in the style of Jim Butterfield's Supermon, but for
the Z80. Memory, a disassembler, an assembler, breakpoints, single
stepping and the disk, on a 40-column screen with the C64's full
keyboard. `X` or F5, and the program carries on as if nothing happened.
[See it on the real machine](img/demo.mp4).

ZX81 owners in 1981 had a membrane keyboard, a tape recorder and `POKE`.
Here the C64 becomes a Z80 development machine: write a routine, run it
from BASIC, stop it, step through it, fix it, save it. And since the
ZX81 is about as simple as a Z80 computer gets, it's a fine place to
learn.

<p align="center">
  <img src="img/shot-mon-mazogs.png" width="70%" alt="The monitor after F5 in Mazogs: the registers, and D at the game's PC">
</p>

The screen editor works as the C64's. The monitor's headings and
messages start with `#`, an error is `#?`, and RETURN on such a line
does nothing, so moving about the screen is safe. HOME goes to the top
row, CTRL+HOME to the bottom one. A memory line from `M` or a
disassembly line from `D` can be edited in place and entered again; on
an `M` line, the hex or the characters, `PRINT` to `PRONT` say. The
characters are stored as they show: a reversed one as the inverse
character, a plain one not. RVS ON and OFF work as on the C64; RETURN
turns it off too. A character the ZX81 hasn't got, such as `!`, is `?`.
After RETURN the line is drawn again from memory, so it shows what was
stored. Numbers are hex; `=` converts. RUN/STOP stops a long listing.

CRSR UP on the top row and CRSR DOWN on the bottom one scroll an `M` or
`D` listing: the line before or after it comes in, and `M` or `D` alone
goes on after the last. Under a short listing, CRSR DOWN on the bottom
row fills the rows down to it, and the cursor stays there. Going back in
a `D` listing, the monitor finds the instruction before by disassembling
from a few bytes earlier; data mixed with the code can make that come
out differently.

    M s [e]          memory, 8 bytes a line, with their ZX81 characters
    D s [e]          disassemble; M or D alone goes on
    A a text         assemble at a
    : a b 'TEXT' ... store bytes and ZX81 text (M's lines too)
    R                the registers, as ; and ' lines to edit
    G [a]            carry on (at a); X does the same
    B [a]            breakpoint on or off (four at most); B alone lists
    S                one step; RETURN steps again
    F s e b          fill
    T s e d          transfer (overlap is fine)
    C s e d          compare
    H s e b b ...    hunt bytes; H s e 'TEXT hunts ZX81 characters
    $                the disk's directory
    L "NAME" [a]     load a program, as LOAD; with a: a file to a
    W "NAME" [s e]   save the program, as SAVE; with s e: s-e as a PRG
    @[cmd]           the drive's status, or a DOS command
    = n              n in hex, decimal and binary; +n is decimal, %n binary
    Z n              line 1 a REM of n bytes, for code at 16514
    ?                help

F5 works wherever zx64 reads the keyboard: always in SLOW mode, and in
FAST mode at the prompt and between BASIC statements. There's no NMI, so
FAST machine code that never reads the keyboard can't be stopped.

Nothing is protected: the ROM, zx64 and the C64's I/O are all memory, and
the monitor changes whatever you tell it to. `:C020 02` makes the
border red, from the Z80; leaving the monitor puts the colours back.
Only the disk commands refuse the 6510's page and the I/O chips.

### Machine code in a REM line

The classic ZX81 way: a `REM` line at the start of the program holds the
machine code. Its first byte after the `REM` is at 16514 (`$4082`), and
`USR 16514` runs it.

Hello world. First the room for it, 23 bytes (`$17`): F5, and

    Z 17

`Z` makes line 1 a `REM` of that many bytes, NOPs and a `RET` last. With
no program, it adds the line that runs it too, `10 RAND USR 16514`.

Then `A` at `$4082`. After each line the monitor offers the next
address; RETURN on an empty one ends, and `A 4082` alone offers the first.
Then the text, after the code, with `WORLD` typed in RVS ON:

    A 4082 LD HL,$408D
    LD A,(HL)
    INC A
    RET Z
    DEC A
    RST $10
    INC HL
    JR $4085

    :408D 'HELLO WORLD' FF

<p align="center">
  <img src="img/shot-asm.png" width="49%" alt="The assembler: each line turned into its address, bytes and instruction, then the text">
  <img src="img/shot-rem.png" width="49%" alt="LIST: 1 REM, the code as characters and keywords, HELLO, an inverse WORLD and COPY">
</p>

`RST $10` is the ZX81's CHROUT: it prints the character in A, keywords
and NEWLINE too, and keeps BC, DE and HL: it works in the other register
set, with `EXX`. The text ends with `FF`, as [Text in
memory](#text-in-memory) explains: `INC A` makes it 0, and `RET Z` goes
back to BASIC. `USR` returns BC as its value; `RAND USR` throws it away,
`PRINT USR` would print it after the text. Leave IX alone, and IY, which
the ROM needs to hold `$4000`.

The assembler takes Zilog's mnemonics as `D` writes them, numbers as
`$12` or with a leading digit, `0DE`; a bare `DE` is the register. It
works by search: it tries encodings, disassembles each, and keeps the
one that reads as your text, so whatever `D` prints, `A` takes back.
That's up to about a second for the rarest instructions on the real
machine. A line from `D` changed on the screen and entered is assembled
too. If the new instruction is shorter or longer than the old one, the
`D` line under it is no longer the next instruction, so the next address
is offered instead, as `A` does.

`X`, then `LIST`: the `REM` now holds the code, shown as ZX81 characters
and keywords, then `HELLO`, an inverse `WORLD`, and the `FF` as `COPY`,
the keyword with that code. Some of the code is missing: `$7E` marks a
number in a BASIC line, and `LIST` skips the 5 bytes after it. `RUN`
prints the same, `WORLD` inverse. `M 4082 4099` shows all the bytes, and
the text:

<p align="center">
  <img src="img/shot-mon-m.png" width="70%" alt="M 4082 4099: the code, then HELLO, an inverse WORLD and FF">
</p>

Not sure how much room the code will need? Start with some, and `Z`
again when it runs out: on a line 1 that is a `REM` already, `Z n` makes
it n bytes, keeping what is in it, with NOPs added at the end or bytes
cut from it. On a program without a line 1, `Z` puts the `REM` in front
of it, and adds no `RAND USR` line. A line 1 that isn't a `REM`, or no
room for it, is `?`. The program moves, so leaving after `Z` goes to
BASIC as after `L`: report 0, not back to what was running.

The code has to be assembled where it runs, at `$4082` on: `A` uses the
address it writes to for jumps and calls, so code tried out at `$7000`
doesn't work from the `REM` unless it only uses relative jumps, `JR` and
`DJNZ`.

To watch it run, set a breakpoint on the `RST $10`:

    B 4089           a breakpoint on the RST $10
    X                back to BASIC; RUN
                     the monitor opens at 4089: A = 2D, an H
    G                on: it stops there again, A = 2A, an E
    B 4089           the breakpoint off; G, and the rest is printed

`S` steps one instruction instead; on the `RST $10` it goes into the
ROM, at `$0010`. RETURN steps again; to go on, delete the `S` and type
`G`. A breakpoint is a `RST $38` in place of the instruction's first
byte; zx64's interrupt handler tells it from an interrupt. It works
without the `/INT` wire too. The monitor puts the
real bytes back while it's open, so `M` and `D` show the code as it is.
Not possible: breakpoints in zx64 or the monitor (`$2000-$3FFF`), at
`$0038`, or from `$C000` up.

The ROM has a string printer too, the one `PRINT "..."` uses: BC
characters from DE, at `$0B6B`. With it, hello world is three
instructions and needs no end mark:

    A 4082 LD DE,$408B
    LD BC,$000B
    JP $0B6B

    :408B 'HELLO WORLD

`$000B` is the length, 11. The `JP` lets the ROM's routine return to
BASIC itself.

Or straight into the Z80's registers, without BASIC at all. F5, then

    A 7000 ADD HL,DE
    R

On the `;` line, note the PC: it's where F5 stopped the ZX81. Type
`7000` over it, `4321` over DE and `1234` over HL, and RETURN. `S` runs
that one instruction: HL is `5555`. Then delete the `S` offered, put the
old PC back on the `;` line, and `X`: the ZX81 goes on as it was.

### Reading the ROM

The ROM is RAM here, readable and writable like the rest. `D` shows
zx64's patches in place:

<p align="center">
  <img src="img/shot-mon-rom.png" width="70%" alt="D 0000: five NOPs and JP $03CB; D 0038: JP $2000; D 0277: CALL $2190, JP $0229">
</p>

- `0038`, the ZX81's INT, is `JP $2000`: zx64's raster interrupt.
- `0277`, DISPLAY-1, calls zx64's frame wait and goes back to `$0229`.
- `0000` should be `NOP NOP` and `LD BC,$7FFF`, but shows five NOPs. The
  ROM's floating-point calculator uses the first five bytes of memory as
  scratch space; on a ZX81 those writes hit ROM and vanish, here they
  stick. Harmless, since only a reset runs that code, and zx64's reset
  skips it.

### Patching the ROM

The ROM's keyword table holds each keyword in ZX81 characters, the last
one inverted. `H` finds `PRIN` twice: in `LPRINT` at `$0171`, and `PRINT`
itself at `$01C3`. Overwrite it with `WRITE`:

    H 0000 1FFF 'PRIN
    :01C3 3C 37 2E 39 AA

<p align="center">
  <img src="img/shot-hunt.png" width="49%" alt="H finds PRIN at 0171 and 01C3; M shows PRINT, then WRITE after the :">
  <img src="img/shot-write.png" width="49%" alt="LIST: 10 WRITE &quot;HELLO&quot;">
</p>

Back in BASIC, `LIST` shows `WRITE`, and the keyword works as before:
the ROM finds keywords by their position in the table, not their text.
F7 notices the changed ROM and reads it again from the disk, with the
bar on the top row: " LOADING ZX81 ROM".

The same as text: `:01C3 'WRIT' AA`, where `AA` is an inverse `E`. Or
`M 01C3` and type over `PRINT` on its line.

### Text in memory

`:` takes text between `'`s, as ZX81 characters, mixed with bytes;
characters typed with RVS ON are stored inverse. A
text that runs to the end of the line needs no closing `'`, and the
monitor offers the next line to go on with:

    :7000 'THE QUICK BROWN FOX JUMPS
    :7019 ' OVER THE LAZY DOG' FF

The second line's `:7019 '` is the monitor's; type the rest after it.
Spaces at a line's end are left out, so the space between the words
starts the second line; or close the first with `'`. RETURN on the
offered line with nothing added ends.

The `FF` ends the string. Not `00`: that's the ZX81's space. The ROM's
own ways are an inverse last character, as in the keyword table, and
`$76`, NEWLINE, which ends BASIC lines and the display file's rows.
`$FF` isn't a character at all, and `INC A` / `JR Z` finds it. `H 7000
7FFF 'LAZY` finds the text again.

### Disk commands

`$` lists the directory. Without addresses, `L` and `W` are BASIC's
`LOAD` and `SAVE`: the program, from `$4009` up to `E_LINE`, with the
code in its `REM` lines. So a program can be loaded to work on in the
monitor:

    L "HELLO"                #LOADED 4009-xxxx; D 4082 shows its code
    W "HELLO"                saved again, changes and all

After `L`, leaving the monitor with `X`, `G` or F5 goes on as `LOAD` does:
what was running is gone, a program saved from a program line runs, and
any other stops at the K cursor with report 0. `L` refuses a file that
isn't a program, `#? NOT A PROGRAM`, or one that doesn't fit, `#? TOO
BIG`, before anything is written; `LOAD` gives reports D and 4 for them.

With addresses they are for memory. `W "NAME" s e` writes s-e as a PRG
with the C64's load address, so `LOAD "NAME",8,1` on a plain C64 puts it
back where it was; `L "NAME" a` loads a PRG to a:

    W "ROM" 0000 1FFF        the patched ROM, 33 blocks (C64 $1000)
    L "ROM" 0000             back where it was
    L "ROM" 8000             or to $8000

`@` alone reads the drive's status; `@` with text sends a DOS command:

    @S:ROM                   scratch
    @R:MAZOGS.P=MAZOGS       rename

The text goes to the drive as it is, so an SD2IEC's own commands work
from here too, without leaving the ZX81:

    @CD:GAMES.D64            mount another disk image
    @CD:←                    and back

## The test programs

The d64 always has four, made from `progs/*.bas` with zx64's addresses
filled in. Each runs as it loads.

- **`SPEED`** checks the setup and times 50 turns of an empty `FOR`
  loop. PAL or NTSC; `/INT SEEN: 1` means the wire works; stray IRQs,
  interrupts the VIC didn't raise, mean noise on the wire. zx64 takes 30
  frames, a UK ZX81 56-58, as [The picture](#the-picture) explains. In
  FAST mode it's the other way round: the ZX81's 3.25 MHz Z80 is about
  twice as fast as the cartridge's, which gets about 1.8 T-states per
  C64 cycle.
- **`MEM`** tests every free byte: machine code in a `REM` writes a
  pattern from each byte's address into all of them, reads them back,
  then the same with the complement. 14,728 bytes in 16K, 31,112 in 32K.
- **`PAUSE`** does `PAUSE 500` between GO and STOP: 10 seconds on PAL,
  to time with a stopwatch. A check that the interrupt comes 50 times a
  second.
- **`FAST`** counts to 100 in FAST mode while the picture holds, prints
  how many frames went by meanwhile, 0 as on a ZX81, then loops in FAST
  for you to stop with SPACE or RUN/STOP: report D/230.

## Troubleshooting

- **The picture freezes while a program runs; games ignore keys.** The
  `/INT` wire is missing or loose. `SPEED` says `/INT SEEN: 0`. Push the
  cartridge fully home; half-seated, the picture freezes and keys come
  and go.
- **"NO Z80: ZX64 NEEDS THE C64 CP/M CARTRIDGE."** zx64 found no Z80:
  no cartridge, or it isn't seated.
- **"ZX64 NOT LOADED"** after `RUN`: the disk has the boot file, `ZX81`,
  but not `ZX64`, or there was a disk error. Put all four files of
  `build/zx64.d64` on it: `ZX81`, `ZX64`, `zx64mon` and `zx64mon2`.
- **Report D on LOAD.** The file isn't on the drive zx64 came
  from, under that name or with `.P`. `@` in the monitor shows the
  drive's message.
- **A game crashes, or F7 hangs.** It may write where it shouldn't:
  `tools/pcheck.py -v` shows its `OUT`s and where they land. F7 repairs
  the ROM, but not zx64's own code: the top row then says `ZX64 CHANGED:
  LOAD IT AGAIN`; load the boot file again.
- **"ROM NOT RELOADED: NO ZX64"** or **"OTHER ZX64"** on F7: the disk
  in the drive has no `ZX64`, or one from another version of zx64. The
  ROM stays as it is.
- **"NO ZX64MON ON THE DISK"** on F5: the files `zx64mon` and `zx64mon2`
  aren't on the drive zx64 booted from.
- **Typing in VICE gives the wrong keys.** Set VICE's keyboard mapping
  to positional.

## The source

| Path | |
|---|---|
| `z80/zx64.asm` | the Z80 side: interrupts, picture, keyboard, disk via the mailbox |
| `z80/mon.asm` | zx64mon |
| `c64/boot.asm` | the 6510 side: boot, VIC setup, disk I/O |
| `tools/build.py` | patches the ROM, assembles, builds the d64 |
| `tools/pcheck.py` | checks `.p` files for what won't work |
| `tools/zxbasic.py` | BASIC text to `.p`, for `progs/` |
| `tools/simulate.py` | `make test`: both CPUs in emulators |
| `tools/shots.py` | this manual's screenshots, from the same emulators |
| `progs/` | the test programs |
| `scripts/` | headless VICE, for testing on Linux |

More: what zx64 relies on about the cartridge, with sources, in
[cpm-cart.md](cpm-cart.md); what has been tested, in
[testing.md](testing.md).
