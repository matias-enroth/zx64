#!/usr/bin/env python3
"""ZX0 (Einar Saukas's format, version 2, forward) in Python: pack() and
unpack(), for the function ROM's image (tools/build.py; c128/from.asm
unpacks it on the 8502).

The format, as its README describes it: a stream of bits (read from a
byte's top bit down, a new byte when they run out) with whole bytes
(literals, an offset's low bits) in between, in the order they are read.
Three blocks:
  literals            0, Elias(length), the bytes
  copy, last offset   0, Elias(length)
  copy, new offset    1, Elias(MSB + 1), a byte, Elias(length - 1)
The first block is literals, without its 0; after literals comes a copy
(0: the last offset, 1: a new one); after a copy, literals (0) or a copy
from a new offset (1). The last offset starts as 1. Elias(v) is interlaced
Elias gamma: for each bit of v below its top one, from the top, a 0 then
the bit; then a 1. A new offset (1 to 32640) is MSB = (offset - 1) / 128,
its Elias data bits inverted, then the byte (127 - (offset - 1) % 128) * 2,
whose bit 0 is Elias(length - 1)'s first bit (a 1: length 2). MSB + 1 =
256 (no byte after it) ends the stream.

pack() parses for the fewest bits in one pass from the front: each
position keeps its best way in, ended by a copy or by literals, and a
copy at the last offset uses the offset its way in has (one, where the
reference compressor keeps every offset: a little less tight). Its
weight trades size for the unpacker's time on the 8502: a block costs its
bits plus weight times CYCLES' guess of its cycles (0: the smallest).
Deterministic: the same bytes in, the same bytes out. Written from the
format's description, not checked against the reference tools (none are
here); unpack() and c128/from.asm agree with pack().
"""

import sys

MAX_OFFSET = 32640              # (offset - 1) / 128 + 1 <= 255: MSB + 1 = 256 is the end
LONG = 48                       # a copy longer than this: only its full length is tried (and up to this)


def elias_bits(v):
    """Bits of Elias(v), v >= 1."""
    return 2 * v.bit_length() - 1


def matches(d, maxoff=MAX_OFFSET):
    """For each position i of d: [(length, offset)], the lengths rising,
    each with the nearest offset that gives it (2 bytes at least): a hash
    chain on the next two bytes."""
    n = len(d)
    head, prev, out, last = {}, [-1] * n, [()] * n, {}
    run = [0] * n                               # where the run of equal bytes at i starts
    for i in range(1, n):
        run[i] = run[i - 1] if d[i] == d[i - 1] else i
    for i in range(n - 1):
        key = d[i] << 8 | d[i + 1]
        j, best, lim, res = head.get(key, -1), 1, n - i, []
        while j >= 0 and i - j <= maxoff:
            if d[j + best] == d[i + best]:
                k = last.get(i - j, 0) - 1       # (one less than the last position's, at the same offset)
                if k < 2:
                    k = 2
                    while k < lim and d[j + k] == d[i + k]:
                        k += 1
                if k > best:
                    res.append((k, i - j))
                    best = k
                    if k == lim:
                        break
            if j > run[i] and d[i] == d[i + 1]:  # (the rest of i's run gives no more: past it)
                j = run[i]
            j = prev[j]
        prev[i], head[key] = head.get(key, -1), i
        out[i] = res
        last = {o: k for k, o in res}
    return out


