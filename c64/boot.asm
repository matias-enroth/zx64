; zx64 - 6510 side: the boot file. LOAD "ZX81",8 and RUN.
;
; Sets up the VIC for the ZX81 picture, then hands the bus to the Z80,
; which starts the ZX81 ROM. From then on the 6510 only wakes up when the
; Z80 hands the bus back with a command in the mailbox (LOAD, SAVE, the
; monitor's disk commands, the ROM again), does the disk I/O through the
; kernal and hands the bus back again.
;
; tools/build.py puts this at $0801 and the patched ROM and the Z80 code
; behind it, so the Z80 image lands at $1000-$3xxx.

!cpu 6510

MB      = $3f00         ; mailbox (Z80 $2F00): +0 command, +1 status, +2 length, +3 name
SPZ80   = MB+$20        ; the Z80's SP as it handed over: its stack is from there up
ZXROM   = $1000         ; Z80 $0000
CHARSRC = ZXROM+$1e00   ; the ZX81 font in the ROM
DFZ80   = $5009         ; Z80 $4009, where a .P file goes
ELINE   = $5014         ; Z80 $4014, E_LINE: a .P file ends there
PTR     = $fb

CMD_LOAD = 1
CMD_SAVE = 2
CMD_PRG  = 3            ; a PRG file to its own load address (the monitor, L)
CMD_DIR  = 4            ; the monitor's $: open the directory,
CMD_DIRL = 5            ; its next line (to MB+$80),
CMD_DIRC = 6            ; close it early
CMD_WRITE = 7           ; the monitor's W: memory to a PRG file
CMD_DCMD = 8            ; the monitor's @: a DOS command, the drive's status to MB+$80
CMD_ROM  = 9            ; F7 or F3: the ZX81 ROM again, from the boot file
ST_OK    = 0
ST_ERR   = 1            ; not found, or the drive reported an error
ST_BIG   = 2            ; the program would run into the Z80's stack

SETNAM  = $ffbd
SETLFS  = $ffba
OPEN    = $ffc0
CLOSE   = $ffc3
CHKIN   = $ffc6
CHKOUT  = $ffc9
CLRCHN  = $ffcc
CHRIN   = $ffcf
CHROUT  = $ffd2
READST  = $ffb7
CINT    = $ff81
IOINIT  = $ff84
RESTOR  = $ff8a

*= $0801
        !byte $0b,$08,$0a,$00,$9e,$32,$30,$36,$31,$00,$00,$00  ; 10 SYS2061

start:  sei
        lda $ba                 ; the drive the boot file came from
        bne +
        lda #8
+       sta dev
        lda #<nmi
        sta $0318
        sta $fffa
        lda #>nmi
        sta $0319
        sta $fffb
        lda #$7f                ; silence the CIA interrupts
        sta $dc0d
        sta $dd0d
        lda $dc0d
        lda $dd0d

        ldx #0                  ; charset at $E800 (RAM under the kernal,
cs:     lda CHARSRC,x           ; which the VIC sees): 0-63 the ZX81 font,
        sta $e800,x             ; 128-191 inverse, 64-127 blank, 192-255
        eor #$ff                ; solid
        sta $ec00,x
        lda CHARSRC+$100,x
        sta $e900,x
        eor #$ff
        sta $ed00,x
        lda #0
        sta $ea00,x
        sta $eb00,x
        lda #$ff
        sta $ee00,x
        sta $ef00,x
        inx
        bne cs

        lda #0                  ; ZX81 space is 0; colour RAM black
cl:     sta $e000,x
        sta $e100,x
        sta $e200,x
        sta $e300,x
        sta $d800,x
        sta $d900,x
        sta $da00,x
        sta $db00,x
        inx
        bne cl
        sta $4003               ; a zx64mon from before a reset (RAM keeps
                                ; it): its "ZM" gone, so F5 loads it again
                                ; from this disk, with a clear screen

        lda #1                  ; white border and background
        sta $d020
        sta $d021
        lda $dd02               ; VIC bank 3 ($C000-$FFFF)
        ora #3
        sta $dd02
        lda $dd00
        and #$fc
        sta $dd00
        lda #$8a                ; screen $E000, chars $E800: $C000-$CFFF
        sta $d018               ; is left for the ZX81's 32K
        lda #$17                ; 24 rows, yscroll 7: rows 0-23 exactly fill
        sta $d011               ; the 192-line window
        lda #250
        sta $d012
        lda #$ff
        sta $d019
        lda #1
        sta $d01a               ; raster IRQ -> Z80 /INT, where it is wired
        lda #0
        sta MB
        sta MB+1
        lda #$35                ; I/O on, ROMs off
        sta $01

        lda #$a5                ; Z80 $4000 (ERR_NR): the ROM's start
        sta $5000               ; writes over it
        lda #0
        sta $de00               ; start the Z80; it hands back with a command
        nop
        lda $5000               ; back at once, $4000 as it was: no Z80
        cmp #$a5
        bne cmd
        jmp noz80

