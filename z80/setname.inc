; setname.inc - a ZX81 name to the mailbox as PETSCII. Shared by zx64 and
; zx128. The includer provides MBOX and zx2pet (vars.inc).

; DE = name in ZX81 codes, C = length-1  ->  PETSCII name in the mailbox,
; 16 characters at most (the last one has bit 7 set by NAME: dropped).
setname:
        ld a,c
        inc a
        cp 17
        jr c,sn1
        ld a,16
sn1:    ld (MBOX+2),a
        ld b,a
        ld hl,MBOX+3
sn2:    ld a,(de)
        and $3F
        cp 38                   ; A-Z
        jr c,sn_dig
        add a,'A'-38
        jr sn4
sn_dig: cp 28                   ; 0-9
        jr c,sn_tab
        add a,'0'-28
        jr sn4
sn_tab: push de                 ; the rest: zx2pet
        ld de,zx2pet
        add a,e
        ld e,a
        jr nc,sn3
        inc d
sn3:    ld a,(de)
        pop de
sn4:    ld (hl),a
        inc hl
        inc de
        djnz sn2
        ret
