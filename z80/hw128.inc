; zx128's hardware access: the C128's VIC and CIAs (io128.inc, shared
; with zx128vic), colour RAM and the VDC, as its Z80 sees them: every
; access IN or OUT with BC = the chip's address, as io128.inc's.
;
; And the VDC, which only zx128 has:
;
;   vdc_wr reg      VDC register reg <- A
;   vdc_addr        R18/R19 (the update address) <- HL, then R31 (data)
;                   selected: vdc_put writes there
;   vdc_put         A -> R31: at the update address, which moves on by one
;   vdc_bput        the same with BC = VDC already (a loop's: BC, A kept)
;
; vdc_put relies on R31 still being the selected register, as vdc_addr
; left it: anything that selects another one in between (vdc_wr, or an
; IRQ that touches the VDC) must vdc_addr again, or put R31 back.
;
; Before each access to the VDC's data ($D601) its status ($D600 bit 7)
; is polled until the chip is ready (vdc_wait), as the 8563 asks. The Z80
; may not need it (it is slow: 3x in VICE's guess): VDC_POLL 0 switches
; it off, here only.

        include "io128.inc"     ; VIC, CIA1, CIA2 and their macros, the keys

COLOUR:  equ $D800
VDC:     equ $D600              ; register select / status; data at VDC+1
VDC_POLL: equ 1                 ; wait for the VDC's ready before its data
SCHEMES: equ 4                  ; F2's colour schemes (msgs.inc's msg_col0-3,
                                ; zx128's own: tools/build.py)
MSGS128: equ 1                  ; build.py's TEXT128: zx128's own text for some messages

col_ptr: macro
        ld hl,COLOUR
        endm

col_wr:  macro                  ; (keeps HL and B, as hw64.inc's)
        push bc
        ld b,h
        ld c,l
        out (c),a
        pop bc
        endm

col_end: macro                  ; (hw64.inc's: nothing)
        endm

; reset.inc's message (hw64.inc's): show only marks the panel's rows for
; the IRQ, which the restart's RAM test keeps off (seconds in 32K), so
; they are written at once too, polled (panelhi.inc's pn_shnow: the
; message's rows 13-14 and F8's size, row 9)
rs_show: macro
        call show
        call pn_shnow
        endm

vdc_wait: macro                 ; BC = VDC: until it is ready (A changes)
        if VDC_POLL
        in a,(c)
        jp p,$-2
        endif
        endm

vdc_wr:  macro reg
        push bc
        push af
        ld bc,VDC
        ld a,reg
        out (c),a
        vdc_wait
        pop af
        inc c
        out (c),a
        pop bc
        endm

vdc_addr: macro
        push bc
        ld bc,VDC
        ld a,18
        out (c),a
        vdc_wait
        inc c
        out (c),h
        dec c
        ld a,19
        out (c),a
        vdc_wait
        inc c
        out (c),l
        dec c
        ld a,31
        out (c),a
        pop bc
        endm

vdc_put: macro
        push bc
        ld bc,VDC
        if VDC_POLL
        push af
        vdc_wait
        pop af
        endif
        inc c
        out (c),a
        pop bc
        endm

vdc_bput: macro                 ; BC = VDC: A -> R31, polled; keeps A, BC
        if VDC_POLL
        in f,(c)
        jp p,$-2
        endif
        inc c
        out (c),a
        dec c
        endm

; The monitor's screen and memory (z80/mon.asm, as hw64.inc's): its 48
; columns at the VDC's 32-79 (z80/monvdc.inc), in common RAM but for the
; screen (z80/zx128.asm's map). mflush, mdirtyall, mcmd and mpoll call
; monvdc.inc's (mcmd with mon.asm's lptr: past the command's letter);
; mdirty marks row A in MDIRTY (bit 0: changed). A later F5 is quiet
; (MQUIET). L and W: a file's address is bank 1's own, and
; W saves any range: nothing in bank 1 is I/O.
MCOLS:   equ 48
MSCR:    equ $C400              ; to $C8AF
MDIRTY:  equ $FC00              ; a byte a row (page aligned): bit 0 changed,
                                ; bit 1 reversed characters on the VDC
MBUF:    equ $FC19              ; to $FD35
MSTACK:  equ $FEFE              ; from $FEFD down ($FEFE: IN A,($FE)'s $FE row)
MQUIET:  equ 1

mflush:  macro
        call mon_flush
        endm

mdirty:  macro
        ld l,a
        ld h,MDIRTY/256
        set 0,(hl)
        endm

mdirtyall: macro
        call mon_all
        endm

mcmd:    macro
        ld hl,(lptr)
        call mon_cmd
        endm

mpoll:   macro
        call mon_poll
        endm

MOFF:    equ 0

w_from:  macro                  ; (any range: but W of $F000-$F1FF saves the
        endm                    ; copy of $0000-$01FF parked at ROM01 meanwhile,
                                ; monvdc.inc's mon_6510, and of $FF00-$FF04 the
                                ; MMU's registers)
