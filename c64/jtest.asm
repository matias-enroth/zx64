; jtest - a probe for zx64's fast loading: not part of zx64, nor on its
; disk. make jtest builds build/jtest.prg.
;
; Does the drive answer JiffyDOS, and does a JiffyDOS byte read with the
; screen on bring the same bytes as the kernal's, and how much faster?
; Put it on a disk with zx64's files, then LOAD "JTEST",8 and RUN (no
; cartridge needed). ZX64, ZX64MON and ZX64MON2 are each read three times,
; and each read shows its bytes, time, bytes a second and a checksum:
;   k   the kernal: OPEN, CHKIN, CHRIN
;   j7  zx64's JiffyDOS reader (c64/jcore.asm, at $0D00 in this program
;       and put into place as zx64's start does), y-scroll 7 as zx64
;   j-  the same, the screen off (no bad lines at all)
; "ok": the same bytes and sum as k. "jiffy no": the drive didn't answer,
; and the j reads went through the kernal's ACPTR after jtalk's TALK.
; (Its first version, 2026-10-22, had its own copy of the protocol and a
; j pass with the screen as it is, y-scroll 3: all ok on an SD2IEC.)
;
; The protocol, worked out from sd2iec's source and SJLOAD's (read, not
; copied):
; - Asking: our own TALK under ATN, with a pause of ~500 us before its
;   last bit. A JiffyDOS drive answers by pulling DATA for ~100 us, then
;   talks JiffyDOS until the next ATN.
; - A byte: the drive releases CLK when it has one ready. We release DATA
;   (go), it puts the byte on CLK and DATA two bits at a time, low bits
;   first, ~10 us apart, then a mark: CLK low, more to come; DATA low, it
;   was the last. We pull DATA: got it. The reads are timed to the cycle,
;   so no bad line may fall among them: we only go on raster lines that
;   leave room.

!cpu 6510

SETNAM  = $ffbd
SETLFS  = $ffba
OPEN    = $ffc0
CLOSE   = $ffc3
CHKIN   = $ffc6
CLRCHN  = $ffcc
CHRIN   = $ffcf
CHROUT  = $ffd2
READST  = $ffb7
ACPTR   = $ffa5
UNTLK   = $ffab
STROUT  = $ab1e         ; BASIC: print the string at A/Y (low/high), to a 0
LINPRT  = $bdcd         ; BASIC: print A/X (high/low) in decimal
STATUS  = $90
DEVNUM  = $ba
PALFLAG = $02a6         ; 1 on a PAL machine
NPTR    = $fc           ; the file's name

JCORE = $0d00                   ; zx64's JiffyDOS reader, at $0D00 here
        !source "jcore.asm"

*= $0801
        !byte $0b,$08,$0a,$00,$9e,$32,$30,$36,$31,$00,$00,$00  ; 10 SYS2061

main:   lda DEVNUM
        cmp #8
        bcs +
        lda #8
+       sta dev
        lda #<9852              ; CIA cycles in 1/100 s, PAL
        ldx #>9852
        ldy PALFLAG
        bne +
        lda #<10227             ; NTSC
        ldx #>10227
+       sta tick
        stx tick+1
        lda #$7f                ; no NMIs from CIA 2's timers
        sta $dd0d
        jsr jinst               ; the reader into place, as zx64's start
        lda #<title
        ldy #>title
        jsr STROUT
        lda #0
        sta fidx
floop:  ldx fidx
        cpx #3
        beq fin
        lda flen,x
        sta nlen
        lda fnlo,x
        sta NPTR
        lda fnhi,x
        sta NPTR+1
        lda #13
        jsr CHROUT
        ldy #0
-       lda (NPTR),y
        jsr CHROUT
        iny
        cpy nlen
        bne -
        lda #':'
        jsr CHROUT
        jsr kpass
        lda #1
        jsr jpass
        lda #2
        jsr jpass
        lda #<jyes              ; what the drive said, the last time
        ldy #>jyes
        ldx jflag
        bne +
        lda #<jno
        ldy #>jno
