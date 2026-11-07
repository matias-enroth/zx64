; zx128 - 8502 side: ZX128, which the C128's kernal loads from the disk's
; boot sector (track 1 sector 0, written by tools/build.py) to $1300 in
; bank 0 and starts there.
;
; Puts the payload behind it (the patched ZX81 ROM, the Z80 code) into RAM
; bank 1, sets the VDC up (with the fonts, also in the payload), and
; starts the Z80 at $FFEE, which starts the ZX81 ROM (z80/zx128.asm).
; From then on the 8502 only wakes up when the Z80 hands back with a
; command in the mailbox (server: LOAD, SAVE, F7's ROM, the monitor's
; disk commands, through the C128 kernal), and hands back again once it
; is done.
;
; The MMU (as VICE's x128 has it): $D506 = $0A (8K of common RAM at the
; top, none at the bottom); for the Z80 the page pointers on bank 1 and
; $FF00 = $7F (bank 1, all RAM, I/O off: with I/O on the Z80 would see
; colour RAM at $1000-$13FF). $FF00 is one register for both CPUs, and the
; MMU (the CPU switch, the page pointers) answers only with I/O on, so
; each CPU switches from code in common RAM ($F000-$FFFF), which is there
; whatever $FF00 says: the 8502's below (com), the Z80's in z80/zx128.asm
; (zentry, zsw). The 8502's zero page and stack are bank 0's: the page
; pointers are on bank 1 only while the Z80 runs.
;
; Bank 0 once booted:
;   0000-12FF  the kernal's (zero page, stack, vectors, its buffers): its
;              disk routines are called from here (the disk, below)
;   1300-...   this code: the boot, the server and the disk's code and
;              tables, com (copied to common RAM, F300), up to prom
;   prom       the patched ZX81 ROM, 8K, as the boot file brought it: F7's
;              first source (dorom); nothing writes it but dorom itself
;   MBC        (prom + $2000) the mailbox's page, copied for a command;
;              the disk's variables from its +$40
;   BUF        (MBC + $100) to DFFF: LOAD's file, SAVE's bytes, F7's
;              ZX128. Booting, the rest of the payload was here (the core,
;              the own area, the panel, the font, the monitor): no longer
;              needed
;   E000-FFFF  common RAM (z80/zx128.asm's map)
;
; VDC (from tools/build.py): 1 for zx128, the picture on the
; VDC (vdcinit, the panel's rows, the fonts there); 0 for zx128vic
; (z80/zx128vic.asm), zx64's picture on the VIC: vicinit points the VIC
; at bank 1's $C000 (the ZX81's screen) and $C800 (its font, made here),
; the C128's character ROM copied to $D000 for the monitor (F7 and F8
; make them again: CMD_FONT, vfonts); no panel: the disk's rows go on the
; VIC's top row, as zx64's 6510 draws its bar (wrow, row14, bar), and its
; messages over it as a setting's (show's MSGBUF). Each says which screen
; to use if the 40/80 key picks the other: zx128 on the VIC's (msg40),
; zx128vic on the VDC's (msg80).
;
; tools/build.py assembles this with the payload's files from build/obj,
; ZENTRY (the Z80's entry in common RAM), HICODE (where zx128's own code
; area starts, $C900), ROMSUM (the ROM's sum, as romsum_v), ROMSUMV, OVL
; and OVLMSG (romsum_v, ovl, ovl_msg in the core), MBOX, MSGBUF and PND
; (bank 1's mailbox, show's message and the panel's jobs, pn_d),
; disk128.a (the disk's tables), and MONCODE, MONUP (zx64mon,
; resident: its code's place in common RAM, and its mon_up there; zx128vic:
; no MONCODE, that code is in its common RAM part), into
; build/obj/zx128.prg.

!cpu 6502

                        ; (MBOX, from tools/build.py: the mailbox in bank
                        ; 1, +0 command, +1 status)
ROM01   = $f000         ; the ROM's first two pages, for zentry to put at $0000
STAGE   = $f200         ; a page on its way to bank 1 (tobank1)
COM     = $f300         ; com: this code's part in common RAM
ZCOM    = $f400         ; the Z80's part (z80/zx128.asm)
CR      = $ff00         ; the MMU's configuration register
MCR     = $d505         ; the CPU switch, and the 40/80 key (bit 7, 0: down)
RCR     = $d506         ; common RAM
P0L     = $d507         ; the page pointers: high bytes (the bank) first
P0H     = $d508
P1L     = $d509
P1H     = $d50a
VDCS    = $d600         ; the VDC: register select, status (bit 7: ready)
VDCD    = $d601         ; its data
SRC     = $fb           ; tobank1's pointers (the kernal leaves $FA-$FE to the
DST     = $fd           ; user: those are all of boot128's zero page)
CNT     = $fa           ; vfill: bytes after the first
TLAST   = $fa           ; tobank1: the bytes of its last page (0: 256)
VA      = $fb           ; vdcinit: an attribute row's address (SRC's:
                        ; tobank1 sets SRC and DST itself, TLAST is set
                        ; just before phi's copy)

ST_ERR  = 1

* = $1300
entry:  cld
        sei
        lda $ba                 ; the drive the boot sector came from (the
        bne +                   ; disk's: server)
        lda #8
+       sta dev
        lda #$3e                ; bank 0, all RAM, I/O on
        sta CR
        lda #$0a                ; 8K of common RAM at the top, none at the
        sta RCR                 ; bottom (the VIC on bank 0; zx128vic's on
        ldx #$ff                ; bank 1 from vicinit)
        txs
        lda #$7f                ; no CIA interrupts
        sta $dc0d
        sta $dd0d
        lda $dc0d
        lda $dd0d
        lda #0                  ; none from the VIC until the Z80 wants its
        sta $d01a               ; raster IRQ
        lda #$ff
        sta $d019
        sta $d02f               ; no C128 key column selected (k2scan does)
        lda #<nmi               ; RESTORE does nothing, whichever bank is on
        sta $fffa               ; (the kernal's ROM in, for the disk: its
        lda #>nmi               ; NMI comes through $0318, nmik)
        sta $fffb
        lda #<nmik
        sta $0318
        lda #>nmik
        sta $0319

!if VDC {
        lda MCR                 ; the 40/80 key: up, a 40-column monitor
        bpl +
        ldx #0                  ; is looking: say so on the VIC's screen,
-       lda #$20                ; which stays on
        sta $0400,x
        sta $0500,x
        sta $0600,x
        sta $06e8,x
        inx
        bne -
-       lda msg40,x
        beq ++
        sta $0400,x
        inx
        bne -
+       lda $d011               ; down: the VIC blanked (no bad lines), but
        and #$ef                ; its raster still the Z80's 50 Hz
        sta $d011
++
} else {                        ; (zx128vic: the VIC as vicinit sets it)
        lda MCR                 ; the 40/80 key: down, an 80-column monitor
        bmi ++                  ; is looking: say so on the VDC's screen
        lda #$20                ; (its cursor off: R10's blink bits 01)
        ldx #10
        jsr vw
        jsr vat                 ; (the kernal's, at $0000: 8 x 250 spaces,
        ldy #8                  ; then the words), its attributes as they
--      lda #250                ; are; nothing else here touches the VDC
        sta CNT
-       lda #$20
        jsr vw
        dec CNT
        bne -
        dey
        bne --
        jsr vat
-       lda msg80,y
        beq ++
        jsr vw
        iny
        bne -
++
}
        lda $d011               ; raster line 250 (bit 8 clear)
        and #$7f
        sta $d011
        lda #250
        sta $d012

        ldx #0                  ; into common RAM: com, the ROM's first two
-       lda com_src,x           ; pages (zentry puts them in place), the
        sta COM,x               ; Z80's part
        lda prom,x
        sta ROM01,x
        lda prom+$100,x
        sta ROM01+$100,x
        lda pzcom,x
        sta ZCOM,x
        inx
        bne -
-       lda pzcom+$100,x        ; the Z80's part's next pages (the panel)...
        sta ZCOM+$100,x
        lda pzcom+$200,x
        sta ZCOM+$200,x
        inx
        bne -
        ldx #$fe                ; ...to $F7FD ($F7FE is IN A,($FE)'s $F7 row)
-       lda pzcom+$2ff,x
        sta ZCOM+$2ff,x
        dex
        bne -
        lda #$c3                ; $FFEE, where the Z80 starts: JP zentry
        sta $ffee
        lda #<ZENTRY
        sta $ffef
        lda #>ZENTRY
        sta $fff0
        lda #0                  ; whole pages
        sta TLAST
        lda #(>prom) + 2        ; the rest of the ROM to bank 1 $0200
        ldy #$02
        ldx #$1e
        jsr tobank1
        lda #>pcore             ; the core to bank 1 $2000
        ldy #$20
        ldx #CORE_PAGES
        jsr tobank1
!if VDC {
        jsr vblk                ; (into phi's blk_cfg: before it goes over)
        jsr vdcinit
} else {
        jsr vicinit             ; (zx128vic) the VIC's screens and fonts
}
        lda #<(phi_end - phi)   ; zx128's own code area to bank 1 HICODE,
        sta TLAST               ; no further: its end may be near $DFFE
        lda #>phi               ; (IN A,($FE)'s $DF row)
        ldy #>HICODE
        ldx #HI_PAGES
        jsr tobank1
        lda #0                  ; zx64mon: its part 1 to bank 1 $3000 (whole
        sta TLAST               ; pages, to $3FFF at most)
        lda #>pmon1
        ldy #$30
        ldx #MON1_PAGES
        jsr tobank1
        lda #<pmon2             ; its part 2 to $E000, no further: its end
        sta SRC                 ; may be near $EFFE (IN A,($FE)'s $EF row)
        lda #>pmon2
        sta SRC+1
        lda #$00
        sta DST
        lda #$e0
        sta DST+1
        lda #<(pmon2_end - pmon2)
        sta TLAST
        ldx #>(pmon2_end - pmon2)
        jsr mcopy
        lda #<pmon3             ; its part 3 (the C128 builds' own commands)
        sta SRC                 ; to $FF05, no further: $FFEE is the Z80's
        lda #>pmon3             ; entry, written above
        sta SRC+1
        lda #$05
        sta DST
        lda #$ff
        sta DST+1
        lda #<(pmon3_end - pmon3)
        sta TLAST
        ldx #0
        jsr mcopy
!if VDC {
        lda #<pmhi              ; zx128's code for it to MONCODE, after the
        sta SRC                 ; picture's queue (z80/monvdc.inc)
        lda #>pmhi
        sta SRC+1
        lda #<MONCODE
        sta DST
        lda #>MONCODE
        sta DST+1
        lda #<(pmhi_end - pmhi)
        sta TLAST
        ldx #>(pmhi_end - pmhi)
        jsr mcopy
}                               ; (zx128vic's: in its common RAM part, pzcom)

        lda #$ff                ; the raster IRQ: the Z80's
        sta $d019
        lda #1
        sta $d01a
        jmp tozx

; The command in the mailbox, A (MBOX+0): LOAD, SAVE, F7's ROM, and the
; monitor's 3-8 (its L "NAME" a, $, W s e and @: the disk, below); any
; other fails, ST_ERR.
server: cmp #CMD_LOAD
        bne +
        jmp doload
+       cmp #CMD_SAVE
        bne +
        jmp dosave
+       cmp #CMD_ROM
        bne +
        jmp dorom
+
!if VDC = 0 {
        cmp #CMD_FONT           ; (zx128vic) F7's and F8's: the VIC's fonts
        bne +
        jsr vfonts
        lda #ST_OK
        jmp answer
+
}
        sec                     ; the monitor's: mtab's, after dbeg (whose
        sbc #CMD_PRG            ; RTS goes there)
        cmp #CMD_DCMD-CMD_PRG+1
        bcs +
        asl
        tax
        lda mtab+1,x
        pha
        lda mtab,x
        pha
        jmp dbeg
+
        lda #ST_ERR
        jmp answer

; X whole pages from SRC to DST, then TLAST bytes more, in bank 0 (here
; common RAM: the monitor's parts).
mcopy:  ldy #0
        cpx #0
        beq mc_t
mc_p:   lda (SRC),y
        sta (DST),y
        iny
        bne mc_p
        inc SRC+1
        inc DST+1
        dex
        bne mc_p
mc_t:   cpy TLAST
        beq mc_x
        lda (SRC),y
        sta (DST),y
        iny
        bne mc_t
mc_x:   rts

; An NMI (RESTORE) while the kernal's ROM is in (the disk): its handler
; has saved the registers and $FF00 and come here through $0318; back
; through its own end, which puts them back.
nmik:   jmp $ff33

!if VDC {
msg40:  !scr "zx128: the 80-column screen, please", 0
} else {
msg80:  !scr "zx128vic: the 40-column screen, please", 0
; (zx128vic) The VDC's update address $0000, R31 selected: X 31, A 0.
vat:    lda #0
        ldx #18
        jsr vw
        inx
        jsr vw
        ldx #31
        rts
; VDC register X <- A, once the VDC is ready. Keeps A, X, Y.
vw:     stx VDCS
-       bit VDCS
        bpl -
        sta VDCD
        rts
}

!if VDC {
; ------------------------------------------------------------ the VDC
; Registers on top of the kernal's set-up: the screen at $0000, the
; attributes at $0800, character set 0 at $2000 (set 1, attribute bit 7,
; at $3000), attributes on, one background colour for the whole screen.
; The colours are colour scheme 0's (z80/panelhi.inc's pn_cols: white on
; black): the background black; attributes: the picture's area
; (rows 0-23, columns 0-63) white in set 0, the rest (the panel at
; columns 64-79, row 24) white in set 1. The screen is $00: blank in both
; sets (the left and the right half of a space: the Z80's shadow starts
; as spaces), and so is the monitor's ($1000-$17FF: z80/monvdc.inc's).
; Then the fonts (vfont).
vdcinit:
        lda #0
        ldx #12
        jsr vdcw                ; R12/R13: the screen
        inx
        jsr vdcw
        lda #$08
        ldx #20
        jsr vdcw                ; R20/R21: the attributes
        lda #0
        inx
        jsr vdcw
        ldx #28                 ; R28: the character sets at $2000 (bit 4,
        jsr vdcr                ; the RAM type, kept)
        and #$1f
        ora #$20
        jsr vdcw
        ldx #25                 ; R25: text, attributes on (the scroll kept)
        jsr vdcr
        and #$0f
        ora #$40
        jsr vdcw
        lda #$f0                ; R26: the background black
        ldx #26
        jsr vdcw
        ldx #24                 ; R24 bit 7 clear: R30 fills
        jsr vdcr
        and #$7f
        jsr vdcw

        lda BCFG+1              ; fills of 128 (two a page) and of 64 as vblk
        bne +                   ; found them (else as R31 and 63 more: its
        lda #63                 ; counts weren't one of those expected)
+       sta VA+1                ; (VA+1: a fill of 64's R30)
        clc
        adc #64
        sta CNT
        ldx #0                  ; the screen, $0000-$07FF: blank
-       lda #$00
        jsr vpage
        inx
        cpx #8
        bne -
-       lda #$8f                ; the attributes, $0800-$0FFF: set 1
        jsr vpage
        inx
        cpx #16
        bne -
-       lda #$00                ; the monitor's screen, $1000-$17FF: blank
        jsr vpage
        inx
        cpx #$18
        bne -
        lda VA+1                ; the picture's 64 columns of rows 0-23:
        sta CNT                 ; set 0
        lda #$00
        sta VA
        lda #$08
        sta VA+1
-       lda #$0f
        ldx VA+1
        ldy VA
        jsr vfill
        lda VA
        clc
        adc #80
        sta VA
        bcc +
        inc VA+1
+       cmp #<($0800+24*80)
        bne -
        lda VA+1
        cmp #>($0800+24*80)
        bne -
                                ; (on into vfont)
; The fonts (tools/build.py's font128), the VDC's 16-byte cell a glyph (8
; bytes, then 0s): set 0 at $2000 made here from the ROM's 64 glyphs (at
; $1E00 in prom): code c is glyph c & $3F, its left 4 pixels (c & $40
; clear) or right 4 doubled (wide), inverted if c & $80; set 1 at $3000:
; codes 0-127 the ROM's glyphs as they are, inverted from 64, then the
; payload's 96 (font: ASCII $20-$7F, 8 bytes each), then 32 blank.
vfont:  lda #$20
        ldx #18
        jsr vdcw
        lda #$00
        inx
        jsr vdcw
        ldx #31
        stx VDCS
        ldx #0                  ; X: the code
vf_c:   jsr vglyph
        ldy #0
vf_r:   lda (SRC),y
        sty DST                 ; (DST: Y kept)
        pha
        txa
        and #$40
        beq vf_l
        pla                     ; the right half
        and #$0f
        jmp vf_w
vf_l:   pla                     ; the left half
        lsr
        lsr
        lsr
        lsr
vf_w:   tay
        lda wide,y
        cpx #$80
        bcc vf_n
        eor #$ff
vf_n:   jsr vput
        ldy DST
        iny
        cpy #8
        bne vf_r
        lda #0
-       jsr vput
        dey
        bne -
        inx
        bne vf_c
vs_c:   jsr vglyph              ; set 1: on at $3000 (X 0 again)
        ldy #0
vs_r:   lda (SRC),y
        cpx #$40
        bcc +
        eor #$ff
+       jsr vput
        iny
        cpy #8
        bne vs_r
        lda #0
-       jsr vput
        dey
        bne -
        inx
        bpl vs_c
        lda #<font
        sta SRC
        lda #>font
        sta SRC+1
--      ldy #0
-       lda (SRC),y
        jsr vput
        iny
        cpy #8
        bne -
        lda #0
-       jsr vput
        dey
        bne -
        lda SRC
        clc
        adc #8
        sta SRC
        bcc --
        inc SRC+1
        lda SRC+1
        cmp #>font_end
        bne --
        lda #0                  ; 32 blank: 512 zeros (Y is 0)
        ldx #2
-       jsr vput
        dey
        bne -
        dex
        bne -
        rts

; SRC: code X's glyph in the ROM (X & $3F). Keeps X.
vglyph: txa
        and #$3f
        sta SRC
        lda #0
        asl SRC
        rol
        asl SRC
        rol
        asl SRC
        rol
        adc #(>prom) + $1e
        sta SRC+1
        rts

wide:   !byte $00, $03, $0c, $0f, $30, $33, $3c, $3f    ; 4 pixels doubled
        !byte $c0, $c3, $cc, $cf, $f0, $f3, $fc, $ff

; A to the VDC's data, R31 selected, once it is ready. Keeps A, X, Y.
vput:   bit VDCS
        bpl vput
        sta VDCD
        rts

; The VDC's block fill and copy tried, for the Z80's picture
; (z80/vdcpic.inc's blk_step): 40 zeros at BLK_AT (VDC RAM nothing uses yet:
; the monitor's attributes later, z80/monvdc.inc's map, which mon_on fills),
; a fill there (R31 $A5, then R30 = 12: 13 bytes if BLK_FILLN is right),
; a copy of it (R30 = 8) to BLK_AT + $18, read back. Into the Z80's code
; area's blk_cfg (phi + BLK_CFG, before it goes to bank 1): R30 for a copy
; of 64 and for a fill of 64 after R31's byte, BLK_COPYN and BLK_FILLN
; moved by one if a count is one off, anything else 0 (no block
; operations); R24 for a fill; the counts, the copy's and the fill's.
; The 40 bytes zeroed again.
BCFG    = phi + BLK_CFG
vblk:   ldx #24
        jsr vdcr
        and #$7f
        sta BCFG+2
        jsr vdcw
        jsr vbzero
        lda #12
        sta CNT
        lda #$a5
        ldx #>BLK_AT
        ldy #<BLK_AT
        jsr vfill
        lda BCFG+2              ; the copy
        ora #$80
        ldx #24
        jsr vbw
        lda #>(BLK_AT+$18)
        ldx #18
        jsr vdcw
        lda #<(BLK_AT+$18)
        inx
        jsr vdcw
        lda #>BLK_AT
        ldx #32
        jsr vdcw
        lda #<BLK_AT
        inx
        jsr vdcw
        lda #8
        ldx #30
        jsr vdcw
        lda BCFG+2
        ldx #24
        jsr vbw
        jsr vbat                ; read back
        ldx #31
        stx VDCS
        ldy #0
-       bit VDCS
        bpl -
        lda VDCD
        sta STAGE,y
        iny
        cpy #40
        bne -
        ldx #0                  ; the counts: $A5s from 0 and from $18
-       lda STAGE,x
        cmp #$a5
        bne +
        inx
        bne -
+       stx BCFG+4
        ldx #0
-       lda STAGE+$18,x
        cmp #$a5
        bne +
        inx
        bne -
+       stx BCFG+3
        jsr vbzero
        lda BCFG+4              ; the fill: 13, one more or less
        sec
        sbc #12
        cmp #3
        bcs vb_off
        sta CNT
        lda #BLK_FILLN+1
        sec
        sbc CNT
        sta BCFG+1
        lda BCFG+3              ; the copy: 8, one more or less
        sec
        sbc #7
        cmp #3
        bcs vb_off
        sta CNT
        lda #BLK_COPYN+1
        sec
        sbc CNT
        sta BCFG
        rts
vb_off: lda #0
        sta BCFG
        rts
vbzero: jsr vbat
        ldy #40
        lda #0
        ldx #31
-       jsr vbw
        dey
        bne -
        rts
vbat:   lda #>BLK_AT            ; R18/R19 <- BLK_AT
        ldx #18
        jsr vbw
        lda #<BLK_AT
        inx
                                ; (on into vbw)
; vdcw once the VDC is ready (an operation done) before the select too.
vbw:    bit VDCS
        bpl vbw
        jmp vdcw

; A to page X, two fills of 128 (CNT). Keeps X.
vpage:  stx DST+1
        sta DST
        ldy #0
        jsr vfill
        lda DST
        ldx DST+1
        ldy #$80
        jsr vfill
        ldx DST+1
        rts

; A at X*256+Y (R18, R19), and CNT bytes more of it (R30)
vfill:  pha
        txa
        ldx #18
        jsr vdcw
        tya
        ldx #19
        jsr vdcw
        pla
        ldx #31
        jsr vdcw
        lda CNT
        ldx #30
                                ; (on into vdcw)
; VDC register X <- A, once the VDC is ready. Keeps A, X, Y.
vdcw:   stx VDCS
-       bit VDCS
        bpl -
        sta VDCD
        rts

; A <- VDC register X
vdcr:   stx VDCS
-       bit VDCS
        bpl -
        lda VDCD
        rts

} else {
; ------------------------------------------------------------ the VIC
; (zx128vic) Bank 1's $C000-$D7FF, the VIC's (z80/zx128vic.asm's map),
; a page at a time through STAGE (vstage, then tobank1): the ZX81's
; screen $C000-$C3FF blank (0: a space) but for its frame (vframe),
; FRAME, the font's inverse space, solid, round the 32x24 picture; the
; monitor's $C400-$C7FF blank ($20: its space); the ZX81's font
; $C800-$CFFF from the ROM's 64 glyphs (prom + $1E00) as zx64's boot
; makes it (c64/boot.asm's chars): codes 0-63 as they are, 64-127 blank,
; 128-191 inverted, 192-255 solid; the monitor's font $D000-$D7FF, the
; character ROM's first 2K (upper case and graphics: zx64's monitor's on
; the C64). Then colour RAM black, the frame's cells white, the border
; and background white (F2's scheme 0 as zx64's boot sets it, the frame
; in the border's colour: so the Z80's setcol colours it in every
; scheme), and the VIC onto them: screen $C000, font $C800 ($D018 $02),
; 24 rows from y-scroll 7 as zx64's ($D011 $17: raster line 250 too),
; its 16K at $C000 ($DD00), its RAM bank 1 ($D506 bit 6: 8K of common
; RAM at the top kept). Colour RAM is two banks on the C128: $01's bit 0 picks the
; one the CPUs write (the Z80's writes too), bit 1 the one the VIC shows
; (VICE x128: Z80 writes with bit 0 clear went where the VIC didn't
; show them). Both set, as the C128's kernal leaves them ($73).
vicinit:
        ldx #8                  ; (every page: the monitor's screen too)
        jsr vpages
        lda $01                 ; colour RAM's bank 1, the CPUs' and the VIC's
        ora #3
        sta $01
        lda #0                  ; colour RAM: black
        tax
-       sta $d800,x
        sta $d900,x
        sta $da00,x
        sta $db00,x
        inx
        bne -
        stx vf_st+1             ; the frame's cells white (X 0: $D800 + page)
        lda #1
        sta vfa
        lda #3
-       pha
        ora #>$d800
        sta vf_st+2
        pla
        pha
        jsr vframe
        pla
        sec
        sbc #1
        bpl -
        lda #1                  ; the border and background white
        sta $d020
        sta $d021
        lda $dd02               ; the VIC's 16K at $C000
        ora #3
        sta $dd02
        lda $dd00
        and #$fc
        sta $dd00
        lda #$02                ; screen $C000, font $C800
        sta $d018
        lda #$17                ; 24 rows, y-scroll 7, the display on (and
        sta $d011               ; raster line 250: bit 8 clear)
        lda #$4a                ; RAM bank 1 for the VIC, 8K of common RAM at
        sta RCR                 ; the top, none at the bottom
        rts

; (CMD_FONT, F7's and F8's; and dorom's, the ROM put back) The ZX81's
; screen and both fonts made again as vicinit makes them: a program's POKE
; or OUT may have written over them. The monitor's screen (pages 4-7) as
; it is.
vfonts: ldx #4
                                ; (on into vpages)
; vicinit's pages 0-23, $C000 + A*256, through STAGE (vstage): from 0 to
; X-1, then from 8 (X 8: all of them). Leaves $FF00 $3E.
vpages: stx vsk
        lda #0
        sta TLAST               ; (whole pages)
        sta vpg
-       lda vpg
        jsr vstage
        lda vpg
        clc
        adc #$c0
        tay
        lda #>STAGE             ; (tobank1 copies STAGE to itself first;
        ldx #1                  ; $FF00 is $3E: vstage's)
        jsr tobank1
        inc vpg
        lda vpg
        cmp vsk
        bne +
        lda #8
        sta vpg
+       cmp #$18
        bne -
        rts
vsk:    !byte 0
vpg:    !byte 0

; STAGE: page A of vicinit's (0-23: $C000 + A*256). Leaves $FF00 $3E.
vstage: cmp #8
        bcs vs_f
        cmp #4
        bcs vs_mon
        pha                     ; the ZX81's screen: 0, the frame FRAME
        lda #0
        jsr vs_fill
        lda #<STAGE
        sta vf_st+1
        lda #>STAGE
        sta vf_st+2
        lda #FRAME
        sta vfa
        pla
        jmp vframe
vs_mon: lda #$20                ; the monitor's: its space
vs_fill:
        ldx #0
-       sta STAGE,x
        inx
        bne -
        rts
vs_f:   cmp #16
        bcs vs_rom
        and #7                  ; the ZX81's font: X its page, 0-7
        tax
        and #2
        beq vs_cp
        lda #0                  ; 2, 3 blank; 6, 7 solid
        cpx #4
        bcc vs_fill
        lda #$ff
        bne vs_fill
vs_cp:  txa                     ; 0, 1 the glyphs; 4, 5 inverted
        and #1
        clc
        adc #(>prom) + $1e
        sta vs_src+2
        lda #0
        cpx #4
        bcc +
        lda #$ff
+       sta vs_eor+1
        ldx #0
vs_src: lda $ff00,x             ; (its page)
vs_eor: eor #0                  ; (0 or $FF)
        sta STAGE,x
        inx
        bne vs_src
        rts

; Page A (0-3) of the ZX81's screen's 1000 cells (40 x 25, from $C000;
; colour RAM's from $D800 likewise) at vf_st's address: vfa into its
; frame's cells (columns 0-3 and 36-39 of rows 0-23, all of row 24,
; round the ZX81's 32x24 picture from column 4), the rest left. The VIC
; can't give a cell its own background (extended colour mode would cut
; the font to 64 characters), so the frame is a solid character in the
; border's colour, and only the picture shows the background. vf_c0 and
; vf_r0: each page's first cell's column and row (A*256 = row*40 + column).
FRAME   = $80           ; the ZX81 font's inverse space: all set (vstage)
vframe: tax
        lda vf_c0,x
        sta vf_col
        lda vf_r0,x
        sta vf_row
        ldy #0
vf_cell:
        lda vf_row
        cmp #24
        beq vf_put              ; row 24: all frame
        bcs vf_done             ; past the 1000th cell
        lda vf_col
        cmp #4
        bcc vf_put
        cmp #36
        bcc vf_next             ; the picture's
vf_put: lda vfa
vf_st:  sta $ffff,y             ; (the page)
vf_next:
        inc vf_col
        lda vf_col
        cmp #40
        bne +
        lda #0
        sta vf_col
        inc vf_row
+       iny
        bne vf_cell
vf_done:
        rts
vf_c0:  !byte 0, 16, 32, 8
vf_r0:  !byte 0, 6, 12, 19
vf_col: !byte 0
vf_row: !byte 0
vfa:    !byte 0

vs_rom: and #7                  ; the character ROM's page
        clc
        adc #$d0
        sta vr_src+2
        lda #$01                ; bank 0, the character ROM at $D000 (the
        sta CR                  ; kernal's ROM above: STAGE is written to
        ldx #0                  ; the RAM below it)
vr_src: lda $d000,x             ; (its page)
        sta STAGE,x
        inx
        bne vr_src
        lda #$3e
        sta CR
        rts
}

; ------------------------------------------------------------ the disk
; LOAD, SAVE and F7's ROM through the C128 kernal, on the drive
; zx128 booted from (dev). The mailbox's page is copied to MBC first, and
; the data goes through BUF: bank 0's RAM from the page after it up to
; $DFFF, the payload's but for the ROM's copy (prom), which the boot no
; longer needs. The kernal's LOAD (the 1571's burst) is twice as fast as
; its bytes one at a time (VICE x128, a true 1571, MAZOGS: 5.4 s against
; 11.2 s), so LOAD reads the file into BUF, where it is checked, then
; copies it to bank 1; SAVE writes from BUF a byte at a time (the
; kernal's SAVE would put a load address in front). The panel's rows
; 13-14 say what is going on: " LOADING NAME", then the bar once data
; has come; the drive's status if it says no (into show's MSGBUF, which
; the panel shows for ovl's frames). Written polled, the VDC ready before
; each select too: the Z80 may have left a block operation going.
; (zx128vic: the VIC's top row instead, the word, the name and the bar
; in one row, as zx64's; the status over it as zx64's messages are.)

KCR     = $0e           ; $FF00 for the kernal: bank 0, its ROM at $C000-
                        ; $FFFF, I/O (the code here is all below $4000)
ISTOP   = $0328         ; the kernal's STOP vector: its LOAD calls it before
EAL     = $ae           ; each block of the file, EAL where the block goes
                        ; (from tools/build.py, both in bank 1: MSGBUF,
                        ; show's message, 32 ZX81 codes, z80/zx128.asm's;
                        ; PND, the panel's jobs, a byte a row,
                        ; z80/panel.inc's pn_d)
CMD_LOAD = 1
CMD_SAVE = 2
CMD_PRG = 3             ; (3-8: the monitor's)
CMD_DCMD = 8
CMD_ROM = 9
CMD_FONT = 10           ; (zx128vic) the VIC's fonts again (vfonts)
ST_OK   = 0
ST_BIG  = 2             ; (report 4)
ST_NOTP = 3             ; not a ZX81 program (report D)
!if VDC {
EMPTY   = $08           ; the bar's cells (set 1): the ZX81's grey,
FULL    = $40           ; filled: an inverse space
} else {
EMPTY   = $00           ; (zx128vic: the top row's, as zx64's: a space,
HALF    = $05           ; then its left half black, then an inverse
FULL    = $80           ; space)
TOP     = $c004         ; the VIC's top row: the picture's columns 0-31
}
MBC     = prom + $2000  ; the mailbox's page, copied
BUF     = MBC + $100    ; the data, up to BUFEND
BUFEND  = $de00         ; LOAD stops before a block from here on: a block
                        ; is 254 bytes at most, and the kernal's burst LOAD
                        ; reads its last block without STOP (kernal $F477-
                        ; $F47F): a block let through
                        ; below $DE00 ends by $DEFC, the last one after it
                        ; by $DFFA. Common RAM is at $E000

!macro kern .a {        ; a kernal call: by its stub (below)
        jsr .a
}
!macro kstub .a {       ; (a stub: the routine's entry, $FFxx, for kgo)
        pha
        lda #<.a
        bne kgo
}
; Each kernal routine the disk calls, through a stub that hands its entry
; to kgo: the kernal's ROM in first ($FF00 KCR; A, X, Y kept for it),
; interrupts off again after it (its burst LOAD and its fast serial end
; with CLI: $F48F, $E5BA); its A, X, Y and flags kept.
SETMSG: +kstub $ff90
SETBNK: +kstub $ff68
READST: +kstub $ffb7
SETLFS: +kstub $ffba
SETNAM: +kstub $ffbd
OPEN:   +kstub $ffc0
CLOSE:  +kstub $ffc3
CHKIN:  +kstub $ffc6
CHKOUT: +kstub $ffc9
CLRCHN: +kstub $ffcc
CHRIN:  +kstub $ffcf
CHROUT: +kstub $ffd2
LOAD:   +kstub $ffd5
kgo:    sta kj+1
        lda #KCR
        sta CR
        pla
kj:     jsr $ff00               ; (the stub's entry)
        sei
        rts
!macro ram .a {         ; a call into com, all RAM first (keeps A, X, Y)
        pha
        lda #$3e
        sta CR
        pla
        jsr .a
}


; ---- LOAD: like zx64's (c64/boot.asm's doload): the first 13 bytes
; ($4009-$4015) read first, so a program that isn't one (report D) or
; won't fit (E_LINE past the Z80's stack: report 4) changes nothing; NAME,
; then NAME.P. Then the whole file by the kernal's LOAD to BUF+$0B (it
; takes the first two bytes for an address): copied to bank 1 if it
; reaches E_LINE and starts as the 13 did, up to E_LINE only, the game
; patches in (ptab).
doload: jsr dbeg
        ldx #w_load-w_load
        jsr wrow
        lda #$80                ; (no bar before data)
        jsr row14
        jsr tryopen
        bcc ld_got
        ldx MBC+2               ; not found: NAME.P
        cpx #15
        bcs ld_nf
        lda #'.'
        sta MBC+3,x
        lda #'P'
        sta MBC+4,x
        inx
        inx
        stx MBC+2
        jsr tryopen
        bcc ld_got
ld_nf:  jsr dstat
        lda #ST_ERR
        jmp dend
ld_got: ldx #0                  ; the 13 bytes, E_LINE the last two
        lda first
ld_h:   sta hdr,x
        inx
        cpx #13
        beq ld_hd
        stx hx
        +kern READST
        and #$c3                ; ended, or an error, already
        bne ld_he
        +kern CHRIN
        ldx hx
        jmp ld_h
ld_he:  jsr close2
        jsr dstat
        lda #ST_ERR
ld_f:   jmp dend
ld_hd:  jsr close2
        jsr isprog
        lda #ST_NOTP
        bcs ld_f
        lda hdr+11
        ldx hdr+12
        jsr setend
        lda #ST_BIG
        bcs ld_f
        sec                     ; the bar, data having come: LOAD's bytes,
        lda eend                ; $400B up to E_LINE
        sbc #$0b
        tax
        lda eend+1
        sbc #$40
        jsr binit
        lda #<(BUF+$0b)
        sta lbase
        lda #>(BUF+$0b)
        sta lbase+1
        jsr kload
        bcc +
        jmp ld_le
+       lda eend+1              ; its end at E_LINE at least (in BUF:
        sec                     ; BUF + E_LINE - $4000)
        sbc #$40
        clc
        adc #>BUF
        sta pt+1
        lda lend
        cmp eend
        lda lend+1
        sbc pt+1
        bcc ld_bad
        ldx #10                 ; its start as the 13 bytes (the same file)
-       lda BUF+$0b,x
        cmp hdr+2,x
        bne ld_bad
        dex
        bpl -
        lda btot                ; the bar full
        sta bdone
        lda btot+1
        sta bdone+1
        jsr bar
        lda #0                  ; BUF from $4000 on: $4000-$4008 as they are
        sta SRC
        lda #$40
        sta SRC+1
        ldy #8
-       +ram peek1
        sta BUF,y
        dey
        bpl -
        lda hdr                 ; (and the two bytes LOAD took)
        sta BUF+9
        lda hdr+1
        sta BUF+10
        lda #0
        sta pdir
        jsr patch
        lda eend                ; to bank 1 up to E_LINE: whole pages, the
        sta TLAST               ; last one up to it
        sec
        sbc #1
        lda eend+1
        sbc #$40
        tax
        inx
        lda #>BUF
        ldy #$40
        +ram tobank1
        lda #ST_OK
ld_end: jmp dend
ld_le:  lda #ST_BIG             ; stopped at BUFEND: bigger than RAM
        ldx kstop
        bne ld_end
        jsr dstat
ld_bad: lda #ST_ERR
        jmp dend

; C=1 if hdr (the file's first 13 bytes, $4009-$4015) isn't the start of
; a ZX81 program: D_FILE from $407D (past the system variables), VARS
; not before it, E_LINE after VARS (as zx64's isprog; VERSN isn't looked
; at).
isprog: lda hdr+3               ; D_FILE >= $407D
        cmp #$7d
        lda hdr+4
        sbc #$40
        bcc ip_no
        lda hdr+7               ; VARS >= D_FILE
        cmp hdr+3
        lda hdr+8
        sbc hdr+4
        bcc ip_no
        lda hdr+7               ; VARS < E_LINE: C=0
        cmp hdr+11
        lda hdr+8
        sbc hdr+12
        rts
ip_no:  sec
        rts

; A/X = E_LINE -> eend. C=1 if it makes no sense (not past the system
; variables) or the program would run into the Z80's stack, from its SP
; as it handed over (the mailbox's +$20) up.
setend: sta eend
        stx eend+1
        cpx #$40
        bcc se_no
        bne +
        cmp #$80
        bcc se_no
+       lda MBC+$20             ; SP - E_LINE: carry set if E_LINE <= SP
        cmp eend
        lda MBC+$21
        sbc eend+1
        bcc se_no
        clc
        rts
se_no:  sec
        rts

; Open the name in MBC, read its first byte (first). C=1: not there (the
; file closed again).
tryopen:
        lda MBC+2
        ldx #<(MBC+3)
        ldy #>(MBC+3)
        +kern SETNAM
        lda #2
        ldx dev
        ldy #0                  ; SA 0: its bytes, no load address
        +kern SETLFS
        +kern OPEN
        bcs to_no
        ldx #2
        +kern CHKIN
        bcs to_no
        +kern CHRIN
        sta first
        +kern READST
        and #$83                ; a time-out, or no drive
        bne to_no
        clc
        rts
to_no:  jsr close2
        sec
        rts
close2: +kern CLRCHN
        lda #2
        +kern CLOSE
        rts

; The file named in MBC by the kernal's LOAD to lbase (bank 0), the bar
; following it (lhook). C=1 if it failed: kstop 1, stopped at BUFEND;
; lerrno, the kernal's error (4: not there). lend: its end.
kload:  lda ISTOP
        sta stvec
        lda ISTOP+1
        sta stvec+1
        lda #<lhook
        sta ISTOP
        lda #>lhook
        sta ISTOP+1
        lda MBC+2
        ldx #<(MBC+3)
        ldy #>(MBC+3)
        +kern SETNAM
        lda #1
        ldx dev
        ldy #0                  ; to X/Y, not its own address
        +kern SETLFS
        lda #0
        ldx lbase
        ldy lbase+1
        +kern LOAD
        sta lerrno
        stx lend
        sty lend+1
        php
        lda stvec
        sta ISTOP
        lda stvec+1
        sta ISTOP+1
        plp
        bcs kl_x
        +kern READST
        and #$83
        bne kl_no
        lda kstop
        bne kl_no
        clc
        rts
kl_no:  sec
kl_x:   rts

; The kernal's STOP while it loads (ISTOP), before each block but the
; last (each byte on a drive without burst), EAL where it goes: Z (stop,
; the LOAD ends) from BUFEND on (see there: the last block comes
; unguarded); else the bar, and on. Keeps X, Y and $FF00 (I/O in for the
; bar's writes). A kernal that never calls STOP (none of the C128's) would
; load on into common RAM.
lhook:  lda EAL+1
        cmp #>BUFEND
        bcs lh_stop
        stx lhx
        sty lhy
        lda CR
        sta lhcr
        lda #KCR
        sta CR
        sec
        lda EAL
        sbc lbase
        sta bdone
        lda EAL+1
        sbc lbase+1
        sta bdone+1
        lda bshown              ; the bar once data has come (F7's: dorom)
        bne +
        lda bdone
        ora bdone+1
        beq ++
        jsr bdraw
+       jsr bar
++      lda lhcr
        sta CR
        ldx lhx
        ldy lhy
        lda #$ff                ; (not Z: on)
        rts
lh_stop:
        lda #1
        sta kstop
        lda #0                  ; (Z: stop)
        rts

; ---- SAVE: $4009 up to E_LINE as "@0:NAME" (an old one replaced), as
; zx64's dosave, the game patches out again first; then the drive asked
; whether it went well: a full or write-protected disk shows only there.
dosave: jsr dbeg
        ldx #w_save-w_load
        jsr wrow
        lda #$80
        jsr row14
        ldx #<$4014             ; E_LINE
        ldy #>$4014
        jsr get1
        sta eend
        ldx #<$4015
        ldy #>$4015
        jsr get1
        sta eend+1
        lda eend                ; $400A to $C000, or nothing
        cmp #$0a
        lda eend+1
        sbc #$40
        bcc +
        lda #0
        cmp eend
        lda #$c0
        sbc eend+1
        bcc +
        lda #<(BUFEND - BUF + $4000)    ; (and what BUF holds)
        cmp eend
        lda #>(BUFEND - BUF + $4000)
        sbc eend+1
        bcs ++
+       jmp sv_bad
++      lda eend                ; to BUF, the pages up to E_LINE
        sec
        sbc #1
        lda eend+1
        sbc #$40
        tax
        inx
        lda #$40
        ldy #>BUF
        +ram frombank1
        lda #1
        sta pdir
        jsr patch
        jsr wopen
        bcs sv_no
        sec                     ; the bar: the bytes, $4009 up to E_LINE
        lda eend
        sbc #9
        tax
        lda eend+1
        sbc #$40
        jsr binit
        lda #0
        sta bdone
        sta bdone+1
        lda #<(BUF+9)
        sta sv_ld+1
        lda #>(BUF+9)
        sta sv_ld+2
sv_l:   lda bdone
        cmp btot
        lda bdone+1
        sbc btot+1
        bcs sv_d
        lda #$3e                ; (all RAM: BUF goes past $C000 for 32K,
        sta CR                  ; where KCR has the kernal's ROM)
sv_ld:  lda BUF+9               ; (its address goes up)
        +kern CHROUT
        inc sv_ld+1
        bne +
        inc sv_ld+2
+       inc bdone
        bne +
        inc bdone+1
+       lda bdone               ; (the bar every 16 bytes)
        and #$0f
        bne sv_l
        jsr bar
        jmp sv_l
sv_d:   jsr bar
        jsr close2
        jsr dstat
        lda #ST_ERR
        bcs +
        lda #ST_OK
+       jmp dend
sv_no:  jsr close2
        jsr dstat
sv_bad: lda #ST_ERR
        jmp dend

; "@0:" + the name + ",P,W", opened as 2 for writing. C=1: it failed.
wopen:  ldx #0
-       lda wpre,x
        sta wname,x
        inx
        cpx #3
        bne -
        ldy #0
-       cpy MBC+2
        beq +
        lda MBC+3,y
        sta wname,x
        inx
        iny
        bne -
+       ldy #0
-       lda wpw,y
        sta wname,x
        inx
        iny
        cpy #4
        bne -
        txa
        ldx #<wname
        ldy #>wname
        +kern SETNAM
        lda #2
        ldx dev
        ldy #2
        +kern SETLFS
        +kern OPEN
        bcs +
        ldx #2
        +kern CHKOUT
+       rts

; ---- F7's ROM (F8's too: z80/reset.inc's romfix, when romsum says a
; program has written over it). First from the boot file's
; copy, which stays in bank 0 (prom: neither the kernal, nor the disk's
; buffers, nor this code's variables are there; the Z80 never sees bank
; 0), if it adds up to this build's sum (ROMSUM, as romsum_v); only if it
; doesn't, from ZX128 on the disk (the name in MBC), the bar across it,
; into BUF: its ROM (as far into the file as prom is) put in place, and
; into prom, if that adds up. If neither, why, in the panel (as zx64's
; dorom puts it on the top row), for 5 seconds, ST_ERR: the ZX81 starts
; with the ROM as it is. zx128's own copy of the sum written over (zx128
; itself was): no disk, the panel says so.
dorom:  jsr dbeg
        ldx #<ROMSUMV
        ldy #>ROMSUMV
        jsr get1
        cmp #<ROMSUM
        bne ro_chg
        ldx #<(ROMSUMV+1)
        ldy #>(ROMSUMV+1)
        jsr get1
        cmp #>ROMSUM
        beq +
ro_chg: ldx #rm_chg-rm_none
ro_bad: jsr rmsg
        lda #ST_ERR
        jmp dend
+       lda #>prom
        jsr rsum
        bne ro_disk
        jsr romput
        lda #ST_OK
        jmp dend
ro_disk:
        ldx #w_load-w_load
        jsr wrow
        lda #$80                ; (no bar before data)
        jsr row14
        ldx #<(BAREND-$1300)    ; the bar: the file, if this build's
        lda #>(BAREND-$1300)
        jsr bset
        lda #<BUF
        sta lbase
        lda #>BUF
        sta lbase+1
        jsr kload
        bcc ro_got
        ldx #rm_other-rm_none
        lda kstop
        bne ro_bad
        ldx #rm_none-rm_none
        lda lerrno
        cmp #4                  ; (not there)
        beq ro_bad
        ldx #rm_err-rm_none
        bne ro_bad
ro_got: lda bshown              ; the bar full
        bne +
        jsr bdraw
+       lda btot
        sta bdone
        lda btot+1
        sta bdone+1
        jsr bar
        lda lend                ; as far as the ROM's end at least
        cmp #<(RBUF+$2000)
        lda lend+1
        sbc #>(RBUF+$2000)
        bcc ro_oth
        lda #>RBUF
        jsr rsum
        bne ro_oth
        lda #0                  ; into prom, then bank 1
        sta SRC
        sta DST
        tay
        lda #>RBUF
        sta SRC+1
        lda #>prom
        sta DST+1
        ldx #$20
-       lda (SRC),y
        sta (DST),y
        iny
        bne -
        inc SRC+1
        inc DST+1
        dex
        bne -
        jsr romput
        lda #ST_OK
        jmp dend
ro_oth: ldx #rm_other-rm_none
        jmp ro_bad
RBUF    = BUF + prom - $1300    ; the ROM in ZX128, read into BUF

; Z if the 8K from page A (bank 0) adds up to ROMSUM from its byte 5 on
; (as z80/reset.inc's romsum: $0000-$0004 are the calculator's).
rsum:   sta SRC+1
        lda #0
        sta SRC
        sta acc
        sta acc+1
        ldx #$20
        ldy #5
-       lda (SRC),y
        clc
        adc acc
        sta acc
        bcc +
        inc acc+1
+       iny
        bne -
        inc SRC+1
        dex
        bne -
        lda acc
        cmp #<ROMSUM
        bne +
        lda acc+1
        cmp #>ROMSUM
+       rts

; prom to bank 1 $0000-$1FFF through tobank1, whose pages 0 and 1 go to
; ROM01 in common RAM (pmap), as at boot, for the Z80 to put in place
; (z80/zx128.asm's rombk, on ST_OK): the 8502 can't write bank 1's $0000
; and $0001 (its own I/O port is there, whatever the MMU says).
romput: lda #0
        sta TLAST
        tay
        lda #>prom
        ldx #$20
        +ram tobank1
!if VDC = 0 {
        jmp vfonts              ; (zx128vic) the ZX81's font from it too
} else {
        rts
}

; ---- the monitor's (z80/mon.asm's "the disk"): L "NAME" a, $, W s e and
; @, as zx64's (c64/boot.asm's kernal path). The mailbox: +2 the name's
; length, +3 the name (the command); +$22 a start, +$24 an end (the byte
; after): bank 1's own addresses; lines back at +$80 (dbuf), ended
; by 0, the page copied back (mok). The monitor's screen is up (quiet):
; nothing drawn, and the drive's status left for its own @ (derr). Bank
; 1's pages 0 and 1 are at ROM01 meanwhile (com's pmap; z80/mon6510.inc's
; mon_6510).
mtab:   !word doprg-1, dodir-1, dodirl-1, dodirc-1, dowrite-1, docmd-1

; L "NAME" a: the file to bank 1 from a (+$22), not to its own address.
; Refused (ST_ERR, nothing written) unless all of it lands in $0000-$1FFF
; (the ROM: F7 repairs it) or $4000-$BFFF (the ZX81's RAM), never in the
; core, the mailbox and the monitor ($2000-$3FFF), nor the picture's,
; the monitor's and common RAM ($C000 up): so it is read into BUF first,
; at a's place in the page, BUF's first page bank 1's (what is below a
; kept), its length known; then copied. +$24: its end.
pr_no:  lda #ST_ERR
        jmp dend
doprg:  lda MBC+$23
        ldx #$20                ; the room's end: $2000...
        cmp #$20
        bcc +
        ldx #$c0                ; ...or $C000
        cmp #$40
        bcc pr_no
        cmp #$c0
        bcs pr_no
+       stx plim
        cmp #2                  ; (bank 1's pages 0 and 1: ROM01, as pmap
        bcs +                   ; has them)
        ora #>ROM01
+       ldy #>BUF
        ldx #1
        +ram frombank1
        lda MBC+$22
        sta lbase
        lda #>BUF
        sta lbase+1
        jsr kload
        bcs pr_no
        lda lend                ; its end: a + its length (BUF starts a page)
        sta MBC+$24
        sta TLAST               ; (the last page's bytes)
        lda lend+1
        sec
        sbc #>BUF
        clc
        adc MBC+$23
        bcs pr_no
        sta MBC+$25
        lda MBC+$24             ; not past the room's end
        cmp #1
        lda MBC+$25
        sbc plim
        bcs pr_no
        lda MBC+$24             ; its pages: a's up to its last byte's
        cmp #1
        lda MBC+$25
        sbc MBC+$23
        bcc mok                 ; (none: nothing at a page's start)
        tax
        inx
        lda #>BUF
        ldy MBC+$23
        +ram tobank1
                                ; (on into mok)
; The mailbox's page back to bank 1 (+$22, +$24, the line at +$80), and
; ST_OK.
mok:    lda #0
        sta TLAST
        lda #>MBC
        ldy #>MBOX
        ldx #1
        +ram tobank1
        lda #ST_OK
        jmp dend

; $: the directory ("$", the monitor's name) opened as a program, past its
; load address; then a line at a time, TALK and UNTALK each.
dodir:  jsr tryopen             ; (its first byte)
        bcs dc_no
        +kern CHRIN
        jmp dl_ok

; The directory's next line: its blocks at +$80, its text from +$82 up
; to its 0 (64 at most, as zx64's). ST_ERR at its end (the link 0 0), or
; when closed early (CMD_DIRC, RUN/STOP).
dodirl: ldx #2
        +kern CHKIN
        bcs dodirc
        +kern CHRIN             ; the link
        sta first
        +kern CHRIN
        ora first
        beq dodirc
        ldx #0
dl_l:   stx hx
        +kern CHRIN
        ldx hx
        sta dbuf,x
        cpx #2
        bcc +                   ; (the blocks may be 0)
        tay
        beq dl_ok
+       inx
        cpx #66
        bcc dl_l
        lda #0
        sta dbuf,x
dl_ok:  +kern CLRCHN
        jmp mok
dodirc: jsr close2
dc_no:  lda #ST_ERR
        jmp dend

; @: a DOS command (+2, +3; none: just the status), then the drive's
; status line at +$80 (dbuf). ST_ERR: no drive.
docmd:  lda MBC+2
        ldx #<(MBC+3)
        ldy #>(MBC+3)
        jsr dsread
        bcs dc_no
        ldx dlen
        lda #0
        sta dbuf,x
        jmp mok

; W s e: bank 1 from +$22 up to +$24 ($0000: to its end) as "@0:NAME", a
; PRG, +$22 its load address; a byte at a time (any range, more than BUF
; holds). Two ranges aren't what M shows: $F000-$F1FF is ROM01, holding
; bank 1's $0000-$01FF meanwhile (mon_6510), and $FF00-$FF04 reads as the
; MMU's registers.
dowrite:
        jsr wopen
        bcs dodirc
        lda MBC+$22
        +kern CHROUT
        lda MBC+$23
        +kern CHROUT
wr_l:   lda MBC+$23
        cmp #2                  ; (pages 0 and 1: ROM01, as pmap has them)
        bcs +
        ora #>ROM01
+       sta SRC+1
        lda MBC+$22
        sta SRC
        ldy #0
        +ram peek1
        +kern CHROUT
        inc MBC+$22
        bne +
        inc MBC+$23
+       lda MBC+$22
        cmp MBC+$24
        bne wr_l
        lda MBC+$23
        cmp MBC+$25
        bne wr_l
        jsr close2
        lda #ST_OK
        jmp dend

; ---- what they share
; A command's start: the mailbox's page to MBC, no message of show's
; over the rows (LOAD's and SAVE's: zx64's lstat does it too; F7's has
; its own); the kernal without messages (the 80-column screen is the
; picture's), names and data in bank 0.
dbeg:   lda #>MBOX
        ldy #>MBC
        ldx #1
        +ram frombank1
        lda MONUP               ; the monitor's screen up (mon6510.inc's
        sta quiet               ; mon_up): nothing drawn, no status read
        lda #0
        sta kstop
        lda MBC
        cmp #CMD_ROM
        beq +
        lda #0
        ldx #<OVL
        ldy #>OVL
        jsr put1
+       lda #0
        +kern SETMSG
        lda #0
        tax
        +kern SETBNK
        rts

; A command's end, A its status: rows 13-14 the panel's again (pn_d's
; bit 1, its pn_row: empty, or show's message), no CIA interrupts (the
; kernal's serial code may leave some on), then the answer.
dend:   sei                     ; (as after each kernal call)
        sta dstv
!if VDC {
        ldx #<(PND+13)
        jsr pmark
        ldx #<(PND+14)
        jsr pmark
}
        lda #$7f
        sta $dc0d
        sta $dd0d
        lda $dc0d
        lda $dd0d
        lda #$3e
        sta CR
        lda dstv
        jmp answer
!if VDC {
pmark:  stx pmx
        ldy #>PND
        jsr get1
        ora #2
        ldx pmx
        ldy #>PND
                                ; (on into put1)
}
; A to bank 1 at Y*256+X. Changes Y.
put1:   stx DST
        sty DST+1
        ldy #0
        +ram poke1
        rts
; A from bank 1 at Y*256+X. Changes Y.
get1:   stx SRC
        sty SRC+1
        ldy #0
        +ram peek1
        rts

; The drive's status, its error channel's line (dbuf, dlen): C=0 if it
; says 00. Else C=1, and the line on the panel's rows 13-14 for 2
; seconds, if there was one: its words on 13, its numbers on 14 (e.g.
; "FILE NOT FOUND", "62,00,00"). With the monitor up (quiet), C=0 and
; nothing read (not known, so not an error): its derr and @ ask the
; drive themselves, after (reading it here would leave them the drive's
; 00).
dstat:
        lda quiet
        bne ds_ok
        lda #0
        jsr dsread
        bcs ds_x
        lda dlen
        cmp #2
        bcc ds_x
        lda dbuf
        cmp #'0'
        bne ds_m
        lda dbuf+1
        cmp #'0'
        bne ds_m
ds_ok:  clc
        rts
ds_m:   jsr dmsg
        lda #100
        jsr smsg
ds_x:   sec
        rts

; The drive's error channel opened with the command A, X/Y (none: A 0),
; its line read (dbuf, dlen). C=1: no drive.
dsread: +kern SETNAM
        lda #15
        ldx dev
        ldy #15
        +kern SETLFS
        +kern OPEN
        bcs ds_no
        ldx #15
        +kern CHKIN
        bcs ds_no
        ldx #0
ds_l:   stx hx
        +kern CHRIN
        ldx hx
        cmp #13
        beq ds_e
        sta dbuf,x
        inx
        +kern READST
        and #$42                ; the end, or nothing there
        bne ds_e
        cpx #40
        bcc ds_l
ds_e:   stx dlen
        jsr cl15
        clc
        rts
ds_no:  jsr cl15
        sec
        rts
cl15:   +kern CLRCHN
        lda #15
        +kern CLOSE
        rts

; msgb: dbuf's line as 32 ZX81 codes, inverse: the words (after its
; first comma, up to the next) on row 13, the number and from its second
; comma on (the track and sector) on row 14, each cut to 16. (zx128vic:
; both on the top row: a drive's words begin with a space, "62, FILE NOT
; FOUND,00,00", so they come from column 1 as zx64's messages do.)
dmsg:   ldx #31
        lda #$80
-       sta msgb,x
        dex
        bpl -
        inx                     ; (X 0) after the first comma
-       cpx dlen
        bcs dm_n
        lda dbuf,x
        inx
        cmp #','
        bne -
        ldy #0
-       cpx dlen
        bcs dm_n
        lda dbuf,x
        cmp #','
        beq dm_n
        jsr p2z
        sta msgb,y
        inx
        iny
        cpy #16
        bcc -
dm_n:   stx dmx                 ; (where the words ended)
        ldy #16
        ldx #0
-       cpx dlen                ; the number
        bcs dm_x
        lda dbuf,x
        cmp #','
        beq +
        jsr p2z
        sta msgb,y
        inx
        iny
        bne -
+       ldx dmx
-       cpx dlen                ; the second comma
        bcs dm_x
        lda dbuf,x
        cmp #','
        beq +
        inx
        bne -
+
-       cpx dlen                ; and on
        bcs dm_x
        cpy #32
        bcs dm_x
        lda dbuf,x
        jsr p2z
        sta msgb,y
        inx
        iny
        bne -
dm_x:   rts

; A, PETSCII, as an inverse ZX81 code (pet2zx; '?' for what it has not).
; Keeps X, Y.
p2z:    sty p2y
        sec
        sbc #$20
        cmp #$40
        bcc +
        lda #'?'-$20
+       tay
        lda pet2zx,y
        ora #$80
        ldy p2y
        rts

; X: a ROM message (rm_none on, 32 each): to show's MSGBUF, 5 seconds.
rmsg:   ldy #0
-       lda rm_none,x
        sta msgb,y
        inx
        iny
        cpy #32
        bne -
        lda #250
                                ; (on into smsg)
; msgb's 32 codes to show's MSGBUF (bank 1), shown for A frames (ovl).
smsg:   pha
        lda #<MSGBUF
        sta DST
        lda #>MSGBUF
        sta DST+1
        ldy #31
-       lda msgb,y
        +ram poke1
        dey
        bpl -
        lda #<MSGBUF
        ldx #<OVLMSG
        ldy #>OVLMSG
        jsr put1
        lda #>MSGBUF
        ldx #<(OVLMSG+1)
        ldy #>(OVLMSG+1)
        jsr put1
        pla
        ldx #<OVL
        ldy #>OVL
        jmp put1

!if VDC {
; Row 13: an inverse word (X: from w_load), then MBC's name, cut to 16 in
; all, as set 1's codes (inverse ZX81 ones).
wrow:   ldy #0
-       lda w_load,x
        sta rowb,y
        inx
        iny
        cpy #9
        bne -
        ldx #0
-       lda #$40                ; (an inverse space)
        cpx MBC+2
        bcs +
        lda MBC+3,x
        jsr p2z
        eor #$c0                ; (set 1's inverse: $40 up)
+       sta rowb,y
        inx
        iny
        cpy #16
        bne -
        lda #13
                                ; (on into vrow)
; Row A (13 or 14) of the panel, columns 64-79: rowb's 16 codes (none
; under the monitor's screen: quiet).
vrow:
        ldx quiet
        bne vr_x
        ldy #$50                ; (13: $0450, 14: $04A0)
        cmp #13
        beq +
        ldy #$a0
+       lda #$04
        ldx #18
        jsr vbw
        tya
        inx
        jsr vbw
        ldx #31
-       bit VDCS                ; (ready before the select too)
        bpl -
        stx VDCS
        ldy #0
-       lda rowb,y
        jsr vput
        iny
        cpy #16
        bne -
vr_x:   rts

} else {
; (zx128vic) The VIC's top row, as zx64's lstat makes it: inverse spaces,
; the word (X: from w_load, 9 ZX81 codes, inverse) from column 0, MBC's
; name from column 9 (12 at most), inverse; the bar's cells (row14) from
; column 22, the 8 of them columns 22-29.
wrow:   lda #0
        sta tcol
-       lda w_load,x
        jsr tnext
        inx
        lda tcol
        cmp #9
        bne -
        ldx #0
-       lda #$80                ; (an inverse space)
        cpx #12
        bcs +
        cpx MBC+2
        bcs +
        lda MBC+3,x
        jsr p2z
+       jsr tnext
        inx
        lda tcol
        cmp #32
        bne -
        rts
; A to the top row's column tcol, then the next column. Keeps A, X.
tnext:  ldy tcol
        inc tcol
                                ; (on into tput)
; A to the top row's column Y (TOP: bank 1's $C004 on), none under the
; monitor's screen (quiet). Keeps A, X. Y 0 (or as it was: quiet).
tput:   pha
        lda quiet
        bne tp_x
        tya
        clc
        adc #<TOP
        sta DST
        lda #>TOP
        sta DST+1
        pla
        ldy #0
        +ram poke1
        rts
tp_x:   pla
        rts
}

; Row 14 all A: a space ($80) before data, EMPTY the bar's start.
; (zx128vic: the top row's 8 bar cells.)
row14:
!if VDC {
        ldx #15
-       sta rowb,x
        dex
        bpl -
        lda #14
        jmp vrow
} else {
        ldy #22
        sty tcol
-       jsr tnext
        ldy tcol
        cpy #30
        bne -
        rts
}

; The bar for A*256+X bytes: row 14 its empty cells (binit; bset: not
; yet, lhook draws them, bdraw, once data has come). It fills a cell a
; sixteenth at a time (bar), by a running sum, as zx64's pstep does: no
; dividing.
binit:  jsr bset
bdraw:  lda #1
        sta bshown
        lda #EMPTY
        jmp row14
bset:   stx btot
        sta btot+1
        ora btot
        bne +
        inc btot                ; (none: no dividing by 0)
+       lda btot
        sta bnext
        lda btot+1
        sta bnext+1
        lda #0
        sta bnext+2
        sta bunits
        sta bshown
        rts

; The bar's cells for bdone bytes done of btot, those not filled yet
; (none under the monitor's screen). Changes A, X. (zx128vic: 8 cells,
; each a half, HALF, and then whole, FULL: 16 steps as zx128's 16 cells,
; zx64's pstep's way.)
bar:
        lda quiet
        bne bar_x
        lda bdone
        sta bt
        lda bdone+1
        sta bt+1
        lda #0
        sta bt+2
        ldx #4
-       asl bt
        rol bt+1
        rol bt+2
        dex
        bne -
bar_l:  lda bunits
        cmp #16
        bcs bar_x
        lda bt                  ; bdone * 16 up to bnext: a cell more
        cmp bnext
        lda bt+1
        sbc bnext+1
        lda bt+2
        sbc bnext+2
        bcc bar_x
!if VDC {
        lda #$04
        ldx #18
        jsr vbw
        lda bunits
        ora #$a0
        inx
        jsr vbw
        lda #FULL
        ldx #31
        jsr vbw
} else {
        lda bunits              ; step k: cell k/2 (column 22 on), a half
        lsr                     ; if k is even, whole if odd
        tay
        lda #HALF
        bcc +
        lda #FULL
+       pha
        tya
        clc
        adc #22
        tay
        pla
        jsr tput
}
        inc bunits
        lda bnext
        clc
        adc btot
        sta bnext
        lda bnext+1
        adc btot+1
        sta bnext+1
        bcc bar_l
        inc bnext+2
        jmp bar_l
bar_x:  rts

; The game patches (ptab, from tools/build.py's patches_load128) on BUF,
; which holds bank 1 from $4000 up to E_LINE (eend). pdir 0 (LOAD) puts
; a game's in where all of their bytes are there, 1 (SAVE) takes them out
; where all of the new ones are: a game is all, or nothing.
patch:  lda #$3e                ; (all RAM: BUF past $C000)
        sta CR
        lda #<ptab
        sta SRC
        lda #>ptab
        sta SRC+1
pa_g:   ldy #0
        lda (SRC),y             ; a game: its entries (0: no more)
        bne +
        rts
+       sta pcnt
        inc SRC
        bne +
        inc SRC+1
+       lda SRC
        sta pg0
        lda SRC+1
        sta pg0+1
        lda #0
        sta ppass               ; 0: look, 1: put
pa_ps:  lda pg0
        sta SRC
        lda pg0+1
        sta SRC+1
        lda pcnt
        sta pn
pa_e:   ldy #0                  ; DST: its address in BUF
        lda (SRC),y
        sta DST
        clc
        ldy #2
        adc (SRC),y             ; (its end, for E_LINE)
        sta pt
        dey
        lda (SRC),y
        adc #0
        sta pt+1
        lda (SRC),y
        sec
        sbc #$40
        bcc pa_n1
        clc
        adc #>BUF
        sta DST+1
        lda eend                ; its end up to E_LINE
        cmp pt
        lda eend+1
        sbc pt+1
        bcs +
pa_n1:  jmp pa_no
+
        ldy #2
        lda (SRC),y
        sta plen
        clc                     ; the bytes looked at, the bytes put
        adc #3
        ldx pdir
        bne +
        sta oto
        lda #3
        sta ofrom
        bne ++
+       sta ofrom
        lda #3
        sta oto
++      ldx #0
pa_b:   txa
        clc
        adc ofrom
        ldy ppass
        beq +
        txa
        clc
        adc oto
+       tay
        lda (SRC),y
        sta pb
        txa
        tay
        lda pb
        ldx ppass
        bne pa_put
        cmp (DST),y
        bne pa_no
        beq +
pa_put: sta (DST),y
+       tya
        tax
        inx
        cpx plen
        bne pa_b
        lda plen                ; the next entry
        asl
        clc
        adc #3
        adc SRC
        sta SRC
        bcc +
        inc SRC+1
+       dec pn
        beq +
        jmp pa_e
+       lda ppass               ; all there: put them in (SRC at the next
        beq +                   ; game once they are)
        jmp pa_g
+       inc ppass
        jmp pa_ps
pa_no:  lda pg0                 ; not this game: past its entries
        sta SRC
        lda pg0+1
        sta SRC+1
-       ldy #2
        lda (SRC),y
        asl
        clc
        adc #3
        adc SRC
        sta SRC
        bcc +
        inc SRC+1
+       dec pcnt
        bne -
        jmp pa_g

        !source "disk128.a"     ; pet2zx, the words, the ROM's messages, ptab (tools/build.py)
wpre:   !text "@0:"
wpw:    !text ",P,W"

dev:    !byte 8                 ; the drive (kept: the boot sector's)
; The rest is a command's own, in MBC's page past the mailbox's $40
; bytes (frombank1 copies the whole page at its start): not in the file.
VARS    = MBC + $40
first   = VARS + $00            ; a file's first byte (tryopen)
hdr     = VARS + $01            ; its first 13
hx      = VARS + $0E
eend    = VARS + $0F            ; E_LINE
kstop   = VARS + $11            ; 1: LOAD stopped at BUFEND (lhook)
lerrno  = VARS + $12            ; the kernal's LOAD: its error,
lend    = VARS + $13            ; its end,
lbase   = VARS + $15            ; where it was to go
stvec   = VARS + $17            ; ISTOP as it was
lhx     = VARS + $19            ; (lhook's)
lhy     = VARS + $1A
lhcr    = VARS + $1B
btot    = VARS + $1C            ; the bar: bytes in all,
bdone   = VARS + $1E            ; done,
bnext   = VARS + $20            ; the next cell at this many sixteenths,
bunits  = VARS + $23            ; cells filled
bt      = VARS + $24
rowb    = VARS + $27            ; a row for vrow
tcol    = VARS + $B0            ; (zx128vic) the top row's next column (tnext)
dlen    = VARS + $37            ; (dbuf's)
dmx     = VARS + $38
p2y     = VARS + $39
pmx     = VARS + $3A
dstv    = VARS + $3B
acc     = VARS + $3C            ; (rsum's)
pdir    = VARS + $3E            ; patch's: 0 in, 1 out
quiet   = VARS + $3F            ; the monitor's screen up (dbeg)
dbuf    = VARS + $40            ; the drive's status line; the mailbox's +$80
                                ; (the monitor's lines: 67 bytes to +$C2)
wname   = dbuf                  ; "@0:NAME,P,W" (only until OPEN has it)
msgb    = VARS + $83            ; a message for smsg
pcnt    = VARS + $A3
pn      = VARS + $A4
ppass   = VARS + $A5
pg0     = VARS + $A6
pt      = VARS + $A8
plen    = VARS + $AA
ofrom   = VARS + $AB
oto     = VARS + $AC
pb      = VARS + $AD
bshown  = VARS + $AE            ; 1: the bar's empty cells drawn
plim    = VARS + $AF            ; (doprg's)
!if $40 + $B1 > $100 { !error "the disk's variables are more than MBC's page has" }

; ------------------------------------------------------------ common RAM
com_src:
!pseudopc COM {
; X pages from bank 0 at A*256 to bank 1 at Y*256 (pmap's), each through
; STAGE, the last of them only its first TLAST bytes (0: all 256). Called
; from bank 0, which it goes back to.
tobank1:
        sta SRC+1
        sty DST+1
        ldy #0
        sty SRC
.page:  lda #$3e
        sta CR
.in:    lda (SRC),y
        sta STAGE,y
        iny
        bne .in
        lda DST+1
        jsr pmap
        sta .st+2
        lda #$7f                ; bank 1, I/O off: $D000-$DFFF is RAM (the
        sta CR                  ; zero page stays bank 0's)
        lda #0
        cpx #1
        bne +
        lda TLAST
+       sta .lim+1
.out:   lda STAGE,y
.st:    sta $0000,y             ; (its page: DST+1's, pmap's)
        iny
.lim:   cpy #0                  ; (the page's end: 0, or TLAST)
        bne .out
        inc SRC+1
        inc DST+1
        dex
        bne .page
        lda #$3e
        sta CR
        rts

; A: a page of bank 1 as the 8502 reaches it: its pages 0 and 1 are the
; 8502's own zero page and stack, so bank 1's wait at ROM01 (the ROM's,
; for z80/zx128.asm's zentry and rombk; the monitor's L and W: its
; mon_6510 puts them there and back). Keeps X, Y.
pmap:   cmp #2
        bcs +
        ora #>ROM01
+       rts

; The server's answer, A, to MBOX+1 and the command taken; then the Z80
; runs (tozx) until it hands back with the next one, which goes to the
; server in A.
answer: ldx #$7e                ; bank 1: the mailbox
        stx CR
        sta MBOX+1
        lda #0
        sta MBOX
tozx:   ldx #1                  ; pages 0 and 1 on bank 1's for the Z80: no
        stx P0H                 ; zero page or stack from here
        dex
        stx P0L
        inx
        stx P1H
        stx P1L
        lda #$b0
        sta MCR                 ; the Z80 runs...
        nop
        ldx nmic                ; ...and has handed back ($FF00 as it left
        beq +                   ; it, I/O on). A RESTORE meanwhile: taken
        ldx #3                  ; here, its PC and P into page 1, bank 1's
-       lda ROM01+$1fc,x        ; $01FD-$01FF (the ROM's): ROM01 has them,
        sta $01fc,x             ; as the boot, romput and mon_6510 leave it
        dex
        bne -
        stx nmic
+       stx P0H                 ; pages 0 and 1 bank 0's again
        stx P0L
        stx P1H
        inx
        stx P1L
        lda #$7e
        sta CR
        lda MBOX
        ldx #$3e
        stx CR
        jmp server

; An NMI (RESTORE) while $FF00 is as the Z80 left it: through $FFFA, so in
; common RAM, or it would land in bank 1's ZX81 ROM. Counted, for tozx.
nmi:    inc nmic
        rti
nmic:   !byte 0

; X pages from bank 1 at A*256 to bank 0 at Y*256, each through STAGE.
; Called from bank 0, which it goes back to. (The disk's mailbox and
; SAVE's bytes.)
frombank1:
        sta SRC+1
        sty DST+1
        ldy #0
        sty SRC
        sty DST
.fpage: lda #$7f
        sta CR
.fin:   lda (SRC),y
        sta STAGE,y
        iny
        bne .fin
        lda #$3e
        sta CR
.fout:  lda STAGE,y
        sta (DST),y
        iny
        bne .fout
        inc SRC+1
        inc DST+1
        dex
        bne .fpage
        rts

; A to bank 1 at (DST),Y; peek1: A from bank 1 at (SRC),Y. Called from
; bank 0, which they go back to. Keep X, Y.
poke1:  pha
        lda #$7f
        sta CR
        pla
        sta (DST),y
        pha
        lda #$3e
        sta CR
        pla
        rts
peek1:  lda #$7f
        sta CR
        lda (SRC),y
        pha
        lda #$3e
        sta CR
        pla
        rts
}
com_end:
!if com_end - com_src > $100 { !error "com is more than a page: past COM's" }


; ------------------------------------------------------------ the payload
codeend:                        ; (the code's end. build.py reports prom -
!align 255, 0                   ; codeend: the bytes of code above before
                                ; prom moves a page, zx128.prg 256 bytes
                                ; with it; zx128's function ROM hasn't
                                ; room for that, and the build says so)
prom:   !binary "zx128rom.bin"  ; the patched ZX81 ROM, for $0000 (8K)
pcore:  !binary "zx128core.bin" ; the Z80's code, for $2000
pcore_end:
!align 255, 0
phi:    !binary "zx128hi.bin"   ; its own code area, for HICODE
phi_end:
pzcom:  !binary "zx128com.bin"  ; its part in common RAM, for ZCOM, $F400-
                                ; $F7FD (the panel: ~4 pages; the copy takes
                                ; them whole, what follows here with them,
                                ; but $F7FE); right after phi, not after the
                                ; core
phi_tail:                       ; (phi and pzcom end here)
!align 255, 0
!if VDC {
font:   !binary "zx128font.bin" ; the VDC's set 1's text, 8 bytes a glyph (the rest: vfont)
font_end:
BAREND  = font_end              ; (dorom's bar: the file to here)
} else {
BAREND  = phi_tail
}
pmon1:  !binary "zx128mon1.bin" ; zx64mon's part 1, for bank 1 $3000
pmon1_end:                      ; (resident; whole pages copied: page
                                ; aligned, after the font; zx128vic: after
                                ; phi_tail's page)
pmon2:  !binary "zx128mon2.bin" ; its part 2, for $E000
pmon2_end:
pmon3:  !binary "zx128mon3.bin" ; its part 3, for $FF05
pmon3_end:
!if pmon3_end - pmon3 > $ffee - $ff05 { !error "the monitor's part 3 is past $FFED" }
!if VDC {
pmhi:   !binary "zx128mhi.bin"  ; zx128's code for it, for MONCODE
pmhi_end:
}
MON1_PAGES = (pmon1_end - pmon1 + 255) >> 8
!if pmon1 & $ff { !error "the monitor's part 1 must start a page" }
!if MON1_PAGES > 16 { !error "the monitor's part 1 is past $3FFF" }

CORE_PAGES = (pcore_end - pcore + 255) >> 8
HI_PAGES = (phi_end - phi + 255) >> 8
!if HICODE & $ff { !error "HICODE must start a page" }
!if VDC {
!if (font_end - font) != $300 { !error "the font: set 1's text, 96 glyphs of 8 bytes" }
}