loop:   lda #0
        sta $de00               ; run the Z80 until it hands back
        nop                     ; required after the switch (Commodore's
                                ; CP/M guide, 6.6.1)
cmd:    lda MB                  ; take the command, so a stray write to
        ldx #0                  ; $DExx (Z80 $CExx) finds nothing to redo
        stx MB
        cmp #CMD_LOAD
        beq doload
        cmp #CMD_SAVE
        bne +
        jmp dosave
+       jmp more                ; the monitor's, and the ROM again (see $0C00)

done:   lda #0
        sta ind                 ; no progress shown (the monitor's W uses sloop)
        lda #$35
        sta $01
        jmp loop

; ------------------------------------------------------------ LOAD
; Like the ROM's LOAD, read from $4009 up to E_LINE (which arrives with
; the system variables) and stop there, whatever follows in the file.
; Refused if the program wouldn't fit: report 4, nothing changed.
doload: lda #$36                ; kernal and I/O, not BASIC: RAM at
        sta $01                 ; $A000-$BFFF holds a 32K ZX81's
        jsr tryopen
        bcc got
        ldx MB+2                ; not found: try NAME.P
        cpx #15
        bcs notfound
        lda #'.'
        sta MB+3,x
        lda #'P'
        sta MB+4,x
        inx
        inx
        stx MB+2
        jsr tryopen
        bcc got
notfound:
        lda #ST_ERR
        sta MB+1
        jmp done

got:
        ldx #0                  ; the first 13 bytes, $4009-$4015, to hdr:
        lda first               ; E_LINE is the last two
hloop:  sta hdr,x
        inx
        cpx #13
        beq hdone
        lda st
        and #$c3                ; ended, or a read error, already
        bne rerr
        jsr CHRIN
        pha
        jsr READST
        sta st
        pla
        jmp hloop
hdone:  lda hdr+11              ; E_LINE: does the program fit? Checked
        ldx hdr+12              ; before anything is written, so a refused
        jsr setend              ; load leaves the ZX81 as it was
        bcs rbig
        ldx #12
-       lda hdr,x
        sta DFZ80,x
        dex
        bpl -
        lda #<(DFZ80+13)
        sta PTR
        lda #>(DFZ80+13)
        sta PTR+1
        jsr pinit               ; the top row shows how far it is
rloop:  lda PTR                 ; at E_LINE: done, whatever follows
        cmp eend
        lda PTR+1
        sbc eend+1
        bcs rok
        lda st
        and #$c3                ; the file ended before E_LINE, or an error
        bne rerr
        jsr CHRIN
        pha
        jsr READST
        sta st
        pla
        ldy #0
        sta (PTR),y
        jsr pstep
        inc PTR
        bne rloop
        inc PTR+1
        jmp rloop

rok:    lda #ST_OK
        beq rend
rbig:   lda #ST_BIG
        bne rend
rerr:   lda #ST_ERR
rend:   sta MB+1
        jsr CLRCHN
        lda #2
        jsr CLOSE
        jmp done

; A/X = E_LINE -> eend, as a C64 address. C=1 if E_LINE makes no sense
; (not past the system variables) or the program would run into the
; Z80's stack, which is in use from SPZ80 up while the 6510 loads.
setend: sta eend
        txa
        clc
        adc #$10
        sta eend+1
        cmp #$50
        bcc ++
        bne +
        lda eend
        cmp #$80
        bcc ++
+       lda SPZ80+1             ; SP as a C64 address, minus eend:
        clc                     ; carry set if eend <= SP
        adc #$10
        sta sph
        lda SPZ80
        cmp eend
        lda sph
        sbc eend+1
        bcc ++
        clc
        rts
++      sec
        rts

