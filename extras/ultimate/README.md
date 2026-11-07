# ultimate.py: the Ultimate-II+'s REST API from the command line

Drive a C64 or C128 with an Ultimate-II+ from another computer: mount a
disk image, reset the machine, type on it, read and write its memory,
and wait for a byte to change. One Python 3 file, nothing to install,
for the REST API of the Ultimate's firmware 3.11 and later.

It is for test runs on a machine nobody sits at: mount, reset,
start the program, wait for it to say it's done, read the result.

## Commands

    ultimate.py info
    ultimate.py mount FILE [--drive a] [--mode readwrite|readonly|unlinked] [--type d64|g64|d71|g71|d81]
    ultimate.py unmount [--drive a]
    ultimate.py reset
    ultimate.py readmem ADDR LEN [-o FILE]
    ultimate.py writemem ADDR FILE
    ultimate.py drive-mode 1541|1571|1581 [--drive a]
    ultimate.py load-rom FILE [--drive a]
    ultimate.py pause | resume
    ultimate.py type TEXT [--c64]
    ultimate.py wait ADDR VALUE [--timeout S] [--delay S]
    ultimate.py run IMAGE [--drive a] [--wait ADDR VALUE] [--timeout S] [--delay S]

- **`mount`** sends the image to the Ultimate and puts it in the drive;
  the type comes from the file's extension unless `--type` says.
- **`readmem`** prints a hex dump, or writes the bytes to `-o`. `ADDR` is
  hex (`$1C01`, `0x1C01` or `1C01`), `LEN` decimal or hex.
- **`pause`** and **`resume`** stop and restart the CPU (the DMA line;
  the timers run on).
- **`type`** puts `TEXT` into the kernal's keyboard buffer, ten keys at
  a time, each lot once the last has been read: a C128's, or with
  `--c64` a C64's (a C128 in C64 mode too). Letters in either case are
  BASIC's; `\n` or `{return}` is RETURN, `{N}` the PETSCII code N.
- **`wait`** polls a byte until it has the value, and exits 1 after
  `--timeout` seconds (default 30).
- **`run`** mounts an image unlinked and resets; a C128 then starts it
  from its boot sector. With `--wait ADDR VALUE` it first writes VALUE
  XOR `$FF` there, so a flag left from the last run doesn't count, then
  waits as `wait` does.

Each command exits 0 on an HTTP 2xx, and 1 with the status and the body
otherwise.

## Setting it up

    export ULTIMATE_HOST=192.168.1.64       # or host:port

A network password, if the Ultimate has one, comes from
`$ULTIMATE_PASSWORD`, or else the first line of
`~/.config/zx64/ultimate-password` (`$ULTIMATE_PASSWORD_FILE` names
another file). It is sent as the `X-Password` header, to the Ultimate
only (no proxies), and never printed.

From Python:

```python
from ultimate import Ultimate
u = Ultimate("192.168.1.64", None)
u.mount("game.d64", "a")
u.reset()
u.wait(0xC000, 0xA5, 60)
print(u.readmem(0x0400, 1000))
```

Also `.writemem`, `.unmount`, `.pause`, `.resume`, `.type`, `.run`, and
`.request(method, path, params, body)` for the rest of the API.

## Two things the API doesn't say

- **Every read or write of memory is a DMA**, `pause` too. On a C128 the
  Z80 doesn't survive one: it runs on, fetching garbage. While a C128's
  Z80 may be running, give `--delay` seconds without polling first, and
  poll only for a flag set once the 8502 has the bus again.
- **On a C128, `readmem` and `writemem` see the RAM bank the MMU's
  `$D506` bits 6-7 pick**, not `$FF00`'s, with ROM and I/O where `$FF00`
  maps them. Below `$0400` is common RAM, the same in both banks.

## Seen working

An Ultimate-II+ with firmware 3.15a, in a flat PAL C128: zx128's test
runs on the real machine, unattended: mounting, resetting, typing,
polling and reading the screen. `type --c64` is untried on a
real C64. `test_ultimate.py` tests every command against a stub of
the API (`python3 -m unittest test_ultimate.py`, 24 tests).

## About

ultimate.py runs the C128 builds' tests of [zx64](../../README.md), a
ZX81 on the C64's CP/M cartridge and on the C128's own Z80, on the real
machine. API documentation:
[1541u-documentation](https://1541u-documentation.readthedocs.io/en/latest/api/api_calls.html).
MIT licence, see [LICENSE](../../LICENSE).
