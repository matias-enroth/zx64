; io128.inc - the C128's VIC and CIAs as its Z80 sees them, for both C128
; builds: zx128 (z80/hw128.inc, the VDC's) and zx128vic (z80/hwvic128.inc,
; the VIC's). The same macro names as hw64.inc (see its header for what
; each does, and for the register contract: A and F change, nothing
; else), but here every access is IN or OUT with BC = the chip's
; address: stores to $Dxxx hit RAM on the C128.
; So each macro saves BC, and anything else it uses, itself. The MMU's
; register and the CPU switch, as the Z80 uses them. And the
; C128's own keys: the numeric keypad and the top row's cursor keys
; (columns K0-K2) into the matrices, for kbd.inc's scan and the monitor's
; kscan.

VIC:     equ $D000
CIA1:    equ $DC00
CIA2:    equ $DD00
CR:      equ $FF00              ; the MMU's configuration register
CR_Z80:  equ $7F                ; bank 1, all RAM, I/O off: the Z80's
CR_IO:   equ $7E                ; the same with I/O on (the MMU; zx128vic:
                                ; colour RAM at $1000-$13FF too)
SWITCH:  equ $D505              ; the CPU switch: $B1 hands over to the 8502

vic_rd:  macro reg
        push bc
        ld bc,VIC+reg
        in a,(c)
        pop bc
        endm

vic_wr:  macro reg
        push bc
        ld bc,VIC+reg
        out (c),a
        pop bc
        endm

cia1_rd: macro reg
        push bc
        ld bc,CIA1+reg
        in a,(c)
        pop bc
        endm

cia1_wr: macro reg
        push bc
        ld bc,CIA1+reg
        out (c),a
        pop bc
        endm

cia2_wr: macro reg
        push bc
        ld bc,CIA2+reg
        out (c),a
        pop bc
        endm

cia2_rd3: macro                 ; port A three times: each bit as two of
        push bc                 ; the reads have it (mon.asm's rd3)
        push de
        ld bc,CIA2
        in d,(c)
        in e,(c)
        in a,(c)
        ld b,a
        and d
        ld c,a
        ld a,b
        and e
        or c
        ld c,a
        ld a,d
        and e
        or c
        pop de
        pop bc
        endm

; The C128's own keys (kbd.inc's scan): its "is any key down" read takes
; the K0-K2 columns ($D02F bits 0-2: the keypad, the top row's cursor
; keys) with the C64 columns, and kbd_more puts their keys into cmat
; (k2scan.inc).
kbd_all: macro
        ld a,$F8
        vic_wr $2F              ; K0-K2 selected...
        xor a
        cia1_wr 0               ; ...with every C64 column
        cia1_rd 1
        push af
        ld a,$FF
        vic_wr $2F
        pop af
        endm

kbd_more: macro                 ; (BC, DE and HL too: k2scan.inc)
        call k2scan
        endm

; And the monitor's (mon.asm's kscan, hw64.inc's): the keypad and K2's
; cursor keys into its kmat as the C64's keys (k2mon.inc, in the monitor)
kscan_more: macro
        call k2mon
        endm