; Open the name in the mailbox and read the first byte.
; C=0: open, the byte is in first. C=1: not found (file closed again).
tryopen:
        lda MB+2
        ldx #<(MB+3)
        ldy #>(MB+3)
        jsr SETNAM
        lda #2
        ldx dev
        ldy #0                  ; SA 0: the raw bytes, no load address
        jsr SETLFS
        jsr OPEN
        bcs tofail
        ldx #2
        jsr CHKIN
        bcs tofail
        jsr CHRIN
        sta first
        jsr READST
        sta st
        and #$83
        bne tofail
        clc
        rts
tofail:
        jsr CLRCHN
        lda #2
        jsr CLOSE
        sec
        rts

; ------------------------------------------------------------ SAVE
; Write $4009 up to E_LINE as "@0:NAME" (replacing an old one), then ask
; the drive whether it went well: a full or write-protected disk shows up
; only on the error channel.
dosave: lda #$36
        sta $01
        jsr wopen               ; "@0:NAME,P,W" (see $0C00)
        bcs sfail
        lda #<DFZ80
        sta PTR
        lda #>DFZ80
        sta PTR+1
        lda ELINE
        ldx ELINE+1
        jsr setend
        jsr pinit
sloop:  lda PTR
        cmp eend
        lda PTR+1
        sbc eend+1
        bcs sdone
        ldy #0
        lda (PTR),y
        jsr CHROUT
        jsr pstep
        inc PTR
        bne sloop
        inc PTR+1
        jmp sloop
sdone:  jsr CLRCHN
        lda #2
        jsr CLOSE
        jsr drvok
        bcs sfail2
        lda #ST_OK
        sta MB+1
        jmp done
sfail:  jsr CLRCHN
        lda #2
        jsr CLOSE
sfail2: lda #ST_ERR
        sta MB+1
        jmp done

; Read the drive's error channel. C=0 if it says "00", C=1 otherwise.
drvok:  lda #0
        jsr SETNAM
        lda #15
        ldx dev
        ldy #15
        jsr SETLFS
        jsr OPEN
        bcs dbad
        ldx #15
        jsr CHKIN
        bcs dbad
        jsr CHRIN
        cmp #'0'
        bne dbad
        jsr CHRIN
        cmp #'0'
        bne dbad
        jsr CLRCHN
        lda #15
        jsr CLOSE
        clc
        rts
dbad:   jsr CLRCHN
        lda #15
        jsr CLOSE
        sec
        rts

nmi:    rti

; LOAD and SAVE show how far they are on the top row of the ZX81's
; picture, which the Z80 has set up: " LOADING NAME", an empty bar of 8
; cells at BAR, the spinner's cell at SPIN (the row inverse, the bar
; white). The bar fills black from the left, a half cell, 1/16, at a
; time, by a running sum (16 for each byte, the total taken off each
; time it is reached: no dividing); the spinner, zedwire MUSIC's, turns
; every 128 bytes. pinit: from PTR to eend; pzero: tot as it is; pstep:
; a byte more (keeps Y).
BAR     = $e01a                 ; Z80 $D01A: row 0, column 22
SPIN    = $e023                 ; column 31
pinit:  lda eend
        sec
        sbc PTR
        sta tot
        lda eend+1
        sbc PTR+1
        sta tot+1
pzero:  lda tot
        ora tot+1
        bne +
        inc tot                 ; nothing to do: no dividing by 0
+       lda #0
        sta acc
        sta acc+1
        sta units
        sta bcnt
        sta spn
        lda #1
        sta ind
        rts
pstep:  lda ind
        beq pdone
        lda acc
        clc
        adc #16
        sta acc
        bcc pchk
        inc acc+1
pchk:   lda acc                 ; another 1/16 reached?
        cmp tot
        lda acc+1
        sbc tot+1
        bcc pspn
        lda acc
        sbc tot
        sta acc
        lda acc+1
        sbc tot+1
        sta acc+1
        inc units
        lda units
        cmp #17
        bcs pchk
        sec                     ; cell (units-1)/2: a half if units is odd,
        sbc #1                  ; then full
        lsr
        tax
        lda #$05                ; ZX81 5: the left half black
        bcc +
        lda #$80                ; an inverse space: all black
+       sta BAR,x
        jmp pchk
pspn:   inc bcnt
        lda bcnt
        and #$7f
        bne pdone
        ldx spn
        inx
        txa
        and #7
        sta spn
        tax
        lda spglyph,x
        sta SPIN
pdone:  rts
spglyph:                        ; zedwire's, inverse: a quarter, half, three
        !byte $81,$83,$04,$00,$01,$03,$84,$80   ; quarters, full, and back

