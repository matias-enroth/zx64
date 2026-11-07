; zx64 - Z80 side. The ZX81 ROM runs on the C64 CP/M cartridge's Z80, and
; this code sits next to it, doing what the ZX81's ULA and tape port did:
; the picture, the keyboard, LOAD and SAVE.
;
; Z80 view of memory (C64 address = Z80 address + $1000, wrapping):
;   0000-1FFF  ZX81 ROM, patched by tools/build.py   (C64 1000-2FFF)
;   2000-2DFF  this code and its tables              (C64 3000-3DFF)
;   2E00-2EFF  ZX81 keyboard rows, indexed by B      (C64 3E00-3EFF)
;   2F00-2FFF  mailbox to the 6510                   (C64 3F00-3FFF)
;   4000-BFFF  ZX81 RAM: 16K to 7FFF, 32K to BFFF     (C64 5000-CFFF)
;   3000-3FFF  zx64mon, once F5 has loaded it        (C64 4000-4FFF)
;   C000-CFFF  C64 I/O: VIC C000, CIA1 CC00, cartridge switch CE00
;   D000-D3FF  VIC screen, font at D800              (C64 E000-E3FF)
;   D400-D4FD  the monitor's buffers (MBUF)          (C64 E400-E4FD)
;   D500-D6FF  zx64's second area, ZX64HI: code that (C64 E500-E6FF)
;              isn't on the per-frame or per-key path; start (c64/boot.asm)
;              puts it there from behind the JiffyDOS reader in ZX64
;   D700-D7FF  the monitor's stack, from D7FF down   (C64 E700-E7FF)
;   E000-EFFF  zx64mon2, the monitor's second part   (C64 F000-FFFF)
;   F000-FFFF  the 6510's page: its loader           (C64 0000-0FFF)
;
; Entry points, all reached from the patched ROM (see tools/build.py):
;   irqh      RST $38, the VIC raster IRQ at line 250, once a frame
;   frame     DISPLAY-1's picture: wait for the next frame
;   keywait   the editor's call of DISPLAY-1 (its key wait)
;   slowfast  SLOW/FAST
;   mykbd     KEYBOARD
;   brk       BREAK-1's IN A,($FE)
;   myload    LOAD, mysave SAVE: the 6510 does the disk I/O
; and F5 enters the monitor, zx64mon (z80/mon.asm), through mon_irq or
; mon_call.
;
; As far as the ROM knows, its display never runs (CDFLAG bit 7 is kept
; clear). SLOW mode: interrupts are on, and the IRQ does the display's
; work between frames: the picture, FRAMES, LAST_K. FAST mode: as on a
; ZX81, no interrupts while a program runs (the picture stays as it was);
; they are on only while the ROM waits for a key or does a PAUSE.
; Without /INT (the original cartridge doesn't connect it), the picture
; only changes while the ROM waits for a key or a PAUSE, in either mode.

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

        include "hw64.inc"      ; VIC, CIA and colour RAM access (macros)
CARTSW:  equ $CE00
SCREEN:  equ $D000              ; C64 $E000, RAM under the kernal

KPAGE:   equ $2E00              ; ZX81 keyboard rows, KPAGE + row select
                                ; The rest of its page: buffers whose contents
                                ; don't matter at the start
cmat:    equ KPAGE              ; C64 matrix, one byte a column: page aligned
                                ; (scan counts columns in its low byte)
kq:      equ KPAGE+$10          ; the type-ahead queue, 16 slots of 2 bytes
bptab:   equ KPAGE+$30          ; the monitor's breakpoints: 6 x (address, the
                                ; byte it replaced)
MSGBUF:  equ KPAGE+$44          ; the message on the top row (show), 32 bytes
JMSG:    equ KPAGE+$80          ; the joystick's message (joyshow), 32 bytes
JTEACH:  equ KPAGE+$A0          ; the layout being taught (teach), 10 bytes
MBOX:    equ $2F00              ; +0 command, +1 status, +2 name length, +3 name,
                                ; +$20 SP when the 6510 takes over
CMD_LOAD: equ 1
CMD_SAVE: equ 2
CMD_PRG: equ 3                  ; a PRG file to its own load address
CMD_ROM: equ 9                  ; the ROM again, from ZX64
MON:     equ $3000              ; zx64mon: JP its entry, then "ZM" (C64 $4000)
MON2:    equ $E000              ; zx64mon2, its second part: "M2" (C64 $F000)
ST_TOOBIG: equ 2                ; mailbox status: 0 ok, 1 not found or disk error, 2 too big,
                                ; 3 not a ZX81 program (LOAD: report D, as 1)

