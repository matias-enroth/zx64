; k2scan.inc - the C128's own keys in its columns K0-K2 ($D02F bits 0-2):
; the numeric keypad and the top row's cursor keys, for kbd.inc's scan
; (io128.inc's kbd_more): into cmat as the C64 keys zx64 reads for them,
; so the keymap, the type-ahead and its SHIFT and the IN copies take them
; as those: the keypad's digits, + - and . as the main keys', ENTER as
; RETURN; RIGHT as CRSR RIGHT, DOWN as CRSR DOWN, LEFT as SHIFT+CRSR
; RIGHT would be (<-, SHIFT 5), UP as SHIFT+CRSR DOWN (the up arrow,
; SHIFT 7). HELP, TAB, ESC, LINE FEED, ALT and NO SCROLL are left out.
; The C128 kernal's decode table ($FA80, entries 64-87) and VICE's C128
; keymap have K0-K2's keys in these rows:
;   K0: HELP 8 5 TAB 2 4 7 1, K1: ESC + - LF ENTER 6 9 3,
;   K2: ALT 0 . UP DOWN LEFT RIGHT NO SCROLL (rows 0-7).
; Not while the stick is held: its lines select C64 columns too. Changes
; BC, DE and HL (io128.inc's kbd_more: scan sets them again after). k2keys
; (from all up, no stick) is the monitor's k2mon's way in. Shared by
; zx128 and zx128vic; the includer provides KPFAST, cmat (KPAGE: page
; aligned, its bytes 8-15 unused), jnow (vars.inc), cread (kbd.inc), VIC
; and CIA1 (io128.inc).
;
;
; Its time is a program's (scan runs from the IRQ and from the ROM's
; KEYBOARD): with none of these keys down one read,
; as K2's alone was; with one down, not much more (sim128's
; kbd_c128_held, sim128vic's vic_keys_held pin it). So one read of K0-K2
; together, each bit as two of three reads have it (cread), says which
; rows have a key down; then each column alone, K2 (the arrows) first,
; only to say whose those rows are, and only until every row is placed.
; KPFAST 0 (zx128: its core has little room): by a table, kptab, and
; each column's read voted too (crd: one wrong read, the cartridge's kind,
; would drop a held key for a scan, and the type-ahead would take it
; twice: kbd_c128_glitch); a keypad key held costs about 8%. KPFAST 1
; (zx128vic: room in its own area): a key at a time in code, and the last
; scan's one key again at once while its column still reads it; a single
; read a column (a wrong one can only miss the cache: the columns are
; read again; vic_keys_glitch), quicker (the keys' cost there is about
; five times zx128's).

        if KPFAST = 0
k2scan: ld a,(jnow)
        inc a
        ret nz
k2keys:                         ; (the monitor's k2mon: from here, into cmat)
        ld bc,VIC+$2F
        ld a,$F8
        out (c),a               ; K0-K2
        ld a,$FF
        call cread              ; (keeps BC)
        cpl
        ld h,a                  ; H: rows down, not placed yet
        ld de,kptab+16+7        ; K2's entries, from row 7
        ld l,$FB                ; K2, then K1, then K0
kp_col: inc h
        dec h
        jr z,kp_end             ; every row placed (or none down)
        ld a,l
        out (c),a               ; this column alone
        call crd                ; its rows, voted (cread's reads: $DC00 is
        cpl                     ; $FF since the first)
        and h                   ; those of H's in this column
        call nz,kp_keys
        ld a,e
        sub 8
        ld e,a                  ; the next column's entries (kptab in one
        rrc l                   ; page: build.py); $FB, $FD, $FE: carry
        jr c,kp_col             ; till past K0
kp_end: ld a,$FF                ; none selected
        out (c),a
        ret

; A = this column's rows down (1), DE = its row 7's entry: each such
; row's C64 key down in cmat; H without them. Keeps BC, DE, L.
kp_keys:
        push de
        push af
        xor h
        ld h,a
        pop af
kk_row: add a,a                 ; carry: this row down (7 first); Z: no more
        jr nc,kk_nx
        push af
        push hl
        ld a,(de)               ; row * 16 + column
        ld l,a
        and $70
        rrca
        or $86                  ; RES row,(HL)'s second byte
        ld (kk_res+1),a
        ld a,l
        and $0F
        ld l,a
        ld h,cmat/256           ; cmat + column (8: a spare byte, no key)
kk_res: res 0,(hl)
        pop hl
        pop af
kk_nx:  dec de                  ; (no flags: the add's Z)
        jr nz,kk_row
        pop de
        ret

; The C64 key each of K0-K2's rows stands for, as build.py's MATRIX has
; it: row * 16 + column ($08: none, a byte past cmat's).
kptab:  db $08                  ; K0: HELP
        db $33                  ; keypad 8: 8
        db $02                  ; keypad 5: 5
        db $08                  ; TAB
        db $37                  ; keypad 2: 2
        db $31                  ; keypad 4: 4
        db $03                  ; keypad 7: 7
        db $07                  ; keypad 1: 1
        db $08                  ; K1: ESC
        db $05                  ; keypad +: +
        db $35                  ; keypad -: -
        db $08                  ; LINE FEED
        db $10                  ; ENTER: RETURN
        db $32                  ; keypad 6: 6
        db $04                  ; keypad 9: 9
        db $01                  ; keypad 3: 3
        db $08                  ; K2: ALT
        db $34                  ; keypad 0: 0
        db $45                  ; keypad .: .
        db $66                  ; UP: the up arrow
        db $70                  ; DOWN: CRSR DOWN
        db $17                  ; LEFT: <-
        db $20                  ; RIGHT: CRSR RIGHT
        db $08                  ; NO SCROLL

        else

k2scan: ld a,(jnow)
        inc a
        ret nz
k2keys: ld bc,VIC+$2F
        ld a,$F8
        out (c),a               ; K0-K2
        ld a,$FF
        call cread              ; (keeps BC)
        cpl
        ld e,a                  ; E: rows down, not placed yet
        or a
        jr z,kf_end             ; none
; A key held: the same one row as at the last scan, and that key's column
; has it still: that key again, at once (kf_put kept it). Else every
; column.
kf_last: cp 0                   ; (kf_put: the row; 0: none kept)
        jr nz,kf_all
kf_lsel: ld a,$FF               ; (kf_col: its column)
        out (c),a
        ld a,CIA1/256
        in a,(1)                ; (CIA 1's port B: its rows)
        cpl
        and e
        jr z,kf_all
kf_lhl: ld hl,cmat+8            ; (kf_put: its key)
kf_lres: res 0,(hl)
        jr kf_end
kf_all: xor a
        ld (kf_last+1),a        ; none kept, unless kf_put keeps one
        ld a,e
        dec a
        and e
        ld a,e
        jr z,kf_1               ; E one row: kf_put may keep it
        xor a
kf_1:   ld (kf_one+1),a
        ld a,$FB
        call kf_col             ; K2
        call nz,kf_k2
        ld a,$FE
        call kf_col             ; K0
        call nz,kf_k0
        ld a,$FD
        call kf_col             ; K1
        call nz,kf_k1
kf_end: ld a,$FF                ; none selected
        out (c),a
        ret

; A = $D02F, one column: NZ and A its rows of E's (1), E without them;
; Z if none (or E is empty: not read).
kf_col: inc e
        dec e
        ret z
        ld (kf_lsel+1),a        ; (the last read: the one with E's last row)
        out (c),a
        ld a,CIA1/256
        in a,(1)
        cpl
        and e
        ret z
        ld d,a
        xor e
        ld e,a
        ld a,d
        or a
        ret

; Carry: the row just rotated out is down: its C64 key down in cmat (kk
; as kptab's entries, row * 16 + column: z80asm's macros take one
; argument, two gave "empty macro argument").
kf_key: macro kk
        jr nc,$+10
        ld hl,cmat+(kk & 15)
        ld d,$86+(kk/16)*8      ; RES row,(HL)'s second byte
        call kf_put
        endm

; HL, D: a key's byte in cmat and RES's second byte: that key down, and
; kept for the next scan (kf_last), if it is E's only row (kf_one). Keeps
; A, E.
kf_put: push af
        ld a,d
        ld (kf_pres+1),a
        ld (kf_lres+1),a
kf_pres: res 0,(hl)
        ld (kf_lhl+1),hl
kf_one: ld a,0                  ; (kf_all: E if one row, else 0)
        ld (kf_last+1),a
        pop af
        ret

kf_k2:  rrca                    ; ALT
        rrca
        kf_key $34              ; keypad 0: 0
        rrca
        kf_key $45              ; keypad .: .
        rrca
        kf_key $66              ; UP: the up arrow
        rrca
        kf_key $70              ; DOWN: CRSR DOWN
        rrca
        kf_key $17              ; LEFT: <-
        rrca
        kf_key $20              ; RIGHT: CRSR RIGHT
        ret                     ; (NO SCROLL)

kf_k0:  rrca                    ; HELP
        rrca
        kf_key $33              ; keypad 8: 8
        rrca
        kf_key $02              ; keypad 5: 5
        rrca                    ; TAB
        rrca
        kf_key $37              ; keypad 2: 2
        rrca
        kf_key $31              ; keypad 4: 4
        rrca
        kf_key $03              ; keypad 7: 7
        rrca
        kf_key $07              ; keypad 1: 1
        ret

kf_k1:  rrca                    ; ESC
        rrca
        kf_key $05              ; keypad +: +
        rrca
        kf_key $35              ; keypad -: -
        rrca                    ; LINE FEED
        rrca
        kf_key $10              ; ENTER: RETURN
        rrca
        kf_key $32              ; keypad 6: 6
        rrca
        kf_key $04              ; keypad 9: 9
        rrca
        kf_key $01              ; keypad 3: 3
        ret
        endif
