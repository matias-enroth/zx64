; blk8l.asm - (tools/sim128.py's pic_blk checks)
; a SCROLL or a CLS of a full screen, NFLIP times: the ROM's CLS, rows 0
; to 21 of D_FILE filled (each its own characters), WAIT frames to
; settle, then the command (OP 1: SCROLL, 2: CLS) through the ROM's
; command table, as BASIC calls it (zx128's hooks are there; a build
; without them runs the ROM's own). From its return it counts the frames
; (FRAMES, one an IRQ) until no run waits to be written and no block
; operation waits or goes on (looked at often: the frame that happens
; in) with zx128's shadow then equal to D_FILE (a collapsed row padded
; with spaces: a SCROLL leaves one): into res, one byte a flip (255: not
; within WAIT). OP 3: a SCROLL (the display collapsed), then
; PRINT AT 21,0 and a line, a character at a time into the collapsed
; line (the ROM's PRINT-AT and PRINT-A, as BASIC's PRINT: MAKE-ROOM for
; each), the frames from its last to the same into lagr, then the
; measured SCROLL. res and lagr are in the system variables' page. (The
; frame recorded is the last one seen
; idle before same confirmed the shadow: for these full-screen
; operations the VDC is D_FILE's by then; in general, an IRQ during same
; doing the last of it, it can read a frame early.) Machine code for a
; REM at 16514; no $76 in it.

        include "blkcfg.inc"    ; NFLIP, WAIT, OP (sim128.py)
SHADOW:  equ $C000              ; vdcpic.inc's: 24 rows of 32 codes
QN:      equ $C37A              ; pic_qn: runs waiting
BPEND:   equ $C3A8              ; blk_pend, blk_k: block operations waiting,
BK:      equ $C3AA              ; going on (0 in a build without them)
FRAMES:  equ $4034
TAB_CLS: equ $0C96              ; the command table's CLS and SCROLL
TAB_SCR: equ $0CA5

PRINTAT: equ $08F5              ; the ROM's PRINT-AT: B line, C column

        org 16514
        jr start
res:    ds 16,255               ; (16516: the frames, a flip each)
lagr:   ds 16,255               ; (16532: OP 3's, the PRINT's)
start:  ld hl,res
        ld (rp),hl
        ld hl,lagr
        ld (lp),hl
        ld b,NFLIP
fl:     push bc
        ld hl,(TAB_CLS)         ; a clean expanded display
        call jphl
        ld hl,($400C)           ; rows 0-21: row r column c = (r + c) & $3F,
        inc hl                  ; inverse on odd rows
        ld c,0
rw:     ld b,32
        ld e,c
ch:     ld a,e
        and $3F
        bit 0,c
        jr z,ch1
        or $80
ch1:    ld (hl),a
        inc hl
        inc e
        djnz ch
        inc hl                  ; past the row's NEWLINE
        inc c
        ld a,c
        cp 22
        jr nz,rw
        call now
        ld (f0),a
st:     call since              ; settled
        cp WAIT
        jr c,st
        if OP = 3
        ld hl,(TAB_SCR)         ; a SCROLL: the display collapsed
        call jphl
        ld bc,21*256            ; PRINT AT 21,0; the line
        call PRINTAT
        ld hl,line
pl:     ld a,(hl)
        inc a
        jr z,pd
        dec a
        push hl
        rst $10
        pop hl
        inc hl
        jr pl
pd:     call now
        ld (f0),a
pw:     ld a,(QN)               ; (as below)
        ld hl,BPEND
        or (hl)
        ld hl,BK
        or (hl)
        jr nz,pn
        call since
        ld (fd),a
        call same
        jr z,pe
pn:     call since
        cp WAIT
        jr c,pw
        ld a,255
        ld (fd),a
pe:     ld a,(fd)
        ld hl,(lp)
        ld (hl),a
        inc hl
        ld (lp),hl
        endif
        if OP = 2
        ld hl,(TAB_CLS)
        else
        ld hl,(TAB_SCR)
        endif
        call jphl
        ld hl,opn               ; (one more: tools/sim128.py watches it)
        inc (hl)
        call now
        ld (f0),a
ck:     ld a,(QN)               ; no run waits and no block operation is
        ld hl,BPEND             ; left (looked at often: the frame it
        or (hl)                 ; happens in, not same's ~0.7 frame later)
        ld hl,BK
        or (hl)
        jr nz,cn
        call since
        ld (fd),a
        call same               ; and the shadow is D_FILE: done then
        jr z,cd
cn:     call since
        cp WAIT
        jr c,ck
        jr nx
cd:     ld a,(fd)               ; how long it took
        ld hl,(rp)
        ld (hl),a
nx:     ld hl,(rp)
        inc hl
        ld (rp),hl
        pop bc
        dec b
        jp nz,fl
        ret

jphl:   jp (hl)

now:    ld a,(FRAMES)
        ret

; A: the frames since f0 (FRAMES counts down)
since:  ld a,(f0)
        ld hl,FRAMES
        sub (hl)
        ret

; Z if the shadow equals D_FILE: each row to its NEWLINE, the rest of
; the 32 spaces
same:   ld hl,($400C)
        inc hl
        ld de,SHADOW
        ld c,24
sr:     ld b,32
sc:     ld a,(hl)
        sub $75                 ; (a NEWLINE: no $76 byte in the code)
        dec a
        jr z,sp
        ld a,(hl)
        ex de,hl
        cp (hl)
        ex de,hl
        ret nz
        inc hl
        inc de
        djnz sc
        jr se
sp:     ld a,(de)               ; past the row's end: spaces
        or a
        ret nz
        inc de
        djnz sp
se:     ld a,(hl)               ; the row's NEWLINE
        sub $75
        dec a
        ret nz
        inc hl
        dec c
        jr nz,sr
        ret

rp:     dw 0
lp:     dw 0
f0:     db 0
fd:     db 0                    ; the frame the picture was found idle in
opn:    db 0                    ; the commands done
line:   db $31,$2E,$33,$2A,$00,$1D,$00,$26,$27,$28,$29,$2A,$2B,$2C,$2D
        db $2E,$2F,$30,$31,$32,$33,$34,$35,$36,$37,$38,$FF ; LINE 1 ABC..S
