# zxbasic.py: ZX81 BASIC from a text file to a .p file

Write a ZX81 program in a text editor and get a `.p` file, as the ZX81's
own `SAVE` would write it: ready for an emulator, a ZXpand's SD card or
anything else that loads `.p` files. One Python 3 file, nothing to
install.

    python3 zxbasic.py prog.bas prog.p

`prog.bas`:

    10 FOR I=1 TO 10
    20 PRINT AT I,I;"HELLO"
    30 NEXT I

## What it takes

- One BASIC line per text line, its number first.
- Keywords spelled out as the ZX81 lists them: `PRINT`, `PEEK`,
  `INKEY$`, `<>`, `**`. Spaces outside strings don't matter.
- Capital letters, digits and the ZX81's symbols (`"` `£` `$` `:` `?`
  `(` `)` `>` `<` `=` `+` `-` `*` `/` `;` `,` `.`).
- Whole numbers, up to 2^31. Each goes in as the ZX81 stores it:
  its digits, then its value in the 5-byte floating point.

Not: lower case, inverse or block graphics characters, or fractions in
the program's text (`1/2` works: the ZX81 works it out).

## What it makes

The program runs from its first line as soon as it has loaded, as one
saved by `SAVE` in a program line does. The rest is a 16K ZX81's: a full
display file, cleared, and no variables.

Two extras, for programs that go with machine code:

- **`10 REM {bin:name}`** as the first line puts machine code in the
  `REM`, at 16514, where `USR 16514` runs it, as ZX81 programs did. From
  Python: `p_file(text, blobs={"name": code})`; the code may not hold
  `$76`, which would end the line.
- **`{label}`** or **`{label+1}`** anywhere in a line is replaced by a
  label's address, from a z80asm label file (`LABEL: equ $1234` lines)
  given as a third argument:

        python3 zxbasic.py prog.bas prog.p labels.lbl

From Python:

```python
from zxbasic import p_file
open("prog.p", "wb").write(p_file(open("prog.bas").read()))
```

## Seen working

zx64's test programs are made with it, from the `.bas` files in
`progs/`, and run on zx64, zx128 and zx128vic, in their emulators and on
the real C64 and C128. Not tried on a real ZX81 or in a ZX81
emulator.

## About

zxbasic.py makes the test programs of [zx64](../../README.md), a ZX81 on
the C64's CP/M cartridge and on the C128's own Z80.
MIT licence, see [LICENSE](../../LICENSE).
