; zx64 - the JiffyDOS reader, resident in RAM that neither the kernal nor
; zx64 uses: the cassette buffer ($0334-$03FF), $02A7-$02FF (jget's timed
; part, which the buffer has no room for) and BASIC's input buffer ($0200-
; $0258, unused once the boot file runs: jbyte).
;
; A file opened the kernal's way (OPEN with SETNAM and SETLFS) is then read
; without CHKIN and CHRIN: jtalk makes the drive talk, asking JiffyDOS on
; the way, and jget takes a byte at a time; jend stops it. A drive that
; doesn't answer JiffyDOS gets jend at once, and the kernal's CHKIN and
; CHRIN as before.
;
; The protocol, worked out from sd2iec's source and SJLOAD's (read, not
; copied), tried on an SD2IEC with c64/jtest.asm (2026-10-22):
; - Asking: our own TALK under ATN, with a pause of ~500 us before its
;   last bit. A JiffyDOS drive answers by pulling DATA for ~100 us, then
;   talks JiffyDOS until the next ATN. The secondary address and the turn
;   around are the kernal's (TKSA).
; - A byte: the drive releases CLK when it has one ready. We release DATA
;   (go), it puts the byte on CLK and DATA two bits at a time, low bits
;   first, ~10 us apart, then a mark: CLK low, more to come; DATA low, it
;   was the last. We pull DATA: got it. The reads are timed to the cycle,
;   so no bad line may fall among them: we only go on raster lines that
;   leave room.
;
; build.py puts it in the boot file at $3E00, the keyboard page and the
; mailbox, which don't matter at the start: jinst there, run once by start
; (c64/boot.asm) before it sets the mailbox up and the Z80 has the pages,
; copies the three pieces into place. c64/boot.asm
; gets these labels from the symbol list build.py has acme write.

!cpu 6510

TKSA    = $ff96
UNTLK   = $ffab
CHRIN   = $ffcf
READST  = $ffb7
R2D2    = $a3                   ; the kernal's EOI flag for its next byte out

JREL    = $02                   ; $DD00 with ATN, CLK and DATA released (the
JPULL   = $03                   ; VIC bank, PA2); with DATA pulled; what
JFIX    = $04                   ; jget's four reads make of those bits
JFLAG   = $05                   ; 1: the drive said yes to JiffyDOS
JST     = $06                   ; $40 the last byte, $02 a time-out or no mark
JBYTE   = $07                   ; jtalk's TALK byte, as it goes out
JWAIT   = $08                   ; jget's time-out, in 0.6 s steps; jwd's level
JSA     = $09                   ; jtalk's secondary address
JNY     = $0a                   ; 7 less the y-scroll: jget's raster guard

!ifndef JCORE { JCORE = $3e00 }  ; (c64/stub.asm and c64/jtest.asm put it elsewhere)
*= JCORE

; The three pieces into place; no JiffyDOS read open.
jinst:  ldx #jc1end-jtalk
-       lda jimg1-1,x
        sta jtalk-1,x
        dex
        bne -
        ldx #jc2end-jg1
-       lda jimg2-1,x
        sta jg1-1,x
        dex
        bne -
        ldx #jc3end-jbyte
-       lda jimg3-1,x
        sta jbyte-1,x
        dex
        bne -
        stx JFLAG
        rts

