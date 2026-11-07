; vicpic.inc - zx64's picture on the VIC: the ZX81's display file copied
; to the VIC's screen (blit), a setting's message over its top row (show,
; showb, ovl_put, ovl_top), and F2's colour schemes (nextcol, setcol,
; schemes). Shared by zx64 (z80/zx64.asm) and zx128vic (z80/zx128vic.asm).
; The colours are a macro, vic_colours, which the includer puts where its
; core has them (zx64's: after kbd.inc); the rest assembles where this is
; included. Includes msgx.inc. The includer provides:
;
;   equates   SCREEN (the VIC's screen, 40 columns: the picture from
;             column 4, 24 rows), DFILE VARS DSIZE MSGBUF
;   variables ovl ovl_msg scheme (vars.inc)
;   code      msgn, msg_col0 (msgs.inc), and the vic_wr, col_ptr,
;             col_wr and col_end macros
;   VFRAME    1: setcol colours the frame round the picture (the screen's
;             columns 0-3 and 36-39, row 24) the border's colour, the
;             picture's cells the characters'; 0: every cell the
;             characters'

; ---------------------------------------------------------------- picture
; Copy D_FILE to the VIC screen, 32 columns from column 4, 24 rows.
; A 16K ZX81 keeps the display fully expanded, 33 bytes a line; 1K
; programs bring a collapsed one, where a line ends at its $76.
ldi8:   macro
        ldi
        ldi
        ldi
        ldi
        ldi
        ldi
        ldi
        ldi
        endm

; A message for a setting (HL, from msgs.inc) on the top row for 2
; seconds, over the ZX81's picture: each copy of the picture puts it back
; right after copying the top row (ovl_top), while the VIC is still in the
; bottom border (after the whole copy would be too late: the VIC would
; already be drawing the top row). showb: HL is 32 characters already.
show:   ld de,MSGBUF
        push de
        call msgx
        pop hl
showb:  ld (ovl_msg),hl
        ld a,100
        ld (ovl),a
ovl_put:
        ld hl,(ovl_msg)
        ld de,SCREEN+4
        ld bc,32
        ldir
        ret

        include "msgx.inc"

ovl_top:                        ; the top row is copied: the message over it
        push af
        ld a,(ovl)
        or a
        jr z,ot_done
        push bc
        push de
        push hl
        call ovl_put
        pop hl
        pop de
        pop bc
ot_done:
        pop af
        ret

blit:   ld hl,(VARS)
        ld de,(DFILE)
        and a
        sbc hl,de
        ld bc,DSIZE
        sbc hl,bc               ; carry is clear: VARS >= D_FILE
        ex de,hl                ; HL = D_FILE
        jr nz,blit_c
        inc hl                  ; skip the leading $76
        ld de,SCREEN+4
        ld a,24
bf_line:
        ldi8
        ldi8
        ldi8
        ldi8
        inc hl                  ; skip the $76
        ex de,hl
        ld bc,8
        add hl,bc
        ex de,hl
        cp 24
        call z,ovl_top
        dec a
        jr nz,bf_line
        ret

blit_c: inc hl                  ; collapsed: copy each line to its $76
        ld de,SCREEN+4          ; and pad the row with spaces
        ld b,24
bc_line:
        ld c,32
bc_ch:  ld a,(hl)
        inc hl
        cp $76
        jr z,bc_pad
        ld (de),a
        inc de
        dec c
        jr nz,bc_ch
bc_skip:                        ; 32 characters copied: on to the $76
        ld a,(hl)
        inc hl
        cp $76
        jr nz,bc_skip
        jr bc_next
bc_pad: xor a
bc_p1:  ld (de),a
        inc de
        dec c
        jr nz,bc_p1
bc_next:
        ex de,hl
        ld a,b
        ld bc,8
        add hl,bc
        ld b,a
        ex de,hl
        cp 24
        call z,ovl_top
        djnz bc_line
        ret

; ---------------------------------------------------------------- colours
; (A macro: z80asm takes a label in one only on an instruction's line.)
vic_colours: macro
; F2 (SHIFT+F1 on a C64): the next colour scheme, as monochrome monitors
; had them, its name on the top row. F7 and F8 keep it, and so does the
; monitor, which puts it back as it leaves (SETCOL).
NSCHEMES: equ 6
nextcol: ld a,(scheme)
        inc a
        cp NSCHEMES
        jr c,nc1
        xor a
nc1:    ld (scheme),a
        call setcol
        ld a,(scheme)
        ld hl,msg_col0
        call msgn
        jp show

; The scheme into the VIC and colour RAM: the characters' colour (written
; to every cell, never read: see docs/cpm-cart.md), the background, the
; border. (VFRAME, zx128vic's and zx64's: the cells round the picture the
; border's colour instead.)
setcol: ld a,(scheme)
        ld l,a
        ld h,0
        ld e,l
        ld d,h
        add hl,hl
        add hl,de
        ld de,schemes
        add hl,de
        ld a,(hl)
        push hl
        if VFRAME
        inc hl                  ; the picture's 32x24
        inc hl                  ; cells the characters' colour, the frame round
        ld e,(hl)               ; them (columns 0-3 and 36-39 of rows 0-23,
        ld d,a                  ; all of row 24: a solid character, boot128's
        col_ptr                 ; vframe, zx64's start) the border's, so that
        ld a,e                  ; only the picture shows the background: D
        ld b,4                  ; the characters', E the border's
sf1:    col_wr                  ; row 0's columns 0-3
        inc hl
        djnz sf1
        ld c,24
sf2:    ld a,d                  ; a row's picture
        ld b,32
sf3:    col_wr
        inc hl
        djnz sf3
        ld a,e                  ; its columns 36-39, the next row's 0-3
        ld b,8
sf4:    col_wr
        inc hl
        djnz sf4
        dec c
        jr nz,sf2
        ld b,36                 ; the rest of row 24
sf5:    col_wr
        inc hl
        djnz sf5
        col_end
        else
        col_ptr                 ; colour RAM
        ld c,4
sc1:    ld b,250
sc2:    col_wr
        inc hl
        djnz sc2
        dec c
        jr nz,sc1
        col_end
        endif
        pop hl
        inc hl
        ld a,(hl)
        vic_wr $21
        inc hl
        ld a,(hl)
        vic_wr $20
        ret
                                ; characters, background, border (C64 colours):
schemes: db 0,1,1               ; black on white, as the boot sets it
        db 1,0,0                ; white on black
        db 13,0,0               ; green screen: light green on black
        db 8,0,0                ; amber: orange on black
        db 0,13,13              ; black on green
        db 14,6,14              ; the C64's own: light blue on blue
        endm
