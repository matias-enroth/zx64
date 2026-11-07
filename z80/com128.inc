; com128.inc - the C128 builds' code in common RAM, zx128's and
; zx128vic's, at ZCOM: zentry (where the Z80 starts), zsw (call6510's CPU
; switch), inrow (a game's keyboard read, patched at LOAD), rombk
; (F7's ROM). The includer provides CR CR_Z80 CR_IO SWITCH (io128.inc),
; ROM01 KPAGE MBOX, call6510 (call128.inc), and the zentry_more macro
; (its own start: may change any register but SP) and zsw_cpu (zsw's,
; below: may change AF BC).

; The Z80 starts here (JP zentry at $FFEE) when the 8502 first hands over,
; $FF00 still as the 8502 had it (I/O on, to reach the CPU switch): the
; Z80's own first. The 8502 has written bank 1, but not its pages 0 and 1
; (the page pointers make them its own zero page and stack): the ROM's
; first 512 bytes wait at ROM01. The keyboard page and the mailbox start
; clear; then the build's own start (zentry_more: zx128's picture shadow
; and panel), then the ZX81's power on. No interrupts meanwhile: the 8502
; has enabled the raster IRQ, and $0038 isn't in place yet.
zentry: di
        ld a,CR_Z80
        ld (CR),a
        ld hl,ROM01
        ld de,0
        ld bc,$200
        ldir
        ld hl,KPAGE
        ld de,KPAGE+1
        ld bc,$1FF
        ld (hl),0
        ldir
        zentry_more             ; (the build's own)
        jp 0

; call6510's switch: $FF00 with I/O on, for the MMU, then the 8502 runs
; until it hands back; $FF00 is then whatever it left, so the Z80's goes
; back first. zsw_cpu (the includer's macro) as the 8502 takes over and
; once it is back: zx128's panel shows which CPU has the machine. Changes
; A and F only (call6510 keeps the registers zx64's does).
zsw:    push bc
        zsw_cpu
        ld a,CR_IO
        ld (CR),a
        ld bc,SWITCH
        ld a,$B1
        out (c),a               ; the 8502 runs...
        nop                     ; (on the cartridge the byte after the switch
                                ; can be lost: kept, as no one knows yet here)
        ld a,CR_Z80             ; ...and has handed back
        ld (CR),a
        zsw_cpu
        pop bc
        ret

; A game's own keyboard read, LD A,(HL) / IN A,($FE) with the
; row's select from its table, is made CALL inrow as it loads (BoulderL:
; build.py's patches_load128): with A = $DF, IN reads I/O 2 on the C128,
; not the IN mirror. A: what IN would read on zx64, the mirror's copy at
; A*256+$FE (every stick key in it: KPAGE has jone's one). Keeps the
; rest, the flags too.
inrow:  ld a,(hl)
        push hl
        ld h,a
        ld l,$FE
        ld a,(hl)
        pop hl
        ret

; romfix's: the 8502 puts the ROM back (CMD_ROM), all but its
; first two pages, which it can't write here (its own I/O port answers
; for $0000 and $0001): it leaves them at ROM01, as at boot, and they go
; in place here, if it says it put the ROM back.
rombk:  call call6510
        ld a,(MBOX+1)
        or a
        ret nz
        ld hl,ROM01
        ld d,a
        ld e,a
        ld bc,$200
        ldir
        ret
