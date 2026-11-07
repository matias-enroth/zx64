; vars.inc - the variables and tables of zx64's core, which kbd.inc and
; the other shared includes use: zx128 has them all too (some, as bpcnt
; and scheme, only for what zx64 has). Includes the
; tables tools/build.py writes to build/obj: keychr.inc, zx2pet.inc,
; msgs.inc, keymap.inc, kshift.inc.

; ---------------------------------------------------------------- data
tick:     db 0                  ; frames seen, low byte
irqseen:  db 0                  ; an IRQ has arrived: /INT is wired
d1active: db 0                  ; the ROM's DISPLAY-1 ran within 2 frames
inkbd:    db 0                  ; mykbd is running
stray:    dw 0                  ; IRQs taken with the VIC's raster flag clear
kbuf:     db 1                  ; type-ahead on (F1 switches it; F7 keeps it)
edit:     db 0                  ; the editor or INPUT is taking keys
eframes:  db 0                  ; frames since its key wait, to 50
f1down:   db 0                  ; F1 is down
f5down:   db 0                  ; F5 is down
monreq:   db 0                  ; F5 pressed: the monitor at the next chance
moniff:   db 0                  ; the monitor goes back with interrupts on
monwhy:   db 0                  ; 0 F5, 1 a breakpoint
bpcnt:    db 0                  ; the monitor's breakpoints armed (bptab)
ramsize:  db 1                  ; 0 1K, 1 16K, 2 32K (F8; F7 keeps it)
scheme:   db 0                  ; the colours (F2; F7 keeps them)
joyidx:   db 0                  ; the stick's layout, 0 5678+0, 1 taught (F3; F7 keeps it)
joyhave:  db 0                  ; a custom layout has been taught
jnow:     db $FF                ; the stick at this scan (jread)
jprev:    db $FF                ; at the last one (jmerge)
jlast:    db $FF                ; the entry KEYBOARD gets, $FF none
jmulti:   db 0                  ; more than one stick key down (jone)
joylays:                        ; up, down, left, right, fire (see jread)
        db $EF,$F7, $EF,$EF, $F7,$EF, $EF,$FB, $EF,$FE  ; 7 6 5 8 0
joycus: db $FE,$FF, $FE,$FF, $FE,$FF, $FE,$FF, $FE,$FF  ; taught (hold F3)
f3on:     db 0                  ; F3 down: 1, held a second: 2
f3t0:     db 0                  ; tick as F3 went down
f3old:    db 0                  ; joyidx before it
teaching: db 0                  ; hold F3 is asking for keys
        include "keychr.inc"
hello:    db 1                  ; the version not shown yet
ramtops:  dw $43FF,$7FFF,$BFFF  ; the last byte of RAM for each
ovl:      db 0                  ; frames the message stays on the top row
ovl_msg:  dw 0                  ; the message
kq_in:    db 0                  ; the type-ahead queue: 16 slots, 15 keys, as HL
kq_out:   db 0
kpup:     db 0                  ; kprev is all up
kand:     db $FF                ; the rows ANDed, for KALL
kprev:    db $FF,$FF,$FF,$FF,$FF,$FF,$FF,$FF  ; the ZX81 rows at the last scan
zx2pet:                         ; ZX81 code 0-27 -> PETSCII
        include "zx2pet.inc"
        include "msgs.inc"
keymap:
        include "keymap.inc"
kshtab:                         ; (kshift)
        include "kshift.inc"
