; zx128vic - Z80 side. The ZX81 ROM on the C128's own Z80, in RAM bank 1,
; as zx128 (z80/zx128.asm) runs it, with zx64's picture (z80/zx64.asm,
; vicpic.inc) on the C128's VIC instead of the VDC: the 40-column screen,
; the ZX81's 32 columns from column 4, the top row for a setting's
; message, zx64's colour schemes. The 8502's side is c128/boot128.asm,
; built with VDC=0.
;
; Z80 view of memory (RAM bank 1; E000-FFFF is common RAM, the same bytes
; the 8502 sees in bank 0):
;   0000-1FFF  ZX81 ROM, patched by tools/build.py (with the MMU's I/O on,
;              $FF00 = $7E, $1000-$13FF is colour RAM: colon's window)
;   2000-2DFF  this code and its tables, to coreend
;   2E00-2EFF  ZX81 keyboard rows, indexed by B, and buffers (cmat, kq,
;              bptab, MSGBUF, JMSG, JTEACH: as zx64's; cmat's bytes 8-15
;              unused, k2scan.inc's kptab would use byte 8)
;   2F00-2FFF  mailbox to the 8502
;   3000-3FFF  the monitor, zx64mon's part 1 (z80/mon.asm, assembled for
;              zx128vic: MON128 2)
;   4000-BFFF  ZX81 RAM: 16K to 7FFF, 32K to BFFF
;   C000-C3FF  the ZX81's screen, SCREEN (the VIC's, 40 x 25): blit's
;              32x24 from column 4, round it the frame (boot128's
;              vframe, a solid character in the border's colour, setcol)
;   C400-C7FF  the monitor's screen, MSCR (the VIC's)
;   C800-CFFF  the ZX81's font (the VIC's: boot128 makes it from the ROM's
;              as zx64's boot does)
;   D000-D7FF  the monitor's font (the VIC's: the C128's character ROM,
;              upper case and graphics, copied by boot128)
;   D800-DFFD  zx128vic's own code, HICODE to hiend: rs_vic, k2scan.inc,
;              vidpal.inc (DFFE is IN A,($FE)'s $DF row, see below)
;   E000-EFFD  the monitor's part 2
;   F000-F1FF  the ROM's first two pages on their way in (zentry), and
;              again when F7 puts the ROM back (rombk); the monitor's L
;              and W have bank 1's there meanwhile (mon6510.inc)
;   F200-F3FF  the 8502's code in common RAM, and its staging page
;   F400-F7FD  this code's part in common RAM: zentry, zsw, inrow, rombk,
;              the colours (setcol and its window), the monitor's code
;              here (monvic.inc, bp.inc), to zcomend. (F7FE is IN A,($FE)'s
;              $F7 row)
;   F800-FBFD  free
;   FC00-FEFD  the monitor's buffers (MBUF) FC00-FCFC, its stack (MSTACK)
;              FE00-FEFD (hwvic128.inc); FCFD-FDFD free; FDFE-FDFF the IN
;              A,($FE) copy
;   FF00-FF04  the MMU; FF05-FFED the monitor's part 3 (its own commands:
;              V), to part3end; FFEE the Z80's entry: JP zentry
; (and the IN A,($FE) copies at A*256+$FE: $FEFE, $FDFE, $FBFE, $F7FE
; and $EFFE are in common RAM, $DFFE at the own area's end).
;
; The VIC reads bank 1 ($D506 bit 6, set by boot128), its 16K at $C000
; ($DD00), screen $C000 and font $C800 ($D018 $02): it shows what the Z80
; writes there, no I/O between (VICE and the real C128). The chips are
; reached by IN and OUT (io128.inc), with $FF00 = $7F: bank 1, all RAM,
; I/O off, as zx128's.
;
; Entry points, all reached from the patched ROM (see tools/build.py), as
; zx64's: irqh (RST $38, the VIC raster IRQ at line 250, once a frame:
; the picture every other frame, zx64's blit), frame, keywait, slowfast,
; mykbd, brk, myload, mysave.

FRAMES:  equ $4034
CDFLAG:  equ $403B
DFILE:   equ $400C
VARS:    equ $4010
MARGIN:  equ $4028
LASTK:   equ $4025
DEBOUNCE: equ $4027
RAMTOP:  equ $4004
KALL:    equ $00FE              ; where IN A,($FE) with A = 0 reads: a byte of
                                ; the ROM's K-GRAPH table (see mirror)
        include "rom.inc"       ; KALL_ROM: the ROM's byte there (build.py)
NAMEFN:  equ $03A8              ; ROM NAME: DE = start, C = length-1, carry if empty
RAMFILL: equ $03CB              ; ROM RAM-FILL, from START with BC = $7FFF
ERR_F:   equ $02F4              ; ROM "RST 8 / DB $0E", report F

        include "hwvic128.inc"  ; VIC and CIA access (macros), the picture's place,
                                ; the monitor's (z80/monvic.inc)

KPAGE:   equ $2E00              ; ZX81 keyboard rows, KPAGE + row select
                                ; The rest of its page: buffers whose contents
                                ; don't matter at the start
cmat:    equ KPAGE              ; C64 matrix, one byte a column: page aligned
                                ; (scan counts columns in its low byte)
kq:      equ KPAGE+$10          ; the type-ahead queue, 16 slots of 2 bytes
bptab:   equ KPAGE+$30          ; the monitor's breakpoints (bp.inc)
MSGBUF:  equ KPAGE+$44          ; the message on the top row (show), 32 bytes
JMSG:    equ KPAGE+$80          ; the joystick's message (joyshow), 32 bytes
JTEACH:  equ KPAGE+$A0          ; the layout being taught (teach), 10 bytes
MBOX:    equ $2F00              ; +0 command, +1 status, +2 name length, +3 name,
                                ; +$20 SP when the 8502 takes over
CMD_LOAD: equ 1
CMD_SAVE: equ 2
CMD_PRG: equ 3                  ; the monitor's L "NAME" a (always to a)
CMD_WRITE: equ 7                ; its W s e (both: mon6510.inc's mon_6510)
CMD_ROM: equ 9                  ; the ROM again, from ZX128VIC
CMD_FONT: equ 10                ; the VIC's fonts and the ZX81's screen made again
ST_TOOBIG: equ 2                ; mailbox status: 0 ok, 1 not found or disk error, 2 too big,
                                ; 3 not a ZX81 program (LOAD: report D, as 1)
ROM01:   equ $F000              ; the ROM's $0000-$01FF, as the 8502 left them
ZCOM:    equ $F400              ; this code's part in common RAM
HICODE:  equ $D800              ; zx128vic's own code area, to $DFFD

DSIZE:   equ 24*33+1            ; VARS - D_FILE of a fully expanded display

        org $2000

pic_tick: macro                 ; the picture from the IRQ (irq.inc) and
        ld a,(tick)             ; frame's poll (rompatch.inc): at 25 Hz, as
        rra                     ; zx64's
        call nc,blit
        endm
pic_poll: macro                 ; (blit copies to RAM: an IRQ meanwhile
        pic_tick                ; does no harm)
        endm
kb_lkhold: macro                ; a key from the type-ahead (rompatch.inc's
        ld a,2                  ; kb_key): the next 2 IRQs scan but leave
        ld (lkhold),a           ; LAST_K alone (irq_lastk). Else one could put
        endm                    ; its own there (no key: $FFFF) before the
                                ; ROM has read the key just handed it: a
                                ; key from the queue at keywait's start is
                                ; handed wherever the raster is, and DECODE
                                ; then loops for ever (as zx128's; seen in
                                ; simulate.py's typing in bursts)
kw_hello: macro                 ; (rompatch.inc's keywait: nothing more; boot128
        endm                    ; coloured the frame, vicinit)
irq_lastk: macro                ; (irq.inc) the IRQ's keys (HL) to LAST_K,
        ld a,(lkhold)           ; unless kb_lkhold holds it: an IRQ less
        or a                    ; each time. zx128's lastk, in line here:
        jr z,lk_put             ; a CALL would take the IRQ with no key
        dec a                   ; down past simulate.py's 1,300 T. Held:
        ld (lkhold),a           ; LAST_K put back as it is
        ld hl,(LASTK)
lk_put: ld (LASTK),hl
        endm
irq_early: macro                ; (irq.inc: nothing here, as on zx64)
        endm
zentry_more: macro              ; (com128.inc's zentry: the 8502 has made the
        ld sp,MBOX+$100         ; VIC's screens and fonts) PAL or NTSC, for
        call vidm               ; SPEED (vidpal.inc; a stack in the mailbox's
        endm                    ; page: SP is anything yet)
zsw_cpu: macro                  ; (com128.inc's zsw: no panel here)
        endm

        include "irq.inc"       ; irqh, the raster IRQ

lkhold: db 0                    ; kb_lkhold's count of IRQs (irq_lastk)

        include "vicpic.inc"    ; the picture: blit, show, ovl_top (and
                                ; msgx.inc); the colours' vic_colours

; ---------------------------------------------------------------- not here
; What the shared code calls that zx128vic has elsewhere: the loading row
; (lstat: the 8502 draws it on the top row, as zx64's 6510 draws its bar:
; c128/boot128.asm's wrow). It keeps every register. (The monitor's
; breakpoints, bp_hit and bp_off: in common RAM, with the monitor's code.)
lstat:
        ret

        include "rompatch.inc"  ; frame, notbad, slowfast, keywait

        include "kbd.inc"

        include "reset.inc"     ; F7, F8, romsum

; Changed: the 8502 puts it back (CMD_ROM, c128/boot128.asm's dorom), as
; zx128's does: from the boot file's copy in its bank 0 if that adds up
; to the build's sum, else from ZX128VIC on the disk.
romfix: ld hl,rom_name
        ld de,MBOX+2
        ld bc,9
        ldir
        ld a,CMD_ROM
        ld (MBOX),a
        jp rombk
rom_name:
        db 8,"ZX128VIC"

        include "romkbd.inc"    ; mykbd, mirror, brk

; ---------------------------------------------------------------- LOAD/SAVE
; The 8502's server does the disk I/O through the C128 kernal (c128/
; boot128.asm).
        include "loadsave.inc"
        include "setname.inc"

        include "call128.inc"   ; call6510; F5, F3: mon_irq, mon_call (the
                                ; monitor: monvic.inc's mon_in)

        include "vars.inc"
coreend:                        ; (tools/build.py: the core ends here)

; ---------------------------------------------------------------- own area
; zx128vic's own code, past the VIC's screens and fonts: what the core
; needn't have. c128/boot128.asm puts it at HICODE; build.py stops if it
; reaches $DFFE.

        org HICODE
hicode:
; F7 and F8 (reset.inc's rs_show, HL the size's message): the 8502 makes
; the VIC's fonts and the ZX81's screen again (CMD_FONT: boot128's
; vfonts), as at boot: a program's POKE or OUT (A*256+port) into
; $C000-$DFFF writes over what the VIC shows. Then the message, show's.
rs_vic: push hl
        ld a,CMD_FONT
        ld (MBOX),a
        call call6510
        pop hl
        jp show

KPFAST:  equ 1                 ; (k2scan.inc: a key at a time: quicker)
        include "k2scan.inc"    ; the C128's keypad and cursor keys, for scan
                                ; (and k2keys, for the monitor's k2mon)
        include "vidpal.inc"    ; PAL or NTSC (zentry_more), SPEED's {vidpal}
hiend:

; ---------------------------------------------------------------- common RAM
; In common RAM at ZCOM (c128/boot128.asm puts it there), for what runs
; while $FF00 may not be the Z80's.

        org ZCOM

        include "com128.inc"    ; zentry, zsw, inrow, rombk

        vic_colours             ; F2: nextcol, setcol, schemes (vicpic.inc):
                                ; here, as setcol fills colour RAM through
                                ; the window, $D000-$DFFF the I/O meanwhile

; col_ptr's and col_end's (hwvic128.inc): the window onto colour RAM, at
; $1000-$13FF over the ROM's bytes while $FF00 is CR_IO. colon: the
; interrupts' state kept (coliff), then off, I/O on, HL = COLRAM. coloff:
; $FF00 the Z80's again, the interrupts as they were. Each keeps every
; register but F (and colon's HL). Between them the code and the stack
; (colon's POP and RET, coloff's PUSH are made with $FF00 CR_IO) must be
; outside $1000-$13FF and $D000-$DFFF, and no window opens inside another
; (coliff): hwvic128.inc.
colon:  push af
        ld a,i                  ; P/V: interrupts on (read again if it says
        jp pe,co_ie             ; off: an NMOS Z80 reads 0 if an interrupt
        ld a,i                  ; is taken during it)
co_ie:  di
        ld a,0
        jp po,co_off
        inc a
co_off: ld (coliff),a
        ld a,CR_IO
        ld (CR),a
        pop af
        ld hl,COLRAM
        ret
coloff: push af
        ld a,CR_Z80
        ld (CR),a
        ld a,(coliff)
        or a
        jr z,cf_di
        pop af
        ei
        ret
cf_di:  pop af
        ret
coliff: db 0

; ---------------------------------------------------------------- the monitor
; zx64mon's screen switch on the VIC, its way in, its disk path and its
; breakpoints (boot128 puts the monitor itself at $3000 and $E000): here,
; as its colour fill runs through colon's window
        include "monvic.inc"
zcomend:

        end