DSIZE:   equ 24*33+1            ; VARS - D_FILE of a fully expanded display

        org $2000

pic_tick: macro                 ; the picture from the IRQ (irq.inc) and
        ld a,(tick)             ; frame's poll (rompatch.inc): at 25 Hz
        rra
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
kw_hello: macro                 ; (rompatch.inc's keywait, the first key wait)
        call blit               ; start (c64/boot.asm) left every cell solid
        call setcol             ; white: the picture over its cells first
        endm                    ; (without /INT no blit has run yet), then
                                ; the frame's colours (vicpic.inc), so no
                                ; cell shows black meanwhile
irq_lastk: macro                ; (irq.inc) the IRQ's keys (HL) to LAST_K,
        ld a,(lkhold)           ; unless kb_lkhold holds it: an IRQ less
        or a                    ; each time. zx128's lastk, in line here:
        jr z,lk_put             ; a CALL would take the IRQ with no key
        dec a                   ; down past simulate.py's 1,300 T. Held:
        ld (lkhold),a           ; LAST_K put back as it is
        ld hl,(LASTK)
lk_put: ld (LASTK),hl
        endm
irq_early: macro                ; (irq.inc: nothing on zx64)
        endm

        include "irq.inc"

lkhold: db 0                    ; kb_lkhold's count of IRQs (irq_lastk)

        include "vicpic.inc"    ; the picture: blit, show, ovl_top (and
                                ; msgx.inc); the colours' vic_colours

        include "rompatch.inc"

        include "kbd.inc"

        vic_colours             ; F2: nextcol, setcol, schemes (vicpic.inc)

        include "reset.inc"

; Changed: the 6510 reads it again from ZX64 (the file ZX81 loaded) on the
; disk zx64 came from, with the bar on the top row (about 20 seconds), and
; puts it in place only if it is this build's ROM (dorom in c64/boot.asm).
romfix: ld hl,txt_load
        ld de,txt_rom
        ld c,7
        call lstat
        ld hl,rom_name
        ld de,MBOX+2
        ld bc,5
        ldir
        ld a,CMD_ROM
        ld (MBOX),a
        call call6510
        ld hl,MSGBUF            ; the size on the top row again, or why the
        call showb              ; ROM wasn't read again: the 6510 put it
        ld a,(MBOX+1)           ; there (dorom), and it stays 5 seconds
        or a
        ret z
        ld a,250
        ld (ovl),a
        ret
rom_name:
        db 4,"ZX64"

        include "romkbd.inc"

        include "loadsave.inc"

        include "setname.inc"

; Hand the bus to the 6510, which does what the mailbox says and hands it
; back. The raster IRQ is off meanwhile, so the 6510 never sees it.
; Returns with interrupts off (LOAD and SAVE end through slowfast).
call6510:
        di
        xor a
        vic_wr $1A
        dec a
        vic_wr $19
        ld a,1
        ld (MBOX+$20),sp        ; the 6510 must not LOAD over the stack
        ld (CARTSW),a           ; the Z80 stops here...
        nop                     ; "You MUST follow the mode switching store
                                ; instruction with a NOP" (Commodore's CP/M
                                ; guide, 6.6.1): the byte after it can be
                                ; lost when the Z80 is switched back on
sw_back:                        ; ...and carries on here
        ld a,$FF
        vic_wr $19
        ld a,1
        vic_wr $1A
        ret

; ---------------------------------------------------------------- monitor
; F5: zx64mon, the machine code monitor (z80/mon.asm), loaded from the
; disk the first time, to MON and MON2 (two files). It is entered with the registers on the
; stack as the IRQ leaves them, HL DE BC AF and the return address, and
; comes back through mon_ret with them, changed or not, at the SP it
; was given (or another, if it was changed there). moniff: interrupts
; on when it returns.
mon_irq:                        ; from the IRQ, which found monreq set
        xor a
        ld (monwhy),a
        inc a                   ; interrupts were on
        jr mon_go
mon_call:                       ; from zx64's code: the same on the stack
        push af
        push bc
        push de
        push hl
        xor a
        ld (monwhy),a
        ld a,i                  ; P/V: interrupts on
        di
        ld a,0
        jp po,mon_go
        inc a