+       jsr STROUT
        inc fidx
        jmp floop
fin:    lda #<donetxt
        ldy #>donetxt
        jsr STROUT
        cli
        rts

; The kernal's read, timed from OPEN to CLOSE.
kpass:  lda #<ktxt
        ldy #>ktxt
        jsr STROUT
        jsr clrsum
        jsr tstart
        jsr fopen
        bcs kend
        ldx #2
        jsr CHKIN
        bcs kend
kloop:  jsr CHRIN
        tax
        jsr READST
        sta st
        and #$83                ; not there, or a time-out: no byte
        bne kend
        txa
        jsr addsum
        lda st
        and #$40                ; the last one
        beq kloop
kend:   jsr CLRCHN
        lda #2
        jsr CLOSE
        jsr tstop
        lda cnt
        sta kcnt
        lda cnt+1
        sta kcnt+1
        lda sum
        sta ksum
        lda sum+1
        sta ksum+1
        jsr result
        lda st
        and #$83
        beq +
        lda #<errtxt
        ldy #>errtxt
        jsr STROUT
+       rts

; jtalk and jget (or the kernal's ACPTR when the drive didn't answer),
; timed from OPEN to CLOSE. A: 1 y-scroll 7, 2 the screen off.
jpass:  sta mode
        tax
        lda jlabl-1,x
        ldy #>jtxt
        jsr STROUT
        jsr clrsum
        ldx mode
        lda $d011
        sta d011s
        and #$f8                ; y-scroll 7, as zx64
        ora #7
        cpx #2
        bne +
        and #$ef                ; the screen off
+       sta $d011
        jsr tstart
        jsr fopen
        bcs jnone
        lda dev
        ldx #$62
        jsr jtalk
        lda JFLAG
        sta jflag
        bne jjl
        lda #0
        sta STATUS
jkl:    jsr ACPTR
        tax
        lda STATUS
        sta st
        and #$83
        bne jdone
        txa
        jsr addsum
        lda STATUS
        and #$40
        beq jkl
        bne jdone
jnone:  lda #$02                ; no file
        sta st
        bne jfail
jjl:    jsr jget
        tax
        lda JST
        and #$02                ; a time-out: no byte
        bne jdone
        txa
        jsr addsum
        lda JST
        and #$40
        beq jjl
jdone:  jsr jend
jfail:  lda #2
        jsr CLOSE
        jsr tstop
        lda d011s
        sta $d011
        cli
        lda st
        ora JST
        sta st
        jsr result
        lda st
        and #$83
        beq +
        lda #<errtxt
        ldy #>errtxt
        jmp STROUT
+       lda cnt                 ; the same as the kernal's?
        cmp kcnt
        bne jdiff
        lda cnt+1
        cmp kcnt+1
        bne jdiff
        lda sum
        cmp ksum
        bne jdiff
        lda sum+1
        cmp ksum+1
        bne jdiff
        lda #<oktxt
        ldy #>oktxt
        jmp STROUT
jdiff:  lda #<difftxt
        ldy #>difftxt
        jmp STROUT

; Open the file as 2 (SA 2), the kernal's way. C=1: it failed.
fopen:  lda #0
        sta STATUS
        lda nlen
        ldx NPTR
        ldy NPTR+1
        jsr SETNAM
        lda #2
        ldx dev
        ldy #2
        jsr SETLFS
        jmp OPEN

clrsum: lda #0
        sta st
        sta JST
        sta cnt
        sta cnt+1
        sta sum
        sta sum+1
        rts

addsum: clc
        adc sum
        sta sum
        bcc +
        inc sum+1
+       inc cnt
        bne +
        inc cnt+1
+       rts

; CIA 2 counts hundredths: timer A one each, timer B its underflows.
tstart: lda #0
        sta $dd0e
        sta $dd0f
        lda tick
        sta $dd04
        lda tick+1
        sta $dd05
        lda #$ff
        sta $dd06
        sta $dd07
        lda #$51                ; B: A's underflows, loaded, started
        sta $dd0f
        lda #$11                ; A: continuous, loaded, started
        sta $dd0e
        rts
