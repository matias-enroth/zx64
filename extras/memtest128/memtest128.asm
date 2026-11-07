; memtest128: a VDC RAM and REU test for the C128 (C128 mode, 8502).
;
; Loops until a key is held: each pass tests the VDC's RAM, 16K or 64K as
; found at the start (two patterns, written and read back polled; the 80-column screen shows garbage while
; it runs and is restored after) and then the whole REU, twice (a pattern
; and its complement): every 64K bank is written in 8K DMA blocks, then
; all banks are verified with the REU's own compare (a failed block is
; fetched and compared byte by byte to find the bad bytes), then one bank
; (a different one each time) is fetched and compared by the CPU. Every
; 256-byte page carries its bank and page number, so address faults show.
; Progress, the time and the errors are on the 40-column screen and, when
; the VDC isn't being tested, the same on the 80-column one.
;
; Runs at 1 MHz (the REU needs it), with interrupts off; the time is CIA 1's
; time-of-day clock. Memory: the program at $1C01 (BASIC's SYS), buffers at
; $4000-$83E7 in bank 0 (with $FF00 = $0E: RAM from $4000 to $BFFF, I/O, the
; kernal). acme -DFAULT=1 builds a version that plants one bad byte in the
; VDC and one in the REU each round, to check that errors are found.

!cpu 6502
!ifndef FAULT { FAULT = 0 }

SCREEN  = $0400                 ; the VIC's 40-column text
COLRAM  = $d800
PAT     = $4000                 ; 8K: what a block should hold
FET     = $6000                 ; 8K: a block fetched back
SAVE    = $8000                 ; the 40-column screen across CINT
VDCA    = $d600                 ; the VDC's register select / status
VDCD    = $d601                 ; the VDC's data
REU     = $df00
MMUCR   = $ff00
ATTR    = $0f                   ; the 80-column text's attribute: white

CINT    = $ff81
DLCHR   = $ff62                 ; the 80-column character set, from ROM
PLOT    = $fff0

cur     = $fa                   ; zero page ($FA-$FF are the user's)
sp      = $fc
tp      = $fe

; rows of the screen
R_PASS  = 2
R_VDC   = 4
R_VPH   = 5
R_VBAR  = 6
R_VFST  = 7
R_VLST  = 8
R_REU   = 10
R_RPH   = 11
R_RBAR  = 12
R_RFST  = 13
R_RLST  = 14
R_ODD   = 15
R_RES   = 17
R_BAD   = 18
R_TMO   = 19
R_KEY   = 23

!macro at .r, .c {
        ldx #.r
        ldy #.c
        jsr goto
}
!macro text .s {
        lda #<.s
        ldy #>.s
        jsr prs
}
!macro num16 .v {
        lda .v
        sta n16
        lda .v+1
        sta n16+1
        jsr pdec16
}
!macro sat16 .v {               ; +1, stopping at 65535
        inc .v
        bne .done
        inc .v+1
        bne .done
        dec .v
        dec .v+1
.done
}

        * = $1c01
        !word .link, 10         ; 10 SYS7181
        !byte $9e
        !text "7181"
        !byte 0
.link   !word 0

start
!if start != 7181 { !error "the SYS line's address" }
        sei
        cld
        lda MMUCR
        sta oldcr
        lda #$0e
        sta MMUCR
        lda $d030
        and #$fe
        sta $d030               ; 1 MHz
        ldx #vars_end-vars-1    ; a fresh start every RUN
        lda #0
-       sta vars,x
        dex
        bpl -
        lda #0
        sta $d020
        sta $d021
        jsr clrvic
        jsr vdcdetect
        jsr DLCHR               ; (the detection's tags hit the font)
        jsr vdcclear
        lda #1
        sta vdclive
        jsr drawui
        jsr todstart
        jsr reudetect
        jsr showreu
        jsr flushall

passlp  inc pass
        bne +
        inc pass+1
+       lda #0
        sta vdcpe
        sta vdcpe+1
        sta reupe
        sta reupe+1
        jsr showcnt
        jsr vdctest
        lda stop
        bne exit
        lda reuok
        cmp #1
        bne passend
        lda #0
        sta inv
        jsr reupass
        lda stop
        bne exit
        lda #$ff
        sta inv
        jsr reupass
        lda stop
        bne exit
passend jsr showres
        jmp passlp

exit    jsr showcnt
        +at R_KEY, 0
        +text t_stop
        ldx #0                  ; CINT clears both screens: keep ours
-       lda SCREEN,x
        sta SAVE,x
        lda SCREEN+$100,x
        sta SAVE+$100,x
        lda SCREEN+$200,x
        sta SAVE+$200,x
        lda SCREEN+$2e8,x
        sta SAVE+$2e8,x
        inx
        bne -
        jsr CINT
        sei
        lda #$0e
        sta MMUCR
        ldx #0
-       lda SAVE,x
        sta SCREEN,x
        lda SAVE+$100,x
        sta SCREEN+$100,x
        lda SAVE+$200,x
        sta SCREEN+$200,x
        lda SAVE+$2e8,x
        sta SCREEN+$2e8,x
        lda #1
        sta COLRAM,x
        sta COLRAM+$100,x
        sta COLRAM+$200,x
        sta COLRAM+$2e8,x
        inx
        bne -
        lda #0
        sta $d020
        sta $d021
        sta vdclive
        jsr vdcclear
        lda #1
        sta vdclive
        jsr flushall
-       lda #0                  ; wait for the key to go up
        sta $dc00
        lda $dc01
        cmp #$ff
        bne -
        lda #$7f
        sta $dc00
        ldx #R_KEY+1
        ldy #0
        clc
        jsr PLOT                ; READY. below the results
        lda oldcr
        sta MMUCR
        cli
        rts

; ---- the VDC's RAM ----------------------------------------------------------

!zone vdctest
vdctest lda #0
        sta vdclive
        sta vstep
        lda vdiv
        sta vsub
        lda vk64
        beq +
        lda oldr28              ; 64K: the 64K chips' addressing
        ora #$10
        ldx #28
        jsr vreg
+       lda #0
        sta vpat
        jsr vdcpat
        lda stop
        bne .rest
        lda #$ff
        sta vpat
        jsr vdcpat
.rest   +at R_VPH, 5
        +text t_vrest
        lda oldr28
        ldx #28
        jsr vreg
        jsr DLCHR
        jsr vdcclear
        lda #1
        sta vdclive
        +at R_VPH, 5
        +text t_vdone
        lda #32
        ldx #R_VBAR
        jsr bar
        jsr flushall
        rts

; one pattern: byte = address lo ^ address hi ^ vpat, written to all of it,
; then read back
!zone vdcpat
vdcpat  lda #0
        sta vprn
        +at R_VPH, 5
        +text t_vwr
        lda vpat
        jsr phex8
        lda #0
        sta vadr
        sta vadr+1
        jsr vsetad
        ldx #0
.wp     txa
        eor vpat
        sta .wk+1
        ldy #0
.wb     tya
.wk     eor #0
        jsr vwait
        sta VDCD
        iny
        bne .wb
        jsr vprog
        lda stop
        bne .out
        inx
        cpx vpages
        bne .wp
!if FAULT {
        lda #$34                ; one bad byte at $1234
        sta vadr
        lda #$12
        sta vadr+1
        jsr vsetad
        lda #$27              ; $34 ^ $12 ^ 1
        eor vpat
        jsr vwait
        sta VDCD
}
        +at R_VPH, 5
        +text t_vrd
        lda vpat
        jsr phex8
        lda #0
        sta vadr
        sta vadr+1
        jsr vsetad
        ldx #0
.rp     txa
        eor vpat
        sta .rk+1
        ldy #0
.rb     jsr vwait
        lda VDCD
        sta vgot
        tya
.rk     eor #0
        cmp vgot
        bne .err
.rn     iny
        bne .rb
        jsr vprog
        lda stop
        bne .out
        inx
        cpx vpages
        bne .rp
.out    rts
.err    sta vexp
        stx vah
        sty val
        jsr vrecord
        jmp .rn

; a VDC error: count it, show the first and (a few a pattern) the last.
; Keeps X and Y.
!zone vrecord
vrecord stx .xs+1
        sty .ys+1
        lda vdcerr
        ora vdcerr+1
        php
        +sat16 vdcerr
        +sat16 vdcpe
        plp
        bne .notfst
        +at R_VFST, 5
        +text t_first
        jsr vshow
.notfst lda vprn
        cmp #8
        bcs .x
        inc vprn
        +at R_VLST, 5
        +text t_last
        jsr vshow
.x
.xs     ldx #0
.ys     ldy #0
        rts

vshow   lda #$24
        jsr putc
        lda vah
        jsr phex8
        lda val
        jsr phex8
        +text t_wrote
        lda vexp
        jsr phex8
        +text t_read
        lda vgot
        jmp phex8

; after each page: the bar, the time, the key. Keeps X and Y.
!zone vprog
vprog   stx .xs+1
        sty .ys+1
        dec vsub                ; the bar: a step every vdiv pages
        bne +
        lda vdiv
        sta vsub
        inc vstep
+       lda vstep
        lsr
        lsr
        lsr
        ldx #R_VBAR
        jsr bar
        jsr showtime
        jsr showcnt
        jsr chkkey
.xs     ldx #0
.ys     ldy #0
        rts

; how much RAM the VDC has: with R28 bit 4 set (the addressing for 64K
; chips), a tag in the first two bytes of every 256-byte page, written from
; page 255 down, read from page 0 up. 16K chips (4416) can't hold 256
; different pages, so a tag gets overwritten. 64K: vk64 = 1. R28 is put
; back to the kernal's value either way.
!zone vdcdetect
vdcdetect
        lda #1                  ; 16K: 64 pages, a bar step a page
        sta vdiv
        lda #$40
        sta vpages
        lda #0
        sta vk64
        ldx #28
        stx VDCA
        jsr vwait
        lda VDCD
        sta oldr28
        ora #$10
        jsr vreg
        lda #0
        sta vadr
        lda #$ff
        sta vadr+1
.w      jsr vsetad
        lda vadr+1
        jsr vwait
        sta VDCD
        eor #$ff
        jsr vwait
        sta VDCD
        dec vadr+1
        lda vadr+1
        cmp #$ff
        bne .w
        lda #0
        sta vadr+1
.r      jsr vsetad
        jsr vwait
        lda VDCD
        cmp vadr+1
        bne .put
        jsr vwait
        lda VDCD
        eor #$ff
        cmp vadr+1
        bne .put
        inc vadr+1
        bne .r
        lda #1                  ; 64K: 256 pages, a bar step every 4
        sta vk64
        lda #4
        sta vdiv
        lda #0
        sta vpages
.put    lda oldr28
        ldx #28
        jmp vreg

; ---- the VDC's registers ----------------------------------------------------

; wait until the VDC is ready (bit 7); gives up after ~2 ms and counts a
; timeout. Keeps A, X and Y.
!zone vwait
vwait   bit VDCA
        bmi .ok
        sty .ys+1
        ldy #0
.l      bit VDCA
        bmi .ys
        dey
        bne .l
        inc vdcto
        bne .ys
        inc vdcto+1
.ys     ldy #0
.ok     rts

vreg    stx VDCA                ; register X = A
        jsr vwait
        sta VDCD
        rts

vsetad  ldx #18                 ; the address = vadr, R31 selected
        lda vadr+1
        jsr vreg
        ldx #19
        lda vadr
        jsr vreg
        ldx #31
        stx VDCA
        rts

; the 80-column screen: spaces at $0000-$07FF, attributes at $0800-$0FFF
!zone vdcclear
vdcclear
        lda #0
        sta vadr
        sta vadr+1
        jsr vsetad
        ldx #8
        ldy #0
        lda #$20
.s      jsr vwait
        sta VDCD
        iny
        bne .s
        dex
        bne .s
        ldx #8
        lda #ATTR
.a      jsr vwait
        sta VDCD
        iny
        bne .a
        dex
        bne .a
        rts

; the 40-column screen's changed rows, copied to the 80-column screen
!zone flush
flushall
        ldx #24
        lda #1
.d      sta dirty,x
        dex
        bpl .d
flush   lda vdclive
        beq .out
        ldx #0
.r      lda dirty,x
        beq .nx
        lda #0
        sta dirty,x
        stx .xs+1
        lda v80lo,x
        sta vadr
        lda v80hi,x
        sta vadr+1
        lda rowlo,x
        sta .src+1
        lda rowhi,x
        sta .src+2
        jsr vsetad
        ldy #0
.src    lda SCREEN,y
        jsr vwait
        sta VDCD
        iny
        cpy #40
        bne .src
.xs     ldx #0
.nx     inx
        cpx #25
        bne .r
.out    rts

; ---- the REU ----------------------------------------------------------------

; the REU's registers answer? then its size: a marker in each bank's first
; bytes, written from bank 255 down, read from bank 0 up: the first bank
; that doesn't hold its own marker is where the banks wrap.
!zone reudetect
reudetect
        lda #$a5
        sta REU+2
        lda #$5a
        sta REU+3
        lda REU+2
        cmp #$a5
        bne .nojmp
        lda REU+3
        cmp #$5a
        beq .there
.nojmp  jmp .none
.there  lda #2
        sta dlen
        lda #0
        sta dlen+1
        sta dreu
        sta dreu+1
        lda #255
        sta bank
.wl     lda bank
        sta mk
        eor #$5a
        sta mk+1
        lda bank
        sta dreu+2
        lda #<mk
        sta dc64
        lda #>mk
        sta dc64+1
        lda #$90
        jsr dmago
        dec bank
        lda bank
        cmp #$ff
        bne .wl
        lda #0
        sta bank
.rl     lda bank
        sta dreu+2
        lda #<rd
        sta dc64
        lda #>rd
        sta dc64+1
        lda #$91
        jsr dmago
        lda rd
        cmp bank
        bne .end
        lda bank
        eor #$5a
        cmp rd+1
        bne .end
        inc bank
        bne .rl
        lda #255                ; all 256 banks: 16 MB
        sta lastbank
        lda #1
        sta reuok
        rts
.end    lda bank
        beq .bad
        sec
        sbc #1
        sta lastbank
        lda #1
        sta reuok
        rts
.bad    lda #2                  ; registers, but bank 0 doesn't keep data
        sta reuok
        rts
.none   lda #0
        sta reuok
        rts

; a DMA: command A ($90 stash, $91 fetch, $93 verify; executed at once),
; the C128's address dc64, the REU's dreu (3 bytes), dlen bytes.
; Returns the status (bit 6: the end, bit 5: verify failed).
dmago   ldx REU                 ; (clears an old status)
        ldx #0
        stx REU+9
        stx REU+10
        ldx dc64
        stx REU+2
        ldx dc64+1
        stx REU+3
        ldx dreu
        stx REU+4
        ldx dreu+1
        stx REU+5
        ldx dreu+2
        stx REU+6
        ldx dlen
        stx REU+7
        ldx dlen+1
        stx REU+8
        sta REU+1
        lda REU
        rts

; one round of the REU: inv = 0 (the pattern) or $FF (its complement)
!zone reupass
reupass jsr mkpat
        lda #<t_rwr             ; write every bank
        sta phase
        lda #>t_rwr
        sta phase+1
        lda #0
        sta bank
.wb     lda #0
        sta blk
.wk     jsr settags
        jsr blkset
        lda #<PAT
        sta dc64
        lda #>PAT
        sta dc64+1
        lda #$90
        jsr dmago
        inc blk
        lda blk
        cmp #8
        bne .wk
        jsr rprog
        lda stop
        beq .wgo
        rts
.wgo    lda bank
        cmp lastbank
        beq .wdone
        inc bank
        bne .wb
.wdone
!if FAULT {
        lda #0                  ; one bad byte: bank 1 (or 0), $4123
        ldx lastbank
        beq +
        lda #1
+       sta bank
        lda #2
        sta blk
        jsr settags
        lda PAT+$123
        eor #1
        sta mk
        lda #$23
        sta dreu
        lda #$41
        sta dreu+1
        lda bank
        sta dreu+2
        lda #1
        sta dlen
        lda #0
        sta dlen+1
        lda #<mk
        sta dc64
        lda #>mk
        sta dc64+1
        lda #$90
        jsr dmago
}
        lda #<t_rvf             ; verify every bank (the REU compares)
        sta phase
        lda #>t_rvf
        sta phase+1
        lda #0
        sta bank
.vb     lda #0
        sta blk
.vk     jsr settags
        jsr blkset
        lda #<PAT
        sta dc64
        lda #>PAT
        sta dc64+1
        lda #$93
        jsr dmago
        and #$60
        cmp #$40
        beq .vok
        jsr fetchcmp            ; find the bad bytes
        lda blkerr
        ora blkerr+1
        bne .vok
        +sat16 vfyodd           ; the compare failed, the bytes are fine
.vok    inc blk
        lda blk
        cmp #8
        bne .vk
        jsr rprog
        lda stop
        bne .out
        lda bank
        cmp lastbank
        beq .vdone
        inc bank
        bne .vb
.vdone  lda #<t_rft             ; one bank fetched and compared by the CPU
        sta phase
        lda #>t_rft
        sta phase+1
        lda fbank
        sta bank
        lda #0
        sta blk
.fk     jsr settags
        jsr fetchcmp
        inc blk
        lda blk
        cmp #8
        bne .fk
        jsr rprog
        lda fbank
        cmp lastbank
        bne +
        lda #$ff
        sta fbank
+       inc fbank
.out    rts

; the REU's address of block blk in bank, 8K long
blkset  lda #0
        sta dreu
        lda blk
        asl
        asl
        asl
        asl
        asl
        sta dreu+1
        lda bank
        sta dreu+2
        lda #0
        sta dlen
        lda #$20
        sta dlen+1
        rts

; fetch the block into FET and compare it with PAT
fetchcmp
        jsr blkset
        lda #<FET
        sta dc64
        lda #>FET
        sta dc64+1
        lda #$91
        jsr dmago
        jmp cmp8k

; PAT: byte = offset lo ^ offset hi ^ seed (the seed changes every pass)
!zone mkpat
mkpat   lda pass
        asl
        asl
        asl
        eor pass
        eor inv
        sta seed
        ldx #0
.pg     txa
        eor seed
        sta .k+1
        txa
        clc
        adc #>PAT
        sta .st+2
        ldy #0
.b      tya
.k      eor #0
.st     sta PAT,y
        iny
        bne .b
        inx
        cpx #32
        bne .pg
        rts

; each of PAT's pages starts with the bank and its page in the bank
!zone settags
settags lda #<PAT
        sta tp
        lda #>PAT
        sta tp+1
        lda blk
        asl
        asl
        asl
        asl
        asl
        sta pgno
        ldx #32
.p      ldy #0
        lda bank
        eor inv
        sta (tp),y
        iny
        lda pgno
        eor inv
        sta (tp),y
        inc pgno
        inc tp+1
        dex
        bne .p
        rts

; FET against PAT, 8K: every bad byte counted
!zone cmp8k
cmp8k   lda #0
        sta blkerr
        sta blkerr+1
        ldx #0
.pg     txa
        clc
        adc #>FET
        sta .f+2
        txa
        clc
        adc #>PAT
        sta .p+2
        sta .p2+2
        ldy #0
.f      lda FET,y
.p      cmp PAT,y
        bne .e
.n      iny
        bne .f
        inx
        cpx #32
        bne .pg
        rts
.e      sta rgot
.p2     lda PAT,y
        sta rexp
        stx rpg
        sty rlo
        jsr rrecord
        jmp .n

; an REU error: count it, show the first and (a few a block) the last.
; Keeps X and Y.
!zone rrecord
rrecord stx .xs+1
        sty .ys+1
        lda reuerr
        ora reuerr+1
        php
        +sat16 reuerr
        +sat16 reupe
        +sat16 blkerr
        plp
        bne .notfst
        +at R_RFST, 5
        +text t_first
        jsr rshow
.notfst lda blkerr+1
        bne .x
        lda blkerr
        cmp #4
        bcs .x
        +at R_RLST, 5
        +text t_last
        jsr rshow
.x
.xs     ldx #0
.ys     ldy #0
        rts

rshow   lda #$24
        jsr putc
        lda bank
        jsr phex8
        lda #$3a
        jsr putc
        lda blk
        asl
        asl
        asl
        asl
        asl
        clc
        adc rpg
        jsr phex8
        lda rlo
        jsr phex8
        +text t_wrote
        lda rexp
        jsr phex8
        +text t_read
        lda rgot
        jmp phex8

; after each bank: what, where, the bar, the time, the counts, the key
!zone rprog
rprog   +at R_RPH, 5
        lda phase
        ldy phase+1
        jsr prs
        +text t_bank
        lda bank
        sta n16
        lda #0
        sta n16+1
        jsr pdec3
        lda #$2f
        jsr putc
        jsr nbanks
        jsr pdec3
        jsr nbanks              ; the bar: (bank + 1) * 32 / banks
        lda n16
        sta d16
        lda n16+1
        sta d16+1
        lda bank
        clc
        adc #1
        sta n16
        lda #0
        adc #0
        sta n16+1
        ldx #5
.sh     asl n16
        rol n16+1
        dex
        bne .sh
        jsr div16
        lda n16
        ldx #R_RBAR
        jsr bar
        jsr showtime
        jsr showcnt
        jsr chkkey
        lda bank                ; the 80 columns every 8 banks (polled
        and #7                  ; VDC writes are slow) and at the end
        cmp #7
        beq .fl
        lda bank
        cmp lastbank
        beq .fl
        rts
.fl     jmp flush

nbanks  lda lastbank            ; n16 = the banks (1-256)
        clc
        adc #1
        sta n16
        lda #0
        adc #0
        sta n16+1
        rts

; ---- the screen ---------------------------------------------------------------

!zone ui
drawui  +at 0, 0
        +text t_title
        +at R_PASS, 0
        +text t_pass
        +at R_VDC, 0
        +text t_vdc
        +at R_VDC, 5
        lda vk64
        beq +
        +text t_v64
        jmp ++
+       +text t_v16
++
        +at R_REU, 0
        +text t_reu
        +at R_VFST, 0
        +text t_vfst
        +at R_RFST, 0
        +text t_rfst
        +at R_ODD, 0
        +text t_odd
        +at R_TMO, 0
        +text t_tmo
        +at R_BAD, 0
        +text t_bad
        +at 20, 0
        +text t_note
        +at R_KEY, 0
        +text t_key
        lda #0
        ldx #R_VBAR
        jsr bar
        lda #0
        ldx #R_RBAR
        jmp bar

!zone
showreu +at R_REU, 5
        lda reuok
        beq .no
        cmp #2
        beq .bad
        jsr nbanks              ; KB = banks * 64
        ldx #6
.k      asl n16
        rol n16+1
        dex
        bne .k
        jsr pdec16
        lda #$0b
        jmp putc
.no     +text t_rno
        rts
.bad    +text t_rbad
        rts

!zone
showcnt +at R_PASS, 5
        +num16 pass
        +at R_VDC, 27
        +num16 vdcerr
        lda reuok
        cmp #1
        bne .t
        +at R_REU, 27
        +num16 reuerr
        +at R_ODD, 27
        +num16 vfyodd
.t      +at R_TMO, 27
        +num16 vdcto
        +at R_BAD, 27
        +num16 badpass
        rts

; the end of a pass: its result
!zone
showres +at R_RES, 0
        +text t_res
        lda vdcpe
        ora vdcpe+1
        beq +
        +text t_fail
        jmp ++
+
        +text t_ok
++      lda reuok
        cmp #1
        bne +++
        +text t_reu2
        lda reupe
        ora reupe+1
        beq +
        +text t_fail
        jmp ++
+
        +text t_ok
++
+++     lda vdcpe
        ora vdcpe+1
        ora reupe
        ora reupe+1
        beq +
        +sat16 badpass
+       jsr showcnt
        jmp flush

; a bar of 32 at row X, column 4: A filled
!zone
bar     sta bfill
        ldy #4
        jsr goto
        ldx #0
.b      lda #$a0
        cpx bfill
        bcc .p
        lda #$2e
.p      jsr putc
        inx
        cpx #32
        bne .b
        rts

; the time since the start (CIA 1's TOD clock)
!zone
showtime
        +at R_PASS, 25
        lda $dc0b               ; (reading the hours holds the rest)
        and #$1f
        jsr phex8
        lda #$3a
        jsr putc
        lda $dc0a
        jsr phex8
        lda #$3a
        jsr putc
        lda $dc09
        jsr phex8
        lda $dc08               ; (lets it go)
        rts

!zone
todstart
        lda $dc0f
        and #$7f                ; writes set the clock, not the alarm
        sta $dc0f
        lda $dc0e
        ora #$80                ; 50 Hz
        sta $dc0e
        lda #0
        sta $dc0b
        sta $dc0a
        sta $dc09
        sta $dc08               ; (starts it)
        rts

; a key held? then stop at the next safe place
!zone
chkkey  lda #0
        sta $dc00
        lda $dc01
        cmp #$ff
        beq +
        lda #1
        sta stop
+       rts

!zone
clrvic  ldx #0
-       lda #$20
        sta SCREEN,x
        sta SCREEN+$100,x
        sta SCREEN+$200,x
        sta SCREEN+$2e8,x
        lda #1
        sta COLRAM,x
        sta COLRAM+$100,x
        sta COLRAM+$200,x
        sta COLRAM+$2e8,x
        inx
        bne -
        rts

; the cursor to row X, column Y (the row is copied to the 80 columns later)
!zone
goto    lda #1
        sta dirty,x
        tya
        clc
        adc rowlo,x
        sta cur
        lda rowhi,x
        adc #0
        sta cur+1
        rts

; a screen code at the cursor. Keeps X and Y.
!zone
putc    sty .ys+1
        ldy #0
        sta (cur),y
        inc cur
        bne .ys
        inc cur+1
.ys     ldy #0
        rts

; the text at A (low), Y (high), up to $FF
!zone
prs     sta sp
        sty sp+1
        ldy #0
.l      lda (sp),y
        cmp #$ff
        beq .x
        jsr putc
        iny
        bne .l
.x      rts

!zone
phex8   pha
        lsr
        lsr
        lsr
        lsr
        jsr .nib
        pla
        and #$0f
.nib    cmp #10
        bcc .dig
        sbc #9                  ; A-F: screen codes 1-6
        jmp putc
.dig    ora #$30
        jmp putc

; n16 in decimal: 5 digits (pdec16) or the last 3 (pdec3)
!zone
pdec16  ldx #4
        bne .dg
pdec3   ldx #2
.dg     ldy #$30
.sb     lda n16
        sec
        sbc pow10l,x
        sta t0
        lda n16+1
        sbc pow10h,x
        bcc .pr
        sta n16+1
        lda t0
        sta n16
        iny
        bne .sb
.pr     tya
        jsr putc
        dex
        bpl .dg
        rts
pow10l  !byte <1, <10, <100, <1000, <10000
pow10h  !byte >1, >10, >100, >1000, >10000

; n16 = n16 / d16
!zone
div16   lda #0
        sta rem
        sta rem+1
        ldx #16
.l      asl n16
        rol n16+1
        rol rem
        rol rem+1
        lda rem
        sec
        sbc d16
        tay
        lda rem+1
        sbc d16+1
        bcc .n
        sta rem+1
        sty rem
        inc n16
.n      dex
        bne .l
        rts

rowlo   !for r, 0, 24 { !byte <(SCREEN + r * 40) }
rowhi   !for r, 0, 24 { !byte >(SCREEN + r * 40) }
v80lo   !for r, 0, 24 { !byte <(r * 80) }
v80hi   !for r, 0, 24 { !byte >(r * 80) }

!ct scr {
t_title !text "c128 vdc + reu test", $ff
t_pass  !text "pass 00000          time 00:00:00", $ff
t_vdc   !text "vdc                 errors 00000", $ff
t_v16   !text "16k", $ff
t_v64   !text "64k", $ff
t_reu   !text "reu                 errors 00000", $ff
t_vfst  !text "vdc", $ff
t_rfst  !text "reu", $ff
t_odd   !text "reu compare failed,data ok 00000", $ff
t_tmo   !text "vdc not ready (2 ms)       00000", $ff
t_bad   !text "passes with errors         00000", $ff
t_note  !text "80 columns: garbage during the vdc test", $ff
t_key   !text "hold a key to stop", $ff
t_stop  !text "stopped. run to start again.           ", $ff
t_vwr   !text "write   pattern $", $ff
t_vrd   !text "read    pattern $", $ff
t_vrest !text "restoring 80 columns  ", $ff
t_vdone !text "ok so far             ", $ff
t_rwr   !text "write  ", $ff
t_rvf   !text "verify ", $ff
t_rft   !text "fetch  ", $ff
t_bank  !text " bank ", $ff
t_first !text "first ", $ff
t_last  !text "last  ", $ff
t_wrote !text " wrote ", $ff
t_read  !text " read ", $ff
t_rno   !text "not found", $ff
t_rbad  !text "bank 0 fails", $ff
t_res   !text "last pass: vdc ", $ff
t_reu2  !text " reu ", $ff
t_ok    !text "ok  ", $ff
t_fail  !text "fail", $ff
}

; ---- variables (cleared at the start) --------------------------------------
oldcr   !byte 0
oldr28  !byte 0                 ; the VDC's R28 as the kernal left it
vk64    !byte 0                 ; set by vdcdetect: 1 = 64K
vdiv    !byte 0
vpages  !byte 0                 ; pages to test: $40 (16K) or 0 (256)
vars
pass    !word 0
stop    !byte 0
vdclive !byte 0
dirty   !fill 25, 0
vadr    !word 0
vpat    !byte 0
vstep   !byte 0
vsub    !byte 0
vprn    !byte 0
vgot    !byte 0
vexp    !byte 0
vah     !byte 0
val     !byte 0
vdcerr  !word 0
vdcpe   !word 0
vdcto   !word 0
reuok   !byte 0
lastbank !byte 0
bank    !byte 0
blk     !byte 0
fbank   !byte 0
inv     !byte 0
seed    !byte 0
pgno    !byte 0
phase   !word 0
dc64    !word 0
dreu    !byte 0, 0, 0
dlen    !word 0
mk      !byte 0, 0
rd      !byte 0, 0
reuerr  !word 0
reupe   !word 0
blkerr  !word 0
vfyodd  !word 0
badpass !word 0
rgot    !byte 0
rexp    !byte 0
rpg     !byte 0
rlo     !byte 0
n16     !word 0
d16     !word 0
rem     !word 0
t0      !byte 0
bfill   !byte 0
vars_end

!if * > PAT { !error "the program runs into the buffers" }
