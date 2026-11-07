; kbd.inc - the keyboard, the type-ahead queue, the joystick and its
; teaching: what turns the machine's keys and stick into the ZX81's eight
; keyboard rows at KPAGE. Shared by zx64 (z80/zx64.asm) and zx128; it
; assembles wherever it is included. Entries: scan, cread, ghosty, kq_pop,
; kq_flush, jread, teach, joyshow (and edges, edges_up, kq_key, kshift,
; jmerge, jone, jghost, bg0, bg7, joylay, held, shifted).
;
; Every access to the VIC and the CIAs goes through the macros of the
; includer's hardware file (hw64.inc on zx64): vic_rd, vic_wr, cia1_rd,
; cia1_wr. The macros change A and F only: see the register contract at
; the top of hw64.inc, which this code relies on (it keeps B, C, D, E and
; HL live across them). cia1_rd 0 / cia1_rd 1 read CIA 1's port A (the
; stick in port 2 when no column is selected) and port B (the matrix rows
; of the selected column); cia1_wr 0 selects the columns (port A). vic_rd /
; vic_wr $19 is the VIC's raster IRQ flag: polled, then acknowledged,
; where a frame is waited for (tkeys, only once notbad believes the read).
; kbd_all reads the rows with every column selected, kbd_more adds a
; machine's extra keys to cmat (the C128's: hw128.inc). The includer
; provides:
;
;   equates  KPAGE    the ZX81 keyboard rows, KPAGE + row select, and the
;                     page of cmat (= KPAGE, a byte a column, page aligned)
;            cmat, kq (the queue, 16 slots of 2 bytes at KPAGE+$10),
;            JMSG (32 bytes), JTEACH (10 bytes), all in KPAGE's page
;   variables kbuf edit tick f1down f5down monreq kq_in kq_out kprev
;            joyidx joyhave jnow jprev jlast jmulti joycus teaching
;            f3on f3t0 f3old
;   tables   joylays keymap kshtab keychr (kshtab, keymap and keychr
;            are the .inc files of the same names)
;   code     show, showb (the message on the top row), msgx (a message
;            into a buffer), msg_kbon msg_kboff msg_joy (the messages),
;            nextcol (F2), f7go (F7, F8), mirror (the IN A,($FE) copies),
;            notbad (is a raster-flag read to be believed); and on
;            zx128 k2scan (hw128.inc's kbd_more)
;
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
        cia1_rd 0               ; the stick in port 2: one read will do
        ld hl,jnow              ; while it and the last scan say idle
        and (hl)                ; (a wrong read, or a column still
        ld c,a                  ; selected, only costs the three reads)
        inc a                   ; C: $FF, the stick left out
        jr z,sc_kb
        call jread              ; or three reads: jnow
        ld (jnow),a
sc_kb:
        kbd_all                 ; all columns
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
        kbd_more                ; the machine's own keys, if it has more
                                ; (BC, DE, HL: set again from here on)
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
        cia1_wr 0               ; no column selected
        ret

; A = a column select: its rows, each bit as at least two of three
; reads in a row have it. On the cartridge a single read of the CIA (or
; the VIC) can come back wrong: seen on hardware, column 0 read as $D0
; with nothing down, so BREAK-1 took it for F7 and reset the ZX81; the
; next read gave $FF. A wrong read can show a key down that isn't, or
; up that is (a held key would come twice): the majority outvotes it
; either way. Keeps BC, DE, HL.
cread:  cia1_wr 0
crd:    push bc                 ; (zx128's k2scan.inc: the rows of columns
                                ; selected otherwise)
        push de
        cia1_rd 1
        ld b,a
        cia1_rd 1
        ld c,a
        cia1_rd 1
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
        cia1_wr 0               ; no column: port A reads only the stick
        push bc
        push de
        cia1_rd 0
        or $E0
        ld b,a
        cia1_rd 0
        ld c,a
        cia1_rd 0
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
tkeys:  vic_rd $19
        rra
        jr nc,tkeys
        call notbad             ; (see notbad)
        jr c,tkeys
        ld a,1
        vic_wr $19
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
