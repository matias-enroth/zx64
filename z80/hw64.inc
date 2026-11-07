; zx64's hardware access: the C64's VIC and CIAs, as the cartridge's Z80
; sees them. Included by zx64.asm, mon.asm and kbd.inc. Everything that
; touches the VIC, the CIAs or colour RAM goes through these macros, so
; that another platform (zx128: IN/OUT) can supply the same names in its
; own include. Here each one is exactly the instruction it stands for.
;
;   vic_rd reg      A <- VIC register reg ($00-$3F)
;   vic_wr reg      VIC register reg <- A
;   cia1_rd reg     A <- CIA 1 register reg ($00-$0F)
;   cia1_wr reg     CIA 1 register reg <- A
;   cia2_wr reg     CIA 2 register reg <- A
;   cia2_rd3        A <- CIA 2's port A, voted from three reads (mon.asm's
;                   rd3; the serial bus lines can come back wrong). It is
;                   a call of mon.asm's rd3 with HL = CIA2, so another
;                   platform reimplements it outright, not as one IN.
;   col_ptr         HL <- colour RAM offset 0 (a colour RAM fill starts here)
;   col_wr          colour RAM offset HL <- A (HL walks on with INC HL)
;   col_end         the fill is done (zx128vic's closes its colour RAM
;                   window, hwvic128.inc; nothing here)
;   kbd_all         A <- the keyboard's rows with every column selected
;                   (kbd.inc's scan: is any key down?)
;   kbd_more        the machine's extra keys into cmat, after scan has
;                   read the matrix (none on a C64: no code); it may
;                   change BC, DE and HL too (scan sets them again after)
;
; The register contract, for every platform's version of the macros: they
; change A and F, and nothing else. (cia2_rd3 also HL, which it is given;
; col_ptr sets HL.) The *_wr macros take the value in A, and col_wr takes
; HL = the colour RAM offset as col_ptr set it, keeping HL and B: the fill
; loops count with B and C. The code that uses them keeps values in BC, DE
; and HL across them (scan holds C over cia1_wr/cia1_rd, tkeys holds B and
; DE over vic_rd/vic_wr, cread and jread hold B, C and D over theirs). On
; the C64 that is free, each macro being a single LD that touches only A;
; a version with IN A,(C) / OUT (C),A must save and restore BC (and
; anything else it uses) itself.
;
; Colour RAM and the VIC's registers sit on the C64's I/O page; the Z80
; sees it at $C000 (C64 $D000), with the I/O switch (CARTSW) in zx64.asm.

VIC:     equ $C000
CIA1:    equ $CC00
CIA2:    equ $CD00
COLOUR:  equ $C800              ; C64 $D800
SCHEMES: equ 6                  ; F2's colour schemes (msgs.inc's msg_col0-5)
VFRAME:  equ 1                  ; (as zx128vic's) the screen's cells round the
                                ; picture (columns 0-3 and 36-39, row 24): start's
                                ; solid character (c64/boot.asm), in the border's
                                ; colour (vicpic.inc's setcol), so only the picture
                                ; shows the background
MSGS128: equ 0                  ; zx64's messages as they are

vic_rd:  macro reg
        ld a,(VIC+reg)
        endm

vic_wr:  macro reg
        ld (VIC+reg),a
        endm

cia1_rd: macro reg
        ld a,(CIA1+reg)
        endm

cia1_wr: macro reg
        ld (CIA1+reg),a
        endm

cia2_wr: macro reg
        ld (CIA2+reg),a
        endm

cia2_rd3: macro
        ld hl,CIA2
        call rd3
        endm

col_ptr: macro
        ld hl,COLOUR
        endm

col_wr: macro
        ld (hl),a
        endm

col_end: macro
        endm

kbd_all: macro
        xor a
        cia1_wr 0
        cia1_rd 1
        endm

kbd_more: macro
        endm

; reset.inc's message (F7, F8: msg_1k, msg_16k, msg_32k), before the ZX81
; starts again (its RAM test: interrupts off). show writes the top row
; itself here.
rs_show: macro
        call show
        endm

; The monitor's (mon.asm's kscan), after its loop, HL = kmat+8: the
; machine's extra keys into kmat as C64 keys (none on a C64: no code; it
; may change A, F, BC, DE and HL).
kscan_more: macro
        endm

; The monitor's screen and memory (z80/mon.asm), the platform layer of
; its screen:
;
;   MCOLS      the screen's columns (25 rows of them)
;   MSCR       the screen: screen codes, MCOLS a row, reversed with bit 7
;   MSTACK     the monitor's stack, from MSTACK-1 down
;   MBUF       its buffers (mon.asm's LINERV to kprev)
;   mflush     the rows changed since the last flush shown (fwait, as the
;              monitor waits for a key)
;   mdirty     row A changed (rowp; may change HL, which rowp then sets)
;   mdirtyall  every row changed (CLS, scrolling)
;   mcmd       after each command (exec)
;   mpoll      once a line of a long listing (stopchk, $)
;   MQUIET     1: only the first F5 shows the title and the registers, a
;              later one the screen as it was left, the prompt on the line
;              after the last one used; ? starts with the title. 0: every
;              F5 shows them
;
; Here the VIC shows MSCR itself: the macros are empty. And its disk
; commands' (mon.asm's L and W, the 6510's):
;
;   MOFF       added to a Z80 address for a file's: the C64's
;   w_from     W s e from what can't be saved: err (the I/O chips); reads
;              mon.asm's a1, a2 (s, e) and jumps to its cw1 (ok) or err
MCOLS:   equ 40
MSCR:    equ $F400              ; C64 $0400
MSTACK:  equ $D800              ; from $D7FF down, in the 1K between the
                                ; ZX81's screen and font (C64 $E400-$E7FF)
MBUF:    equ $D400              ; at its other end, to $D4FD
; zx64's second code area (zx64.asm), between the two: from ZX64HI up to
; ZX64HIEND, the monitor's stack above it. The monitor's deepest stack use,
; measured in the model (tools/simulate.py: D, M, A, H, =, ?, Z, $, W, L, @,
; a breakpoint hit, S, G), is 32 bytes, to $D7E0; the area's end is 64
; bytes below that or $D700, whichever is lower: $D700 (simulate.py checks
; the 64 bytes, build.py the end)
ZX64HI:  equ $D500              ; C64 $E500, RAM under the kernal
ZX64HIEND: equ $D700
MQUIET:  equ 1                  ; (as zx128's) nothing else writes C64 $0400:
                                ; F7, F8, LOAD, SAVE and the 6510 leave it, so a
                                ; later F5 finds the screen as it was left. A
                                ; monitor read again from the disk (its "ZM" gone:
                                ; the boot's stub after a C64 reset clears it)
                                ; starts afresh (crow 0): the title

mflush:  macro
        endm

mdirty:  macro
        endm

mdirtyall: macro
        endm

mcmd:    macro
        endm

mpoll:   macro
        endm

MOFF:    equ $1000              ; Z80 $0000 is C64 $1000

w_from:  macro                  ; Z80 $C000-$CFFF: the I/O chips (a1, a2: s, e)
        ld a,(a1+1)
        cp $D0
        jr nc,cw1
        ld a,(a2+1)
        cp $C0
        jp nc,err
        endm
