; romkbd.inc - the ROM's keyboard, as zx64 patches it: KEYBOARD (mykbd,
; reading the rows scan made, through zxin), the IN A,($FE) copies a game
; reads (mirror), BREAK-1 (brk) and F5 there (brk_f5). Shared by zx64 and
; zx128. The includer provides:
;
;   equates   KPAGE MARGIN RAMTOP KALL CDFLAG
;   variables inkbd jmulti kpup ramsize edit eframes kand f5down irqseen
;             (vars.inc)
;   code      scan, edges, edges_up, jone, cread, bg0, bg7, held (kbd.inc),
;             f7brk (reset.inc), mon_call (F5), and the cia1_wr macro

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
        cia1_wr 0
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