jimg1:
!pseudopc $0334 {
; TALK to device A, secondary address X (as OPEN had it, $60 added),
; asking JiffyDOS. JFLAG: 1 if the drive said yes; then jget, else jend
; and the kernal (also when the drive stopped answering: a time-out).
; The port's own bits (the VIC bank) and the y-scroll as they are now:
; zx64's picture or the monitor's screen.
jtalk:  ora #$40
        sta JBYTE
        stx JSA
        lda $dd00
        and #$07
        sta JREL
        ora #$20
        sta JPULL
        lda JREL                ; what jget's four reads make of them
        ldx #3
-       lsr
        lsr
        eor JREL
        dex
        bne -
        sta JFIX
        lda $d011
        and #7
        eor #7
        sta JNY
        lda #0
        sta JFLAG
        sta JST
        sta R2D2
        sei
        lda JREL
        ora #$18                ; ATN and CLK low
        sta $dd00
        ldy #200                ; ~1 ms for the devices to answer ATN
-       dey
        bne -
        bit $dd00
        bmi jtnone              ; DATA high: nobody holds it
        lda JREL
        ora #$08                ; CLK released: ready to send
        sta $dd00
        lda #$80                ; the listeners release DATA: ready
        jsr jwd
        bcs jtnone
        ldx #8
jtbit:  lda JREL
        ora #$18                ; CLK low, DATA released
        sta $dd00
        cpx #1
        bne jtsend
        ldy #45                 ; before the last bit, ~500 us: a JiffyDOS
-       bit $dd00               ; drive pulls DATA
        bpl jtyes
        dey
        bne -
        beq jtsend              ; no answer: a plain drive
jtyes:  inc JFLAG
        lda #$80                ; until it lets go
        jsr jwd
        bcs jtnone
jtsend: lda JREL
        ora #$18                ; CLK low
        lsr JBYTE
        bcs +
        ora #$20                ; a 0: DATA low
+       sta $dd00
        jsr jdly                ; ~35 us for it to settle
        and #$ef                ; CLK released: the bit is there
        sta $dd00
        jsr jdly
        jsr jdly
        lda JREL
        ora #$18                ; CLK low, DATA released
        sta $dd00
        dex
        bne jtbit
        lda #0                  ; the listeners take it: DATA low
        jsr jwd
        bcs jtnone
        lda JSA
        jmp TKSA
jtnone: lda JREL                ; nobody, or a time-out: the lines let go,
        sta $dd00               ; and no JiffyDOS
        lsr JFLAG
        rts

; A byte by JiffyDOS. Out: A; JST |= $40 for the last byte, $02 on a
; time-out (~2.5 s) or no mark (A then means nothing).
jget:   sei                     ; (the kernal's TKSA ends with CLI)
        lda #4
        sta JWAIT
jg0:    bit $dd00               ; the drive has a byte: CLK high
        bvc +
        jmp jg1
+       dex
        bne jg0
        dey
        bne jg0
        dec JWAIT
        bne jg0
        pha
        jmp jgerr

jc1end:
}
!if jc1end > $0400 { !error "the JiffyDOS core overflows the cassette buffer" }

jimg2:
!pseudopc $02a7 {
jg1:    ldx JREL
        ldy JPULL
jg2:    lda $d012               ; 0-4 lines after a bad line (the y-scroll's
        clc                     ; line, mod 8): the 73 cycles from this read
        adc JNY                 ; to the mark don't reach the next one
        and #7
        cmp #5
        bcs jg2
        stx $dd00               ; DATA released: go
        nop
        nop
        nop
        nop
        nop
        nop
        lda $dd00               ; +16: bit 0 on CLK (6), bit 1 on DATA (7)
        lsr
        lsr
        nop
        eor $dd00               ; +26: bits 2 and 3
        lsr
        lsr
        nop
        eor $dd00               ; +36: bits 4 and 5
        lsr
        lsr
        nop
        nop
        eor $dd00               ; +48: bits 6 and 7
        eor JFIX                ; the port's own bits out again
        pha
        bit $dd00               ; +58: the mark
        sty $dd00               ; DATA low: got it
        bvc jgok                ; CLK low: more to come
        bmi jgerr               ; both high: no mark
        lda #$40                ; DATA low: that was the last
        !byte $2c
jgerr:  lda #$02
        ora JST
        sta JST
jgok:   pla
        rts
jc2end:
}
!if jc2end > $0300 { !error "jget's timed part overflows into the vectors at $0300" }

jimg3:
!pseudopc $0200 {
; A byte of the file jtalk opened, by JiffyDOS or else the kernal's CHRIN
; (after its CHKIN), ST in JST either way, flags as A. After the last
; byte or an error, no more: JiffyDOS would wait for one. jget changes X
; and Y, CHRIN doesn't.
jbyte:  lda JFLAG
        beq +
        lda JST
        and #$42
        bne ++
        jmp jget
+       jsr CHRIN
        pha
        jsr READST
        sta JST
        pla
++      rts

; Stop the drive talking (after the last byte, or when it said no).
jend:   ldy #20                 ; the drive lets go of DATA ~50 us after
-       dey                     ; the last byte
        bne -
        jmp UNTLK

jdly:   ldy #5                  ; ~35 cycles with the JSR, keeps A and X
-       dey
        bne -
        rts

; Wait until DATA is as A's bit 7 says (1 high, 0 low): C=0. C=1 after
; ~0.9 s without: a time-out. Keeps X.
jwd:    sta JWAIT
        txa
        pha
        ldx #0
        ldy #0
-       lda $dd00
        eor JWAIT
        bpl +
        dey
        bne -
        dex
        bne -
        pla
        tax
        sec
        rts
+       pla
        tax
        clc
        rts
jc3end:
}
!if jc3end > $0259 { !error "jbyte overflows BASIC's input buffer into the kernal's file tables" }
!if * > $4000 { !error "jcore overflows the mailbox into zx64mon's place" }
