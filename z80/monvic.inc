; monvic.inc - zx64mon (z80/mon.asm) on zx128vic's VIC: zx64's look (its
; own screen, MSCR, 40 columns by 25 rows at $C400, in the C128's
; character ROM, which boot128 copies to $D000; light blue on blue), with
; zx128's residency (mon.asm assembled for zx128vic, MON128 2: part 1 at
; $3000, part 2 at $E000, from the boot file), quiet F5 (MQUIET), disk
; path (mon6510.inc) and the C128's keys (k2mon.inc). Both screens are in the
; VIC's 16K of bank 1, so the switch is $D018 (and $D011 for the 25th
; row, the border, the background and colour RAM for the colours), as
; zx64's but for $DD00: the ZX81's screen at $C000 is left as it is (the
; IRQ's blit may write it meanwhile, a step's: unseen).
;
; Each switch is made out of sight (mv_hide): at line 300, past the text
; and what PAL shows of the border below it (NTSC: line 0), the
; registers; then colour RAM from its first cell, which the beam reaches
; at line 51, 63 lines later: a cell takes 26 T (setcol's loops, and some
; 35 T a row more for its frame), the beam 25 (a row's 40 cells in 8
; lines), so it never catches up, and no frame shows part of one look and
; part of the other.
;
; In common RAM (z80/zx128vic.asm): the colour fills run with $D000-$DFFF
; the I/O (hwvic128.inc's window), and so do mon_on and mon_off around
; them. The includer provides scheme (vars.inc), schemes, setcol
; (vicpic.inc's vic_colours), blit (vicpic.inc), and what monin.inc,
; mon6510.inc and bp.inc ask for.
;
;   mon_in     (monin.inc) F5 and a breakpoint enter the monitor, held F3
;              teaches
;   mon_on     mon.asm's scr_on: the monitor's screen shown, in its
;              colours. Back from a step: nothing (it stayed)
;   mon_off    scr_off, A: stepping (S): the monitor's screen stays. Not:
;              the ZX81's picture (blit: a FAST program has no IRQ to make
;              it), then its screen shown, in the scheme's colours (F2's)
;   mon_6510   (mon6510.inc) the monitor's CALL6510 (its $, @, L and W)
; and the breakpoints (bp.inc).

M_TEXT:  equ 13                 ; the monitor's colours: the C128's own
M_BACK:  equ 11                 ; 40-column screen's: light green on dark
M_BORDER: equ 13                ; grey
M_D018:  equ $14                ; screen $C400, font $D000 (the VIC's 16K at $C000)
M_D011:  equ $1B                ; 25 rows, y-scroll 3
Z_D018:  equ $02                ; the ZX81's: screen $C000, font $C800 (boot128's
Z_D011:  equ $17                ; vicinit): 24 rows, y-scroll 7, raster IRQ line
                                ; 250 (bit 7: its bit 8, clear)

        include "monin.inc"     ; mon_in (MON: zx64mon's entry), zx128's

; ---------------------------------------------------------------- on, off
mon_on: ld a,(mon_up)
        or a
        ret nz                  ; back from a step: up already
        inc a
        ld (mon_up),a
        call mv_hide
        ld a,M_BORDER
        vic_wr $20
        ld a,M_BACK
        vic_wr $21
        ld a,M_D011
        vic_wr $11
        ld a,M_D018
        vic_wr $18
        ld a,M_TEXT             ; colour RAM, ahead of the beam
        col_ptr
        ld c,4
mv_f1:  ld b,250
mv_f2:  col_wr
        inc hl
        djnz mv_f2
        dec c
        jr nz,mv_f1
        col_end
        ret

mon_off:
        or a
        ret nz                  ; a step
        ld (mon_up),a
        call blit
        call mv_hide
        ld a,(scheme)           ; the scheme's background and border first:
        ld l,a                  ; setcol puts them in after its fill, the
        add a,a                 ; beam well down the screen by then
        add a,l
        ld l,a
        ld h,0
        ld de,schemes+1
        add hl,de
        ld a,(hl)
        vic_wr $21
        inc hl
        ld a,(hl)
        vic_wr $20
        ld a,Z_D011
        vic_wr $11
        ld a,Z_D018
        vic_wr $18
        jp setcol               ; colour RAM, ahead of the beam (and the two
                                ; again, as they are)

; Until line 300: the VIC's raster flag (its compare, line 250) cleared and
; seen again, then line 256 ($D011 bit 7: the line's bit 8), then 300
; ($D012 44). An NTSC VIC has no line past 262: there the line's wrap to 0
; ends it instead (bit 8 clear again), 51 lines before the text (PAL's
; 300: 63), enough for the fill, its lines being longer (65 cycles). The
; monitor runs with interrupts off: the flag is fwait's too, and the
; IRQ's when the monitor has gone. Changes AF.
mv_hide:
        ld a,1
        vic_wr $19
mh_250: vic_rd $19
        rra
        jr nc,mh_250
mh_256: vic_rd $11
        rla
        jr nc,mh_256            ; 250-255
mh_300: vic_rd $11
        rla
        ret nc                  ; (NTSC) line 0
        vic_rd $12
        cp 300-256
        jr c,mh_300
        ret

        include "mon6510.inc"   ; mon_6510, mon_up, mon_why: zx128's

        include "bp.inc"        ; the monitor's breakpoints
