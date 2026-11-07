; zx128vic's hardware access and platform values: the C128's VIC and
; CIAs (io128.inc, zx128's too), and what zx128vic has as zx64 has it:
; the picture on the VIC's 40 columns (vicpic.inc), zx64's six colour
; schemes, its messages (with zx128's own texts, and its own greeting),
; the monitor's 40 columns (z80/mon.asm assembled for zx128vic includes
; this too: MON128 2). The VIC's screen and fonts are in RAM bank 1,
; where the Z80 writes them as plain memory (z80/zx128vic.asm's map;
; boot128 points the VIC there).

        include "io128.inc"     ; VIC, CIA1, CIA2 and their macros, the keys

SCREEN:  equ $C000              ; the ZX81's picture (vicpic.inc): 40 columns,
                                ; its 32 from column 4, 24 rows
ZXFONT:  equ $C800              ; its font (boot128 makes it, as zx64's boot)
SCHEMES: equ 6                  ; F2's colour schemes: zx64's (msgs.inc's msg_col0-5)
VFRAME:  equ 1                  ; the screen's cells round the picture (its
                                ; columns 0-3 and 36-39, row 24): boot128's solid
                                ; character, in the border's colour (vicpic.inc's
                                ; setcol), so only the picture shows the background
MSGS128: equ 2                  ; build.py's messages: zx128's own texts (TEXT128,
                                ; as MSGS128 1), and TEXTVIC (the greeting)
COLRAM:  equ $1000              ; colour RAM, as the Z80 sees it with $FF00 =
                                ; CR_IO: over the ZX81 ROM's $1000-$13FF

; Colour RAM (vicpic.inc's setcol, the monitor's colours): writes only,
; as zx64's (never read: see hw64.inc). The Z80 reaches it at $1000-$13FF
; with the MMU's I/O on ($FF00 CR_IO), over the ROM's bytes there, and the
; I/O over $D000-$DFFF (the own area's code). So a fill is a window:
; col_ptr opens it (the interrupts' state kept, then off: an IRQ would
; run code the window hides, the ROM's $1000-$13FF, the own area's from
; $D800, k2scan; I/O on), col_wr is a plain write, col_end closes it
; ($FF00 the Z80's, the interrupts as they were). While it is open:
;   - the code AND the stack outside $1000-$13FF and $D000-$DFFF (colon
;     and coloff use the stack inside it: the ZX81's is below RAMTOP,
;     $C000 at most; the monitor's, MSTACK below, in common RAM: zx64's
;     $D800 would break its colours);
;   - no second window inside it (coliff is one byte);
;   - setcol is in common RAM (z80/zx128vic.asm), and so is the
;     monitor's colour fill (z80/monvic.inc's mon_on); mon.asm's code
;     (at $3000 and $E000) opens none.
; col_ptr and col_end keep every register but F (col_ptr sets HL);
; col_wr keeps them all. The writes go to the colour RAM bank the 8502's
; $01 bit 0 picks, the VIC shows the one bit 1 picks: boot128 sets both
; (VICE x128: as the C128's kernal leaves them, $73).
col_ptr: macro
        call colon
        endm

col_wr:  macro
        ld (hl),a
        endm

col_end: macro
        call coloff
        endm

; reset.inc's F7 and F8: the VIC's fonts made again first (a program's
; POKE or OUT may have written over them: $C000-$DFFF is the VIC's), then
; the size's message on the top row (z80/zx128vic.asm's rs_vic)
rs_show: macro
        call rs_vic
        endm

; The monitor's screen and memory (z80/mon.asm's platform layer, as
; hw64.inc's: see there for each): its 40 columns on the VIC at MSCR in
; bank 1, its font the C128's character ROM at $D000 (boot128 copies it),
; shown by $D018 (z80/monvic.inc's mon_on and mon_off: the ZX81's screen
; at $C000 is left as it is). The VIC shows MSCR itself, so mflush,
; mdirty, mdirtyall, mcmd and mpoll are nothing, as on zx64. Its buffers
; and stack in common RAM, as zx128's (z80/zx128vic.asm's map): the stack
; never in $1000-$13FF or $D000-$DFFF (the colour RAM window's rule,
; above). A later F5 is quiet (MQUIET, zx128's). L and W: a file's
; address is bank 1's own, and W saves any range (zx128's: MOFF 0, no
; w_from refusal; W of $D000-$DFFF saves the RAM there, the VIC's font
; and the own area, not the I/O).
MCOLS:   equ 40
MSCR:    equ $C400              ; to $C7E7
MBUF:    equ $FC00              ; to $FCFC (mon.asm's LINERV to kprev; to $FDFD
                                ; at most: $FDFE is IN A,($FE)'s $FD row)
MSTACK:  equ $FEFE              ; from $FEFD down ($FEFE: IN A,($FE)'s $FE row)
MQUIET:  equ 1

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

MOFF:    equ 0

w_from:  macro                  ; (any range: W of $F000-$F1FF saves the copy
        endm                    ; of $0000-$01FF parked at ROM01 meanwhile,
                                ; mon6510.inc's mon_6510, and of $FF00-$FF04
                                ; the MMU's registers, as zx128's)
