# zx0.py: the ZX0 packer and unpacker in Python

[ZX0](https://github.com/einar-saukas/ZX0) is Einar Saukas's compression
format for 8-bit machines: tight, with a tiny, fast unpacker on the Z80
and the 6502. `zx0.py` packs and unpacks it in plain Python 3, nothing
to install: handy in a build script that has Python anyway.

It does ZX0's version 2 format, forward (the current default), offsets
up to 32,640 bytes. It follows the format's description, not
the reference compressor's source, and its output hasn't been
checked against the reference tools: what it packs, its own `unpack()`
and the 6502 unpacker below take apart again.

## Using it

```python
import zx0
packed = zx0.pack(data)            # bytes in, bytes out; checked by unpacking
data = zx0.unpack(packed)
```

`pack(data, weight)` trades size for unpacking time: each block costs
its bits plus `weight` times a guess of its cycles on the 6502. 0, the
default, packs smallest. The same bytes in always give the same bytes
out.

From the command line it reports what it would pack to:

    $ python3 zx0.py zx128vic.prg
    zx128vic.prg: 24781 -> 19164 (0.773) in 0.7 s

`unpack(s, copies)` can also list each copy as it is made: the stream's
bytes read by then, the output's length, the offset and the length.
That is what checks an in-place unpacker: `phase1_reads()` uses it to
find copies that would read memory the unpacker can't see yet.

## How it packs

It parses for the fewest bits in one pass from the front: each position
keeps its best way in, ended by a copy or by literals, and a copy at the
last offset uses the offset of the way in it has. The reference
compressor keeps every offset there, so it packs a little tighter.

## Seen working

- zx128's function ROM: packed to about three quarters of its size,
  and unpacked by its 6502 unpacker on a real C128, from an Ultimate's cartridge; in
  VICE from the internal function ROM socket too.
- Packed and unpacked again on every build, and round trips of edge
  cases (one byte, long runs, far offsets) in zx64's tests.

## About

zx0.py packs the function ROM of [zx64](../../README.md)'s C128 build,
zx128; its 6502 unpacker is `c128/from.asm`. ZX0 is Einar
Saukas's; this Python version is MIT licensed, see
[LICENSE](../../LICENSE).