mon_go: di
        ld (moniff),a
        ld hl,monreq
        ld a,(hl)
        ld (hl),0
        cp 2                    ; F3 held: teach, no monitor
        jr nz,mg_mon
        call teach
        jr mon_ret
mg_mon: call mon_here
        call nz,mon_load
        jp z,MON
        call show               ; HL: why not (mon_here), on the top row
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

mon_load:                       ; from the disk, both parts: Z if they came,
        ld hl,txt_load          ; the top row's bar going across both
        ld de,txt_mon
        ld c,6
        call lstat
        ld hl,(monsz)
        ld de,(monsz+2)
        add hl,de
        ld (MBOX+$28),hl
        ld a,1
        ld (MBOX+$27),a
        ld hl,mon_name
        call mon_file
        ld a,2
        ld (MBOX+$27),a
        ld hl,mon_name2
        call mon_file
        xor a
        ld (MBOX+$27),a         ; the monitor's own L shows nothing
        call blit               ; the picture over the top row again
        jp mon_here
mon_file:
        xor a                   ; to the file's own address (see the 6510's
        ld (MBOX+$26),a         ; doprg)
        ld de,MBOX+2
        ld bc,9
        ldir
        ld a,CMD_PRG
        ld (MBOX),a
        jp call6510
mon_name:
        db 7,"ZX64MON",0        ; length, PETSCII
mon_name2:
        db 8,"ZX64MON2"
monsz:  dw 0,0                  ; their sizes: build.py puts them in

        include "bp.inc"        ; bp_hit, bp_off

        include "vars.inc"
coreend:                        ; the core ends here: below KPAGE (build.py)

; ---------------------------------------------------------------- ZX64HI
; zx64's second area (hw64.inc), past the core in the assembled file:
; build.py stages it behind the JiffyDOS reader in ZX64 and start copies it
; to C64 $E500 before the Z80 starts. Nothing here may be needed before
; that, or by the 6510; it stays in place through F7 (the ROM read again),
; LOAD and the monitor (its stack stays 64 bytes above ZX64HIEND).
        org ZX64HI

; The top row while the 6510 loads or saves (it fills it in: pstep in
; c64/boot.asm): HL's word (8 characters), the name (12 at most), an
; empty bar of 8 cells from column 22, white, the spinner's cell at 31.
; Inverse, as the settings' messages are. Keeps DE and C, NAME's.
lstat:  push de
        push bc
        xor a
        ld (ovl),a              ; no setting's message over it
        push hl
        ld hl,SCREEN+4
        ld b,32
ls1:    ld (hl),$80
        inc hl
        djnz ls1
        ld hl,SCREEN+26         ; the bar: white, the 6510 fills it black
        ld b,8
ls0:    ld (hl),0
        inc hl
        djnz ls0
        pop hl
        ld de,SCREEN+5
        ld bc,8
        ldir
        pop bc
        pop de
        push de
        push bc
        ld a,c
        inc a
        cp 13
        jr c,ls2
        ld a,12
ls2:    ld b,a
        ld hl,SCREEN+13
ls3:    ld a,(de)
        and $3F
        or $80
        ld (hl),a
        inc hl
        inc de
        djnz ls3
        pop bc
        pop de
        ret

; Z: this build's zx64mon is at MON and MON2: their tags ("ZM", "M2") and,
; beside each, this build's stamp (build.py puts it in mstamp and in both
; parts). Else NZ and HL the top row's message: none there (msg_nomon), or
; one from another build (msg_othmon), whose calls into the core would
; go astray. The next F5 tries the disk again either way.
mon_here:
        ld hl,(MON+3)
        ld de,$4D5A             ; "ZM"
        and a
        sbc hl,de
        jr nz,mh_no
        ld hl,(MON2)
        ld de,$324D             ; "M2"
        sbc hl,de
        jr nz,mh_no
        ld de,(mstamp)
        ld hl,(MON+6)
        sbc hl,de
        jr nz,mh_oth
        ld hl,(MON2+2)
        sbc hl,de
        ret z
mh_oth: ld hl,msg_othmon
        ret
mh_no:  ld hl,msg_nomon
        ret
mstamp: dw 0                    ; the build's stamp: build.py puts it in

hiend:                          ; below ZX64HIEND (build.py)

        end