def parse(d, weight=0.0, window=256):
    """The blocks for d: [("lit", length), ("rep", length), ("new", offset,
    length)]. A block's cost is its bits, plus weight times CYCLES' guess
    of the 6502's cycles for it (0: the smallest)."""
    n = len(d)
    if n == 0:
        raise ValueError("ZX0 needs at least one byte")
    inf = float("inf")
    cm, mway, moff = [inf] * (n + 1), [None] * (n + 1), [1] * (n + 1)   # ended by a copy
    cl, lway, loff = [inf] * (n + 1), [0] * (n + 1), [1] * (n + 1)      # ended by literals
    cyc = CYCLES
    lit_c = [0] + [cyc["lit"] + cyc["lit_byte"] * k for k in range(1, n + 1)]
    m = matches(d)
    reps = {}                                    # a last offset's copy: where it was measured, its length
    slope = 8 + weight * cyc["lit_byte"]
    far, fs = inf, -1                            # the best start further back than window
    for p in range(n + 1):
        if p:                                    # literals from s to p (s 0, or after a copy)
            best, bs = inf, -1
            for s in range(p - 1, max(-1, p - window - 1), -1):
                base = 0 if s == 0 else cm[s] + 1
                if base < inf:
                    k = p - s
                    c = base + elias_bits(k) + 8 * k + weight * lit_c[k]
                    if c < best:
                        best, bs = c, s
            s = p - window - 1                   # (one more falls out of the window)
            if s >= 0:
                base = 0 if s == 0 else cm[s] + 1
                if base - slope * s < far:
                    far, fs = base - slope * s, s
            if fs >= 0:
                k = p - fs
                c = (0 if fs == 0 else cm[fs] + 1) + elias_bits(k) + 8 * k + weight * lit_c[k]
                if c < best:
                    best, bs = c, fs
            cl[p], lway[p] = best, bs
            loff[p] = 1 if bs == 0 else moff[bs]
        if p == n:
            break
        if p and cl[p] < inf:                    # a copy at the last offset, after literals
            o = loff[p]
            q, k = reps.get(o, (p, 0))
            k -= p - q                           # (as far as it went from q, less the way since)
            if k < 1:
                k = 0
                while p + k < n and d[p + k - o] == d[p + k]:
                    k += 1
            reps[o] = p, k
            for ln in list(range(1, min(k, LONG) + 1)) + ([k] if k > LONG else []):
                c = cl[p] + 1 + elias_bits(ln) + weight * (cyc["rep"] + cyc["byte"] * ln)
                if c < cm[p + ln]:
                    cm[p + ln], mway[p + ln], moff[p + ln] = c, ("rep", p, ln, o, 1), o
        for frm, base in ((1, cl[p]), (0, cm[p])):   # a copy from a new offset
            if not p or base == inf:
                continue
            lo = 2
            for k, o in m[p]:
                oc = base + 1 + elias_bits((o - 1) // 128 + 1) + 8 + weight * cyc["new"]
                for ln in list(range(lo, min(k, LONG) + 1)) + ([k] if k > LONG else []):
                    c = oc + elias_bits(ln - 1) - 1 + weight * cyc["byte"] * ln
                    if c < cm[p + ln]:
                        cm[p + ln], mway[p + ln], moff[p + ln] = c, ("new", p, ln, o, frm), o
                lo = k + 1
    blocks = []                                   # back from the end
    p, lit = n, cl[n] <= cm[n]
    while p:
        if lit:
            s = lway[p]
            blocks.append(("lit", p - s))
            p, lit = s, False
        else:
            kind, q, ln, o, frm = mway[p]
            blocks.append(("rep", ln) if kind == "rep" else ("new", o, ln))
            p, lit = q, bool(frm) if kind == "new" else True
    blocks.reverse()
    return blocks


# The 6502's cycles for a block, roughly (c128/from.asm's unpacker): lit,
# rep, new for the block, byte for each byte a copy makes, lit_byte for
# each literal. Only weight * these count in parse().
CYCLES = dict(lit=60, lit_byte=18, rep=70, new=115, byte=18)


class Bits:
    """The stream as it is written: bits into a byte put in when the last
    one is full (where the unpacker reads its next), bytes in between;
    back: the next bit goes into the byte just written's bit 0."""

    def __init__(self):
        self.out, self.mask, self.at, self.back = bytearray(), 0, 0, False

    def bit(self, b):
        if self.back:                            # the byte just written's bit 0
            if b:
                self.out[-1] |= 1
            self.back = False
            return
        if not self.mask:
            self.mask, self.at = 0x80, len(self.out)
            self.out.append(0)
        if b:
            self.out[self.at] |= self.mask
        self.mask >>= 1

    def byte(self, v):
        self.out.append(v)

    def elias(self, v, invert=False):
        top = v.bit_length() - 1
        for i in range(top - 1, -1, -1):
            self.bit(0)
            self.bit((v >> i & 1) ^ invert)
        self.bit(1)


def write(d, blocks):
    """The ZX0 stream for d's blocks."""
    w, p, first = Bits(), 0, True
    for blk in blocks:
        if blk[0] == "lit":
            if not first:
                w.bit(0)
            w.elias(blk[1])
            for b in d[p:p + blk[1]]:
                w.byte(b)
            p += blk[1]
        elif blk[0] == "rep":
            w.bit(0)
            w.elias(blk[1])
            p += blk[1]
        else:
            o, ln = blk[1], blk[2]
            w.bit(1)
            w.elias((o - 1) // 128 + 1, invert=True)
            w.byte((127 - (o - 1) % 128) << 1)
            w.back = True
            w.elias(ln - 1)
            p += ln
        first = False
    w.bit(1)                                      # the end: MSB + 1 = 256
    w.elias(256, invert=True)
    return bytes(w.out)


def pack(d, weight=0.0):
    """d packed (ZX0), and checked by unpacking it again."""
    d = bytes(d)
    out = write(d, parse(d, weight))
    if unpack(out) != d:
        raise AssertionError("zx0: the packed stream doesn't unpack to its input")
    return out


def unpack(s, copies=None):
    """A ZX0 stream unpacked. copies: a list that gets, for each copy as
    it is made, (the stream's bytes read by then, the output's length
    before it, its offset, its length)."""
    s = bytes(s)
    out = bytearray()
    st = dict(i=0, mask=0, cur=0, back=False)

    def byte():
        v = s[st["i"]]
        st["i"] += 1
        return v

    def bit():
        if st["back"]:
            st["back"] = False
            return st["last"] & 1
        if not st["mask"]:
            st["cur"], st["mask"] = byte(), 0x80
        b = 1 if st["cur"] & st["mask"] else 0
        st["mask"] >>= 1
        return b

    def elias(invert=False):
        v = 1
        while not bit():
            v = v << 1 | (bit() ^ invert)
        return v

    def copy(n):
        if last > len(out):
            raise ValueError(f"zx0: offset {last} before the start")
        if copies is not None:
            copies.append((st["i"], len(out), last, n))
        for _ in range(n):
            out.append(out[-last])
    last, state = 1, "lit"
    while True:
        if state == "lit":
            for _ in range(elias()):
                out.append(byte())
            state = "new" if bit() else "rep"
        elif state == "rep":
            copy(elias())
            state = "new" if bit() else "lit"
        else:
            msb = elias(invert=True)
            if msb == 256:
                return bytes(out)
            lsb = byte()
            st["last"], st["back"] = lsb, True
            last = (msb - 1) * 128 + 127 - (lsb >> 1) + 1
            copy(elias() + 1)
            state = "new" if bit() else "lit"


def phase1_reads(s, at, out=0x1300, split=0xC000, limit=0x8000):
    """For the stream s unpacked from address at to out, as c128/from.asm
    does it: the copies that would read the ROM's bytes, not the output's,
    as [(its first output address, the last address it reads)]: those made
    while the stream's pointer is below split (the function ROM still at
    $8000-$BFFF then) that read at limit or above, and any that reads at
    split or above (the ROM is at $C000 in both phases). None, or the
    unpack goes wrong."""
    cps = []
    unpack(s, cps)
    bad = []
    for i, pos, off, n in cps:
        last = out + pos - off + n - 1
        if (at + i < split and last >= limit) or last >= split:
            bad.append((out + pos, last))
    return bad


if __name__ == "__main__":
    import time
    for path in sys.argv[1:]:
        data = open(path, "rb").read()
        t = time.time()
        packed = pack(data)
        print(f"{path}: {len(data)} -> {len(packed)} ({len(packed) / len(data):.3f}) in {time.time() - t:.1f} s")
