; zx64 - Z80 side. The ZX81 ROM runs on the C64 CP/M cartridge's Z80, and
; this code sits next to it, doing what the ZX81's ULA and tape port did:
; the picture, the keyboard, LOAD and SAVE.
;
; Z80 view of memory (C64 address = Z80 address + $1000, wrapping):
;   0000-1FFF  ZX81 ROM, patched by tools/build.py   (C64 1000-2FFF)
;   2000-2DFF  this code and its tables              (C64 3000-3DFF)
;   2E00-2EFF  ZX81 keyboard rows, indexed by B      (C64 3E00-3EFF)
;   2F00-2FFF  mailbox to the 6510                   (C64 3F00-3FFF)
;   4000-BFFF  ZX81 RAM: 16K to 7FFF, 32K to BFFF     (C64 5000-CFFF)
;   3000-3FFF  zx64mon, once F5 has loaded it        (C64 4000-4FFF)
;   C000-CFFF  C64 I/O: VIC C000, CIA1 CC00, cartridge switch CE00
;   D000-D3FF  VIC screen, font at D800              (C64 E000-E3FF)
;   D400-D7FF  the monitor's stack                   (C64 E400-E7FF)
;   E000-EFFF  zx64mon2, the monitor's second part   (C64 F000-FFFF)
;   F000-FFFF  the 6510's page: its loader           (C64 0000-0FFF)
;
; Entry points, all reached from the patched ROM (see tools/build.py):
;   irqh      RST $38, the VIC raster IRQ at line 250, once a frame
;   frame     DISPLAY-1's picture: wait for the next frame
;   keywait   the editor's call of DISPLAY-1 (its key wait)
;   slowfast  SLOW/FAST
;   mykbd     KEYBOARD
;   brk       BREAK-1's IN A,($FE)
;   myload    LOAD, mysave SAVE: the 6510 does the disk I/O
; and F5 enters the monitor, zx64mon (z80/mon.asm), through mon_irq or
; mon_call.
;
; As far as the ROM knows, its display never runs (CDFLAG bit 7 is kept
; clear). SLOW mode: interrupts are on, and the IRQ does the display's
; work between frames: the picture, FRAMES, LAST_K. FAST mode: as on a
; ZX81, no interrupts while a program runs (the picture stays as it was);
; they are on only while the ROM waits for a key or does a PAUSE.
; Without /INT (the original cartridge doesn't connect it), the picture
; only changes while the ROM waits for a key or a PAUSE, in either mode.

FRAMES:  equ $4034
CDFLAG:  equ $403B
DFILE:   equ $400C
VARS:    equ $4010
MARGIN:  equ $4028
LASTK:   equ $4025
DEBOUNCE: equ $4027
RAMTOP:  equ $4004
KALL:    equ $00FE              ; where IN A,($FE) with A = 0 reads: a byte of
                                ; the ROM's K-GRAPH table (see mirror)
        include "rom.inc"       ; KALL_ROM: the ROM's byte there (build.py)
NAMEFN:  equ $03A8              ; ROM NAME: DE = start, C = length-1, carry if empty
RAMFILL: equ $03CB              ; ROM RAM-FILL, from START with BC = $7FFF
ERR_F:   equ $02F4              ; ROM "RST 8 / DB $0E", report F

VIC:     equ $C000
CIA1:    equ $CC00
CARTSW:  equ $CE00
SCREEN:  equ $D000              ; C64 $E000, RAM under the kernal

KPAGE:   equ $2E00              ; ZX81 keyboard rows, KPAGE + row select
                                ; The rest of its page: buffers whose contents
                                ; don't matter at the start
cmat:    equ KPAGE              ; C64 matrix, one byte a column: page aligned
                                ; (scan counts columns in its low byte)
kq:      equ KPAGE+$10          ; the type-ahead queue, 16 slots of 2 bytes
bptab:   equ KPAGE+$30          ; the monitor's breakpoints: 6 x (address, the
                                ; byte it replaced)
MSGBUF:  equ KPAGE+$44          ; the message on the top row (show), 32 bytes
JMSG:    equ KPAGE+$80          ; the joystick's message (joyshow), 32 bytes
JTEACH:  equ KPAGE+$A0          ; the layout being taught (teach), 10 bytes
MBOX:    equ $2F00              ; +0 command, +1 status, +2 name length, +3 name,
                                ; +$20 SP when the 6510 takes over
CMD_LOAD: equ 1
CMD_SAVE: equ 2
CMD_PRG: equ 3                  ; a PRG file to its own load address
CMD_ROM: equ 9                  ; the ROM again, from ZX64
MON:     equ $3000              ; zx64mon: JP its entry, then "ZM" (C64 $4000)
MON2:    equ $E000              ; zx64mon2, its second part: "M2" (C64 $F000)
ST_TOOBIG: equ 2                ; mailbox status: 0 ok, 1 not found or disk error, 2 too big,
                                ; 3 not a ZX81 program (LOAD: report D, as 1)

DSIZE:   equ 24*33+1            ; VARS - D_FILE of a fully expanded display

        org $2000

