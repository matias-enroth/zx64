; bp.inc - the monitor's breakpoints, bp_hit and bp_off, for zx64mon
; (z80/mon.asm). Shared by zx64 (z80/zx64.asm) and zx128 (z80/zx128.asm,
; in common RAM). The includer provides:
;
;   equates   bptab (6 x 3 bytes: an address, the byte it replaced)
;   variables bpcnt monwhy (vars.inc)
;   code      mon_go (the monitor, entered with the registers on the stack
;             as irqh leaves them, A: the interrupts were on)

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
        jp po,bh_iff
        inc a
bh_iff: ld hl,10
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
