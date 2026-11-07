; monin.inc - zx64mon's way in on the C128, resident (z80/mon.asm at
; $3000 and $E000), for both C128 builds: zx128 (z80/monvdc.inc, the
; VDC's) and zx128vic (z80/monvic.inc, the VIC's). The includer provides
; monwhy (vars.inc), teach (kbd.inc), mon_ret (call128.inc) and mon_why
; (mon6510.inc).

MON:     equ $3000              ; zx64mon: JP its entry (mon.asm)

; mon_go's, A: monreq as it was. 2 (F3 held): teach. 1 (F5) or 0 (bp_hit,
; which has just set monwhy, or F5 in BREAK-1, romkbd.inc's brk_f5, which
; hasn't): the monitor, with the registers on the stack. monwhy is taken
; here, into mon_why (the monitor's MONWHY), and cleared: a breakpoint's
; 1 is for that entry only.
mon_in: cp 2
        jr nz,mi_mon
        call teach
        jp mon_ret
mi_mon: ld hl,monwhy
        ld b,(hl)
        ld (hl),0
        dec a                   ; monreq 1: F5, whatever monwhy said
        jr nz,mi_why
        ld b,a
mi_why: ld a,b
        ld (mon_why),a
        jp MON
