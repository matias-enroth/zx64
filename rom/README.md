# rom/

Your ZX81 ROM goes here as `zx81.rom` (not included; it's Sinclair's).
The standard second-version ROM: 8192 bytes, md5
`db398d4e4e93a6d4dee3bfe146918219`. `make` checks the bytes it patches
and refuses another ROM. Elsewhere: `make ROM=path/to/rom`.

## Dumping your own ROM (ZXpand)

With a ZXpand on your ZX81, `romdump.p` copies the ROM to RAM. The
ZXpand shows its own patched ROM at 0-8191, so the routine turns that
off first (until reset), copies Sinclair's ROM to 32768, and waits.

1. Copy `romdump.p` to the SD card, `LOAD "ROMDUMP"` and `RUN` it.
   (`romdump.bas` is its listing.)
2. When the screen goes blank, press the ZXpand's reset button. The
   ZXpand's ROM is back, and the copy is still there: the ROM's start-up
   only clears the RAM below 32768.
3. `PRINT PEEK 32768` should give 211 (the ROM's first byte), then
   `SAVE "ZX81ROM;32768,8192"`.
4. The card now has `ZX81ROM.P`, the ROM's 8192 bytes: copy it here as
   `zx81.rom`. `make` checks it.