pw:     !text ",P,W"
dev:    !byte 8
first:  !byte 0
st:     !byte 0
eend:   !word 0
sph:    !byte 0
hdr:    !fill 13,0
sname:  !fill 24,0
tot:    !word 0                 ; the progress: bytes in all, the running
acc:    !word 0                 ; sum, sixteenths shown, bytes for the
units:  !byte 0                 ; spinner, its step, and whether to show
bcnt:   !byte 0
spn:    !byte 0
ind:    !byte 0

; No CP/M cartridge (the write to $DE00 did nothing): back to BASIC.
noz80:  lda #$37
        sta $01
        jsr IOINIT
        jsr RESTOR
        jsr CINT
        ldx #0
-       lda noztxt,x
        beq +
        jsr CHROUT
        inx
        bne -
+       cli
        jmp ($a002)             ; BASIC's warm start: READY.
noztxt: !pet 13, "no z80: zx64 needs the c64 cp/m", 13, "cartridge.", 13, 0

!if * > $0bfe { !error "6510 code overflows into $0BFE, where the Z80 puts a keyboard row (IN A,($FE), A = $FB)" }

; The Z80 puts keyboard rows at $0BFE, $0DFE and $0EFE (see mirror in
; z80/zx64.asm): more 6510 code goes between them.
*= $0c00

; ------------------------------------------------------------ the monitor's
; Commands 3-8, for zx64mon (z80/mon.asm): loading a file to its own
; address, the directory a line at a time, writing memory to a file, DOS
; commands and the drive's status; and 9, the ROM again (dorom). The mailbox: +2 the name's
; length, +3 the name; +$22 a start (C64), +$24 an end (C64, the byte
; after), +$26 1: load at +$22, not the file's own address; lines come
; back at +$80, ended by 0.
more:   sec
        sbc #CMD_PRG
        cmp #7
        bcs +
        asl
        tax
        lda mtab+1,x
        pha
        lda mtab,x
        pha
        rts
+       jmp loop
mtab:   !word doprg-1, dodir-1, dodirl-1, dodirc-1, dowrite-1, docmd-1, dorom-1

