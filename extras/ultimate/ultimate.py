#!/usr/bin/env python3
"""The Ultimate-II+'s REST API from the command line (firmware 3.11+).

    extras/ultimate/ultimate.py info
    extras/ultimate/ultimate.py mount FILE [--drive a] [--mode readwrite|readonly|unlinked]
                                 [--type d64|g64|d71|g71|d81]
    extras/ultimate/ultimate.py unmount [--drive a]
    extras/ultimate/ultimate.py reset
    extras/ultimate/ultimate.py readmem ADDR LEN [-o FILE]
    extras/ultimate/ultimate.py writemem ADDR FILE
    extras/ultimate/ultimate.py drive-mode 1541|1571|1581 [--drive a]
    extras/ultimate/ultimate.py load-rom FILE [--drive a]
    extras/ultimate/ultimate.py pause | resume
    extras/ultimate/ultimate.py type TEXT [--c64]
    extras/ultimate/ultimate.py wait ADDR VALUE [--timeout S] [--delay S]
    extras/ultimate/ultimate.py run IMAGE [--drive a] [--wait ADDR VALUE] [--timeout S] [--delay S]

For mounting disk images on the real C64/C128, resetting it and reading
or writing its memory. ADDR is hex ($1C01, 0x1C01 or 1C01), LEN decimal
(or $hex / 0xhex). readmem prints a hex dump, or writes the bytes to -o.
mount takes the image type from FILE's extension unless --type says
otherwise, and sends the filename too. Each command exits 0 on an HTTP 2xx, and 1 with the status and body
otherwise.

For a C128 (or C64) nobody sits at: pause/resume stop and restart its CPU
(the DMA line; the timers run on). type puts TEXT into the C128 kernal's
keyboard buffer (--c64: the C64's, a C128's in C64 mode too), ten keys
at a time, each lot once the last has been read: letters in either case are the unshifted ones (BASIC's), "\\n" or
{return} is RETURN, {N} the PETSCII code N. wait polls the byte at ADDR
until it is VALUE (exit 1 after --timeout seconds, default 30). run
mounts IMAGE unlinked and resets (a C128 then starts it from the boot
sector); with --wait it first writes VALUE xor $FF to ADDR, so a flag
left over from the last run doesn't count, then waits as wait does.
Every poll (any readmem, writemem or pause) is a DMA, and a C128's Z80
doesn't survive one: it runs on, fetching garbage
(measured on the C128). While the Z80 may be running, --delay
seconds without polling first, and poll only for a flag set once the
8502 has the bus again. On a C128, readmem and writemem see the RAM bank
that the MMU's $D506 bits 7-6 pick (not $FF00's bank), with ROM and I/O
where $FF00 maps them.

The Ultimate's address is $ULTIMATE_HOST (host or host:port). If it has
a network password, that is $ULTIMATE_PASSWORD or else the first line of
~/.config/zx64/ultimate-password ($ULTIMATE_PASSWORD_FILE names another
file); it is sent as X-Password and never printed.

From Python: Ultimate(host, password).request(method, path, params, body),
.readmem(addr, n), .writemem(addr, data), .mount(path, drive), .unmount(drive), .reset(),
.pause(), .resume(), .type(text), .wait(addr, value, timeout),
.run(path, drive, (addr, value), timeout).
API docs: https://1541u-documentation.readthedocs.io/en/latest/api/api_calls.html
"""
import argparse
import json
import os
import re
import sys
import time
import urllib.error
import urllib.parse
import urllib.request

IMAGE_TYPES = ["d64", "g64", "d71", "g71", "d81"]
TIMEOUT = 10                                     # seconds
PASSWORD_FILE = "~/.config/zx64/ultimate-password"
# the kernal's keyboard buffer (KEYD) and its count (NDX): the C128's
# (kernal 318020-05 at $C6B7: LDX NDX / CPX XMAX / STA KEYD,X / STX NDX),
# below $0400, which is common RAM, so the bank doesn't matter; and the
# C64's, also a C128's in C64 mode. Ten keys fit in either (XMAX)
KEYD, NDX, KEYS = 0x034A, 0xD0, 10
KEYD64, NDX64 = 0x0277, 0xC6
POLL = 0.1                                       # seconds between polls
# no proxies: the password goes to the Ultimate and nowhere else
OPENER = urllib.request.build_opener(urllib.request.ProxyHandler({}))


class UltimateError(Exception):
    """An HTTP error (or none at all) from the Ultimate."""


