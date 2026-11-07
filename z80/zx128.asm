; zx128 - Z80 side. The ZX81 ROM runs on the C128's own Z80, in RAM bank
; 1, and this code sits next to it, doing what the ZX81's ULA and tape port
; did: what zx64 (z80/zx64.asm) does on the C64's CP/M cartridge, with
; much of the same code (kbd.inc) and the same ROM patches. The 8502's
; side is c128/boot128.asm.
;
; Z80 view of memory (RAM bank 1; F000-FFFF is common RAM, the same bytes
; the 8502 sees in bank 0):
;   0000-1FFF  ZX81 ROM, patched by tools/build.py
;   2000-2DF1  this code and its tables (and the picture's part the ROM's
;              patches call: vdccore.inc; the C128's keys, k2scan.inc, its
;              k2keys the monitor's k2mon's too); 2DF2-2DFF spare (14)
;   2E00-2EFF  ZX81 keyboard rows, indexed by B, and buffers: cmat 00-07
;              (08: k2scan.inc's kptab's "no key"),
;              kq 10-2F, the monitor's bptab 30-41, MSGBUF 44-63, the panel's
;              pn_buf and flags 64-77, JMSG 80-9F, JTEACH A0-A9, the
;              panel's pn_d C0-D8; spare 42-43, 78-7E, AA-BE, D9-DE, E0-EE,
;              F0-F6, F8-FA, FC (the ZX81 rows: 7F BF DF EF F7 FB FD FE)
;   2F00-2FFF  mailbox to the 8502 (zentry's stack for pn_boot below 3000)
;   3000-3FFF  the monitor, zx64mon's part 1 (z80/mon.asm, assembled for
;              zx128)
;   4000-BFFF  ZX81 RAM: 16K to 7FFF, 32K to BFFF
;   C000-C2FF  the picture's shadow, C300-C3FF its state (vdcpic.inc)
;   C400-C8AF  the monitor's screen, MSCR (48 x 25: hw128.inc); C8B0-C8FF
;              free
;   C900-DFFD  zx128's own code: the picture (vdcpic.inc), the panel's
;              parts here (panelhi.inc); to hiend, 233 spare (sim128's
;              zx128_room keeps 128). (DFFE is IN A,($FE)'s $DF row, see
;              below)
;   E000-EFFD  the monitor's part 2
;   F000-F1FF  the ROM's first two pages on their way in (zentry), and
;              again when F7 puts the ROM back (rombk); the monitor's L
;              and W have bank 1's there meanwhile (monvdc.inc's mon_6510)
;   F200-F3FF  the 8502's code in common RAM, and its staging page
;   F400-F7FD  this code's part in common RAM: zentry, zsw, inrow (a
;              game patch's), rombk (F7's ROM), the panel (panel.inc), to
;              zcomend; 24 spare. (F7FE is IN A,($FE)'s $F7 row). In
;              zx128.prg the own area and this part share their pages
;              (boot128's phi to phi_tail): the build says how many bytes
;              before one more (build.py's page_room), which the function
;              ROM may have no room for
;   F800-F8BF  the picture's queue (vdcpic.inc's pic_q)
;   F8C0-FBFD  the monitor's code here (monvdc.inc, bp.inc), and pn_cpu
;              (the panel's CPU row) and vidpal.inc
;              (SPEED's PAL or NTSC), to monend
;   FC00-FEFD  the monitor's rows changed (MDIRTY) FC00-FC18, its buffers
;              (MBUF) FC19-FD35, its stack (MSTACK) FE00-FEFD (hw128.inc);
;              FD36-FDFD free; but for the IN A,($FE) copies FDFE-FDFF
;   FF00-FF04  the MMU
;   FF05-FFED  the monitor's part 3 (the C128 builds' own commands: V),
;              to part3end
;   FFEE       the Z80's entry: JP zentry
; (and the IN A,($FE) copies at A*256+$FE, see mirror: $FEFE, $FDFE,
; $FBFE, $F7FE and $EFFE are in common RAM, $DFFE among the buffers).
;
; The chips are reached by IN and OUT only (z80/hw128.inc), with $FF00 =
; $7F: bank 1, all RAM, I/O off (with I/O on, $1000-$13FF would be colour
; RAM, not the ROM). $FF00 is the MMU's one register for both CPUs, and
; the MMU itself (the CPU switch) answers only with I/O on: the switch is
; done from common RAM (zsw), which is there whatever $FF00 says.
;
; Entry points, all reached from the patched ROM (see tools/build.py):
;   irqh      RST $38, the VIC raster IRQ at line 250, once a frame:
;             the picture's work for it (pic_step)
;   frame     DISPLAY-1's picture: wait for the next frame
;   keywait   the editor's call of DISPLAY-1 (its key wait)
;   slowfast  SLOW/FAST
;   mykbd     KEYBOARD
;   brk       BREAK-1's IN A,($FE)
;   myload    LOAD, mysave SAVE: the 8502 does the disk I/O
;
; As on zx64, as far as the ROM knows its display never runs (CDFLAG bit
; 7 is kept clear); the IRQ does the display's work between frames in
; SLOW mode (FRAMES, LAST_K, the picture on the VDC: vdcpic.inc), and
; FAST mode takes no interrupts while a program runs (the picture holds
; until the next key wait).

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

        include "hw128.inc"     ; VIC, CIA and VDC access (macros)

KPAGE:   equ $2E00              ; ZX81 keyboard rows, KPAGE + row select
                                ; The rest of its page: buffers whose contents
                                ; don't matter at the start
cmat:    equ KPAGE              ; C64 matrix, one byte a column: page aligned
                                ; (scan counts columns in its low byte)
kq:      equ KPAGE+$10          ; the type-ahead queue, 16 slots of 2 bytes
bptab:   equ KPAGE+$30          ; the monitor's breakpoints (bp.inc)
MSGBUF:  equ KPAGE+$44          ; the message for the top row (show), 32 bytes
JMSG:    equ KPAGE+$80          ; the joystick's message (joyshow), 32 bytes
JTEACH:  equ KPAGE+$A0          ; the layout being taught (teach), 10 bytes
MBOX:    equ $2F00              ; +0 command, +1 status, +2 name length, +3 name,
                                ; +$20 SP when the 8502 takes over
CMD_LOAD: equ 1
CMD_SAVE: equ 2
CMD_PRG: equ 3                  ; the monitor's L "NAME" a (zx128's: always
                                ; to a)
CMD_WRITE: equ 7                ; its W s e (both: monvdc.inc's mon_6510)
CMD_ROM: equ 9                  ; the ROM again, from ZX128
ST_TOOBIG: equ 2                ; mailbox status: 0 ok, 1 not found or disk error, 2 too big,
                                ; 3 not a ZX81 program (LOAD: report D, as 1)
ROM01:   equ $F000              ; the ROM's $0000-$01FF, as the 8502 left them
ZCOM:    equ $F400              ; this code's part in common RAM
HICODE:  equ $C900              ; zx128's own code area, to $DFFD
MONCODE: equ $F8C0              ; (the monitor's code: common RAM, to $FBFD)

        org $2000

pic_tick: macro                 ; (the picture: irq_early's, first)
        endm
kw_hello: macro                 ; (rompatch.inc's keywait: nothing more)
        endm
irq_early: macro                ; the picture, in the VDC's blank if it can
        call pic_irq            ; (vdclock.inc)
pic_iret: equ $                 ; (vdcpic.inc's pic_mvd looks for it)
        endm
kb_lkhold: macro                ; a key from the type-ahead (rompatch.inc's
        ld a,2                  ; kb_key): the next 2 IRQs scan but leave
        ld (lkhold),a           ; LAST_K alone (lastk). Else one could put
        endm                    ; its own there (no key: $FFFF) before the
                                ; ROM has decoded the key just handed it,
                                ; when the ROM's way from the key wait to
                                ; DECODE outlasts what the IRQ (the picture's
                                ; 6 ms) leaves of the frame: DECODE then
                                ; loops for ever (seen in sim128)
irq_lastk: macro                ; (irq.inc)
        call lastk
        endm
pic_poll: macro                 ; the same from frame's poll (rompatch.inc),
        di                      ; where interrupts are on: pic_step isn't
        call pic_pstep          ; to be entered twice (the VDC's address,
        ei                      ; its state), and an IRQ might yet come
        endm                    ; (pic_pstep: vdccore.inc)

zentry_more: macro              ; (com128.inc's zentry) the picture's shadow
        ld hl,SHADOW            ; and state clear (the VDC's screen is
        ld de,SHADOW+1          ; blank)
        ld bc,$3FF
        ld (hl),0
        ldir
        xor a                   ; (zx64's version message: the panel's row 0
        ld (hello),a            ; says zx128)
        ld sp,MBOX+$100         ; (a stack for it, in the mailbox's page:
        call pn_boot            ; SP is anything yet) the panel, at once
        call vidm               ; (vidpal.inc)
        endm
zsw_cpu: macro                  ; (com128.inc's zsw) row 24 of the panel:
        call pn_cpu             ; (the normal build's: pn_cpu is beside
        endm

        include "irq.inc"       ; irqh, the raster IRQ

; ---------------------------------------------------------------- messages
; A message for a setting (HL, from msgs.inc) for 2 seconds: into MSGBUF,
; 32 characters (msgx), and ovl counts its frames; the panel's rows 13-14
; show it meanwhile (panel.inc's pn_show). showb: HL is 32 characters
; already.
show:   ld de,MSGBUF
        push de
        call msgx
        pop hl
showb:  ld (ovl_msg),hl
        ld a,100
        jp pn_show
        ds 1                    ; (room kept: kbd.inc and vars.inc where
                                ; they were, the scan's time with them)

        include "msgx.inc"

; ---------------------------------------------------------------- not here
; What the shared code calls that zx128 has elsewhere or not at all: the
; loading row (lstat: the 8502 draws it in the panel's rows 13-14 itself,
; c128/boot128.asm). Keeps every register. (The monitor's breakpoints,
; bp_hit and bp_off: bp.inc, in common RAM.)
lstat:
        ret

        include "rompatch.inc"  ; frame, notbad, slowfast, keywait

        include "kbd.inc"

KPFAST:  equ 0                 ; (k2scan.inc: by its table: the core is short of room)
        include "k2scan.inc"    ; the C128's keypad and cursor keys, for scan

; (F2's nextcol: panel.inc.)
        ds 1                    ; (room kept, as at showb)

        include "reset.inc"     ; F7, F8, romsum

; Changed: the 8502 puts it back (CMD_ROM, c128/boot128.asm's dorom): from
; the boot file's copy still in its bank 0 if that adds up to the build's
; sum, else from ZX128 on the disk. If neither, it says why in show's
; MSGBUF (the panel shows it), and the ZX81 starts with the ROM as it is.
romfix: ld hl,rom_name
        ld de,MBOX+2
        ld bc,6
        ldir
        ld a,CMD_ROM
        ld (MBOX),a
        jp rombk
rom_name:
        db 5,"ZX128"

        include "romkbd.inc"    ; mykbd, mirror, brk

; ---------------------------------------------------------------- LOAD/SAVE
; The 8502's server does the disk I/O through the C128 kernal, and draws
; the loading row in the panel (c128/boot128.asm; not under the
; monitor's screen).
        include "loadsave.inc"
        include "setname.inc"

        include "call128.inc"   ; call6510; F5, F3: mon_irq, mon_call

        include "vars.inc"
        include "vdccore.inc"   ; the picture's part the ROM's patches call
                                ; (after vars.inc: its tables where they
                                ; were, kbd.inc's scan's time with them)
coreend:                       ; (tools/build.py: the core ends here)

; ---------------------------------------------------------------- own area
; zx128's own code, past the ZX81's RAM: the core below KPAGE keeps what
; room it has left for what zx64 shares. c128/boot128.asm puts it at HICODE; build.py
; stops if it reaches $DFFE.

        org HICODE
hicode:
        include "vdcpic.inc"    ; the picture
        include "vdclock.inc"   ; its tick on the VDC's frame

; The IRQ's keys (HL) to LAST_K, unless kb_lkhold holds it (an IRQ less
; each time). Keeps HL.
lastk:  ld a,(lkhold)
        or a
        jr z,lk_put
        dec a
        ld (lkhold),a
        ret
lk_put: ld (LASTK),hl
        ret
lkhold: db 0
        include "panelhi.inc"   ; the panel's parts here (panel.inc's)
hiend:
pic_q:   equ $F800              ; the picture's queue (vdcpic.inc), 3 bytes a
                                ; run: in common RAM, page aligned (the own
                                ; area has no room for it; its place before,
                                ; $C600, is the monitor's screen's)
pic_qend: equ pic_q+3*QMAX

; ---------------------------------------------------------------- common RAM
; In common RAM at ZCOM (c128/boot128.asm puts it there), for what runs
; while $FF00 may not be the Z80's.

        org ZCOM

        include "com128.inc"    ; zentry, zsw, inrow, rombk

; ---------------------------------------------------------------- the panel
; (Not for $FF00's sake: the own area and the core have no room for it.
; boot128 copies ZCOM's pages up to $F7FD: $F7FE is IN A,($FE)'s $F7 row.)
        include "panel.inc"
zcomend:
blit:    equ pn_blit             ; LOAD's picture, at once, and the panel's
                                ; rows (loadsave.inc; an equ after what it
                                ; names, or z80asm takes 0)

; ---------------------------------------------------------------- the monitor
; zx64mon's screen on the VDC, and its breakpoints, in common RAM after the
; picture's queue (boot128 puts them there): the own area and the core
; have no room for them.
        org MONCODE
moncode:
        include "monvdc.inc"

; The normal build's two extras, here with the monitor's code:
; the own area and the panel's part in common RAM share their pages in
; the image (zx128.prg, boot128's phi to phi_tail: the build says the
; bytes before a page more, which the function ROM may lack), and this
; part is the image's last, unpadded.
;
; Row 24's CPU, now, polled: the Z80, or the 8502 while a command is in
; the mailbox (panel.inc's pr_cpu), as the LED mod shows it on the C64
; cartridge. zsw calls it as the 8502 takes over and again once it hands
; back: written at once, not as a job (F7 in 32K runs the ZX81's RAM
; test with interrupts off for seconds after the 8502's turn). Keeps DE
; HL (BC: zsw keeps it).
pn_cpu: push de
        push hl
        ld a,24
        call pn_now
        pop hl
        pop de
        ret
        include "vidpal.inc"    ; PAL or NTSC for SPEED's {vidpal}
monend:

        end
