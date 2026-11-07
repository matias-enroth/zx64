; monvdc.inc - zx64mon (z80/mon.asm) on zx128's VDC: the monitor's own
; screen, MSCR (48 x 25, screen codes), at the VDC's columns 32-79, and
; the ZX81 at half width in columns 0-31 beside it, so it stays in view
; and is seen to change; set 1 in both (tools/build.py's font128: ASCII
; text at $80-$DF, the ZX81's characters at 0-63, their inverses at
; 64-127). That screen is a VDC screen of its own, at $1000
; with its attributes at $1800 (MSHOWN), the ZX81's left as it is at
; $0000 and $0800 meanwhile: each is made where it isn't shown, then
; shown at once (mon_show: R12 and R20, from a blank's start), so the
; switch has no half-done frame (on the C128 one showed set 1's
; attributes over the whole picture's characters for a moment). $1000-
; $1FCF is otherwise free (boot128's vblk uses $1F00 at boot; vdcinit
; clears $1000-$17FF: row 24's columns 0-31 are never written here).
; The monitor is resident: mon.asm assembled for zx128 (MON128),
; part 1 at $3000, part 2 at $E000 (boot128 puts them there), entered
; through mon_in. In common RAM (zx128.asm): the core and the own area
; have no room for this.
;
;   mon_in     mon_go's: F5 and a breakpoint enter the monitor, held F3
;              teaches (monin.inc, zx128vic's too)
;   mon_on     mon.asm's scr_on: every attribute set 1 in the panel's
;              colour, the half picture, every row to show, on the
;              monitor's screen (shown at the next mon_flush's end); the
;              IRQ's picture off meanwhile (irqh calls mon_noirq, not
;              pic_irq). Back from a step: the half picture only
;   mon_off    scr_off, A: stepping. Not: the panel's jobs waiting and the
;              whole picture, then the ZX81's screen shown, the IRQ's
;              picture on again. A step (S): the monitor's screen stays
;   mon_flush  mflush's: the rows changed (MDIRTY) onto the VDC (the first
;              after mon_on: then that screen shown)
;   mon_all    mdirtyall's: every row changed
;   mon_cmd    mcmd's: the half picture again after a command that may
;              change memory or the registers
;   mon_poll   mpoll's: in a listing, the rows changed every MPOLL_N frames
;   pic_half   the ZX81's picture at half width
;   mon_6510   the monitor's CALL6510 (its $, @, L and W: mon6510.inc,
;              zx128vic's too)
; The VDC's writes are all polled: the monitor runs with interrupts off.
; The lock (vdclock.inc) is left to find the VDC's blank again by itself
; once the monitor is gone, as after the 8502's LOAD: its next IRQ comes
; late or finds no rise, and it searches.

MSHOWN:  equ $1018              ; R12, R20 for the monitor's screen (the ZX81's: $0008)

        include "monin.inc"     ; mon_in (MON: zx64mon's entry), shared with
                                ; zx128vic's (z80/monvic.inc)

; ---------------------------------------------------------------- on, off
mon_on: ld a,(mon_up)
        or a
        jp nz,pic_half          ; back from a step: up already
        inc a
        ld (mon_up),a
        ld (mon_hd),a           ; (shown at the flush)
        ld hl,mon_noirq         ; (irqh's call of pic_irq)
        ld (pic_iret-2),hl
        call pn_sc              ; the panel's attribute (pn_wr: polled, after
                                ; a CLS's or a SCROLL's block operation too)
        inc hl
        inc hl
        ld a,(hl)
        ld (mon_at),a
        xor a                   ; every row's 80
mo_at:  push af
        call bo_r80
        set 3,h                 ; (+ $800: the attributes; + $1000: the
        set 4,h                 ; monitor's screen)
        push hl
        ld e,64                 ; (64: by the VDC's block fill, if it can)
        call mo_fill
        pop hl
        ld bc,64
        add hl,bc
        ld e,16
        call mo_fill
        pop af
        inc a
        cp 25
        jr c,mo_at
        ld hl,MDIRTY            ; every row to show, none reversed yet
        ld b,25
mo_d:   ld (hl),1
        inc hl
        djnz mo_d
        jp pic_half

mo_fill:
        ld a,(mon_at)           ; E of mon_at at HL (panel.inc's pn_wr)
        ld d,a
        jp pn_wr

mon_noirq:
        ret

; R12 <- D, R20 <- E (the screen's start and its attributes', R13 and R21
; 0): the other screen shown. Both from a blank's start, so the VDC takes
; them for the same frame. Changes AF BC.
mon_show:
        ld bc,VDC
        call bc_vb
        push de
        ld e,d
        ld a,12
        call bc_w
        pop de
        ld a,20
        jp bc_w

mon_off:
        or a
        ret nz                  ; a step
        ld (mon_up),a
        call pn_go              ; the panel's jobs waiting (the 8502's rows
mf_j:   call pn_find            ; 13-14 after $, L or W; FAST's row 23: a
        jr z,mf_pic             ; FAST program has no IRQ to do them), and
        call pn_job             ; the picture, all done here while the
        jr mf_j                 ; monitor's screen is shown (the rest of the
mf_pic: call pic_all            ; ZX81's is as it was left)
        ld de,$0008
        call mon_show
        ld hl,pic_irq
        ld (pic_iret-2),hl
        ret

; ---------------------------------------------------------------- the rows
; Each row changed since the last flush, as set 1's text: screen code
; $00-$1F (@, A-Z ...) at $A0-$BF, $20-$3F at $80-$9F (bit 7, reversed:
; the attribute's reverse bit). Its attributes too if it has a reversed
; character now or had one at the last flush (MDIRTY bit 1). Keeps BC DE
; HL IX.
mon_flush:
        push bc
        push de
        push hl
        push ix
        ld ix,MSCR
        ld de,MDIRTY            ; E: the row
mf_row: ld a,(de)
        rra
        call c,mf_one
        ld bc,MCOLS
        add ix,bc
        inc e
        ld a,e
        cp 25
        jr c,mf_row
        ld de,MSHOWN            ; (after mon_on: its screen now shown)
        ld hl,mon_hd
        srl (hl)
        call c,mon_show
        pop ix
        pop hl
        pop de
        pop bc
        ret

; Row E (IX: its codes, DE: its MDIRTY byte). Changes AF BC HL.
mf_one: ld a,e
        call bo_r80             ; (keeps DE)
        ld bc,32
        add hl,bc
        push hl
        ld bc,VDC
        call mo_addr
        push de
        push ix
        pop hl
        ld de,MCOLS             ; D: the reversed ones, E: the count
mo_ch:  ld a,(hl)
        and $80
        or d
        ld d,a
        ld a,(hl)
        and $7F
        cp $20
        jr nc,mo_t
        add a,$40
mo_t:   add a,$60
        vdc_bput
        inc hl
        dec e
        jr nz,mo_ch
        ld a,d
        rlca                    ; (bit 7 to bit 1: MDIRTY's)
        rlca
        and 2
        ld b,a
        pop de
        pop hl
        ld a,(de)
        or b
        and 2
        ld a,b
        ld (de),a               ; done: bit 1 as now
        ret z                   ; none reversed, now or before
        set 3,h                 ; (+ $800: the attributes)
        ld bc,VDC
        call mo_addr
        push de
        push ix
        pop hl
        ld a,(mon_at)
        ld d,a
        ld e,MCOLS
mo_a:   ld a,(hl)
        and $80
        rrca                    ; (reversed: bit 6)
        or d
        vdc_bput
        inc hl
        dec e
        jr nz,mo_a
        pop de
        ret

; R18/R19 <- HL + $1000 (the monitor's screen), polled, then R31 selected
; (vdc_bput writes there). BC = VDC. Changes AF, H.
mo_addr:
        set 4,h
        push de
        ld e,h
        ld a,18
        call bc_w
        ld e,l
        inc a
        call bc_w
        pop de
        ld a,31
        out (c),a
        ret

; mpoll's (mon.asm's stopchk: once a line of a listing): the rows changed
; shown every MPOLL_N frames (the VIC's raster flag, as fwait reads it), so
; a long listing is seen as it goes on. Keeps BC DE HL IX.
MPOLL_N: equ 25
mon_poll:
        vic_rd $19
        rra
        ret nc
        ld a,1
        vic_wr $19
        ld a,(mon_pn)
        dec a
        ld (mon_pn),a
        ret nz
        ld a,MPOLL_N
        ld (mon_pn),a
        jp mon_flush

mon_all:
        push hl
        push bc
        ld hl,MDIRTY
        ld b,25
ma_l:   set 0,(hl)
        inc hl
        djnz ma_l
        pop bc
        pop hl
        ret

; HL: past the command's letter (mon.asm's lptr). The ones that may change
; memory or the registers: ":", F, T, Z, L, A, "," (a D line), ";", "'".
; (S: mon_on, back from the step.)
mon_cmd:
        dec hl
        ld a,(hl)
        ld hl,mc_cmds
        ld bc,9
        cpir
        ret nz
        jr pic_half
mc_cmds: db ":FTZLA,;",$27

; ---------------------------------------------------------------- the ZX81
; D_FILE's 24 rows at the VDC's columns 0-31, each character one cell of
; set 1 (an inverse one's code | $40), polled; a collapsed display's rows
; padded with spaces, as pic_all has them (pic_src). The shadow and the
; queue are left as they are (mon_off's pic_all writes every row). Changes
; AF BC DE HL.
pic_half:
        ld a,1                  ; (pic_nirq: not from the IRQ, pic_mvd)
        ld (pic_nirq),a
        call ph_go
        xor a
        ld (pic_nirq),a
        ret
ph_go:  ld a,255                ; (no budget: more than enough)
        ld (pic_left),a
        call pic_mode
        jr c,ph_none
        xor a
ph_row: ld (pic_crow),a
        ld a,255                ; (pic_src's walk: more than enough)
        ld (pic_left),a
        ld a,(pic_crow)
        call pic_src
        ex de,hl                ; DE: the row's codes
        ld a,(pic_crow)
        call bo_r80             ; (keeps DE)
        ld bc,VDC
        call mo_addr
        ex de,hl
        ld e,32
ph_ch:  ld a,(hl)
        and $3F
        bit 7,(hl)
        jr z,ph_w
        or $40
ph_w:   vdc_bput
        inc hl
        dec e
        jr nz,ph_ch
        ld a,(pic_crow)
        inc a
        cp 24
        jr c,ph_row
        ret
ph_none:                        ; no display to show: spaces (the full
        xor a                   ; picture's codes would show as set 1's)
ph_nr:  push af
        call bo_r80
        ld bc,VDC
        call mo_addr
        ld e,32
        xor a
ph_ns:  vdc_bput
        dec e
        jr nz,ph_ns
        pop af
        inc a
        cp 24
        jr c,ph_nr
        ret

        include "mon6510.inc"   ; mon_6510 (the disk: $, @, L and W), mon_up,
                                ; mon_why: shared with zx128vic's
mon_pn:  db MPOLL_N             ; mon_poll: frames to the next flush
mon_at:  db 0                   ; its attribute (the panel's, set 1)
mon_hd:  db 0                   ; 1: its screen to be shown (mon_flush)

        include "bp.inc"        ; the monitor's breakpoints