; The ZX81 ROM again, when a program has written over it (F7 or F3): the boot
; file named in the mailbox, its bytes for C64 $1000-$2FFF, skipping the
; load address and the loader before them. The bar across all of it.
dorom:  lda #$36
        sta $01
        jsr tryopen             ; (it reads the load address's first byte)
        bcc +
        jmp notfound
+       lda #<$2800             ; $0800 to skip, $2000 to keep
        sta tot
        lda #>$2800
        sta tot+1
        jsr pzero
        lda #0                  ; PTR counts the $0800 down
        sta PTR
        lda #>$0800
        sta PTR+1
rskip:  jsr CHRIN
        jsr pstep
        lda PTR
        bne +
        dec PTR+1
+       dec PTR
        lda PTR
        ora PTR+1
        bne rskip
        lda #$10                ; PTR = $1000 (its low byte is 0)
        sta PTR+1
rrom:   jsr CHRIN
        ldy #0
        sta (PTR),y
        jsr pstep
        inc PTR
        bne rrom
        inc PTR+1
        lda PTR+1
        cmp #$30
        bne rrom
        jsr READST
        and #$83                ; a time-out or no device: it may be wrong
        beq +
        jmp rerr
+       jmp rok

; A PRG file, the name in the mailbox, to the C64 address its first two
; bytes give (the monitor itself: zx64mon to $4000, zx64mon2 to $F000),
; or to +$22. Never into the 6510's page ($0000-$0FFF) or the I/O chips
; ($D000-$DFFF): report D. +$22 and +$24 say where it went.
doprg:  lda #$36
        sta $01
        jsr tryopen
        bcc +
        jmp notfound
+       lda first
        sta PTR
        jsr CHRIN
        sta PTR+1
        jsr READST
        sta st
        lda MB+$26
        beq +
        lda MB+$22
        sta PTR
        lda MB+$23
        sta PTR+1
+       lda PTR
        sta MB+$22
        lda PTR+1
        sta MB+$23
        lda MB+$27              ; the monitor's own files: the top row's bar,
        beq ploop               ; across both (1: the first, its total at
        cmp #2                  ; +$28; 2: the second, going on)
        beq +
        lda MB+$28
        sta tot
        lda MB+$29
        sta tot+1
        jsr pzero
+       lda #1
        sta ind
ploop:  lda st
        and #$c3                ; ended, or an error
        bne pend
        jsr CHRIN
        pha
        jsr READST
        sta st
        lda PTR+1
        cmp #$10
        bcc pbad
        and #$f0
        cmp #$d0
        beq pbad
        pla
        ldy #0
        sta (PTR),y
        jsr pstep
        inc PTR
        bne ploop
        inc PTR+1
        jmp ploop
pbad:   pla
        jmp rerr
pend:   lda PTR
        sta MB+$24
        lda PTR+1
        sta MB+$25
        lda st
        and #$83                ; an error, not just the end
        beq +
        jmp rerr
+       jmp rok

; "@0:" + the name + ",P,W", opened as 2 for writing. C=1: it failed.
wopen:  ldx #0
        lda #'@'
        sta sname,x
        inx
        lda #'0'
        sta sname,x
        inx
        lda #':'
        sta sname,x
        inx
        ldy #0
-       lda MB+3,y
        sta sname,x
        inx
        iny
        cpy MB+2
        bne -
        ldy #0
-       lda pw,y
        sta sname,x
        inx
        iny
        cpy #4
        bne -
        txa
        ldx #<sname
        ldy #>sname
        jsr SETNAM
        lda #2
        ldx dev
        ldy #2
        jsr SETLFS
        jsr OPEN
        bcs +
        ldx #2
        jsr CHKOUT
+       rts

; Memory from +$22 up to +$24 as a PRG file: +$22 is its load address.
dowrite:
        lda #$36
        sta $01
        jsr wopen
        bcc +
        jmp sfail
+       lda MB+$22
        sta PTR
        jsr CHROUT
        lda MB+$23
        sta PTR+1
        jsr CHROUT
        lda MB+$24
        sta eend
        lda MB+$25
        sta eend+1
        jmp sloop               ; as SAVE: the bytes, then the drive's word

!if * > $0dfe { !error "6510 code overflows into $0DFE, where the Z80 puts a keyboard row (IN A,($FE), A = $FD)" }

*= $0e00

; The directory, "$" opened as a BASIC program: its lines one at a time,
; the blocks (2 bytes) then the text, at +$80. ST_ERR: no more (closed).
dodir:  lda #$36
        sta $01
        jsr tryopen
        bcc +
        jmp notfound
+       jsr CHRIN               ; the load address' high byte
        jsr CLRCHN
        lda #ST_OK
        sta MB+1
        jmp done
dodirl: lda #$36
        sta $01
        ldx #2
        jsr CHKIN
        bcs dlend
        jsr rdb                 ; the link: 0 0 at the end
        sta first
        jsr rdb
        ora first
        beq dlend
        jsr rdb
        sta MB+$80
        jsr rdb
        sta MB+$81
        ldy #2
-       jsr rdb
        beq +
        sta MB+$80,y
        iny
        cpy #66
        bcc -
+       lda #0
        sta MB+$80,y
        jsr CLRCHN
        lda #ST_OK
        sta MB+1
        jmp done
dlend:  jsr CLRCHN
dodirc: lda #2
        jsr CLOSE
        jsr CLRCHN
        lda #ST_ERR
        sta MB+1
        jmp done

rdb:    jsr CHRIN               ; a byte, ST kept in st; flags as A
        pha
        jsr READST
        sta st
        pla
        rts

!if * > $0efe { !error "6510 code overflows into $0EFE, where the Z80 puts a keyboard row (IN A,($FE), A = $FE)" }

*= $0f00

; A DOS command (+2, +3; none: just the status), then the drive's status
; line at +$80.
docmd:  lda #$36
        sta $01
        lda MB+2
        ldx #<(MB+3)
        ldy #>(MB+3)
        jsr SETNAM
        lda #15
        ldx dev
        ldy #15
        jsr SETLFS
        jsr OPEN
        bcs dcbad
        ldx #15
        jsr CHKIN
        bcs dcbad
        ldy #0
-       jsr rdb
        cmp #13
        beq +
        sta MB+$80,y
        iny
        lda st
        and #$42                ; the end, or nothing there
        bne +
        cpy #60
        bcc -
+       lda #0
        sta MB+$80,y
        jsr CLRCHN
        lda #15
        jsr CLOSE
        lda #ST_OK
        sta MB+1
        jmp done
dcbad:  jsr CLRCHN
        lda #15
        jsr CLOSE
        lda #ST_ERR
        sta MB+1
        jmp done

!if * > $1000 { !error "6510 code overflows into the Z80 image at $1000" }
