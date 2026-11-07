; redraw8l.asm - (tools/sim128.py's pic_redraw) a big redraw:
; two screens (768 codes each, after the code: sim128.py's
; redraw_screens) into
; D_FILE in turn, every WAIT frames, NFLIP times. After each flip it
; counts the frames (FRAMES, one an IRQ) until zx128's shadow (SHADOW)
; equals D_FILE and then no run waits to be written (QN 0: the VDC shows
; the shadow): into res, one byte a flip (255: not within WAIT). res is
; in the system variables' page. Machine code for a REM at 16514; no $76 in it.

        include "redrawcfg.inc" ; NFLIP, WAIT (sim128.py)
SHADOW:  equ $C000              ; vdcpic.inc's: 24 rows of 32 codes
QN:      equ $C37A              ; and pic_qn: runs waiting
FRAMES:  equ $4034

        org 16514
        jr start
res:    ds 16,255               ; (16516: the frames, a flip each)
start:  ld hl,res
        ld (rp),hl
        ld b,NFLIP
fl:     push bc
        ld hl,scra
        bit 0,b
        jr z,fa
        ld hl,scrb
fa:     ld de,($400C)
        inc de
        ld c,24
rw:     push bc
        ld bc,32
        ldir
        inc de                  ; past the row's NEWLINE
        pop bc
        dec c
        jr nz,rw
        ld a,(FRAMES)
        ld (f0),a
ck:     call same
        jr nz,cn
cq:     ld a,(QN)               ; the shadow is D_FILE (and stays: nothing
        or a                    ; else writes it): once its runs are written
        jr z,cd
        call since
        cp WAIT
        jr c,cq
        jr wt
cd:     call since              ; how long it took
        ld hl,(rp)
        ld (hl),a
        jr wt
cn:     call since
        cp WAIT
        jr c,ck
wt:     call since             ; on WAIT frames after the flip
        cp WAIT
        jr c,wt
        ld hl,(rp)
        inc hl
        ld (rp),hl
        pop bc
        djnz fl
        ret

; A: the frames since the flip (FRAMES counts down)
since:  ld a,(f0)
        ld hl,FRAMES
        sub (hl)
        ret

; Z if the shadow equals D_FILE (an expanded one)
same:   ld hl,($400C)
        inc hl
        ld de,SHADOW
        ld c,24
sr:     ld b,32
sc:     ld a,(de)
        cp (hl)
        ret nz
        inc hl
        inc de
        djnz sc
        inc hl
        dec c
        jr nz,sr
        ret

rp:     dw 0
f0:     db 0
scra:                           ; (then scrb: sim128.py appends both)
scrb:    equ scra+768
