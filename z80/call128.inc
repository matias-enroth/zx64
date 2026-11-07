; call128.inc - the 8502's turn (call6510), and F5 and F3's way in
; (mon_irq, mon_call, mon_go, mon_ret), for both C128 builds, zx128 and
; zx128vic. The includer provides MBOX, zsw (com128.inc), moniff, monreq
; (vars.inc), mon_in (monin.inc) and the vic_wr macro.

; Hand the machine to the 8502, which does what the mailbox says and hands
; it back (c128/boot128.asm's server). The raster IRQ is off meanwhile.
; Returns with interrupts off (LOAD and SAVE end through slowfast).
call6510:
        di
        xor a
        vic_wr $1A
        dec a
        vic_wr $19
        ld (MBOX+$20),sp        ; the 8502 must not LOAD over the stack
        call zsw                ; (in common RAM)
        ld a,$FF
        vic_wr $19
        ld a,1
        vic_wr $1A
        ret

; ---------------------------------------------------------------- F5, F3
; F5 asks for the monitor, held F3 for teaching the stick's keys (monreq
; 1 or 2: scan): both come here, with the registers on the stack as the
; IRQ leaves them, HL DE BC AF and the return address, and go back through
; mon_ret; a breakpoint too (bp_hit, monreq 0). The monitor is resident:
; mon_in (monin.inc). moniff: interrupts on when it returns.
mon_irq:                        ; from the IRQ, which found monreq set
        ld a,1                  ; interrupts were on
        jr mon_go
mon_call:                       ; from the includer's code: the same on the stack
        push af
        push bc
        push de
        push hl
        ld a,i                  ; P/V: interrupts on (read again if it says
        jp pe,mc_ie             ; off: an NMOS Z80 reads 0 if an interrupt
        ld a,i                  ; is taken during it)
mc_ie:  di
        ld a,0
        jp po,mon_go
        inc a
mon_go: di
        ld (moniff),a
        ld hl,monreq
        ld a,(hl)
        ld (hl),0
        jp mon_in               ; (common RAM: F3 held teaches there)
        ds 2                    ; (room kept: vars.inc where it was)
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
