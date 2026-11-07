; zx128 - the function ROM's start: build/zx128.rom (32K, $8000-$FFFF:
; an EPROM for U36, the internal function ROM, or a cartridge,
; build/zx128.crt), and zx128vic's (build/zx128vic.rom, .crt, with FAST
; below). zx128.prg's bytes are in the ROM packed (ZX0, extras/zx0/zx0.py):
; this unpacks them to bank 0 $1300 on, where the boot sector's LOAD
; would have put them, and jumps to boot128's entry, which carries on as
; from the disk.
;
; The kernal finds the ROM at reset ("CBM" at $8007) and, as its ID is 1,
; calls $8000 at once (JSRFAR), before its own IOINIT, RAMTAS, RESTOR and
; CINT. Its $FF00 then: the ROM at $8000 and at $C000, I/O on, RAM below
; $8000 bank 0 ($2A a cartridge, $16 the internal ROM): the kernal's jump
; table is under this ROM until its $C000 half goes. The flags come from
; zero page nobody has set (JSRFAR's RTI): decimal may be on, interrupts
; too.
;
; CTRL held: back to the kernal, which goes on into C128 BASIC as if
; there were no ROM (joystick 1 held left, which reads as CTRL in every
; column, doesn't count).
;
; The ROM: this code at $8000 (to codeend), $FF (the room left), the
; packed image (STREAM, right up against the unpacker), the unpacker's
; first part (PARTB, to $FEFF), $FF00-$FF04 (the MMU, whatever $FF00
; says), its second part from $FF05 (parta), and the vectors at $FFFA:
; NMI and reset on nmi (an RTI), for RESTORE while this ROM is at $C000,
; the IRQ on irq.
;
; The trap: the output runs past $8000 (zx128's to $9152), where a read
; gets this ROM, not the RAM written below it. So the unpacker lives in
; the ROM's $C000 half, and goes in two phases: first this ROM at $8000
; and $C000 (the stream's start, below $C000, readable), and once the
; stream's pointer has passed $C000 (phase), RAM at $8000-$BFFF ($FF00
; bits 2-3 set; the stream's rest still readable at $C000-$FEFF): from
; then on a copy reads the output, wherever it is below $C000 (this ROM
; stays at $C000 all along, so the image must end below it).
; tools/build.py checks that no copy before that reads $8000 or above
; (zx0.phase1_reads; the stream right-aligned keeps its last 16K above
; $C000), and that the image ends below $C000, and stops if not. The NMI and IRQ handlers are in the $C000 half too, as their
; vectors are: there all along.
;
; Zero page: the unpacker's $F3-$FE; $FA-$FE are the user's (the kernal
; leaves them), $F3-$F9 kept on the stack and put back.
;
; FAST (zx128vic's; off by default): the unpack at 2 MHz
; ($D030 bit 0), from after CINT (IOINIT sets $D030 to 1 MHz itself,
; early) to before the JMP, which goes on at 1 MHz: the VIC shows garbage
; at 2 MHz, and boot128 shows its picture on it. CTRL's skip comes before,
; $D030 left as the kernal has it.
;
; tools/build.py assembles this twice with STREAM (where the packed image
; starts), PARTB (where the unpacker's first part starts: $FF00 less its
; length, which the first run gives) and FAST, into build/obj/from.bin
; (zx128vic's in build/obj/zx128vic/): 32K, $FF where the image goes.

!cpu 6502

CR      = $ff00         ; the MMU's configuration register
PRA     = $dc00         ; CIA 1: the keyboard's columns (out)
PRB     = $dc01         ; its rows (in)
DDRA    = $dc02
DDRB    = $dc03
SLOT    = $0ac0         ; the kernal's poll: the slot it is starting
PAT     = $0ac1         ; the IDs it found, a slot each (BASIC's PHOENIX
                        ; calls every ROM whose ID is there)
LOADAT  = $1300         ; boot128's entry (the boot sector's JMP)
CRU     = $f3           ; the unpack's $FF00 (its first phase)
BITS    = $f4           ; the stream's bits not read yet (and a 1 after)
SRC     = $f5           ; the stream
DST     = $f7           ; the output
PTR     = $f9           ; a copy's source
LEN     = $fb           ; a length (Elias)
OFF     = $fd           ; the last offset, less than 0
KEEP    = $f3           ; $F3-$F9 kept (the kernal's), $FA-$FE the user's
NKEEP   = 7

* = $8000
        jmp cold
        jmp cold                ; (warm start: the same)
        !byte $01               ; ID 1: started at reset
        !text "CBM"

cold:   cld
        sei
        lda CR                  ; the configuration the kernal entered
        pha                     ; with, kept on the stack (RAMTAS clears
                                ; zero page)
        lda DDRA                ; CTRL: CIA 1 as the reset left it (no
        pha                     ; IOINIT yet): kept, then port A out, no
        lda DDRB                ; column low first, port B in
        pha
        lda PRA
        pha
        lda #$ff
        sta PRA
        sta DDRA
        lda #0
        sta DDRB
        jsr rows
        and #$04                ; PB2 low with no column: joystick 1 held
        eor #$04                ; left, not CTRL ($04: boot)
        bne +
        lda #$7f                ; CTRL's column
        sta PRA
        jsr rows
        and #$04                ; row 2: CTRL (0: down)
+       tax
        pla                     ; CIA 1 back as it was (PRA gets what it
        sta PRA                 ; read, $FF, not the reset's latch $00: an
        pla                     ; input port's latch drives nothing, and
        sta DDRB                ; IOINIT writes it)
        pla
        sta DDRA
        txa
        bne boot
        ldx SLOT                ; held: this slot's ID cleared (A = 0), so
        cpx #4                  ; BASIC doesn't start it later (a kernal
        bcs +                   ; whose $0AC0 isn't the poll's slot: left
        sta PAT,x               ; alone); $FF00 as it came, back to the
+       pla                     ; kernal
        rts

boot:   pla
        and #$cf                ; the kernal at $C000 (its jump table), the
        sta CR                  ; rest as entered: $0A, $06
        pha
        jsr $ff84               ; IOINIT
        jsr $ff87               ; RAMTAS
        jsr $ff8a               ; RESTOR
        jsr $ff81               ; CINT
        sei
!if FAST {
        lda $d030               ; 2 MHz for the unpack (the I/O still on)
        ora #$01
        sta $d030
}
        ldx #NKEEP - 1          ; zero page $F3-$F9 kept
-       lda KEEP,x
        pha
        dex
        bpl -
        tsx
        lda $0100 + NKEEP + 1,x ; (the kernal's $FF00, under them)
        and #$0c                ; for the unpack: this ROM at $8000 and at
        sta CRU                 ; $C000 too (its bits twice), I/O off (the
        asl                     ; stream covers $D000-$DFFF), RAM at $4000,
        asl                     ; bank 0 (writes under a ROM go to the RAM
        ora CRU                 ; below it): $2B, $17
        ora #$03
        sta CRU
        sta CR
        lda #<STREAM
        sta SRC
        lda #>STREAM
        sta SRC+1
        lda #<LOADAT
        sta DST
        lda #>LOADAT
        sta DST+1
        jsr unpack              ; (back with $FF00 CRU)
        ldx #0                  ; zero page put back
-       pla
        sta KEEP,x
        inx
        cpx #NKEEP
        bne -
        pla                     ; $FF00 as for the kernal's calls (this
        sta CR                  ; ROM still at $8000, under this code)
!if FAST {
        lda $d030               ; 1 MHz again, before boot128 shows
        and #$fe                ; anything on the VIC
        sta $d030
}
        jmp LOADAT

rows:   lda PRB                 ; CIA 1's rows, once two reads agree (as
        cmp PRB                 ; the kernal reads them)
        bne rows
        rts

codeend:

; ---- the unpacker (ZX0, version 2, forward: extras/zx0/zx0.py says how the
; stream goes). Y is 0 and A holds BITS between blocks; a copy of up to
; 255 bytes is the fast way (X counts), longer ones go by copy. Its first
; part (PARTB) up against $FF00, the second from $FF05: both in the
; $C000 half, there in both phases (above)

* = PARTB

nmi:    rti                     ; (the vectors at $FFFA: below)

irq:    pla                     ; an IRQ before cold's SEI: the kernal's
        ora #$04                ; JSRFAR enters with P from $05 (I maybe
        pha                     ; clear), and the VIC's raster IRQ may be
        rti                     ; on still after the reset button: back
                                ; with I set, not into the IRQ again

unpack: ldy #$ff                ; SRC the stream, DST the output, $FF00 CRU
        sty OFF                 ; (the last offset 1 to start with)
        sty OFF+1
        iny
        jsr phase               ; (the stream may start above $C000)
        lda #$80                ; (no bits: the first ASL reads a byte)
        jmp lits

msbn:   ldx #$fe                ; Elias(MSB + 1) on, its data bits
        stx LEN                 ; inverted: from ~1, ~(MSB + 1) in LEN
-       asl                     ; (8 bits at most: no more than LEN)
        bne +
        jsr refill
+       rol LEN                 ; a data bit
        asl                     ; 1: the end
        bne +
        jsr refill
+       bcc -
        sta BITS
        ldx LEN
        inx
        beq done                ; 256: the end
        txa                     ; -(MSB + 1) = ~MSB
        sec
        jmp msb

lenn:   lda BITS                ; a copy's length: Elias(length - 1) on
        jsr elias1
        sta BITS
        inc LEN
        bne +
        inc LEN+1
+       ldx LEN+1
        bne matchbig
        ldx LEN
        jmp match0
repn:   jsr elias1              ; from the last offset: Elias(length) on
        sta BITS
        ldx LEN+1
        bne matchbig
        ldx LEN
        jmp match0

done:   lda CRU                 ; this ROM at $8000 again, for the RTS
        sta CR
        rts

litfwd: ldy #0                  ; 128-255 literals
        ldx LEN
-       lda (SRC),y
        sta (DST),y
        iny
        dex
        bne -
        jmp litadd

litbig: lda SRC                 ; 256 literals or more
        sta PTR
        lda SRC+1
        sta PTR+1
        jsr copy
        lda PTR
        sta SRC
        lda PTR+1
        sta SRC+1
        jsr phase
        lda BITS
        jmp litend

matchbig:                       ; a copy of 256 bytes or more
        clc
        lda DST
        adc OFF
        sta PTR
        lda DST+1
        adc OFF+1
        sta PTR+1
        jsr copy
        lda BITS
        jmp mend

copy:   ldx LEN                 ; LEN bytes (256-65535) from (PTR) to (DST),
        beq +                   ; both moved on; Y 0 after
        inc LEN+1
+
-       lda (PTR),y
        sta (DST),y
        iny
        bne +
        inc PTR+1
        inc DST+1
+       dex
        bne -
        dec LEN+1
        bne -
        tya
        clc
        adc PTR
        sta PTR
        bcc +
        inc PTR+1
        clc
+       tya
        adc DST
        sta DST
        bcc +
        inc DST+1
+       ldy #0
        rts

ebig:   rol LEN+1               ; Elias past 8 bits: 16 from here
-       asl                     ; (a 1: the end)
        bne +
        jsr refill
+       bcs +
        asl                     ; a data bit
        bne ++
        jsr refill
++      rol LEN
        rol LEN+1
        jmp -
+       rts

phase:  bit SRC+1               ; the stream at $C000 or above: RAM at
        bvc +                   ; $8000-$BFFF from now on (keeps A, carry)
        pha
        lda CRU
        ora #$0c
        sta CR
        pla
+       rts

partb_end:
!if partb_end > $ff00 { !error "the unpacker's first part runs into the MMU" }

* = $ff05
parta:

lits:   asl                     ; literals: Elias(length)'s first bit
        bne +
        jsr refill
+       bcc litn
        sta BITS                ; 1 literal
        lda (SRC),y
        sta (DST),y
        inc SRC
        bne +
        jsr srcpage
+       inc DST
        bne +
        inc DST+1
+       lda BITS
litend: asl                     ; 0: from the last offset, 1: a new one
        bne +
        jsr refill
+       bcs newoff
        asl                     ; Elias(length)
        bne +
        jsr refill
+       bcs +
        jmp repn
+       ldx #1
match:  sta BITS
match0: clc                     ; X bytes (1-255) from DST + OFF
        lda DST
        adc OFF
        sta PTR
        lda DST+1
        adc OFF+1
        sta PTR+1
-       lda (PTR),y
        sta (DST),y
        iny
        dex
        bne -
        tya
        clc
        adc DST
        sta DST
        bcc +
        inc DST+1
+       ldy #0
        lda BITS
mend:   asl                     ; 0: literals, 1: a new offset
        bne +
        jsr refill
+       bcc lits
newoff: asl                     ; Elias(MSB + 1)'s first bit
        bne +
        jsr refill
+       sta BITS
        bcs +
        jmp msbn
+       lda #$ff                ; MSB 0 (carry set)
msb:    ror                     ; -offset's high byte, its bit 0 into the
        sta OFF+1               ; low one's top
        lda (SRC),y
        ror
        sta OFF
        inc SRC
        bne +
        jsr srcpage
+       bcs +                   ; Elias(length - 1)'s first bit (bit 0)
        jmp lenn
+       ldx #2
        bne match0              ; (always)

litn:   jsr elias1              ; 2 literals or more
        sta BITS
        ldx LEN+1
        beq +
        jmp litbig
+       ldy LEN
        bpl +
        jmp litfwd
+       dey
-       lda (SRC),y             ; (2-127, backwards)
        sta (DST),y
        dey
        bpl -
litadd: lda LEN
        clc
        adc DST
        sta DST
        bcc +
        inc DST+1
        clc
+       lda LEN
        adc SRC
        sta SRC
        bcc +
        jsr srcpage
+       ldy #0
        lda BITS
        jmp litend

elias1: ldx #1                  ; Elias(v) on after its first bit (a 0),
        stx LEN                 ; into LEN
        dex
        stx LEN+1
eback:  asl                     ; a data bit
        bne +
        jsr refill
+       rol LEN
        bcc +
        jmp ebig
+       asl                     ; 1: the end
        bne +
        jsr refill
+       bcc eback
        rts

refill: lda (SRC),y             ; 8 bits more (carry set: BITS's 1)
        inc SRC
        bne +
        jsr srcpage
+       rol
        rts

srcpage:
        inc SRC+1               ; (keeps A and carry)
        jmp phase

parta_end:
!if parta_end > $fffa { !error "the unpacker's second part runs into the vectors" }

* = $fffa
        !word nmi               ; NMI
        !word nmi               ; reset
        !word irq               ; IRQ