class Ultimate:
    def __init__(self, host, password=None):
        self.host = host
        self.password = password

    def request(self, method, path, params=None, body=None, headers=None):
        url = "http://%s%s" % (self.host, path)
        if params:
            url += "?" + urllib.parse.urlencode(params, safe="")
        req = urllib.request.Request(url, data=body, method=method)
        if self.password:
            req.add_header("X-Password", self.password)
        if body is not None:
            req.add_header("Content-Type", "application/octet-stream")
        for k, v in (headers or {}).items():
            req.add_header(k, v)
        try:
            with OPENER.open(req, timeout=TIMEOUT) as r:
                return r.read()
        except urllib.error.HTTPError as e:
            text = e.read().decode("utf-8", "replace").strip()
            raise UltimateError("HTTP %d %s: %s" % (e.code, e.reason, text)) from None
        except (urllib.error.URLError, OSError) as e:
            raise UltimateError("%s: %s" % (self.host, getattr(e, "reason", e))) from None

    def readmem(self, addr, n):
        # the query is spelled out: address is bare hex, length decimal
        return self.request("GET", "/v1/machine:readmem?address=%X&length=%d" % (addr, n))

    def writemem(self, addr, data):
        return self.request("POST", "/v1/machine:writemem?address=%X" % addr, body=data)

    def mount(self, path, drive="a", mode=None, type=None):
        # without type the Ultimate goes by the filename, and only if it gets one
        name = os.path.basename(path)
        type = (type or os.path.splitext(name)[1][1:]).lower()
        if type not in IMAGE_TYPES:
            raise UltimateError("%s: image type unknown, give --type %s"
                                % (name, "|".join(IMAGE_TYPES)))
        with open(path, "rb") as f:
            image = f.read()
        params = {"mode": mode} if mode else {}
        params["type"] = type
        return self.request("POST", "/v1/drives/%s:mount" % drive, params, image,
                            {"Content-Disposition": 'attachment; filename="%s"' % name})

    def unmount(self, drive="a"):
        return self.request("PUT", "/v1/drives/%s:remove" % drive)

    def reset(self):
        return self.request("PUT", "/v1/machine:reset")

    def pause(self):
        return self.request("PUT", "/v1/machine:pause")

    def resume(self):
        return self.request("PUT", "/v1/machine:resume")

    def wait(self, addr, value, timeout=30.0, interval=POLL, delay=0.0):
        """Polls the byte at addr, after delay seconds of not looking, until
        it is value; True, or False once timeout seconds (delay included)
        have passed."""
        end = time.monotonic() + timeout
        time.sleep(delay)
        while True:
            if self.readmem(addr, 1)[0] == value:
                return True
            if time.monotonic() >= end:
                return False
            time.sleep(interval)

    def type(self, text, timeout=10.0, c64=False):
        """text (petscii's notation) into the keyboard buffer, KEYS keys at a
        time, each lot once the kernal has taken the last: the C128's, or
        with c64 the C64's (a C128 in C64 mode too)."""
        keyd, ndx = (KEYD64, NDX64) if c64 else (KEYD, NDX)
        keys = petscii(text)
        for i in range(0, len(keys), KEYS):
            if not self.wait(ndx, 0, timeout):
                raise UltimateError("the keyboard buffer isn't being read ($%02X never 0)" % ndx)
            lot = keys[i:i + KEYS]
            self.writemem(keyd, lot)
            self.writemem(ndx, bytes([len(lot)]))

    def run(self, path, drive="a", flag=None, timeout=30.0, delay=0.0):
        """Mounts path unlinked and resets; with flag (addr, value), clears
        it first and waits for it (as wait). True unless the wait timed out."""
        if flag:
            self.writemem(flag[0], bytes([flag[1] ^ 0xFF]))
        self.mount(path, drive, "unlinked")
        self.reset()
        return self.wait(flag[0], flag[1], timeout, delay=delay) if flag else True

    def drive_mode(self, mode, drive="a"):
        return self.request("PUT", "/v1/drives/%s:set_mode" % drive, {"mode": mode})

    def load_rom(self, path, drive="a"):
        with open(path, "rb") as f:
            rom = f.read()
        return self.request("POST", "/v1/drives/%s:load_rom" % drive, body=rom)


def find_password():
    """$ULTIMATE_PASSWORD, else the password file's first line, else None."""
    pw = os.environ.get("ULTIMATE_PASSWORD")
    if pw:
        return pw
    path = os.path.expanduser(os.environ.get("ULTIMATE_PASSWORD_FILE", PASSWORD_FILE))
    try:
        with open(path) as f:
            return f.readline().strip() or None
    except OSError:
        return None


def number(text, base=10):
    """A number as typed: $1C01 and 0x1C01 are hex, otherwise in base."""
    text = text.strip()
    if text.startswith("$"):
        return int(text[1:], 16)
    if text.lower().startswith("0x"):
        return int(text, 16)
    return int(text, base)


def petscii(text):
    """The keys for text: a-z and A-Z the letters BASIC reads (65-90), the
    two characters \\n or {return} RETURN (13), {N} the code N; the rest of
    ASCII 32-93 as it is."""
    out = bytearray()
    for tok in re.findall(r"\\n|\n|\{[^}]*\}|.", text, re.S):
        if tok in ("\\n", "\n") or tok.lower() == "{return}":
            out.append(13)
        elif len(tok) > 1:                       # {N}
            out.append(number(tok[1:-1]))       # (ValueError past 255)
        elif tok.isalpha() and tok.isascii():
            out.append(ord(tok.upper()))
        elif 32 <= ord(tok) <= 93:
            out.append(ord(tok))
        else:
            raise ValueError("no key for %r" % tok)
    return bytes(out)