tstop:  lda #0
        sta $dd0e
        lda #$ff
        sec
        sbc $dd06
        sta tim
        lda #$ff
        sbc $dd07
        sta tim+1
        rts

; " bytes  s.cc s  bytes/s  sum"
result: jsr space
        lda cnt+1
        ldx cnt
        jsr LINPRT
        jsr space
        lda tim                 ; the time: hundredths / 100
        sta num
        lda tim+1
        sta num+1
        lda #0
        sta num+2
        lda #100
        sta den
        lda #0
        sta den+1
        jsr div24
        lda num+1
        ldx num
        jsr LINPRT
        lda #'.'
        jsr CHROUT
        lda rem
        ldx #'0'-1
-       inx
        sec
        sbc #10
        bcs -
        adc #10+'0'
        pha
        txa
        jsr CHROUT
        pla
        jsr CHROUT
        lda #'S'                ; (PETSCII: 's' would be a shifted S)
        jsr CHROUT
        jsr space
        lda tim                 ; bytes a second: bytes * 100 / hundredths
        ora tim+1
        beq rnone
        lda #0
        sta num
        sta num+1
        sta num+2
        ldx #100
-       lda num
        clc
        adc cnt
        sta num
        lda num+1
        adc cnt+1
        sta num+1
        bcc +
        inc num+2
+       dex
        bne -
        lda tim
        sta den
        lda tim+1
        sta den+1
        jsr div24
        lda num+1
        ldx num
        jsr LINPRT
rnone:  lda #<pstxt
        ldy #>pstxt
        jsr STROUT
        lda sum+1
        jsr phex
        lda sum
phex:   pha
        lsr
        lsr
        lsr
        lsr
        jsr +
        pla
        and #$0f
+       cmp #10
        bcc +
        adc #6
+       adc #'0'
        jmp CHROUT

space:  lda #' '
        jmp CHROUT

; num (3 bytes) / den (2) -> num the quotient, rem the remainder
div24:  lda #0
        sta rem
        sta rem+1
        sta rem+2
        ldx #24
dv1:    asl num
        rol num+1
        rol num+2
        rol rem
        rol rem+1
        rol rem+2
        lda rem
        sec
        sbc den
        tay
        lda rem+1
        sbc den+1
        sta tmp
        lda rem+2
        sbc #0
        bcc dv2
        sta rem+2
        lda tmp
        sta rem+1
        sty rem
        inc num
dv2:    dex
        bne dv1
        rts

title:  !pet 147, "jtest: jiffydos probe for zx64", 13
        !pet "k kernal, j7 jcore y-scroll 7, j- off", 13, 0
ktxt:   !pet 13, " k ", 0
jtxt:
jt1:    !pet 13, " j7", 0
jt2:    !pet 13, " j-", 0
jlabl:  !byte <jt1, <jt2
!if >jt1 != >jt2 { !error "jtxt crosses a page" }
pstxt:  !pet "/s ", 0
oktxt:  !pet " ok", 0
difftxt: !pet " diff", 0
errtxt: !pet " err", 0
jyes:   !pet 13, " jiffy yes", 0
jno:    !pet 13, " jiffy no", 0
donetxt: !pet 13, 13, "done.", 13, 0
n0:     !pet "zx64"
n1:     !pet "zx64mon"
n2:     !pet "zx64mon2"
fnlo:   !byte <n0, <n1, <n2
fnhi:   !byte >n0, >n1, >n2
flen:   !byte n1-n0, n2-n1, fnlo-n2

dev:    !byte 8
tick:   !word 0
fidx:   !byte 0
nlen:   !byte 0
mode:   !byte 0
st:     !byte 0
jflag:  !byte 0
d011s:  !byte 0
cnt:    !word 0
sum:    !word 0
kcnt:   !word 0
ksum:   !word 0
tim:    !word 0
num:    !fill 3, 0
den:    !word 0
rem:    !fill 3, 0
tmp:    !byte 0
!if * > JCORE { !error "jtest runs into the reader at JCORE" }
