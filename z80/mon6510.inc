; mon6510.inc - zx64mon's disk commands through the 8502 on the C128, and
; the state both C128 builds' monitors keep: zx128's (z80/monvdc.inc) and
; zx128vic's (z80/monvic.inc). The includer provides CMD_PRG CMD_WRITE
; ROM01 and call6510 (call128.inc).

; ---------------------------------------------------------------- the disk
; The monitor's $, @, L and W: the 8502's server (c128/boot128.asm), which
; draws nothing on the panel's rows (zx128) or the VIC's top row
; (zx128vic) while mon_up says the monitor's screen is there (LOAD's and
; SAVE's row and bar, the drive's message).
; L "NAME" a and W s e may reach bank 1's $0000-$01FF, which the 8502
; can't (its own zero page and stack are there): they wait at ROM01
; meanwhile, as F7's ROM does (rombk), and go back after. A: the command.
mon_6510:
        cp CMD_PRG
        jr z,m6_lo
        cp CMD_WRITE
        jp nz,call6510
m6_lo:  ld hl,0
        ld de,ROM01
        call m6_200
        call call6510
        ld hl,ROM01
        ld de,0
m6_200: ld bc,$200
        ldir
        ret

mon_up:  db 0                   ; 1: the monitor's screen is up
mon_why: db 0                   ; the monitor's MONWHY: 1 a breakpoint