; ---------------------------------------------------------------- IRQ
; VIC raster IRQ -> Z80 /INT -> RST $38 -> (patched) JP irqh.
; Does what the ZX81's SLOW-mode display did every frame: FRAMES counts,
; LAST_K is read. The picture is copied every other frame.
irqh:   push af
        push bc
        push de
        push hl
        ld a,(bpcnt)            ; the monitor's breakpoints are RST $38s:
        or a                    ; is this one of them?
        call nz,bp_hit          ; (it doesn't come back if it is)
        ld a,(VIC+$19)          ; the VIC's raster flag: is it the VIC's?
        rra
        jr c,ih_vic
        ld hl,(stray)           ; no: something else pulled /INT low (count
        inc hl                  ; it, for the test programs; it is still
        ld (stray),hl           ; taken as a frame)
ih_vic: ld a,$FF
        ld (VIC+$19),a          ; acknowledge the raster IRQ
        ld a,1
        ld (irqseen),a
        ld hl,tick
        inc (hl)
        call ovl_tick
        ld a,(d1active)         ; is the ROM's DISPLAY-1 running? It owns
        or a                    ; FRAMES and the keyboard then
        jr z,irq_run
        dec a
        ld (d1active),a
        jr irq_pic
irq_run:                        ; a program is running
        ld hl,CDFLAG
        bit 6,(hl)
        jr z,irq_fast
        call frames_dec
        ld hl,eframes           ; a second away from the key wait: a
        ld a,(hl)               ; program, not the editor, is running (a
        cp 50                   ; machine code one started from the edit
        jr nc,irq_long          ; line passes no BREAK test)
        inc (hl)
        jr irq_kbd
irq_long:
        xor a
        ld (edit),a
irq_kbd:
        ld a,(inkbd)            ; the program is reading the keyboard
        or a                    ; itself right now: leave it alone
        jr nz,irq_pic
        call mykbd
        ld (LASTK),hl           ; games poll LAST_K
        ld a,(monreq)           ; F5: the monitor, with the registers of
        or a                    ; the program running
        jp nz,mon_irq
irq_pic:
        ld hl,CDFLAG
        res 7,(hl)              ; never let the ROM think the NMI display runs
        ld a,(tick)
        rra
        call nc,blit            ; picture at 25 Hz
        pop hl
        pop de
        pop bc
        pop af
        ei
        reti
; FRAMES counts down as DISPLAY-1 does: at $8000 it goes to $0000, then
; on from $FFFF, with bit 15 set again.
frames_dec:
        ld hl,(FRAMES)
        dec hl
        ld a,$7F
        and h
        or l
        jr nz,fd_set
        ld a,h
        rla
        ld h,a
fd_set: ld (FRAMES),hl
        ret

; A setting's message on the top row (see show) counts down its frames.
ovl_tick:
        ld a,(ovl)
        or a
        ret z
        dec a
        ld (ovl),a
        ret

irq_fast:                       ; FAST mode, and a program running: a ZX81
        pop hl                  ; takes no interrupts now. Shouldn't happen
        pop de                  ; (SET-FAST and keywait turn them off); if it
        pop bc                  ; does, go back with them off. SLOW or the
        pop af                  ; next key wait turns them on again
        reti

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

; ---------------------------------------------------------------- frame
; Replaces the picture part of the ROM's DISPLAY-1 ($0277): wait for the
; next frame, then the ROM loops back to $0229 (FRAMES, keyboard).
frame:  ld a,(monreq)           ; F5 (seen by KEYBOARD): the monitor
        or a
        call nz,mon_call
        ld a,2
        ld (d1active),a
        ei
        ld hl,tick
        ld c,(hl)
        ld b,0
fr_wait:
        ld a,(hl)
        cp c
        ret nz                  ; the IRQ has been: next frame
        ld a,(VIC+$19)          ; the raster flag, which the VIC latches at
        rra                     ; line 250 even with its IRQ masked
        jr nc,fr_clr
        call notbad             ; (but see notbad)
        jr c,fr_wait
        ld a,(irqseen)
        or a
        jr z,fr_poll            ; no IRQ so far: do its picture work here
        inc b                   ; /INT has worked, so the IRQ should take
        ld a,b                  ; the flag at once. Still set at the next
        cp 2                    ; read: no IRQs come (irqseen was set by a
        jr c,fr_wait            ; call, USR 8192, or the wire came loose):
        xor a                   ; poll from now on
        ld (irqseen),a
fr_poll:
        ld a,$FF
        ld (VIC+$19),a
        inc (hl)
        call ovl_tick
        ld a,(tick)
        rra
        call nc,blit
        ret
fr_clr: ld b,0                  ; clear: the count starts again
        jr fr_wait

; The raster flag ($D019 bit 0) can read as set when it isn't, just
; after a bad line, when the VIC has had the bus: seen on hardware, the
; monitor's frame wait came back every 32 lines. A flag read while the
; raster is where there are no bad lines is believed: line 250 (where
; it is set) to the end of the frame, and the top border. Carry: not
; there, don't believe it. Keeps all but A and the flags.
notbad: ld a,(VIC+$11)          ; bit 7: the line's bit 8, so 256-311
        rla
        ccf
        ret nc
        ld a,(VIC+$12)
        cp 250
        ret nc                  ; 250-255
        cp 48                   ; 0-47: NC, believed; 48-249: carry
        ccf
        ret

; ---------------------------------------------------------------- SLOW/FAST
; Replaces ROM $0207, which starts or stops the display to suit CDFLAG
; bit 6. SLOW: interrupts on, the IRQ does the display's work. FAST: off,
; as a ZX81 takes none in FAST mode. (SET-FAST, $02E7, is patched to DI.)
slowfast:
        ld hl,CDFLAG
        res 7,(hl)
        bit 6,(hl)
        jr z,sf_fast
        ei
        ret
sf_fast:
        di
        ret

; The editor's key wait (DISPLAY-6): $04CC, CALL Z,DISPLAY-1, patched to
; call here. INPUT waits here too. Returns as DISPLAY-1 does with a key:
; LAST_K set, CDFLAG bit 0 set, HL = CDFLAG.
; frame() has the interrupts on while the ROM waits; in FAST mode they go
; off again once the key is taken, before anything runs.
; With kbuf (F1), keys come from the type-ahead queue instead of through
; the ROM's debounce (see edges).
keywait:
        push af
        ld a,(hello)            ; the first time after power on: the version
        or a                    ; on the top row
        jr z,kw_go
        xor a
        ld (hello),a
        push hl
        ld hl,msg_hello
        call show
        pop hl
kw_go:  ld a,(edit)             ; back from a program: what was typed
        or a                    ; meanwhile was for it, not the editor
        call z,kq_flush
        ld a,1
        ld (edit),a
        ld a,KALL_ROM           ; the ROM's byte back, for graphics mode
        ld (KALL),a
        xor a
        ld (eframes),a
        ld a,(kbuf)
        or a
        jr nz,kw_buf
        pop af
kw_call:
        call $0229
        push af                 ; what was queued meanwhile was the ROM's key
        call kq_flush           ; too (F1 back on during its wait): or it
        pop af                  ; would come twice
kw_end: push af
        ld a,(CDFLAG)
        bit 6,a
        jr nz,kw_done
        di
kw_done:
        pop af
        ret

kw_buf: pop af
kb_loop:
        xor a                   ; as if the ROM's debounce had run down,
        ld (DEBOUNCE),a         ; for when F1 switches back to it
        call mykbd              ; a scan: new key presses into the queue
        call kq_pop
        jr nz,kb_key
        ld a,(kbuf)             ; F1 just now: the ROM's own way from here
        or a
        jr z,kw_call
        call frames_dec         ; FRAMES, as DISPLAY-1 counts it
        call frame
kw_frame:
        jr kb_loop
kb_key: ld (LASTK),hl
        xor a
        ld (d1active),a         ; the IRQ scans again from the next frame
        ld hl,CDFLAG
        set 0,(hl)              ; a key, as DISPLAY-1 says it
        jr kw_end

; ---------------------------------------------------------------- type-ahead
; The ROM takes a key only after every key has been up for 4 frames, and
; the key has then been read the same twice: no rollover, so touch typing
; loses all but the first key. With kbuf on, each scan puts each newly
; pressed key into a queue, with SHIFT as it is at that moment and coded
; as the ROM's KEYBOARD codes a key on its own, and the key wait takes
; them from there. Only while the editor or INPUT is in charge (edit):
; keys pressed while a program runs are its own business.
edges:  call ed_take             ; keys down (cmat is fresh)
        jr z,ed_cp
        ld hl,cmat
        call ghosty             ; a key may be a ghost: take none, and keep
        ret nz                  ; kprev, so what is new once it clears is
        jr ed_go                ; taken then
edges_up:                       ; nothing down: no ghost (cmat not read)
        call ed_take
        jr z,ed_cp
ed_go:  ld hl,kprev
        ld de,KPAGE+$FE
        ld b,8
ed_row: ld a,(de)               ; this row now (0: down)
        ld c,a
        cpl
        and (hl)                ; down now, up last time
        ld (hl),c
        and $1F
        jr z,ed_next
        ld c,a
        ld a,e
        cp $FE
        jr nz,ed_keys
        res 0,c                 ; SHIFT on its own is no key
ed_keys:
        ld a,1                  ; each key in the row, bit by bit
ed_bit: push af
        and c
        call nz,kq_key
        pop af
        add a,a
        cp $20
        jr c,ed_bit
ed_next:
        inc hl
        rlc e                   ; the next row select: FE, FD, FB ... 7F
        djnz ed_row
        ret
ed_cp:  ld hl,kprev
        ld de,KPAGE+$FE
        ld b,8
ed_copy:                        ; not taking keys: just remember the rows
        ld a,(de)
        ld (hl),a
        inc hl
        rlc e
        djnz ed_copy
        ret

ed_take:                        ; NZ: type-ahead on and the editor taking keys
        ld a,(kbuf)
        or a
        ret z
        ld a,(edit)
        or a
        ret

; The C64's keyboard has no diodes: three keys down at three corners of a
; rectangle in its matrix (two columns, two rows) make the fourth read as
; down too. Typing TEST quickly, E and S still down as T goes down, an F
; appeared. HL = the matrix, a byte a column (0: down). NZ: two columns
; have two or more rows down in common, so a key may be a ghost. Uses A,
; BC, E, HL. The monitor uses it too (GHOSTY).
ghosty: push hl                 ; first: keys in two columns at least?
        ld bc,$0800             ; (a single key, the usual, stops here)
gp1:    ld a,(hl)
        inc a                   ; $FF: none down
        jr z,gp2
        inc c
gp2:    inc hl
        djnz gp1
        pop hl
        ld a,c
        cp 2
        jr nc,gh0
        xor a
        ret
gh0:    ld b,7
gh1:    ld a,(hl)
        cpl
        or a
        jr z,gh4                ; none down in this column
        ld c,a                  ; this column's keys down
        push hl
        push bc
gh2:    inc hl                  ; against each column after it
        ld a,(hl)
        cpl
        and c                   ; the rows down in both
        jr z,gh3
        ld e,a
        dec a
        and e                   ; two or more of them
        jr nz,gh_yes
gh3:    djnz gh2
        pop bc
        pop hl
gh4:    inc hl
        djnz gh1
        xor a
        ret
gh_yes: pop bc
        pop hl
        ret

; A = the key's bit, E = its row select: into the queue as KEYBOARD's
; HL, H = the key's bit (0) shifted left with SHIFT (0: down) in bit 0,
; L = the row select. A full queue loses the key. Keeps BC, DE, HL.
kq_key: push hl
        push de
        push bc
        ld b,a
        call kshift             ; carry: SHIFT up
        ld a,b
        cpl
        rla
        ld d,a
        ld a,(kq_in)
        ld c,a
        inc a
        and 15
        ld b,a
        ld a,(kq_out)
        cp b
        jr z,kk_done            ; full
        ld h,0
        ld l,c
        add hl,hl
        push de
        ld de,kq
        add hl,de
        pop de
        ld (hl),e
        inc hl
        ld (hl),d
        ld a,b
        ld (kq_in),a
kk_done:
        pop bc
        pop de
        pop hl
        ret

; kq_key's SHIFT for the key B (its bit) in row E: a C64 SHIFT, or the
; key's own C64 key if that gives it with SHIFT (DEL: SHIFT 0). Not the
; ZX81's SHIFT line: DEL still down as G went down gave LLIST. Carry:
; SHIFT up. Keeps B, E.
kshift: ld a,(KPAGE+$FE)
        rra
        ret c                   ; the ZX81's SHIFT up: none
        call shifted            ; Z, and carry clear (its AND): a C64
        ret z                   ; SHIFT down
        ld hl,kshtab            ; (ZX81 row, its key, cmat column, its row)
ks_ent: ld a,(hl)               ; 0: the end
        or a
        scf
        ret z
        inc hl
        cp e
        ld a,(hl)
        inc hl
        ld c,(hl)
        inc hl
        jr nz,ks_nx             ; (cp's flags)
        and b
        jr z,ks_nx
        push de
        ld e,c
        ld d,cmat/256
        ld a,(de)
        pop de
        and (hl)                ; 0: down, carry clear
        ret z
ks_nx:  inc hl
        jr ks_ent

; The next key from the queue: NZ and HL, or Z if there is none.
kq_pop: ld a,(kq_out)
        ld c,a
        ld a,(kq_in)
        cp c
        ret z
        ld h,0
        ld l,c
        add hl,hl
        ld de,kq
        add hl,de
        ld e,(hl)
        inc hl
        ld d,(hl)
        ex de,hl
        ld a,c
        inc a
        and 15
        ld (kq_out),a
        or 1
        ret

kq_flush:
        ld a,(kq_in)
        ld (kq_out),a
        ret

; ---------------------------------------------------------------- keyboard
; Scan the C64 keyboard into the eight ZX81 rows at KPAGE + row select.
; One read with every column selected says whether any key is down at
; all (Z: none); only then is the matrix read, and only the columns with
; a key down are looked up.
scan:   ld a,$FF
        ld (KPAGE+$FE),a
        ld (KPAGE+$FD),a
        ld (KPAGE+$FB),a
        ld (KPAGE+$F7),a
        ld (KPAGE+$EF),a
        ld (KPAGE+$DF),a
        ld (KPAGE+$BF),a
        ld (KPAGE+$7F),a
        ld a,(CIA1)             ; the stick in port 2: one read will do
        ld hl,jnow              ; while it and the last scan say idle
        and (hl)                ; (a wrong read, or a column still
        ld c,a                  ; selected, only costs the three reads)
        inc a                   ; C: $FF, the stick left out
        jr z,sc_kb
        call jread              ; or three reads: jnow
        ld (jnow),a
sc_kb:
        xor a
        ld (CIA1),a             ; all columns
        ld a,(CIA1+1)
        cp $FF                  ; Z: no key down
        jr nz,sc_keys
        inc c
        jp z,sc_none            ; nothing at all
        jp sc_stick
sc_keys:
        ld hl,cmat
        ld b,$FE
sc_col: ld a,b
        call cread
        ld (hl),a
        inc l
        rlc b
        jr c,sc_col             ; carry until the 0 has gone round
        ld a,(jnow)
        inc a
        call nz,jghost          ; the stick held: its ghosts out
        ld a,(teaching)         ; teaching: the F-keys are its own
        or a
        jp nz,f5_done
        ld a,(cmat)             ; F7 (column 0, row 3): reset the ZX81; with
        and $08                 ; SHIFT it is F8, the next memory size
        jr nz,sc_f1
        ld c,$08
        call held
        jp z,f7go
sc_f1:  ld hl,f1down            ; F1 (column 0, row 4), as it goes down:
        ld a,(cmat)             ; type-ahead on or off
        and $10
        jr nz,f1_up
        or (hl)
        jr nz,f1_done
        ld c,$10
        call held
        jr nz,f1_done
        inc (hl)
        call shifted            ; with SHIFT it is F2: the colours
        jr nz,f1_ta
        call nextcol
        jr f1_done
f1_ta:  ld a,(kbuf)
        xor 1
        ld (kbuf),a
        ld hl,msg_kboff
        jr z,f1_show
        ld hl,msg_kbon
f1_show:
        call show
        jr f1_done
f1_up:  ld (hl),0
f1_done:
        ld a,(cmat)             ; F5 (column 0, row 6), as it goes down: the
        cpl                     ; monitor, at the next chance (monreq). F3
        and $60                 ; (row 5): the next joystick layout, and held
        ld hl,f5down            ; a second, teaching one
        jr z,f5_up
        ld b,a
        ld a,(hl)
        or a
        jr nz,f5_held
        ld c,b
        call held
        jr nz,f5_done
        inc (hl)
        bit 5,b
        jr nz,f3_down
        xor a
        ld (f3on),a
        inc a
        ld (monreq),a
        jr f5_done
f3_down:
        ld a,(joyidx)           ; (put back if teaching is given up)
        ld (f3old),a
        call joynext
        ld a,(tick)
        ld (f3t0),a
        ld a,1
        ld (f3on),a
        jr f5_done
f5_held:
        ld a,(f3on)             ; F3 still down: a second of it?
        dec a
        jr nz,f5_done
        ld a,(f3t0)
        ld b,a
        ld a,(tick)
        sub b
        cp 50
        jr c,f5_done
        ld a,2
        ld (f3on),a
        ld (monreq),a           ; teaching, at the next chance (mon_go)
        jr f5_done
f5_up:  ld (hl),0
f5_done:
        ld hl,keymap            ; per column: a count, then (C64 row mask,
        ld de,cmat              ; ZX81 row, ZX81 key mask) entries
km_col: ld a,(de)
        ld c,a
        ld b,(hl)
        inc hl
        inc a
        jr nz,km_ent
        ld a,b                  ; nothing down in this column: skip it
        add a,a
        add a,b
        add a,l
        ld l,a
        jr nc,km_next
        inc h
        jr km_next
km_ent: ld a,(hl)
        inc hl
        and c
        jr nz,km_up             ; that key is up
        push de
        ld e,(hl)
        ld d,KPAGE/256
        inc hl
        ld a,(de)
        and (hl)
        ld (de),a
        inc hl
        pop de
        djnz km_ent
        jr km_next
km_up:  inc hl
        inc hl
        djnz km_ent
km_next:
        inc e
        ld a,e
        cp 8
        jr nz,km_col
        ld a,(cmat+1)           ; SHIFT with CRSR RIGHT or DOWN means left
        and $80                 ; or up, as on a C64 (and VICE's arrow keys):
        jr z,cr_sh              ; LSHIFT is column 1 row 7, RSHIFT 6 row 4
        ld a,(cmat+6)
        and $10
        jr nz,cr_done
cr_sh:  ld a,(cmat)             ; CRSR RIGHT is column 0 row 2, DOWN row 7
        bit 2,a
        jr nz,cr_up
        ld hl,KPAGE+$EF
        set 2,(hl)              ; not 8 (right)...
        ld l,$F7
        res 4,(hl)              ; ...but 5 (left)
cr_up:  bit 7,a
        jr nz,cr_done
        ld hl,KPAGE+$EF
        set 4,(hl)              ; not 6 (down)...
        res 3,(hl)              ; ...but 7 (up)
cr_done:
        ld a,(cmat)             ; F5 down (SHIFT+F5 too): no SHIFT for the program
        and $40
        jr nz,cr_stick
        ld hl,KPAGE+$FE
        set 0,(hl)
cr_stick:
        ld a,(jnow)             ; the stick's keys too, unless it was
        ld hl,jprev             ; idle then and now
        and (hl)
        inc a
        call nz,jmerge
        or 1                    ; NZ: something is down
        jr sc_done
sc_stick:                       ; the stick, no key
        call jmerge
        xor a
        ld (f1down),a
        ld (f5down),a
        ld a,(jnow)
        inc a                   ; Z: let go just now, nothing is down
        jr sc_done
sc_none:
        xor a                   ; Z: nothing down
        ld (f1down),a
        ld (f5down),a
sc_done:
        ld a,$FF
        ld (CIA1),a             ; no column selected
        ret

; A = a column select: its rows, each bit as at least two of three
; reads in a row have it. On the cartridge a single read of the CIA (or
; the VIC) can come back wrong: seen on hardware, column 0 read as $D0
; with nothing down, so BREAK-1 took it for F7 and reset the ZX81; the
; next read gave $FF. A wrong read can show a key down that isn't, or
; up that is (a held key would come twice): the majority outvotes it
; either way. Keeps BC, DE, HL.
cread:  ld (CIA1),a
        push bc
        push de
        ld a,(CIA1+1)
        ld b,a
        ld a,(CIA1+1)
        ld c,a
        ld a,(CIA1+1)
        ld d,a
cr_maj: and c                   ; (b & c) | (b & d) | (c & d)
        ld e,a
        ld a,b
        and c
        or e
        ld e,a
        ld a,b
        and d
        or e
        pop de
        pop bc
        ret

; ---------------------------------------------------------------- joystick
; The stick in port 2 as ZX81 keys. A layout is five (row select, AND
; mask) pairs, for up, down, left, right and fire, the order of $DC00's
; bits 0-4; none is mask $FF. scan puts every key the stick holds into
; the rows, so the IN A,($FE) copies (mirror) get them all. KEYBOARD
; (LAST_K, INKEY$) gets one, the one pressed last: the ROM takes two keys
; down as no key, so a diagonal would stop a game. jone takes the others
; out again after mirror.

; The stick, three reads (see cread): bits 0-4, 0 pressed, 5-7 set.
; Keeps BC, DE, HL.
jread:  ld a,$FF
        ld (CIA1),a             ; no column: port A reads only the stick
        push bc
        push de
        ld a,(CIA1)
        or $E0
        ld b,a
        ld a,(CIA1)
        ld c,a
        ld a,(CIA1)
        ld d,a
        jr cr_maj               ; (it pops DE and BC)

; jnow into the rows: every key the stick holds, and jlast (the newest)
; for jone, leaving out directions the layout has no key for. jmulti:
; more than one is down. jprev: what was down, so left out.
jmerge: ld a,(teaching)         ; teaching takes keys, not the stick: it
        or a                    ; is up for scan too
        jr nz,jm_tch
        call joylay             ; HL: the layout
        ld a,(jnow)
        ld c,a                  ; C: the stick, shifted out bit by bit
        ld b,$FF                ; B: what is down, shifted in
        ld d,5
jm_ent: ld e,(hl)               ; its row select
        inc hl
        ld a,(hl)               ; its mask
        inc hl
        rr c
        jr c,jm_rot             ; not pressed
        push hl
        ld l,e
        ld h,KPAGE/256
        ld e,a
        and (hl)
        ld (hl),a
        pop hl
        ld a,e
        add a,1                 ; carry: no key ($FF), as if not pressed
jm_rot: rr b
        dec d
        jr nz,jm_ent
        ld a,b                  ; bits 3-7 to 0-4
        rrca
        rrca
        rrca
        ld b,a
        cpl
        and $1F
        ld e,a
        dec a
        and e                   ; NZ: two or more down
        ld (jmulti),a
        ld a,(jprev)
        ld c,a                  ; C: at the last scan
        ld a,b
        ld (jprev),a
        cpl
        and c                   ; pressed now, up before: new
        and $1F
        jr nz,jm_low            ; the newest is KEYBOARD's
        ld a,(jlast)
        cp 5
        jr nc,jm_any
        ld e,a                  ; still down? Then it stays
        inc e
        ld a,b
jm_bit: rrca
        dec e
        jr nz,jm_bit
        ret nc
jm_any: ld a,b                  ; let go: the lowest still down
        cpl
        and $1F
        jr nz,jm_low
        dec a                   ; none
        ld (jlast),a
        ret
jm_low: ld e,0                  ; A: entries (bit set), the lowest
jm_n:   rrca
        jr c,jm_one
        inc e
        jr jm_n
jm_one: ld a,e
        ld (jlast),a
        ret
jm_tch: ld a,$FF
        ld (jnow),a
        ret

; After mirror: the stick's keys other than jlast out of the rows again,
; for KEYBOARD. (A key also held on the keyboard goes with them.)
jone:   call joylay
        ld a,(jprev)
        ld c,a
        ld a,(jlast)
        ld e,a
        ld d,0
jo_ent: rr c
        jr c,jo_next
        ld a,d
        cp e
        jr z,jo_next
        push hl
        ld a,(hl)
        inc hl
        ld b,(hl)
        ld l,a
        ld h,KPAGE/256
        ld a,b
        cpl
        or (hl)
        ld (hl),a
        pop hl
jo_next:
        inc hl
        inc hl
        inc d
        ld a,d
        cp 5
        jr nz,jo_ent
        ret

; F3: the other layout, 5678+0 or the taught one if there is one, shown
; on the top row by its keys.
joynext:
        ld a,(joyhave)
        or a
        jr z,jn_set             ; none taught: 5678+0 (A = 0)
        ld a,(joyidx)
        xor 1
jn_set: ld (joyidx),a
joyshow:
        call joylay
        call jcomp
jshow:  ld hl,JMSG
        jp showb
jcomp:  push hl                 ; HL: a layout. JMSG: msg_joy with its keys
        ld hl,msg_joy
        ld de,JMSG
        call msgx
        pop hl
        ld de,JMSG+12
        ld b,5
js_key: push bc
        ld a,(hl)
        inc hl
        ld c,(hl)
        inc hl
        push hl
        push de
        call keyc
        pop de
        ld (de),a
        inc de
        inc de
        inc de
        pop hl
        pop bc
        djnz js_key
        ret

; Hold F3 (from mon_go, interrupts off, the program frozen): the top row
; asks for each of the stick's keys in turn, the layout so far with a ? at
; the one asked. The first key down other than SHIFT is the answer (a C64
; cursor key: its key without SHIFT), or SHIFT alone; F1: none; F5: give
; up, the layout as before F3. Taken once all keys are up again.
teach:  ld a,1
        ld (teaching),a
        ld hl,JTEACH            ; all none to start with
        ld b,5
tc_clr: ld (hl),$FE
        inc hl
        ld (hl),$FF
        inc hl
        djnz tc_clr
        ld de,JTEACH            ; DE: the key asked for
tc_ask: push de
        ld hl,JTEACH
        call jcomp
        pop de
        ld a,e                  ; the ? at JMSG + 12 + 3 * its number
        sub JTEACH&$FF
        ld l,a
        rra
        add a,l
        add a,(JMSG&$FF)+12
        ld l,a
        ld h,JMSG/256
        ld (hl),$8F             ; an inverse ?
        push de
        call jshow
        pop de
        ld b,0                  ; B: 0 nothing yet, 1 SHIFT, 2 a key
tc_up:  call tkeys
        jr nz,tc_up             ; all keys up first
tc_wait:
        call tkeys
        jr nz,tc_dn
        ld a,b                  ; all up again: answered?
        or a
        jr z,tc_wait
        inc de
        inc de
        ld a,e
        cp (JTEACH+10)&$FF
        jr nz,tc_ask
        ld hl,JTEACH            ; all five: the custom layout
        ld de,joycus
        ld bc,10
        ldir
        ld a,1
        ld (joyidx),a
        ld (joyhave),a
        jr tc_end
tc_dn:  ld a,(cmat)
        bit 6,a
        jr z,tc_out             ; F5
        ld l,$FE
        bit 4,a
        ld a,$FF                ; F1: none
        jr z,tc_two
        ld a,b
        cp 2
        jr z,tc_wait            ; answered already
        ld h,KPAGE/256          ; the first row with a key down
        ld c,8
tc_row: ld a,(hl)
        bit 0,l
        jr nz,tc_r1
        or 1                    ; (SHIFT doesn't count here)
tc_r1:  or $E0
        inc a
        jr nz,tc_key
        rlc l
        dec c
        jr nz,tc_row
        ld a,b                  ; none: SHIFT alone?
        or a
        jr nz,tc_wait
        ld a,(KPAGE+$FE)
        rra
        jr c,tc_wait
        ld l,$FE
        ld a,l
        ld b,1
        jr tc_put
tc_key: dec a                   ; the row: its lowest key
        ld c,$FE
tc_bit: rra
        jr nc,tc_m
        rlc c
        jr tc_bit
tc_m:   ld a,c
tc_two: ld b,2
tc_put: ex de,hl
        ld (hl),e
        inc hl
        ld (hl),a
        dec hl
        ex de,hl
        jr tc_wait
tc_out: ld a,(f3old)
        ld (joyidx),a
tc_end: call tkeys
        jr nz,tc_end            ; until every key is up
        xor a
        ld (teaching),a
        ld (f3on),a
        call mirror             ; the IN A,($FE) copies all up too
        jp joyshow

; The next frame (the raster flag, polled: interrupts are off), then the
; keys: scan's Z if none is down. Keeps B, DE.
tkeys:  ld a,(VIC+$19)
        rra
        jr nc,tkeys
        call notbad             ; (see notbad)
        jr c,tkeys
        ld a,1
        ld (VIC+$19),a
        push bc
        push de
        call scan
        pop de
        pop bc
        ret


; A = a row select, C = an AND mask: the key's character (keychr).
keyc:   ld hl,keychr-5
        ld de,5
kc_row: add hl,de               ; 5 a row: down to the row's 0 bit
        rrca
        jr c,kc_row
        ld a,c
        inc a
        ld a,c
        jr nz,kc_bit
        ld a,(keychr+40)        ; mask $FF: none
        ret
kc_bit: rrca                    ; then along to the key's 0 bit
        jr nc,kc_got
        inc hl
        jr kc_bit
kc_got: ld a,(hl)
        ret

; The stick holds column lines low, so a key down in one of its columns
; shows in every column read, as on any C64: F1 with the stick up would
; be F2 as well, 0 with fire F7. Rows down with no column selected are
; such ghosts: out of every column but the stick's own. (A key really down
; in such a row elsewhere is lost while the stick is held.)
jghost: ld a,$FF
        call cread
        cpl                     ; 1: a ghost row
        ret z
        ld c,a
        ld a,(jnow)
        ld b,a
        cp $FE                  ; column 0 keeps its rows only with up
        jr z,jg_go              ; alone: with another line held, a key
        set 0,b                 ; there would read as an F-key
jg_go:  ld hl,cmat
jg_col: rr b                    ; carry: not one of the stick's columns
        jr nc,jg_next
        ld a,(hl)
        or c
        ld (hl),a
jg_next:
        inc l
        bit 3,l
        jr z,jg_col
        ret

; The same for BREAK-1's reads, A: column 0's (bg0) or 7's (bg7) with
; something down in it. Keeps BC, DE, HL.
bg0:    push de
        ld e,$FE
        jr bg_go
bg7:    push de
        ld e,$7F
bg_go:  push bc
        ld c,a
        ld a,$FF
        call cread
        cpl
        ld b,a                  ; B: the ghost rows
        ld a,e                  ; the column again: a row is down only if
        call cread              ; down in both, as a key let go between the
        or c                    ; reads leaves its ghost in the first but
        ld c,a                  ; not in B (fire held, M let go: BREAK)
        call jread              ; the stick (0: a column it holds)
        cp e
        ld a,c
        jr z,bg_done            ; it holds this one alone: these are real
        or b
bg_done:
        pop bc
        pop de
        ret

; HL = the current layout: joylays (5678+0) or joycus. Keeps BC, DE.
joylay: ld hl,joylays
        ld a,(joyidx)
        or a
        ret z
        ld hl,joycus
        ret

; C = an F-key's bit in column 0: Z if it is down in 32 reads running
; (a few ms), so a wrong read can't reset the ZX81 or start the
; monitor. Keeps BC, DE, HL.
held:   push bc
        ld b,32
hd1:    ld a,$FE
        call cread
        and c
        jr nz,hd_no
        djnz hd1
hd_no:  pop bc
        ret

; Z if either SHIFT is down (LSHIFT column 1 row 7, RSHIFT column 6 row 4).
shifted:
        ld a,(cmat+1)
        and $80
        ret z
        ld a,(cmat+6)
        and $10
        ret

; F2 (SHIFT+F1 on a C64): the next colour scheme, as monochrome monitors
; had them, its name on the top row. F7 and F8 keep it, and so does the
; monitor, which puts it back as it leaves (SETCOL).
NSCHEMES: equ 6
nextcol:
        ld a,(scheme)
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
; border.
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
        ld hl,VIC+$800          ; colour RAM, C64 $D800
        ld c,4
sc1:    ld b,250
sc2:    ld (hl),a
        inc hl
        djnz sc2
        dec c
        jr nz,sc1
        pop hl
        inc hl
        ld a,(hl)
        ld (VIC+$21),a
        inc hl
        ld a,(hl)
        ld (VIC+$20),a
        ret
schemes:                        ; characters, background, border (C64 colours)
        db 0,1,1                ; black on white, as the boot sets it
        db 1,0,0                ; white on black
        db 13,0,0               ; green screen: light green on black
        db 8,0,0                ; amber: orange on black
        db 0,13,13              ; black on green
        db 14,6,14              ; the C64's own: light blue on blue

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
        ld (CIA1),a             ; column 0
rs_up:  ld a,(CIA1+1)
        and c
        jr z,rs_up
        ld a,$FF
        ld (CIA1),a
        xor a
        ld (inkbd),a
        ld (d1active),a
        ld a,(ramsize)          ; msg_1k, msg_16k, msg_32k
        ld hl,msg_1k
        call msgn
        call show
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

; Changed: the 6510 reads it again from ZX64 (the file ZX81 loaded) on the
; disk zx64 came from, with the bar on the top row (about 20 seconds), and
; puts it in place only if it is this build's ROM (dorom in c64/boot.asm).
romfix: ld hl,txt_load
        ld de,txt_rom
        ld c,7
        call lstat
        ld hl,rom_name
        ld de,MBOX+2
        ld bc,5
        ldir
        ld a,CMD_ROM
        ld (MBOX),a
        call call6510
        ld hl,MSGBUF            ; the size on the top row again, or why the
        call showb              ; ROM wasn't read again: the 6510 put it
        ld a,(MBOX+1)           ; there (dorom), and it stays 5 seconds
        or a
        ret z
        ld a,250
        ld (ovl),a
        ret
rom_name:
        db 4,"ZX64"

; "IN A,(C)" for the ROM's keyboard routine: no flags touched, the ROM
; relies on the carry from RLC B.
zxin:   push hl
        ld h,KPAGE/256
        ld l,b
        ld a,(hl)
        pop hl
        ret

; Replaces ROM KEYBOARD ($02BB). From mykbd_rom on it is the ROM's code,
; with the two IN A,(C) turned into CALL zxin. inkbd keeps the IRQ out
; while a program (INKEY$, a game calling $02BB) is in here.
mykbd:  ld a,1
        ld (inkbd),a
        call scan
        jr z,kb_up
        call mirror             ; every stick key for IN A,($FE)...
        ld a,(jmulti)
        or a
        call nz,jone            ; ...one for KEYBOARD and the type-ahead
        call edges
        jr mykbd_rom
kb_up:  ld a,(kpup)             ; nothing down: no new key either, and the
        or a                    ; rows need remembering only once
        jr nz,kb_upk
        call edges_up
        call mirror
kb_upk: call mir_all            ; (the editor may have had KALL back)
        ld a,1
        ld (kpup),a
        jr kb_none
mykbd_rom:
        xor a                   ; not all up any more
        ld (kpup),a
        ld hl,$FFFF
        ld bc,$FEFE
        call zxin
        or 1
kb1:    or $E0
        ld d,a
        cpl
        cp 1
        sbc a,a
        or b
        and l
        ld l,a
        ld a,h
        and d
        ld h,a
        rlc b
        call zxin
        jr c,kb1
        rra
        rl h
        rla
        rla
        rla
        sbc a,a
        and $18
kb_tail:
        add a,$1F
        ld (MARGIN),a
        push af                 ; leave A and the flags as the ROM does
        xor a
        ld (inkbd),a
        pop af
        ret

kb_none:                        ; no key down: what the ROM's code above
        ld hl,$FFFF             ; works out from eight rows of $FF
        ld a,$18
        jr kb_tail

; ---------------------------------------------------------------- IN A,($FE)
; A game that reads the keyboard itself, IN A,($FE) with a row select in
; A (BoulderL), reads memory at A*256+$FE on the cartridge. Each scan puts
; the rows there, so it finds them: $FEFE, $FDFE ... $DFFE are the C64's
; side (free RAM, the 6510's unused IRQ vector, char 255's glyph). A = 0
; reads every row at once: all of them ANDed go to KALL, but only once a
; program runs. The editor reads that byte only just after its key wait,
; which puts it back.
; $BFFE and $7FFE are in the ZX81's RAM range: a row goes there only if
; that is past the RAM (F8's size), or the unused byte just under RAMTOP
; (the ROM's GO SUB end marker is at RAMTOP-1, its stack starts below
; RAMTOP-2). Under a lowered RAMTOP it may be a program's machine code:
; left alone. Keeps all registers.
mrow:   macro sel               ; the row to sel*256+$FE, and ANDed into B
        ld a,(KPAGE+sel)
        ld (sel*256+$FE),a
        and b
        ld b,a
        endm

mirror: push af
        push bc
        push hl
        ld b,$FF
        mrow $FE
        mrow $FD
        mrow $FB
        mrow $F7
        mrow $EF
        mrow $DF
        ld a,(KPAGE+$BF)
        and b
        ld hl,KPAGE+$7F
        and (hl)
        ld (kand),a
        ld hl,(RAMTOP)          ; H: RAMTOP's page, if it starts one
        ld a,l
        or a
        jr z,mr_top
        ld h,0
mr_top: ld a,(ramsize)
        cp 2
        jr c,mr_bf              ; 1K, 16K: $BFFE is past the RAM
        ld a,h
        cp $C0
        jr nz,mr_7f             ; 32K: only just under RAMTOP $C000
mr_bf:  ld a,(KPAGE+$BF)
        ld ($BFFE),a
mr_7f:  ld a,(ramsize)
        or a
        jr z,mr_7p              ; 1K: $7FFE is past the RAM
        ld a,h
        cp $80
        jr nz,mr_done           ; 16K: only just under RAMTOP $8000
mr_7p:  ld a,(KPAGE+$7F)
        ld ($7FFE),a
mr_done:
        call mir_all
        pop hl
        pop bc
        pop af
        ret

mir_all:                        ; KALL, once a program runs
        ld a,(edit)
        or a
        jr z,ma_put
        ld a,(eframes)          ; or 2 frames after the key wait: a machine
        cp 2                    ; code one started from the edit line
        ret c
ma_put: ld a,(kand)
        ld (KALL),a
        ret

; Replaces "LD A,$7F / IN A,($FE)" in BREAK-1 ($0F46). Only bit 0 (SPACE)
; matters to the ROM: SPACE or RUN/STOP is BREAK. F7 (and F8) is looked at
; here too, so it resets a program running in FAST mode.
brk:    xor a                   ; a program line runs (BREAK-1 comes from
        ld (edit),a             ; NEXT-LINE): keys are the program's now
        ld a,$FE
        call cread
        cp $FF
        call nz,bg0             ; a ghost of the stick's?
        call brk_f5
        and $08
        jr nz,bk_brk
        push bc
        ld c,$08
        call held
        pop bc
        jp z,f7brk
bk_brk: ld a,$7F
        call cread
        cp $FF
        call nz,bg7
        push af
        ld a,$FF
        ld (CIA1),a
        pop af
        and $90
        cp $90
        ld a,$FF
        ret z
        ld a,$FE
        ret

; F5 in BREAK-1, as it goes down (A: column 0): the monitor. Keeps all
; registers, as BREAK-1's callers expect.
brk_f5: push af
        push hl
        ld hl,f5down
        and $60                 ; F5 and F3 both up
        cp $60
        jr z,bf_up
        and $40
        jr nz,bf_done           ; F3: scan's, not here (f5down is its too)
        or (hl)
        jr nz,bf_done
        push bc
        ld c,$40
        call held
        pop bc
        jr nz,bf_done
        inc (hl)
        call mon_call
        jr bf_done
bf_up:  ld a,(irqseen)          ; the IRQ scanning (SLOW, /INT): scan says
        or a                    ; when it is up, every frame (an IRQ
        jr z,bf_clr             ; between cread's reads leaves no column
        ld a,(CDFLAG)           ; selected: a false up)
        and $40
        jr nz,bf_done
bf_clr: ld (hl),0
bf_done:
        pop hl
        pop af
        ret

; ---------------------------------------------------------------- LOAD/SAVE
; Replace ROM LOAD ($0340) and SAVE ($02F6). In syntax-checking mode NAME
; returns straight to our caller's caller, as it does for the ROM.
myload: call NAMEFN
        jr c,io_err             ; LOAD "": no name (a tape would load the next program)
        call bp_off             ; the monitor's breakpoints out first
        ld hl,txt_load
        call lstat
        call setname
        ld a,CMD_LOAD
do_io:  ld (MBOX),a
        call call6510
        call blit               ; the picture over the top row at once
        ld a,(MBOX+1)
        or a
        jp z,slowfast           ; done: interrupts back as SLOW/FAST says,
        cp ST_TOOBIG            ; as the ROM's LOAD ends (the loaded
        jr z,io_big             ; program may have the other mode)
io_err: rst 8
        db $0C                  ; report D
io_big: rst 8
        db $03                  ; report 4, no room

mysave: call NAMEFN
        jp c,ERR_F              ; SAVE "": report F, as the ROM does
        ld hl,txt_save
        call lstat
        call setname
        ld a,CMD_SAVE
        jr do_io

; The top row while the 6510 loads or saves (it fills it in: pstep in
; c64/boot.asm): HL's word (8 characters), the name (12 at most), an
; empty bar of 8 cells from column 22, white, the spinner's cell at 31.
; Inverse, as the settings' messages are. Keeps DE and C, NAME's.
lstat:  push de
        push bc
        xor a
        ld (ovl),a              ; no setting's message over it
        push hl
        ld hl,SCREEN+4
        ld b,32
ls1:    ld (hl),$80
        inc hl
        djnz ls1
        ld hl,SCREEN+26         ; the bar: white, the 6510 fills it black
        ld b,8
ls0:    ld (hl),0
        inc hl
        djnz ls0
        pop hl
        ld de,SCREEN+5
        ld bc,8
        ldir
        pop bc
        pop de
        push de
        push bc
        ld a,c
        inc a
        cp 13
        jr c,ls2
        ld a,12
ls2:    ld b,a
        ld hl,SCREEN+13
ls3:    ld a,(de)
        and $3F
        or $80
        ld (hl),a
        inc hl
        inc de
        djnz ls3
        pop bc
        pop de
        ret

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

; Hand the bus to the 6510, which does what the mailbox says and hands it
; back. The raster IRQ is off meanwhile, so the 6510 never sees it.
; Returns with interrupts off (LOAD and SAVE end through slowfast).
call6510:
        di
        xor a
        ld (VIC+$1A),a
        dec a
        ld (VIC+$19),a
        ld a,1
        ld (MBOX+$20),sp        ; the 6510 must not LOAD over the stack
        ld (CARTSW),a           ; the Z80 stops here...
        nop                     ; "You MUST follow the mode switching store
                                ; instruction with a NOP" (Commodore's CP/M
                                ; guide, 6.6.1): the byte after it can be
                                ; lost when the Z80 is switched back on
sw_back:                        ; ...and carries on here
        ld a,$FF
        ld (VIC+$19),a
        ld a,1
        ld (VIC+$1A),a
        ret

; ---------------------------------------------------------------- monitor
; F5: zx64mon, the machine code monitor (z80/mon.asm), loaded from the
; disk the first time, to MON and MON2 (two files). It is entered with the registers on the
; stack as the IRQ leaves them, HL DE BC AF and the return address, and
; comes back through mon_ret with them, changed or not, at the SP it
; was given (or another, if it was changed there). moniff: interrupts
; on when it returns.
mon_irq:                        ; from the IRQ, which found monreq set
        xor a
        ld (monwhy),a
        inc a                   ; interrupts were on
        jr mon_go
mon_call:                       ; from zx64's code: the same on the stack
        push af
        push bc
        push de
        push hl
        xor a
        ld (monwhy),a
        ld a,i                  ; P/V: interrupts on
        di
        ld a,0
        jp po,mon_go
        inc a
mon_go: di
        ld (moniff),a
        ld hl,monreq
        ld a,(hl)
        ld (hl),0
        cp 2                    ; F3 held: teach, no monitor
        jr nz,mg_mon
        call teach
        jr mon_ret
mg_mon: call mon_here
        call nz,mon_load
        jp z,MON
        ld hl,msg_nomon         ; not on the disk: said on the top row
        call show
mon_ret:
        pop hl
        pop de
        pop bc
        ld a,(moniff)
        or a
        jr z,mx_di
        pop af
        ei
        ret
mx_di:  pop af
        ret

mon_here:                       ; Z: zx64mon is at MON and MON2
        ld hl,(MON+3)
        ld de,$4D5A             ; "ZM"
        and a
        sbc hl,de
        ret nz
        ld hl,(MON2)
        ld de,$324D             ; "M2"
        sbc hl,de
        ret

mon_load:                       ; from the disk, both parts: Z if they came,
        ld hl,txt_load          ; the top row's bar going across both
        ld de,txt_mon
        ld c,6
        call lstat
        ld hl,(monsz)
        ld de,(monsz+2)
        add hl,de
        ld (MBOX+$28),hl
        ld a,1
        ld (MBOX+$27),a
        ld hl,mon_name
        call mon_file
        ld a,2
        ld (MBOX+$27),a
        ld hl,mon_name2
        call mon_file
        xor a
        ld (MBOX+$27),a         ; the monitor's own L shows nothing
        call blit               ; the picture over the top row again
        jr mon_here
mon_file:
        xor a                   ; to the file's own address (see the 6510's
        ld (MBOX+$26),a         ; doprg)
        ld de,MBOX+2
        ld bc,9
        ldir
        ld a,CMD_PRG
        ld (MBOX),a
        jp call6510
mon_name:
        db 7,"ZX64MON",0        ; length, PETSCII
mon_name2:
        db 8,"ZX64MON2"
monsz:  dw 0,0                  ; their sizes: build.py puts them in

; The monitor's breakpoints: it puts RST $38 ($FF) at each, saving the
; byte, and lists them in bptab, bpcnt of them. The IRQ handler asks
; bp_hit first: if the RST was one of them (the byte before the return
; address), the monitor is entered there, with the registers and the
; interrupts as they were, and monwhy 1; the PC on the stack is set back
; to the breakpoint. Otherwise bp_hit returns and it was an interrupt.
bp_hit: ld b,a                  ; A: bpcnt
        ld hl,10                ; the return address: past the CALL and
        add hl,sp               ; HL DE BC AF
        ld e,(hl)
        inc hl
        ld d,(hl)
        dec de                  ; where a RST $38 would have been
        ld hl,bptab
bh1:    ld a,(hl)
        cp e
        jr nz,bh2
        inc hl
        ld a,(hl)
        dec hl
        cp d
        jr z,bh_yes
bh2:    inc hl
        inc hl
        inc hl
        djnz bh1
        ret
bh_yes: ld a,i                  ; P/V: interrupts were on (a RST keeps them)
        ld a,0
        di
        jp po,bh_di
        inc a
bh_di:  ld hl,10
        add hl,sp
        ld (hl),e               ; the PC: the breakpoint itself
        inc hl
        ld (hl),d
        pop hl                  ; bp_hit's own return: not going back
        ld hl,monwhy
        ld (hl),1
        jp mon_go

; Every breakpoint's byte back, and none armed. The monitor does it as
; it is entered; LOAD and F7/F8 too, so no $FF stays behind.
bp_off: push hl
        push bc
        ld a,(bpcnt)
        or a
        jr z,bo_done
        ld b,a
        ld hl,bptab
bo1:    push de
        ld e,(hl)
        inc hl
        ld d,(hl)
        inc hl
        ld a,(hl)
        inc hl
        ld (de),a
        pop de
        djnz bo1
        xor a
        ld (bpcnt),a
bo_done:
        pop bc
        pop hl
        ret

; ---------------------------------------------------------------- data
tick:     db 0                  ; frames seen, low byte
irqseen:  db 0                  ; an IRQ has arrived: /INT is wired
d1active: db 0                  ; the ROM's DISPLAY-1 ran within 2 frames
inkbd:    db 0                  ; mykbd is running
stray:    dw 0                  ; IRQs taken with the VIC's raster flag clear
kbuf:     db 1                  ; type-ahead on (F1 switches it; F7 keeps it)
edit:     db 0                  ; the editor or INPUT is taking keys
eframes:  db 0                  ; frames since its key wait, to 50
f1down:   db 0                  ; F1 is down
f5down:   db 0                  ; F5 is down
monreq:   db 0                  ; F5 pressed: the monitor at the next chance
moniff:   db 0                  ; the monitor goes back with interrupts on
monwhy:   db 0                  ; 0 F5, 1 a breakpoint
bpcnt:    db 0                  ; the monitor's breakpoints armed (bptab)
ramsize:  db 1                  ; 0 1K, 1 16K, 2 32K (F8; F7 keeps it)
scheme:   db 0                  ; the colours (F2; F7 keeps them)
joyidx:   db 0                  ; the stick's layout, 0 5678+0, 1 taught (F3; F7 keeps it)
joyhave:  db 0                  ; a custom layout has been taught
jnow:     db $FF                ; the stick at this scan (jread)
jprev:    db $FF                ; at the last one (jmerge)
jlast:    db $FF                ; the entry KEYBOARD gets, $FF none
jmulti:   db 0                  ; more than one stick key down (jone)
joylays:                        ; up, down, left, right, fire (see jread)
        db $EF,$F7, $EF,$EF, $F7,$EF, $EF,$FB, $EF,$FE  ; 7 6 5 8 0
joycus: db $FE,$FF, $FE,$FF, $FE,$FF, $FE,$FF, $FE,$FF  ; taught (hold F3)
f3on:     db 0                  ; F3 down: 1, held a second: 2
f3t0:     db 0                  ; tick as F3 went down
f3old:    db 0                  ; joyidx before it
teaching: db 0                  ; hold F3 is asking for keys
        include "keychr.inc"
hello:    db 1                  ; the version not shown yet
ramtops:  dw $43FF,$7FFF,$BFFF  ; the last byte of RAM for each
ovl:      db 0                  ; frames the message stays on the top row
ovl_msg:  dw 0                  ; the message
kq_in:    db 0                  ; the type-ahead queue: 16 slots, 15 keys, as HL
kq_out:   db 0
kpup:     db 0                  ; kprev is all up
kand:     db $FF                ; the rows ANDed, for KALL
kprev:    db $FF,$FF,$FF,$FF,$FF,$FF,$FF,$FF  ; the ZX81 rows at the last scan
zx2pet:                         ; ZX81 code 0-27 -> PETSCII
        include "zx2pet.inc"
        include "msgs.inc"
keymap:
        include "keymap.inc"
kshtab:                         ; (kshift)
        include "kshift.inc"

        end
