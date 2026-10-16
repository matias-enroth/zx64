; zx64 memory test, for mem.bas: in its first line's REM, so at 16514,
; called by USR 16514. Tests every free byte, from STKEND + 64 up to the
; Z80's stack - 64 (the IRQ's room), in two passes: each byte first gets
; the low XOR high byte of its address, all of them; then each is read
; back, and its complement written and read. Writing all before reading
; any shows a byte that is really another one (16K away, say).
; Returns BC = the bad bytes; mt_from, mt_to and mt_first for PEEK.
; The bytes go into a REM, so none may be $76 (zxbasic.py checks).

STKEND: equ $401C

        org 16514

        ld hl,(STKEND)
        ld de,64
        add hl,de
        ld (mt_from),hl
        ld hl,0
        add hl,sp
        and a
        sbc hl,de
        ld (mt_to),hl
        ld de,(mt_from)
        and a
        sbc hl,de
        ld (mt_len),hl
        ld hl,0
        ld (mt_bad),hl
        ld (mt_first),hl

        ld hl,(mt_from)         ; pass 1: write them all
        ld bc,(mt_len)
p1:     ld a,l
        xor h
        ld (hl),a
        inc hl
        dec bc
        ld a,b
        or c
        jr nz,p1

        ld hl,(mt_from)         ; pass 2: read back, then the complement
        ld bc,(mt_len)
p2:     ld a,l
        xor h
        cp (hl)
        call nz,bad
        cpl
        ld (hl),a
        cp (hl)
        call nz,bad
        inc hl
        dec bc
        ld a,b
        or c
        jr nz,p2
        ld bc,(mt_bad)
        ret

bad:    push af                 ; count it; the first one's address
        push de
        ld de,(mt_bad)
        ld a,d
        or e
        jr nz,bad1
        ld (mt_first),hl
bad1:   inc de
        ld (mt_bad),de
        pop de
        pop af
        ret

mt_from:  dw 0
mt_to:    dw 0                  ; the first byte not tested
mt_len:   dw 0
mt_bad:   dw 0
mt_first: dw 0
