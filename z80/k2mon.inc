; k2mon.inc - the C128's own keys for the monitor's kscan (io128.inc's
; kscan_more), HL past its matrix (kmat+8). The numeric keypad as the
; main keys: the ZX81's k2scan.inc puts K0-K2's keys into cmat (k2keys:
; cmat is free while the monitor runs, the ZX81's scan makes it again),
; from all up, and they are taken into kmat from there (the digits, + -
; and ., ENTER as RETURN), so getkey, its repeat and kup take them as
; those; but not LEFT's and UP's keys there (<-, the up arrow: the
; ZX81's). The cursor keys in the top row as a C64's cursor keys, LEFT
; and UP with LSHIFT (column 1, row 7), as SHIFT+CRSR RIGHT and
; SHIFT+CRSR DOWN, so the monitor takes them as CRSR LEFT and UP. With
; SHIFT held too: SHIFT+RIGHT is left, SHIFT+DOWN up, SHIFT+LEFT and
; SHIFT+UP as they are, as on a C64. In the monitor's part 1 (mon.asm,
; MON128): only it calls this. The stick isn't looked at (zx64's monitor
; doesn't either). Uses A, BC, DE, HL. Shared by zx128 and zx128vic;
; core.inc has CREAD, CMAT and K2KEYS, io128.inc VIC.
k2mon:  push hl
        ld hl,CMAT
        ld b,8
km_up:  ld (hl),$FF             ; all up
        inc hl
        djnz km_up
        call K2KEYS             ; the C128's keys into it, as the ZX81's
        ld hl,CMAT+7
        set 1,(hl)              ; not LEFT's <-...
        dec hl
        set 6,(hl)              ; ...nor UP's up arrow (below)
        pop hl
        ld de,CMAT+8
        ld b,8
km_and: dec hl
        dec de
        ld a,(de)
        and (hl)
        ld (hl),a
        djnz km_and             ; HL: kmat
        inc hl                  ; column 1
        ld bc,VIC+$2F
        ld a,$FB
        out (c),a               ; K2 only: CREAD selects no C64 column
        ld a,$FF
        call CREAD              ; (keeps BC)
        ld d,a
        ld a,$FF
        out (c),a
        ld a,d
        add a,a
        add a,a
        and d                   ; bit 5: LEFT and UP both up
        bit 5,a
        jr nz,km_c0
        res 7,(hl)              ; LSHIFT
km_c0:  dec hl
        ld a,d
        add a,a
        and d                   ; bit 6: RIGHT and LEFT up, bit 4: DOWN and UP
        bit 6,a
        jr nz,km_dn
        res 2,(hl)              ; CRSR RIGHT
km_dn:  bit 4,a
        ret nz
        res 7,(hl)              ; CRSR DOWN
        ret