def hexdump(data, addr):
    lines = []
    for i in range(0, len(data), 16):
        row = data[i:i + 16]
        hexes = " ".join("%02X" % b for b in row)
        text = "".join(chr(b) if 32 <= b < 127 else "." for b in row)
        lines.append("%04X  %-47s  %s" % ((addr + i) & 0xFFFF, hexes, text))
    return "\n".join(lines)


def parser():
    p = argparse.ArgumentParser(description="The Ultimate-II+'s REST API (host: $ULTIMATE_HOST).")
    sub = p.add_subparsers(dest="cmd", required=True)
    sub.add_parser("info", help="print /v1/info")
    s = sub.add_parser("mount", help="mount a disk image")
    s.add_argument("file")
    s.add_argument("--drive", default="a")
    s.add_argument("--mode", choices=["readwrite", "readonly", "unlinked"])
    s.add_argument("--type", choices=IMAGE_TYPES, help="image type (default: from the extension)")
    s = sub.add_parser("unmount", help="take the disk out of the drive")
    s.add_argument("--drive", default="a")
    sub.add_parser("reset", help="reset the machine")
    s = sub.add_parser("readmem", help="read memory")
    s.add_argument("addr", type=lambda t: number(t, 16))
    s.add_argument("len", type=number)
    s.add_argument("-o", "--output", metavar="FILE")
    s = sub.add_parser("writemem", help="write a file into memory")
    s.add_argument("addr", type=lambda t: number(t, 16))
    s.add_argument("file")
    s = sub.add_parser("drive-mode", help="set the drive's type")
    s.add_argument("mode", choices=["1541", "1571", "1581"])
    s.add_argument("--drive", default="a")
    s = sub.add_parser("load-rom", help="load a ROM into the drive")
    s.add_argument("file")
    s.add_argument("--drive", default="a")
    sub.add_parser("pause", help="stop the CPU (DMA line low)")
    sub.add_parser("resume", help="let it run on")
    s = sub.add_parser("type", help="type on the machine through the keyboard buffer")
    s.add_argument("text")
    s.add_argument("--c64", action="store_true", help="a C64's buffer (a C128 in C64 mode too), not a C128's")
    s = sub.add_parser("wait", help="poll a byte until it has a value")
    s.add_argument("addr", type=lambda t: number(t, 16))
    s.add_argument("value", type=number)
    s.add_argument("--timeout", type=float, default=30.0, metavar="S")
    s.add_argument("--delay", type=float, default=0.0, metavar="S", help="don't poll for the first S seconds")
    s = sub.add_parser("run", help="mount an image unlinked and reset (and wait)")
    s.add_argument("file")
    s.add_argument("--drive", default="a")
    s.add_argument("--wait", nargs=2, metavar=("ADDR", "VALUE"))
    s.add_argument("--timeout", type=float, default=30.0, metavar="S")
    s.add_argument("--delay", type=float, default=0.0, metavar="S", help="don't poll for the first S seconds")
    return p


def main(argv=None):
    a = parser().parse_args(argv)
    host = os.environ.get("ULTIMATE_HOST")
    if not host:
        print("ultimate.py: set ULTIMATE_HOST to the Ultimate's address (host or host:port)",
              file=sys.stderr)
        return 1
    u = Ultimate(host, find_password())
    try:
        if a.cmd == "info":
            out = u.request("GET", "/v1/info")
            try:
                print(json.dumps(json.loads(out), indent=2))
            except ValueError:
                print(out.decode("utf-8", "replace"))
        elif a.cmd == "mount":
            u.mount(a.file, a.drive, a.mode, a.type)
        elif a.cmd == "unmount":
            u.unmount(a.drive)
        elif a.cmd == "reset":
            u.reset()
        elif a.cmd == "readmem":
            data = u.readmem(a.addr, a.len)
            if a.output:
                with open(a.output, "wb") as f:
                    f.write(data)
            else:
                print(hexdump(data, a.addr))
        elif a.cmd == "writemem":
            with open(a.file, "rb") as f:
                u.writemem(a.addr, f.read())
        elif a.cmd == "drive-mode":
            u.drive_mode(a.mode, a.drive)
        elif a.cmd == "load-rom":
            u.load_rom(a.file, a.drive)
        elif a.cmd == "pause":
            u.pause()
        elif a.cmd == "resume":
            u.resume()
        elif a.cmd == "type":
            u.type(a.text, c64=a.c64)
        elif a.cmd in ("wait", "run"):
            if a.cmd == "wait":
                flag = (a.addr, a.value)
                ok = u.wait(a.addr, a.value, a.timeout, delay=a.delay)
            else:
                flag = a.wait and (number(a.wait[0], 16), number(a.wait[1]))
                ok = u.run(a.file, a.drive, flag, a.timeout, a.delay)
            if not ok:
                print("ultimate.py: $%04X never became $%02X in %g s"
                      % (flag[0], flag[1], a.timeout), file=sys.stderr)
                return 1
    except UltimateError as e:
        print("ultimate.py: %s" % e, file=sys.stderr)
        return 1
    except (OSError, ValueError) as e:
        print("ultimate.py: %s" % e, file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
