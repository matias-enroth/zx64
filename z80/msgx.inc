; msgx.inc - a setting's message (msgs.inc) made into 32 characters,
; and the n-th message after one. Shared by zx64 and zx128. Needs nothing
; from its includer.

; HL: a message, kept short in msgs.inc: its text, then its key, each
; after its length (ZX81 codes, inverse). DE: 32 characters as the top row
; shows it, " text ...  key ", the key ending a column before the right
; edge. HL: after the message. DE must not cross a page boundary.
msgx:   push de
        ld b,32
mx_sp:  ld a,$80                ; inverse spaces
        ld (de),a
        inc de
        djnz mx_sp
        pop de
        push de
        inc de
        call mx_cp              ; the text from column 1
        pop de
        ld a,(hl)               ; the key, F and its digit, at column 29
        or a                    ; (0: none)
        ret z
        ex de,hl
        ld c,29                 ; (B is 0: djnz, or mx_cp's LDIR)
        add hl,bc
        ld (hl),$AB             ; F, inverse
        inc hl
        ld (hl),a
        ret
mx_cp:  ld a,(hl)
        inc hl
        or a
        ret z
        ld c,a
        ld b,0
        ldir
        ret

; HL: a message, A: n. HL: the message n after it.
msgn:   ld b,a
        inc b
mn_n:   dec b
        ret z
        ld a,(hl)               ; its text's length, the text, its key
        add a,2
        add a,l
        ld l,a
        jr nc,mn_n
        inc h
        jr mn_n
