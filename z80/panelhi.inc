; panelhi.inc - the panel's (panel.inc) parts in the own area (zx128.asm),
; as common RAM has no room for them: show's messages, F2's colours.

; showb's: a message (ovl_msg) for 2 seconds, A = 100. While F3 is held
; (teach: interrupts off, no pic_step) its rows are written at once,
; polled. pn_shnow: the same, and row 9 (F8's size), for F7 and F8
; (reset.inc's rs_show, hw128.inc): the ZX81 starts again, its RAM test
; with interrupts off for up to seconds (32K), so the IRQ would show them
; only after it.
pn_show:
        ld (ovl),a
        call panel_set
        ld a,(teaching)
        or a
        ret z
pn_shnow:
        ld a,9
        call pn_now
        ld a,13
        call pn_now
        ld a,14
pn_now: push af
        call pn_row
        pop af
        call bo_r80
        ld bc,64
        add hl,bc
        ld de,$FF10             ; (pn_buf's 16)
        jp pn_pol

; F2 (SHIFT+F1): the next colour scheme, its name in the messages' rows.
nextcol:
        ld a,(scheme)
        inc a
        cp SCHEMES
        jr c,nx_s
        xor a
nx_s:   ld (scheme),a
        call pn_col
        ld a,(scheme)
        ld hl,msg_col0
        call msgn
        jp show

; HL: the scheme's colours: R26 (the background), the picture's
; attribute, the panel's (set 1: bit 7), in the VDC's RGBI colours. zx128's
; own four, the first at start (vars.inc's scheme 0, boot128's
; vdcinit's colours). Changes AF.
pn_sc:  push bc
        ld a,(scheme)
        ld c,a
        add a,a
        add a,c
        ld c,a
        ld b,0
        ld hl,pn_cols
        add hl,bc
        pop bc
        ret
pn_cols:
        db $F0,$0F,$8F          ; white on black
        db $50,$05,$85          ; C128: light green on black
        db $32,$03,$83          ; C64: light blue on dark blue
        db $0E,$00,$80          ; ZX81: black on light grey
