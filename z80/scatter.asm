; scatter.asm - random characters (all 64 codes, normal and inverse) into
; random cells of an expanded D_FILE, 20 a frame for 250 frames (a 16-bit
; xorshift), then back to BASIC: machine code for a REM at 16514. Used by
; tools/sim128.py (pic_converges, pic_time).

        org 16514
        ld b,250
fr:     push bc
        ld a,($4034)
        ld (lastf),a
        ld b,20
cell:   push bc
        call xrnd
        ld a,h                  ; the row: 0-31 folded into 0-23
        and 31
        cp 24
        jr c,rowok
        sub 8
rowok:  ld c,a
        ld a,l                  ; the column
        and 31
        ld e,a
        ld d,0
        ld hl,($400C)
        inc hl
        add hl,de
        ld a,c
        or a
        jr z,addok
        ld de,33
rowl:   add hl,de
        dec c
        jr nz,rowl
addok:  push hl
        call xrnd
        ld a,l                  ; the character: 0-63 or 128-191
        and $BF
        pop hl
        ld (hl),a
        pop bc
        djnz cell
wait:   ld a,($4034)
        ld hl,lastf
        cp (hl)
        jr z,wait
        pop bc
        djnz fr
        ret
xrnd:   ld hl,$1D29
        ld a,h
        rra
        ld a,l
        rra
        xor h
        ld h,a
        ld a,l
        rra
        ld a,h
        rra
        xor l
        ld l,a
        xor h
        ld h,a
        ld (xrnd+1),hl
        ret
lastf:  db 0
        end
