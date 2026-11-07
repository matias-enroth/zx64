; reset.inc - F7 (start the ZX81 again) and F8 (the next memory size),
; and romsum, the check of the ROM's bytes before it. Shared by zx64 and
; zx128. The includer provides:
;
;   equates   KALL KALL_ROM RAMFILL
;   variables ramsize inkbd d1active ramtops (vars.inc)
;   code      bp_off (the monitor's breakpoints out), cread, held,
;             shifted (kbd.inc), msgn, show, msg_1k (msg_16k and msg_32k
;             after it), romfix (the ROM again, when romsum says it
;             changed), and the cia1_rd/cia1_wr and rs_show macros
;   build.py  puts the patched ROM's sum in romsum_v

; F7: start the ZX81 again, as at power on, once the key is up (or the
; restarted ROM would see it still down). The ROM's start sets up the
; rest, the stack too; zx64's own state is put back here. Works wherever
; the keyboard or BREAK is read: always in SLOW mode, and in FAST mode
; between BASIC statements, but not in machine code that reads no keys.
; F8 (SHIFT+F7) does the same with the next memory size, 1K, 16K, 32K, as if with
; another RAM pack: the ROM's RAM-FILL finds RAMTOP up to the last byte
; in BC (and NEW keeps it). The size is shown on the top row.
f7brk:  ld a,$FD                ; F7 in BREAK-1, which has no fresh cmat: SHIFT
        call cread              ; read now (the stick's ghosts aren't taken
        and $80                 ; out, but F7 is held)
        jr z,memsize
        ld a,$BF
        call cread
        and $10
        jr z,memsize
        jr reset
f7go:   call shifted            ; F8 (SHIFT+F7): the next memory size
        jr z,memsize
reset:  ld c,$08                ; F7's bit in column 0
        jr rs_go
memsize:
        ld a,(ramsize)
        inc a
        cp 3
        jr c,ms_set
        xor a
ms_set: ld (ramsize),a
        ld c,$08                ; F7's bit (F8 is SHIFT+F7)
rs_go:  di
        call bp_off
        ld a,$FE
        cia1_wr 0               ; column 0
rs_up:  cia1_rd 1
        and c
        jr z,rs_up
        ld a,$FF
        cia1_wr 0
        xor a
        ld (inkbd),a
        ld (d1active),a
        ld a,(ramsize)          ; msg_1k, msg_16k, msg_32k
        ld hl,msg_1k
        call msgn
        rs_show                 ; (show, and on zx128 at once)
        ld a,KALL_ROM           ; the ROM's own byte where zx64 puts the rows
        ld (KALL),a
        call romsum             ; has a program written over the ROM?
        call nz,romfix
        ld a,(ramsize)
        add a,a
        ld e,a
        ld d,0                  ; (show moved DE)
        ld hl,ramtops
        add hl,de
        ld c,(hl)
        inc hl
        ld b,(hl)
        jp RAMFILL              ; what the ROM's START does with BC = $7FFF,
                                ; not JP $0000: START is overwritten (romsum)

; The ROM is RAM here, and a program's OUT to an add-on that isn't there
; can land in it (aydemo.p's AY board: OUT ($DF),A to A*256+$DF). F7 and F8
; check it first: its bytes from $0005 on added up (the ROM's calculator
; writes to $0000-$0004 itself), against the sum build.py puts in
; romsum_v. NZ: changed.
romsum: ld hl,5
        ld de,0
        ld bc,$2000-5
rsm1:   ld a,(hl)
        add a,e
        ld e,a
        jr nc,rsm2
        inc d
rsm2:   inc hl
        dec bc
        ld a,b
        or c
        jr nz,rsm1
        ld hl,(romsum_v)
        or a
        sbc hl,de
        ret
romsum_v:
        dw 0
