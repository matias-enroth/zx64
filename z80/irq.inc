; irq.inc - the raster IRQ's handler, irqh (the ROM's RST $38 is patched
; to JP irqh), with FRAMES counted as DISPLAY-1 counts it. Shared by zx64
; (z80/zx64.asm) and zx128 (z80/zx128.asm). The includer provides:
;
;   equates   CDFLAG FRAMES LASTK
;   variables bpcnt tick irqseen stray d1active eframes edit inkbd monreq
;             ovl (vars.inc)
;   code      bp_hit (the monitor's breakpoints: called only with bpcnt
;             not 0), mykbd, mon_irq (F5: entered with the registers on
;             the stack, as irqh pushes them), and the vic_rd/vic_wr
;             macros
;   macro     pic_tick: the picture's work for a frame (zx64: blit every
;             other frame; zx128: pic_step), changing any of AF BC DE HL
;   macro     irq_lastk: HL, the keys just scanned, to LAST_K (but not
;             just after keywait's kb_key, rompatch.inc); may change A
;             and HL
;   macro     irq_early: first, before the VIC is acknowledged (zx128: the
;             VDC-locked picture, vdclock.inc; zx64: nothing); may change
;             AF BC DE HL

; ---------------------------------------------------------------- IRQ
; VIC raster IRQ -> Z80 /INT -> RST $38 -> (patched) JP irqh.
; Does what the ZX81's SLOW-mode display did every frame: FRAMES counts,
; LAST_K is read, the picture (pic_tick).
irqh:   push af
        push bc
        push de
        push hl
        ld a,(bpcnt)            ; the monitor's breakpoints are RST $38s:
        or a                    ; is this one of them?
        call nz,bp_hit          ; (it doesn't come back if it is)
        irq_early
        vic_rd $19              ; the VIC's raster flag: is it the VIC's?
        rra
        jr c,ih_vic
        ld hl,(stray)           ; no: something else pulled /INT low (count
        inc hl                  ; it, for the test programs; it is still
        ld (stray),hl           ; taken as a frame)
ih_vic: ld a,$FF
        vic_wr $19              ; acknowledge the raster IRQ
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
        irq_lastk               ; games poll LAST_K
        ld a,(monreq)           ; F5: the monitor, with the registers of
        or a                    ; the program running
        jp nz,mon_irq
irq_pic:
        ld hl,CDFLAG
        res 7,(hl)              ; never let the ROM think the NMI display runs
        pic_tick
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
