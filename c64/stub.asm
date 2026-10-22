; zx64 - the boot file, ZX81: LOAD "ZX81",8 and RUN.
;
; A stub that loads the rest, ZX64 (c64/boot.asm's file: the 6510 loader,
; the patched ROM and the Z80 code), by JiffyDOS where the drive speaks it
; (c64/jcore.asm), else the kernal's way. On a JiffyDOS drive the monitor
; comes too (zx64mon, zx64mon2), so F5 needs no disk. Then ZX64's start.
;
; ZX64 loads over this, from $0801: the loader runs at $CE00, in the
; ZX81's RAM, which nothing uses until the ZX81 starts.

!cpu 6510

SETNAM  = $ffbd
SETLFS  = $ffba
OPEN    = $ffc0
CLOSE   = $ffc3
CHKIN   = $ffc6
CLRCHN  = $ffcc
CHROUT  = $ffd2
PTR     = $fb
START   = $080d                 ; ZX64's start, its SYS 2061
LOADER  = $ce00                 ; two pages, up to $CFFF: under the I/O
MONZM   = $4003                 ; zx64mon's "ZM" (C64 $4000: JP, then "ZM")

JCORE = $0940                   ; the JiffyDOS reader, put in place from here
        !source "jcore.asm"

*= $0801
        !byte $0b,$08,$0a,$00,$9e,$32,$30,$36,$31,$00,$00,$00  ; 10 SYS2061

        jsr jinst
        ldx #0
-       lda ldimg,x
        sta LOADER,x
        lda ldimg+$100,x
        sta LOADER+$100,x
        inx
        bne -
        jmp ldcode

ldimg:
!pseudopc LOADER {
ldcode: lda #0                  ; a zx64mon from before a reset (RAM keeps
        sta MONZM               ; it): its "ZM" gone, so F5 loads it again
        tax                     ; from this disk, with a clear screen
        jsr fload               ; ZX64
        bcs lderr
        lda fjiffy
        beq go                  ; a plain drive: the monitor waits for F5
        ldx #fn1-fnames
        jsr fload
        bcs nomon
        ldx #fn2-fnames
        jsr fload
        bcc go
nomon:  lda #0                  ; not both parts: F5 loads them
        sta MONZM
go:     jmp START
lderr:  ldy #0                  ; back to BASIC
-       lda nottxt,y
        beq +
        jsr CHROUT
        iny
        bne -
+       rts

; The file fnames+X names (its length, then the name), to the address its
; first two bytes give; "LOADING NAME" on the screen. C=1: not there, a
; disk error, or a byte for a place it mustn't go: below $0400 (the zero
; page, the stack, the JiffyDOS reader), this loader, or the I/O chips.
; fjiffy: 1 if it came by JiffyDOS.
fload:  txa
        clc
        adc #<(fnames+1)
        sta PTR
        lda #>(fnames+1)
        adc #0
        sta PTR+1
        lda fnames,x
        sta flen
        ldy #0
-       lda lodtxt,y
        beq +
        jsr CHROUT
        iny
        bne -
+       ldy #0
-       lda (PTR),y
        jsr CHROUT
        iny
        cpy flen
        bne -
        lda #13
        jsr CHROUT
        lda flen
        ldx PTR
        ldy PTR+1
        jsr SETNAM
        lda #2
        ldx $ba                 ; the drive ZX81 came from
        ldy #0
        jsr SETLFS
        jsr OPEN
        bcs fbad
        lda $ba
        ldx #$60                ; (SA 0)
        jsr jtalk
        lda JFLAG
        sta fjiffy
        bne +
        jsr jend                ; not JiffyDOS: the kernal's way
        ldx #2
        jsr CHKIN
        bcs fbad
+       jsr jbyte               ; the load address
        sta PTR
        jsr jbyte
        sta PTR+1
        lda JST
        and #$83
        bne fbad
fl:     lda JST
        and #$40                ; the last byte taken
        bne fok
        lda PTR+1
        cmp #$04
        bcc fbad
        cmp #>LOADER
        bcc +
        cmp #$e0
        bcc fbad
+       jsr jbyte
        ldy #0
        sta (PTR),y
        inc PTR
        bne +
        inc PTR+1
+       lda JST
        and #$83
        beq fl
fbad:   jsr fclose
        sec
        rts
fok:    jsr fclose
        clc
        rts

fclose: lda JFLAG               ; a JiffyDOS read: stop it, then as usual
        beq +
        lsr JFLAG
        jsr jend
+       jsr CLRCHN
        lda #2
        jmp CLOSE

fnames: !byte 4
        !pet "zx64"
fn1:    !byte 7
        !pet "zx64mon"
fn2:    !byte 8
        !pet "zx64mon2"
lodtxt: !pet "loading ", 0
nottxt: !pet "zx64 not loaded", 13, 0
flen:   !byte 0
fjiffy: !byte 0
ldend:
}
!if ldend > LOADER + $200 { !error "the loader is more than the two pages copied" }

!if * > JCORE { !error "the stub runs into the JiffyDOS reader at JCORE" }
