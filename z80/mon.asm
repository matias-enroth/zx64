; zx64mon - the machine code monitor, on F5. zx64 loads it from the disk
; the first time F5 is pressed, in two parts: zx64mon to Z80 $3000 (C64
; $4000), zx64mon2 to $E000 (C64 $F000, see part 2); and enters it
; with the registers of whatever was running on the stack (mon_irq,
; mon_call in z80/zx64.asm). It has a screen of its own: VIC bank 0, 40
; columns by 25 rows at C64 $0400, in the C64's own characters; the
; ZX81's picture is left as it is, and comes back on leaving.
;
; The commands are Supermon's, in hex, for the Z80:
;   M s [e]        memory, 8 bytes a line with their ZX81 characters
;   D s [e]        disassemble (D or M alone: on from where it stopped)
;   B [a]          a breakpoint at a, or off again if there is one; the list
;   S              one step: the instruction at PC, then back here
;   A a text       assemble at a; ".A next" waits for the next (see cmd_a)
;   $              the directory
;   L "NAME" [a]   load a program, as LOAD; a file to a
;   W "NAME" [s e] save the program, as SAVE; memory to a file
;   @[text]        the drive's status; a DOS command
;   : a b 'TEXT'   store bytes and ZX81 text (M's lines, hex or characters
;                  changed and RETURN pressed)
;   R              the registers, as a ";" and a "'" line to change
;   ; pc af bc de hl sp ix iy
;   ' af' bc' de' hl' i iff
;   G [a]          go on with the registers (at a); X the same
;   F s e b        fill          T s e d   transfer
;   C s e d        compare       H s e b b ... or H s e 'TEXT  hunt
;   = n            n in hex, decimal and binary (+n decimal, %n binary)
;   ?              help
; The screen is edited as on a C64: the cursor keys, INST/DEL, CLR/HOME,
; and RETURN takes the line the cursor is on. CRSR UP/DOWN at the top and
; bottom scroll an M or D listing (sc_up, sc_dn). RUN/STOP stops a long
; listing. F5 or X goes back to the ZX81.

        include "core.inc"      ; zx64's MON_RET, MONIFF, NOTBAD, CREAD, BP_OFF,
                                ; BPCNT, BPTAB, MONWHY, CALL6510, MBOX, SETCOL,
                                ; GHOSTY
                                ; (build.py)

VIC:     equ $C000
CIA1:    equ $CC00
CIA2:    equ $CD00
COLOUR:  equ $C800              ; C64 $D800
MSCR:    equ $F400              ; C64 $0400, the monitor's screen
MSTACK:  equ $D800              ; its stack, from $D7FF down: C64 $E400-$E7FF,
                                ; free between the ZX81's screen and font
BORDERCOL: equ 14                ; the C64's colours: light blue on blue
BACKCOL:  equ 6
TEXTCOL:  equ 14

K_RETURN: equ 13                ; key codes, as PETSCII
K_DOWN:  equ 17
K_HOME:  equ 19
K_DEL:   equ 20
K_RIGHT: equ 29
K_F5:    equ 135
K_UP:    equ 145
K_CLR:   equ 147
K_INST:  equ 148
K_LEFT:  equ 157

        org $3000
        jp entry
        db "ZM",1               ; zx64 looks for "ZM"; the version

; ---------------------------------------------------------------- in, out
; On the stack: HL DE BC AF and the return address, as zx64 left them.
entry:  pop hl
        ld (r_hl),hl
        pop hl
        ld (r_de),hl
        pop hl
        ld (r_bc),hl
        pop hl
        ld (r_af),hl
        pop hl
        ld (r_pc),hl
        ld (r_sp),sp
        ld (r_ix),ix
        ld (r_iy),iy
        exx
        ld (r_bc2),bc
        ld (r_de2),de
        ld (r_hl2),hl
        exx
        ex af,af'
        push af
        pop hl
        ld (r_af2),hl
        ex af,af'
        ld a,i
        ld (r_i),a
        ld a,(MONIFF)
        ld (r_iff),a
        ld sp,MSTACK
        call BP_OFF             ; the breakpoints' bytes back
        xor a
        ld (mmode),a
        ld (loaded),a
        ld a,(MONWHY)
        or a
        jr nz,en_bp
        ld (stepping),a         ; F5: no step pending any more
        ld (gostep),a
        jr en_f5
en_bp:  call bpwhy              ; a breakpoint: which (it may go straight on)
en_f5:  call scr_on
        call kinit              ; keys down now (F5) are not new ones
        ld a,(mmode)
        or a
        jr z,en_hello
        call bpshow             ; stopped at a breakpoint, or a step done
        jr main
en_hello:
        call lstart
        call putsi
        db "ZX64MON ",0
        ld hl,verstr
        call puts
        call putsi
        db "   ? HELP   X OR F5: BACK",0
        call down
        call cmd_r
        call prompt
main:   call getline
        call exec
        jr main

; Back to what was running, with the registers as they are now: the
; same stack layout at SP, through zx64's mon_ret. Every key up first,
; or the ZX81 would take RETURN or F5 for its own.
leave:  call kup
        call scr_off
leave_q:
        ld a,(loaded)           ; a program loaded (L "NAME"): not back to
        or a                    ; what ran, but to BASIC, as a report
        jr z,lq1
        ld hl,pgo
        ld (r_pc),hl
        xor a
        ld (stepping),a
        ld (gostep),a
        ld (sbn),a
lq1:    call arm                ; the breakpoints, as RST $38s
        ld sp,(r_sp)
        ld hl,(r_pc)
        push hl
        ld hl,(r_af)
        push hl
        ld hl,(r_bc)
        push hl
        ld hl,(r_de)
        push hl
        ld hl,(r_hl)
        push hl
        ld a,(r_iff)
        ld (MONIFF),a
        ld a,(r_i)
        ld i,a
        ld hl,(r_af2)
        push hl
        ex af,af'
        pop af
        ex af,af'
        exx
        ld bc,(r_bc2)
        ld de,(r_de2)
        ld hl,(r_hl2)
        exx
        ld ix,(r_ix)
        ld iy,(r_iy)
        jp MON_RET

; After L "NAME", leaving comes here, to go on as the ROM's LOAD does:
; from the loaded NXTLIN (a program saved by a program line runs), else
; report 0. The ROM's error exit, ERROR-3 ($0058), with L = $FF (no
; error): ERR_NR, SP from ERR_SP, SLOW/FAST, and back to what is at
; ERR_SP. That is $0676 while a program runs (the next line, or the
; report), but the editor's key wait ($04CF) in the editor, where it
; would spin (zx64's call is before it): so $0676 is put there first.
; Not RST 8: it sets X_PTR, and a program going on with X_PTR set stops
; with report C. FLAGS bit 7: run, not only check the syntax (the editor
; clears it; LOAD runs as a command, with it set). PPC $FFFE: a command,
; not a program's line (PPC isn't in the file). What ran is left behind,
; as after BREAK.
pgo:    set 7,(iy+$01)          ; FLAGS
        ld hl,$FFFE
        ld ($4007),hl           ; PPC
        ld hl,($4002)           ; ERR_SP
        ld (hl),$76
        inc hl
        ld (hl),$06
        ld l,$FF
        jp $0058

; ---------------------------------------------------------------- screen
; The ZX81's VIC settings are put back as c64/boot.asm makes them, not
; as read: a read of the I/O can come back wrong on the cartridge. CIA2's
; $DD00 also holds the serial bus's lines, so it is read, three times.
ZX_D011: equ $17                ; 24 rows, yscroll 7, raster IRQ line 250
ZX_D018: equ $8A                ; screen $E000, characters $E800

scr_on: ld hl,CIA2
        call rd3
        ld (sv_dd00),a
        ld a,(inited)           ; the first time: a clear screen; then
        or a                    ; as it was left
        call z,cls
        ld a,1
        ld (inited),a
        ld a,TEXTCOL
        call colours
        ld a,BORDERCOL
        ld (VIC+$20),a
        ld a,BACKCOL
        ld (VIC+$21),a
        ld a,(sv_dd00)
        or 3                    ; VIC bank 0: the C64's character ROM at $1000
        ld (CIA2),a
        ld a,$14                ; screen $0400, characters $1000
        ld (VIC+$18),a
        ld a,$1B                ; 25 rows
        ld (VIC+$11),a
        ret

scr_off:
        ld a,(sv_dd00)
        ld (CIA2),a
        ld a,ZX_D018
        ld (VIC+$18),a
        ld a,ZX_D011
        ld (VIC+$11),a
        jp SETCOL               ; zx64's: the colour scheme F2 chose

colours:                        ; A into all of colour RAM: written, never
        ld hl,COLOUR            ; read (an LDIR copies by reading it, and a
        ld c,4                  ; read of the I/O can come back wrong on the
fillc1: ld b,250                ; cartridge: seen, runs of black and grey)
fillc2: ld (hl),a
        inc hl
        djnz fillc2
        dec c
        jr nz,fillc1
        ret

cls:    ld hl,MSCR
        ld (hl),$20
        ld de,MSCR+1
        ld bc,999
        ldir
        xor a
        ld (crow),a
        ld (ccol),a
        ret

rowp:   push de                 ; HL = the start of the cursor's row
        ld a,(crow)
        ld l,a
        ld h,0
        add hl,hl
        add hl,hl
        add hl,hl
        ld d,h
        ld e,l
        add hl,hl
        add hl,hl
        add hl,de
        ld de,MSCR
        add hl,de
        pop de
        ret

cpos:   call rowp               ; HL = the cursor's place
        push de
        ld a,(ccol)
        ld e,a
        ld d,0
        add hl,de
        pop de
        ret

lstart: push hl                 ; the cursor's row cleared, column 0
        push bc
        xor a
        ld (ccol),a
        call rowp
        ld b,40
ls1:    ld (hl),$20
        inc hl
        djnz ls1
        pop bc
        pop hl
        ret

down:   push hl                 ; column 0 of the next row, scrolling at
        push de                 ; the bottom
        push bc
        xor a
        ld (ccol),a
        ld a,(crow)
        cp 24
        jr nc,dn_scr
        inc a
        ld (crow),a
        jr dn_done
dn_scr: ld hl,MSCR+40
        ld de,MSCR
        ld bc,960
        ldir
        ex de,hl                ; DE: the last row (HL is past the screen)
        ld b,40
dn_cl:  ld (hl),$20
        inc hl
        djnz dn_cl
dn_done:
        pop bc
        pop de
        pop hl
        ret

; A = a screen code at the cursor, which moves on (not past column 40).
; Keeps all but A.
pscr:   push hl
        push af
        ld a,(ccol)
        cp 40
        jr nc,ps_no
        call cpos
        inc a
        ld (ccol),a
        pop af
        ld (hl),a
        pop hl
        ret
ps_no:  pop af
        pop hl
        ret

pch:    call a2s                ; A = ASCII
        jr pscr

a2s:    cp $40                  ; ASCII -> screen code: $20-$3F as they
        ret c                   ; are, $40-$5F (@, A-Z ...) to 0-31
        sub $40
        ret

sp1:    push af
        ld a,' '
        call pch
        pop af
        ret

puts:   ld a,(hl)               ; HL: a string ending in 0; HL after it
        inc hl
        or a
        ret z
        call pch
        jr puts

putsi:  ex (sp),hl              ; the string after the CALL
        call puts
        ex (sp),hl
        ret

phex4:  ld a,h                  ; HL, keeps it
        call phex2
        ld a,l
phex2:  push af                 ; A, keeps it
        rrca
        rrca
        rrca
        rrca
        call hexd
        pop af
        push af
        call hexd
        pop af
        ret
hexd:   and $0F
        add a,'0'
        cp '9'+1
        jr c,hx1
        add a,7
hx1:    jp pch

; A = a ZX81 character code, shown as itself: inverse ones in reverse,
; graphics and codes that are no character as "."
pzx:    push de
        ld d,a
        call zxch
        call a2s
        bit 7,d
        jr z,pz_put
        or $80
pz_put: call pscr
        pop de
        ret

zxch:   push hl                 ; A: a ZX81 code -> the ASCII pzx shows it
        bit 6,a                 ; as, not inverse
        jr nz,zc_dot
        and $3F
        ld hl,zx2asc
        add a,l
        ld l,a
        jr nc,zc1
        inc h
zc1:    ld a,(hl)
        cp $7F
        jr nz,zc_ret
zc_dot: ld a,'.'
zc_ret: pop hl
        ret

; HL: an I/O register, read three times: each bit as two of them have it.
rd3:    push bc
        push de
        ld b,(hl)
        ld c,(hl)
        ld d,(hl)
        ld a,b
        and c
        ld e,a
        ld a,b
        and d
        or e
        ld e,a
        ld a,c
        and d
        or e
        pop de
        pop bc
        ret

prompt: call lstart
        ld a,'.'
        jp pch

; ---------------------------------------------------------------- keys
; Polled once a frame (the VIC's raster flag, latched at line 250; the
; interrupts are off in here). A key is taken as it goes down, and
; repeats when held.
fwait:  ld a,(VIC+$19)          ; the raster flag (line 250)
        rra
        jr nc,fwait
        call NOTBAD             ; read just after a bad line it can be
        jr c,fwait              ; wrong (zx64's notbad)
        ld a,1
        ld (VIC+$19),a
        push hl
        ld hl,(nframes)         ; frames counted (make test checks them)
        inc hl
        ld (nframes),hl
        pop hl
        ret

kscan:  ld hl,kmat              ; the C64 matrix, a byte a column (0: down)
        ld b,$FE
ks1:    ld a,b
        call CREAD              ; zx64's: each bit as two of three reads have it
        ld (hl),a
        inc hl
        rlc b
        jr c,ks1
        ld a,$FF
        ld (CIA1),a
        ret

kcopy:  ld hl,kmat
        ld de,kprev
        ld bc,8
        ldir
        ret

kinit:  call kscan
        call kcopy
        ld a,$FF
        ld (klast),a
        ret

kup:    call fwait              ; until every key is up
        call kscan
        ld hl,kmat
        ld b,8
ku1:    ld a,(hl)
        inc a
        jr nz,kup
        inc hl
        djnz ku1
        ret

; A = a key (column * 8 + row): carry if it is up now.
kheld:  ld b,a
        rrca
        rrca
        rrca
        and 7
        ld e,a
        ld d,0
        ld hl,kmat
        add hl,de
        ld a,b
        and 7
        ld b,a
        inc b
        ld a,(hl)
kh1:    rrca
        djnz kh1
        ret

; The next key as PETSCII, with the cursor blinking meanwhile.
getkey: call fwait
        ld hl,blinkc
        dec (hl)
        jr nz,gk_scan
        ld (hl),16
        call curflip
gk_scan:
        call kscan
        ld hl,kmat
        call GHOSTY             ; a key may be a ghost (see zx64's ghosty):
        jr nz,getkey            ; none taken, kprev kept, until it clears
        ld hl,kmat
        ld de,kprev
        ld ix,kmods
        ld c,0
gk_col: ld a,(hl)
        cpl                     ; down now
        ex de,hl
        and (hl)                ; and up before
        ex de,hl
        and (ix+0)              ; not SHIFT, CTRL or C=
        jr nz,gk_new
        inc hl
        inc de
        inc ix
        ld a,c
        add a,8
        ld c,a
        cp 64
        jr c,gk_col
        call kcopy
        ld a,(klast)            ; nothing new: the last one, held?
        cp $FF
        jr z,getkey
        call kheld
        jr c,gk_rel
        ld hl,krep
        inc (hl)
        ld a,(hl)
        cp 25                   ; half a second, then every 3 frames
        jr c,getkey
        ld (hl),22
        ld a,(klast)
        jr gk_code
gk_rel: ld a,$FF
        ld (klast),a
        jr getkey
gk_new: ld b,a                  ; the lowest new key in this column
gk_bit: rrc b
        jr c,gk_got
        inc c
        jr gk_bit
gk_got: ld a,c
        ld (klast),a
        xor a
        ld (krep),a
        call kcopy
        ld a,(klast)
gk_code:
        ld e,a
        ld d,0
        ld hl,keys
        ld a,(kmat+1)           ; LSHIFT (column 1, row 7)
        and $80
        jr z,gk_sh
        ld a,(kmat+6)           ; RSHIFT (column 6, row 4)
        and $10
        jr nz,gk_tab
gk_sh:  ld hl,keys_sh
gk_tab: add hl,de
        ld a,(hl)
        or a
        jp z,getkey             ; no key of ours
        push af
        call curoff
        pop af
        ret

curflip:                        ; the cursor: its character reversed
        ld a,(ccol)
        cp 40
        ret nc
        call cpos
        ld a,(hl)
        xor $80
        ld (hl),a
        ld hl,curst
        ld a,(hl)
        xor 1
        ld (hl),a
        ret

curoff: ld a,(curst)
        or a
        ret z
        jr curflip

; RUN/STOP down: back to the prompt (when it is up again).
stopchk:
        ld a,$7F                ; column 7, row 7
        call CREAD
        push af
        ld a,$FF
        ld (CIA1),a
        pop af
        rla
        ret c
st_up:  call fwait
        call kscan
        ld a,(kmat+7)
        rla
        jr nc,st_up
abort:  ld sp,MSTACK
        call kinit
        call prompt
        jp main

; ---------------------------------------------------------------- line
; Edit the screen until RETURN, then take the cursor's row into linebuf,
; as ASCII, and go to the start of the next row.
getline:
        xor a
        ld (curst),a
        inc a
        ld (blinkc),a
gl_key: call getkey
        cp K_RETURN
        jp z,gl_ret
        ld hl,gl_key            ; each of these comes back to gl_key
        push hl
        cp K_RIGHT
        jr z,crright
        cp K_LEFT
        jr z,crleft
        cp K_DOWN
        jr z,crdown
        cp K_UP
        jr z,crup
        cp K_HOME
        jr z,home
        cp K_CLR
        jp z,cls
        cp K_DEL
        jr z,delch
        cp K_INST
        jr z,insch
        cp K_F5
        jp z,leave
        cp ' '
        ret c
        cp $60
        ret nc
        call a2s                ; typed: at the cursor, which moves on to
        push af                 ; column 39 at most
        call cpos
        pop af
        ld (hl),a
crright:
        ld a,(ccol)
        cp 39
        ret nc
        inc a
        ld (ccol),a
        ret
crleft: ld a,(ccol)
        or a
        ret z
        dec a
        ld (ccol),a
        ret
crdown: ld a,(crow)
        cp 24
        jp nc,sc_dn
cd_row: ld a,(ccol)
        push af
        call down
        pop af
        ld (ccol),a
        ret
crup:   ld a,(crow)
        or a
        jr z,sc_up
        dec a
        ld (crow),a
        ret
home:   xor a
        ld (crow),a
        ld (ccol),a
        ret
delch:  ld a,(ccol)             ; the character left of the cursor out,
        or a                    ; the rest of the row moved up to it
        ret z
        dec a
        ld (ccol),a
        call cpos
        ld d,h
        ld e,l
        inc hl
        ld a,(ccol)
        ld b,a
        ld a,39
        sub b
        jr z,dl_end
        ld c,a
        ld b,0
        ldir
dl_end: ex de,hl
        ld (hl),$20
        ret
insch:  call rowp               ; a space at the cursor, the rest moved on
        ld de,39
        add hl,de
        ld d,h
        ld e,l
        dec hl
        ld a,(ccol)
        ld b,a
        ld a,39
        sub b
        jr z,in_end
        ld c,a
        ld b,0
        lddr
in_end: call cpos
        ld (hl),$20
        ret

; Scrolling, as Super Snapshot's monitor does. CRSR UP on the top row,
; an M or D line: the screen moves down and the line before it comes in.
; CRSR DOWN on the bottom row: the line after the lowest M or D line, in
; the row under it if that is empty or only the prompt's ".", else at the
; bottom, the screen moved up. M and D alone then go on after it. No M or
; D line: as before.
sc_up:  ld hl,MSCR
        call rowmd
        ret c
        ld (sc_ty),a
        ld a,(ccol)
        push af
        ld a,(dbnext)           ; D alone goes on from the bottom: as it was
        push af
        ld a,(sc_ty)
        cp ':'
        jr nz,su_d
        ld hl,-8
        add hl,de
        jr su_put
su_d:   call dback
su_put: ld (a3),hl
        ld hl,MSCR+959          ; rows 0-23 to 1-24 (scline clears row 0)
        ld de,MSCR+999
        ld bc,960
        lddr
        call scline
        pop af
        ld (dbnext),a
        pop af
        ld (ccol),a
        ret

sc_dn:  ld hl,MSCR+960          ; up from row 24, over empty rows and "."
        ld b,24
sd1:    call rowmt
        jr nz,sd2
        ld de,-40
        add hl,de
        dec b
        jp m,cd_row
        jr sd1
sd2:    call rowmd
        jp c,cd_row
        ld (sc_ty),a
        push bc
        cp ':'
        jr nz,sd_d
        ld hl,8
        jr sd_add
sd_d:   call dcount             ; D: its bytes on the screen (a DB: 1)
        ld c,0
        ld a,b
        dec a
        jr nz,sd_db
        ld a,(de)               ; RST $08 alone: the next is its report's DB
        cp $CF
        jr nz,sd_db
        inc c
sd_db:  ld a,c
        ld (dbnext),a
        ld l,b
        ld h,0
sd_add: add hl,de
        ld (a3),hl
        pop bc
        ld a,(ccol)
        push af
        ld a,b
        cp 24
        jr nz,sd_in
        call down               ; at the bottom: up a row
        jr sd_put
sd_in:  inc a                   ; the empty row under it
        ld (crow),a
sd_put: call scline
        ld a,(sc_ty)
        cp ':'
        jr z,sd_m
        ld (dnext),hl
        jr sd_e
sd_m:   ld (mnext),hl
sd_e:   pop af
        ld (ccol),a
        ret

scline: ld hl,(a3)              ; the line at a3 on the cursor's row, as
        ld a,(sc_ty)            ; sc_ty: HL after it
        cp ':'
        jp z,mline
        call ddec
        jp dshow

; HL: a row. Z if it is empty, or only "." in column 0.
rowmt:  push hl
        push bc
        ld a,(hl)
        cp '.'
        jr nz,rt1
        ld a,' '
rt1:    cp ' '
        jr nz,rt_x
        ld b,39
rt2:    inc hl
        ld a,(hl)
        cp ' '
        jr nz,rt_x
        djnz rt2
rt_x:   pop bc
        pop hl
        ret

; HL: a row. An M (".:") or D (".,") line: A ':' or ',', DE its address;
; carry if not. Keeps BC, HL.
rowmd:  push hl
        push bc
        ld a,(hl)
        cp '.'
        jr nz,rd_no
        inc hl
        ld a,(hl)
        cp ':'
        jr z,rd1
        cp ','
        jr nz,rd_no
rd1:    ld c,a
        ld de,0
        ld b,4
rd2:    inc hl
        ld a,(hl)               ; screen code: A-F are 1-6
        cp $20
        jr nc,rm3
        add a,$40
rm3:    call hexval
        jr c,rd_no
        ex de,hl
        add hl,hl
        add hl,hl
        add hl,hl
        add hl,hl
        or l
        ld l,a
        ex de,hl
        djnz rd2
        ld a,c
        pop bc
        pop hl
        and a
        ret
rd_no:  pop bc
        pop hl
        scf
        ret

dcount: push hl                 ; HL: a D row -> B: its bytes (columns 7,
        push de                 ; 10, 13, 16). Keeps DE, HL
        ld de,7
        add hl,de
        ld b,0
dc1:    ld a,(hl)
        cp ' '
        jr z,dc2
        inc b
        inc hl
        inc hl
        inc hl
        ld a,b
        cp 4
        jr c,dc1
dc2:    pop de
        pop hl
        ret

gl_ret: call rowp
        ld de,linebuf
        ld b,40
gr1:    ld a,(hl)               ; screen codes back to ASCII
        and $7F
        cp $20
        jr nc,gr2
        add a,$40
        jr gr3
gr2:    cp $40
        jr c,gr3
        ld a,' '                ; graphics: as spaces
gr3:    ld (de),a
        inc hl
        inc de
        djnz gr1
        xor a
        ld (de),a
        jp down

; ---------------------------------------------------------------- commands
exec:   ld hl,linebuf
ex_sk:  ld a,(hl)
        cp ' '
        jr z,ex_nx
        cp '.'
        jr nz,ex_cmd
ex_nx:  inc hl
        jr ex_sk
ex_cmd: or a
        jp z,prompt             ; an empty line
        inc hl
        ld (lptr),hl
        ld hl,cmds
ex_find:
        ld c,(hl)
        inc c
        dec c
        jp z,err
        inc hl
        ld e,(hl)
        inc hl
        ld d,(hl)
        inc hl
        cp c
        jr nz,ex_find
        xor a
        ld (quiet),a
        ex de,hl
        call jphl
        ld a,(quiet)            ; ":", ";", "'": no prompt, so the next
        or a                    ; line M showed can be changed in turn
        ret nz
        jp prompt
jphl:   jp (hl)

cmds:   db 'M'
        dw cmd_m
        db ':'
        dw cmd_colon
        db 'R'
        dw cmd_r
        db ';'
        dw cmd_semi
        db $27                  ; '
        dw cmd_alt
        db 'G'
        dw cmd_g
        db 'X'
        dw leave
        db 'F'
        dw cmd_f
        db 'T'
        dw cmd_t
        db 'C'
        dw cmd_c
        db 'H'
        dw cmd_h
        db 'D'
        dw cmd_d
        db 'B'
        dw cmd_b
        db 'S'
        dw cmd_s
        db 'A'
        dw cmd_a
        db '$'
        dw cmd_dir
        db 'L'
        dw cmd_l
        db 'W'
        dw cmd_w
        db '@'
        dw cmd_at
        db ','
        dw cmd_comma
        db '?'
        dw cmd_help
        db '='
        dw cmd_eq
        db 0

err:    ld sp,MSTACK            ; "?", and the prompt
        call lstart
        ld a,'?'
        call pch
        call down
        call prompt
        jp main

quietly:
        ld a,1
        ld (quiet),a
        ret

; M s [e]: 8 bytes a line, as ":" lines; 12 lines without e.
cmd_m:  ld hl,(lptr)
        call getw
        jr nc,cm_from
        ld de,(mnext)           ; M alone: on from where the last one ended
        ld (a1),de
        jr cm_12
cm_from:
        ld (a1),de
        call getw
        jr nc,cm_end
cm_12:  ld hl,(a1)
        ld de,$5F
        add hl,de
        ex de,hl
cm_end: ld (a2),de
cm_line:
        call stopchk
        ld hl,(a1)
        call mline
        call down
        ld hl,(a1)              ; where M alone goes on
        ld de,8
        add hl,de
        ld (mnext),hl
        ld hl,(a2)              ; done if e - a < 8
        ld de,(a1)
        and a
        sbc hl,de
        ret c
        ld a,h
        or a
        jr nz,cm_next
        ld a,l
        cp 8
        ret c
cm_next:
        ld hl,(a1)
        ld de,8
        add hl,de
        ld (a1),hl
        ld (mnext),hl
        ret c                   ; past $FFFF
        jr cm_line

; HL: 8 bytes shown as an M line on the cursor's row, as ":" takes
; them back; HL after them.
mline:  call lstart
        call putsi
        db ".:",0
        call phex4
        push hl
        ld b,8
ml_b:   call sp1
        ld a,(hl)
        call phex2
        inc hl
        djnz ml_b
        call sp1
        pop hl
        ld b,8
ml_c:   ld a,(hl)
        call pzx
        inc hl
        djnz ml_c
        ret

; : a b b ... 'TEXT' b ...: bytes from a, and text as ZX81 codes ("'" is
; no ZX81 character). A text running to the end of the line (no closing
; "'", trailing spaces left out) offers the next line, ":a '", to go on.
; After 8 bytes and no text, an M line's characters (a space, then 8):
; one that is not as the byte at a showed it is stored as its ZX81 code,
; inverse if the byte is; as it was, the hex goes. All spaces: no text
; (typed by hand). A character with no ZX81 code: "?". Read into pat
; first, so "?" stores nothing; a line holds fewer bytes than pat.
cmd_colon:
        ld hl,(lptr)
        call needw
        ld (a1),de
        ld de,pat
        ld bc,0                 ; B: a text seen, C: bytes read
co1:    call skipsp
        cp $27
        jr z,co_str
        push de
        call getb
        pop de
        jr c,co_put
        call co_byte
        ld a,c                  ; 8 bytes, no text: an M line's characters?
        cp 8
        jr nz,co1
        inc b
        dec b
        jr nz,co1
        inc hl
        ld a,(hl)
        dec hl
        cp $27
        jr z,co1
        call co_text
        ld c,8
co_put: call co_st
        jp quietly

co_str: inc hl                  ; 'TEXT: to the next "'" or the line's last
        push hl                 ; non-space (a2)
        ld hl,linebuf+40
cs_ls:  dec hl
        ld a,(hl)
        cp ' '
        jr z,cs_ls              ; (there is the ':' at least)
        inc hl
        ld (a2),hl
        pop hl
        ld b,1
        call atend
        jr z,co_put             ; "'" alone at the end: nothing more
cs_ch:  call atend
        jr z,cs_eol
        ld a,(hl)
        inc hl
        cp $27
        jr z,co1                ; closed
        call a2zx
        jp c,err
        call co_byte
        jr cs_ch
cs_eol: call co_st              ; DE: where the next line goes on
        ex de,hl
        call lstart
        ld a,':'
        call pch
        call phex4
        call putsi
        db " '",0
        jp quietly

atend:  push de                 ; Z: HL is at the text's end (a2)
        ld de,(a2)
        and a
        sbc hl,de
        add hl,de
        pop de
        ret

co_byte:
        ld (de),a
        inc de
        inc c
        ret

co_st:  ld a,c                  ; pat to a, C bytes; DE after them
        ld de,(a1)
        or a
        ret z
        ld b,0
        ld hl,pat
        ldir
        ret

co_text:
        ld a,(hl)               ; HL: after the 8th byte
        cp ' '
        ret nz
        inc hl
        push hl
        ld b,8
ct_sp:  ld a,(hl)
        cp ' '
        jr nz,ct_go
        inc hl
        djnz ct_sp
        pop hl                  ; all spaces
        ret
ct_go:  pop hl
        ld de,(a1)
        ld ix,pat
        ld b,8
ct1:    ld a,(de)               ; as the byte showed: the hex goes
        call zxch
        cp (hl)
        jr z,ct_same
        ld a,(hl)
        call a2zx
        jp c,err
        ld c,a
        ld a,(ix+0)
        and $80
        or c
        ld (ix+0),a
ct_same:
        inc hl
        inc de
        inc ix
        djnz ct1
        ret

; R: the registers, as lines that ";" and "'" take back.
cmd_r:  call r_main
        call lstart
        call putsi
        db " AF'  BC'  DE'  HL'  I  IF",0
        call down
        call lstart
        ld a,$27
        call pch
        ld hl,r_af2
        ld b,4
        call pwords
        call sp1
        ld a,(r_i)
        call phex2
        call sp1
        ld a,(r_iff)
        call phex2
        jp down

r_main: call lstart             ; the main registers' two lines
        call putsi
        db " PC   AF   BC   DE   HL   SP   IX   IY",0
        call down
        call lstart
        ld a,';'
        call pch
        ld hl,r_pc
        ld b,8
        call pwords
        jp down

pwords: ld e,(hl)               ; B words from HL, a space between
        inc hl
        ld d,(hl)
        inc hl
        ex de,hl
        call phex4
        ex de,hl
        dec b
        ret z
        call sp1
        jr pwords

; ; pc af bc de hl sp ix iy, as many as are given
cmd_semi:
        ld hl,(lptr)
        ld ix,r_pc
        ld b,8
cs1:    call getw
        jr c,cs_end
        ld (ix+0),e
        ld (ix+1),d
        inc ix
        inc ix
        djnz cs1
cs_end: jp quietly

; ' af' bc' de' hl' i iff
cmd_alt:
        ld hl,(lptr)
        ld ix,r_af2
        ld b,4
ca1:    call getw
        jr c,ca_end
        ld (ix+0),e
        ld (ix+1),d
        inc ix
        inc ix
        djnz ca1
        call getb
        jr c,ca_end
        ld (r_i),a
        call getb
        jr c,ca_end
        and 1
        ld (r_iff),a
ca_end: jp quietly

; G [a]: go on, at a if given.
cmd_g:  ld hl,(lptr)
        call getw
        jp c,leave
        ld (r_pc),de
        jp leave

; s e: a1, a2, and BC = the bytes from s to e (0: all 64K). e < s: "?"
args2:  ld hl,(lptr)
        call needw
        ld (a1),de
        call needw
        ld (a2),de
        push hl
        ex de,hl
        ld de,(a1)
        and a
        sbc hl,de
        jp c,err
        inc hl
        ld b,h
        ld c,l
        pop hl
        ret

; F s e b
cmd_f:  call args2
        call needb
        ld hl,(a1)
        ld (hl),a
        dec bc
        ld a,b
        or c
        ret z
        ld d,h
        ld e,l
        inc de
        ldir
        ret

; T s e d: as LDIR, or LDDR when d is inside s-e
cmd_t:  call args2
        call needw
        ld (a3),de
        ld hl,(a1)
        and a
        sbc hl,de               ; s - d
        jr nc,ct_fwd            ; d at or below s
        ld hl,(a2)
        and a
        sbc hl,de               ; e - d
        jr c,ct_fwd             ; d past e
        ld hl,(a3)
        add hl,bc
        dec hl
        ex de,hl                ; DE: the last byte of the copy
        ld hl,(a2)
        lddr
        ret
ct_fwd: ld hl,(a1)
        ld de,(a3)
        ldir
        ret

; C s e d: the addresses in s-e where s-e and d differ, 8 a line
cmd_c:  call args2
        call needw
        xor a
        ld (ncol),a
        ld hl,(a1)
cc_lp:  ld a,(de)
        cp (hl)
        call nz,paddr
        inc hl
        inc de
        dec bc
        ld a,b
        or c
        jr nz,cc_lp
        jp hend

; H s e b b ...  or  H s e 'TEXT (as ZX81 characters): where it is
cmd_h:  call args2
        ld (cnt),bc
        call skipsp
        ld de,pat
        ld b,0
        cp $27
        jr z,ch_text
ch_byte:
        push de
        call getb
        pop de
        jr c,ch_go
        ld (de),a
        inc de
        inc b
        ld a,b
        cp 32
        jr c,ch_byte
        jr ch_go
ch_text:
        inc hl
ch_t1:  ld a,(hl)
        or a
        jr z,ch_trim
        call a2zx
        jp c,err
        ld (de),a
        inc de
        inc hl
        inc b
        ld a,b
        cp 32
        jr c,ch_t1
ch_trim:                        ; the screen's spaces after the text
        ld a,b
        or a
        jr z,ch_go
        dec de
        ld a,(de)
        or a
        jr nz,ch_go
        dec b
        jr ch_trim
ch_go:  ld a,b
        or a
        jp z,err
        ld (plen),a
        xor a
        ld (ncol),a
        ld hl,(a1)
        ld bc,(cnt)
ch_lp:  push bc
        push hl
        ld de,pat
        ld a,(plen)
        ld b,a
ch_cmp: ld a,(de)
        cp (hl)
        jr nz,ch_no
        inc hl
        inc de
        djnz ch_cmp
        pop hl
        call paddr
        push hl
ch_no:  pop hl
        pop bc
        inc hl
        dec bc
        ld a,b
        or c
        jr nz,ch_lp
        jp hend

; HL: an address found, 8 to a line. Keeps BC, DE, HL.
paddr:  push hl
        push de
        push bc
        ld a,(ncol)
        or a
        jr nz,pa1
        call stopchk
        call lstart
pa1:    call phex4
        call sp1
        ld a,(ncol)
        inc a
        cp 8
        jr c,pa2
        call down
        xor a
pa2:    ld (ncol),a
        pop bc
        pop de
        pop hl
        ret
hend:   ld a,(ncol)             ; a part line ended
        or a
        ret z
        xor a
        ld (ncol),a
        jp down

cmd_help:
        ld hl,help
hp1:    call lstart
        call puts
        call down
        ld a,(hl)
        or a
        jr nz,hp1
        ret

help:   db "M S [E]     MEMORY, 8 BYTES A LINE",0
        db "D S [E]     DISASSEMBLE (M, D ALONE: ON)",0
        db "B [A]       BREAKPOINT AT A (AGAIN: OFF)",0
        db "S           ONE STEP (RETURN: ANOTHER)",0
        db "A A TEXT    ASSEMBLE ($ OR 0 BEFORE HEX)",0
        db "$           THE DIRECTORY",0
        db "L ",$22,"NAME",$22," [A] LOAD; A FILE TO A",0
        db "W ",$22,"NAME",$22," [S E] SAVE; S-E TO A FILE",0
        db "@[TEXT]     THE DRIVE'S STATUS, A COMMAND",0
        db ": A B 'TXT' STORE BYTES, ZX81 TEXT",0
        db "R           REGISTERS (; AND ' TO EDIT)",0
        db "G [A]       GO ON (AT A); X THE SAME",0
        db "F S E B     FILL",0
        db "T S E D     TRANSFER",0
        db "C S E D     COMPARE",0
        db "H S E B ... HUNT BYTES; H S E 'TEXT",0
        db "= N         HEX, +DEC, %BIN: ALL THREE",0
        db "F5         BACK TO THE ZX81",0
        db 0

; ---------------------------------------------------------------- parsing
; HL is the place in the line throughout.
skipsp: ld a,(hl)
        cp ' '
        jr z,sk1
        cp ','
        ret nz
sk1:    inc hl
        jr skipsp

; A hex number into DE; carry if there is none.
getw:   call skipsp
        call hexval
        ret c
        ld de,0
gw1:    ex de,hl
        add hl,hl
        add hl,hl
        add hl,hl
        add hl,hl
        or l
        ld l,a
        ex de,hl
        inc hl
        ld a,(hl)
        call hexval
        jr nc,gw1
        and a
        ret

needw:  call getw
        ret nc
        jp err

getb:   call getw               ; a byte into A; carry if there is none
        ret c
        ld a,d
        or a
        jp nz,err
        ld a,e
        ret

needb:  call getb
        ret nc
        jp err

hexval: sub '0'                 ; A: a hex digit's value; carry if not one
        ret c
        cp 10
        ccf
        ret nc
        sub 'A'-'0'
        ret c
        cp 6
        ccf
        ret c
        add a,10
        ret

a2zx:   push hl                 ; A: ASCII -> its ZX81 code; carry if none
        push bc
        ld hl,zx2asc
        ld bc,64
        cpir
        jr nz,az_no
        ld a,63
        sub c
        pop bc
        pop hl
        ret
az_no:  pop bc
        pop hl
        scf
        ret

; ---------------------------------------------------------------- data
kmods:  db $FF,$7F,$FF,$FF,$FF,$FF,$EF,$DB   ; per column: not SHIFT, CTRL, C=

zx2asc:                         ; ZX81 codes 0-63 as ASCII ($7F: graphics)
        db ' ',$7F,$7F,$7F,$7F,$7F,$7F,$7F,$7F,$7F,$7F
        db '"','#','$',':','?','(',')','>','<','=','+','-','*','/',';',',','.'
        db "0123456789ABCDEFGHIJKLMNOPQRSTUVWXYZ"

        include "monkeys.inc"   ; keys, keys_sh: PETSCII by C64 key (build.py)
        include "version.inc"   ; verstr: zx64's version (build.py)

inited:  db 0                   ; the screen has been cleared once
loaded:  db 0                   ; L "NAME" brought a program: leave to BASIC
msp:     dw 0                   ; the monitor's SP while L uses the ZX81's
sc_ty:   db 0                   ; scrolling: ':' or ',', the line's kind
bk_to:   dw 0                   ; dback: the line, a start tried, bytes
bk_at:   dw 0                   ; left, dbnext there
bk_n:    db 0
bk_db:   db 0
crow:    db 0                   ; the cursor
ccol:    db 0
curst:   db 0                   ; the cursor's character is reversed
blinkc:  db 0
klast:   db $FF                 ; the key last taken (column * 8 + row)
krep:    db 0                   ; frames it has been held
quiet:   db 0
ncol:    db 0                   ; addresses on this line (C, H)
plen:    db 0
sv_dd00: db 0                   ; CIA2's port A as the ZX81 had it
nframes: dw 0
mmode:   db 0                   ; what entering shows: 0 hello, 1 a breakpoint, 2 a step
ubn:     db 0                   ; the user's breakpoints, up to 4
ubp:     ds 8
sbn:     db 0                   ; a step's, up to 2: where the instruction
sbp:     ds 4                   ; may go next
sbad:    db 0
stepping: db 0                  ; S: the next stop is the step's end
gostep:  db 0                   ; G from a breakpoint: stepping past it first
daddr:   dw 0                   ; D: the instruction, the next byte of it,
dptr:    dw 0                   ; where its text goes, how many lines left
dout:    dw 0
dcnt:    db 0
dbnext:  db 0                   ; the next is RST $08's report code
pfx:     db 0                   ; $DD, $FD or 0
dset:    db 0                   ; the displacement has been read (DD CB d op)
ddisp:   db 0
idxmem:  db 0                   ; (IX+d) is an operand: H and L are H and L
dop:     db 0
dx:      db 0
dy:      db 0
dz:      db 0
dp:      db 0
dq:      db 0
mnext:   dw $4000               ; where M and D alone go on
dnext:   dw $4000
lptr:    dw 0
a1:      dw 0
a2:      dw 0
a3:      dw 0
cnt:     dw 0
r_pc:    dw 0                   ; the registers, in the order of the ";" line
r_af:    dw 0
r_bc:    dw 0
r_de:    dw 0
r_hl:    dw 0
r_sp:    dw 0
r_ix:    dw 0
r_iy:    dw 0
r_af2:   dw 0                   ; and of the "'" line
r_bc2:   dw 0
r_de2:   dw 0
r_hl2:   dw 0
r_i:     db 0
r_iff:   db 0
kmat:    ds 8
kprev:   ds 8
pat:     ds 40
linebuf: ds 41
dtext:   ds 24
klist:   ds 8                   ; the numbers' kinds and places (see koff)
aaddr:   dw 0                   ; A: where, the text, the encoding tried,
atext:   dw 0                   ; its length, the pattern
alen:    db 0
apat:    dw 0
cbuf:    ds 4
nvc:     db 0                   ; the text's numbers, how many and their values
nval:    ds 8
cvals:   ds 8
ninp:    ds 40                  ; the text, and a candidate's, normalized
ncand:   ds 24
kptr:    dw klist
part1end:

; ================================================================ part 2
; zx64mon2: the same program's second part, a file of its own loaded to
; Z80 $E000 (C64 $F000, RAM under the kernal). build.py splits the two.
; It must end below $EFFA: the 6510's vectors, and zx64's keyboard row
; for IN A,($FE) with A = $EF at $EFFE.
        org $E000
part2:  db "M2"                 ; zx64 looks for it

; ---------------------------------------------------------------- D
; D s [e]: disassemble from s to e, or 16 instructions; D alone goes
; on. The lines are Supermon's, ".,addr bytes  mnemonic", Zilog's
; mnemonics, numbers in hex. The byte after RST $08 is the ZX81 ROM's
; error code, shown as DB.
cmd_d:  ld hl,(lptr)
        call getw
        jr c,cd_16              ; D alone: on from where the last ended
        ld (dnext),de
        xor a
        ld (dbnext),a
        call getw
        jr c,cd_16
        ld (a2),de
        xor a                   ; 0: up to e
        jr cd_n
cd_16:  ld a,16
cd_n:   ld (dcnt),a
cd_line:
        call stopchk
        ld hl,(dnext)
        call dis1
        ld (dnext),hl
        ld de,(daddr)
        and a
        sbc hl,de
        ret c                   ; past $FFFF
        ld a,(dcnt)
        or a
        jr z,cd_e
        dec a
        ld (dcnt),a
        ret z
        jr cd_line
cd_e:   ld hl,(a2)              ; e - the next: carry when past e
        ld de,(dnext)
        and a
        sbc hl,de
        ret c
        jr cd_line

; DE: a D line's address -> HL: the instruction before it, and dbnext
; for showing it. Z80 instructions are 1-4 bytes, so: decoded from 16
; bytes back, then 15 ..., the first run that lands on DE exactly gives
; it (code falls into step within a few instructions; data may fool it).
; None does: DE-1.
dback:  ld (bk_to),de
        ld b,16
db1:    push bc
        ld hl,(bk_to)
        ld a,l
        sub b
        ld l,a
        jr nc,db2
        dec h
db2:    ld a,b                  ; bytes left to DE
        ld (bk_n),a
        xor a
        ld (dbnext),a
db3:    ld (bk_at),hl
        ld a,(dbnext)
        ld (bk_db),a
        call ddec               ; HL: the next instruction
        push hl
        ld de,(bk_at)
        and a
        sbc hl,de               ; L: its length
        ld a,(bk_n)
        sub l
        pop hl
        jr c,db_no              ; past DE
        ld (bk_n),a
        jr nz,db3
        pop bc                  ; on DE
        ld hl,(bk_at)
        ld a,(bk_db)
        ld (dbnext),a
        ret
db_no:  pop bc
        djnz db1
        ld hl,(bk_to)
        dec hl
        xor a
        ld (dbnext),a
        ret

; HL: an instruction, shown as one line; HL: the next one. ddec only
; decodes it (daddr, dptr, dtext), dshow shows it on the cursor's row.
dis1:   call ddec
        call dshow
        jp down                 ; (keeps HL)

ddec:   ld (daddr),hl
        ld (dptr),hl
        ld hl,dtext
        ld (dout),hl
        ld (hl),0
        xor a
        ld (pfx),a
        ld (dset),a
        ld (idxmem),a
        ld a,(dbnext)
        or a
        jr z,d1_op
        xor a                   ; after RST $08: the report's code
        ld (dbnext),a
        ld a,'D'
        call tch
        ld a,'B'
        call tch
        ld a,' '
        call tch
        call fetch
        call tn
        jr d1_ret
d1_op:  call dec1
        ld hl,(daddr)
        ld a,(hl)
        cp $CF                  ; RST $08, one byte: a report follows
        jr nz,d1_ret
        ld hl,(dptr)
        ld de,(daddr)
        and a
        sbc hl,de
        dec l
        jr nz,d1_ret
        inc a
        ld (dbnext),a
d1_ret: ld hl,(dptr)
        ret

dshow:  call lstart
        call putsi
        db ".,",0
        ld hl,(daddr)
        call phex4
        call sp1
        ld hl,(dptr)            ; its bytes, 1 to 4, then room for 4
        ld de,(daddr)
        and a
        sbc hl,de
        ld b,l
        ld a,4
        sub b
        ld c,a
        ex de,hl
dl1:    ld a,(hl)
        call phex2
        call sp1
        inc hl
        djnz dl1
        ld a,c
        or a
        jr z,dl3
        ld b,a
dl2:    call putsi
        db "   ",0
        djnz dl2
dl3:    ld hl,dtext
        call puts
        ld hl,(dptr)
        ret

fetch:  push hl                 ; the next byte of the instruction
        ld hl,(dptr)
        ld a,(hl)
        inc hl
        ld (dptr),hl
        pop hl
        ret

; Decoding: x, y, z, p, q as in the opcode's bits xxyyyzzz (y = ppq).
; Each group has a pick byte (which of its formats) and the formats;
; a format is text with tokens, filled in by fmt.
dec1:   ld hl,klist             ; its numbers, as they come (for A)
        ld (kptr),hl
        call fetch
        cp $DD
        jr z,d_pfx
        cp $FD
        jr nz,d_main
d_pfx:  ld (pfx),a
        ld hl,(dptr)
        ld a,(hl)
        cp $DD
        jr z,d_bad1
        cp $FD
        jr z,d_bad1
        cp $ED
        jr z,d_bad1
        call fetch
        cp $CB
        jr nz,d_main
        call fetch              ; DD CB d op: d comes first
        ld (ddisp),a
        ld a,1
        ld (dset),a
        call fetch
        call fields
        ld a,6                  ; always on (IX+d)
        ld (dz),a
        jr d_cb2
d_bad1: xor a                   ; a prefix on its own (the next one wins)
        ld (pfx),a
        jp d_bad
d_main: cp $CB
        jr z,d_cb
        cp $ED
        jr z,d_ed
        call fields
        or a
        jr z,d_x0
        dec a
        jr z,d_x1
        dec a
        jr z,d_x2
        ld hl,x3tab
        jr d_z
d_x0:   ld hl,x0tab
d_z:    ld a,(dz)
        add a,a
        ld e,a
        ld d,0
        add hl,de
        ld e,(hl)
        inc hl
        ld d,(hl)
        ex de,hl
        jp pick
d_x1:   ld a,(dop)
        cp $76
        ld hl,s_halt
        jp z,fmt
        ld a,(dy)               ; LD H,(IX+d): H stays H
        cp 6
        jr z,dx1m
        ld a,(dz)
        cp 6
        jr nz,dx1f
dx1m:   ld a,1
        ld (idxmem),a
dx1f:   ld hl,f_ldrr
        jp fmt
d_x2:   ld hl,f_alur
        jp fmt
d_cb:   call fetch
        call fields
d_cb2:  ld a,(dx)
        ld hl,f_cb
        call nth
        jp fmt
d_ed:   call fetch
        call fields
        cp 1
        jr nz,d_ed2
        ld hl,edtab
        jr d_z
d_ed2:  cp 2
        jr nz,d_bad
        ld a,(dz)
        cp 4
        jr nc,d_bad
        ld a,(dy)
        sub 4
        jr c,d_bad
        add a,a
        add a,a
        ld c,a
        ld a,(dz)
        add a,c
        ld hl,blinames
        call nth
        jp fmt
d_bad:  ld hl,s_bad
        jp fmt

fields: ld (dop),a              ; A: the opcode -> its fields; A = x
        ld c,a
        and 7
        ld (dz),a
        ld a,c
        rrca
        rrca
        rrca
        and 7
        ld (dy),a
        ld b,a
        and 1
        ld (dq),a
        ld a,b
        rrca
        and 3
        ld (dp),a
        ld a,c
        rlca
        rlca
        and 3
        ld (dx),a
        ret

; HL: a pick byte, then formats ended by 0 each. Pick: 0 the only one,
; 1 y, 2 q, 3 q*4+p, 4 y up to 4, 5 q ? p+1 : 0, 6 y = 6, 7 y = 1.
pick:   ld c,(hl)
        inc hl
        xor a
        or c
        jr z,pk_n
        ld a,(dy)
        dec c
        jr z,pk_n
        dec c
        jr z,pk_q
        dec c
        jr z,pk_qp
        dec c
        jr z,pk_y4
        dec c
        jr z,pk_qp1
        dec c
        jr z,pk_y6
        cp 1
        jr pk_eq
pk_y6:  cp 6
pk_eq:  ld a,0
        jr nz,pk_n
        inc a
        jr pk_n
pk_q:   ld a,(dq)
        jr pk_n
pk_qp:  ld a,(dq)
        add a,a
        add a,a
        ld c,a
        ld a,(dp)
        add a,c
        jr pk_n
pk_y4:  cp 4
        jr c,pk_n
        ld a,4
        jr pk_n
pk_qp1: ld a,(dq)
        or a
        jr z,pk_n
        ld a,(dp)
        inc a
pk_n:   call nth
        ; and on into fmt

; HL: a format: text, and tokens (1-16) for the operands, ended by 0.
fmt:    ld a,(hl)
        inc hl
        or a
        ret z
        cp ' '
        jr c,fm_tok
        call tch
        jr fmt
fm_tok: push hl
        dec a
        add a,a
        ld e,a
        ld d,0
        ld hl,toks
        add hl,de
        ld e,(hl)
        inc hl
        ld d,(hl)
        ex de,hl
        call jphl
        pop hl
        jr fmt

T_RY:   equ 1                   ; the tokens
T_RZ:   equ 2
T_RP:   equ 3
T_RP2:  equ 4
T_CCY:  equ 5
T_CCY4: equ 6
T_N:    equ 7
T_NN:   equ 8
T_REL:  equ 9
T_HLX:  equ 10
T_YD:   equ 11
T_RST:  equ 12
T_IM:   equ 13
T_ALU:  equ 14
T_ROT:  equ 15
T_ZERO: equ 16                  ; OUT (C),0's 0: part of the opcode
toks:   dw t_ry,t_rz,t_rp,t_rp2,t_ccy,t_ccy4,t_n,t_nn,t_rel,t_hlx,t_yd,t_rst,t_im,t_alu,t_rot
        dw t_zero

t_ry:   ld a,(dy)
        jr t_r
t_rz:   ld a,(dz)
t_r:    cp 6                    ; A: a register 0-7
        jr z,t_mem
        ld c,a
        ld a,(pfx)              ; with DD/FD, H and L are IXH, IXL ...
        or a
        jr z,t_rn
        ld a,(idxmem)           ; ... unless (IX+d) is the other operand
        or a
        jr nz,t_rn
        ld a,c
        cp 4
        jr c,t_rn
        cp 6
        jr nc,t_rn
        call t_ix
        ld a,c
        cp 4
        ld a,'H'
        jr z,tr_h
        ld a,'L'
tr_h:   jp tch
t_rn:   ld a,c
        ld hl,rnames
        jp t_name
t_mem:  ld a,(pfx)              ; (HL), or (IX+d)
        or a
        ld a,6
        ld hl,rnames
        jp z,t_name
        ld a,'('
        call tch
        call t_ix
        ld a,(dset)
        or a
        jr z,tm0
        ld c,2                  ; DD CB d op: d at 2, read already
        ld a,K_DISP
        call krec
        ld a,(ddisp)
        jr tm1
tm0:    ld a,K_DISP
        call koff
        call fetch
tm1:    ld c,a
        ld a,'+'
        bit 7,c
        jr z,tm2
        ld a,c
        neg
        ld c,a
        ld a,'-'
tm2:    call tch
        ld a,c
        call tn
        ld a,')'
        jp tch
t_ix:   ld a,'I'                ; IX or IY
        call tch
        ld a,(pfx)
        cp $DD
        ld a,'X'
        jr z,ti1
        ld a,'Y'
ti1:    jp tch
t_rp:   ld hl,rpnames
        jr t_rpx
t_rp2:  ld hl,rp2names
t_rpx:  ld a,(dp)
        cp 2
        jr nz,t_name
        ld a,(pfx)
        or a
        jr nz,t_ix
        ld a,2
        jr t_name
t_hlx:  ld a,(pfx)
        or a
        jr nz,t_ix
        ld a,2
        ld hl,rpnames
        jr t_name
t_ccy:  ld a,(dy)
        jr t_cc
t_ccy4: ld a,(dy)
        and 3
t_cc:   ld hl,ccnames
        jr t_name
t_alu:  ld a,(dy)
        ld hl,alunames
        jr t_name
t_rot:  ld a,(dy)
        ld hl,rotnames
t_name: call nth
tstr:   ld a,(hl)               ; HL: text ended by 0, into dtext
        inc hl
        or a
        ret z
        call tch
        jr tstr
t_n:    ld a,K_BYTE
        call koff
        call fetch
        jp tn
t_nn:   ld a,K_WORD
        call koff
        call fetch
        ld l,a
        call fetch
        ld h,a
        jr tnn
t_rel:  ld a,K_REL
        call koff
        call fetch              ; the target, from the next instruction
        ld e,a
        ld d,0
        bit 7,a
        jr z,tr1
        dec d
tr1:    ld hl,(dptr)
        add hl,de
        jr tnn
t_zero: xor a
        jr t_lit
t_yd:   ld a,(dy)
t_lit:  ld c,a
        ld a,K_LIT
        call krec
        ld a,c
        add a,'0'
        jr tch
t_rst:  ld a,(dy)
        add a,a
        add a,a
        add a,a
        ld c,a
        ld a,K_LIT
        call krec
        ld a,c
        jr tn
t_im:   ld a,(dy)
        and 3
        ld e,a
        ld d,0
        ld hl,imtab
        add hl,de
        ld a,(hl)
        sub '0'
        ld c,a
        ld a,K_LIT
        call krec
        ld a,c
        add a,'0'
        jr tch

; The numbers in an instruction, as the formatter meets them: kind and
; where its byte is (or, for K_LIT, its value), for A to fill in.
K_BYTE: equ 1                   ; n
K_WORD: equ 2                   ; nn
K_REL:  equ 3                   ; a JR's or DJNZ's target
K_DISP: equ 4                   ; d of (IX+d)
K_LIT:  equ 5                   ; part of the opcode: BIT's, IM's, RST's
koff:   push hl                 ; A: a kind; at the byte fetch gets next
        push de
        ld hl,(dptr)
        ld de,(daddr)
        and a
        sbc hl,de
        ld c,l
        pop de
        pop hl
krec:   push hl                 ; A: a kind, C: its place or value
        ld hl,(kptr)
        ld (hl),a
        inc hl
        ld (hl),c
        inc hl
        ld (kptr),hl
        pop hl
        ret

tnn:    ld a,'$'                ; HL as "$xxxx"
        call tch
        ld a,h
        call thex2
        ld a,l
        jr thex2
tn:     push af                 ; A as "$xx"
        ld a,'$'
        call tch
        pop af
thex2:  push af
        rrca
        rrca
        rrca
        rrca
        call thexd
        pop af
thexd:  and $0F
        add a,'0'
        cp '9'+1
        jr c,tch
        add a,7
tch:    push hl                 ; A into dtext
        ld hl,(dout)
        ld (hl),a
        inc hl
        ld (hl),0
        ld (dout),hl
        pop hl
        ret

nth:    or a                    ; HL: strings ended by 0; A: n -> the nth
        ret z
        push bc
        ld b,a
nt1:    ld a,(hl)
        inc hl
        or a
        jr nz,nt1
        djnz nt1
        pop bc
        ret

x0tab:  dw x0z0,x0z1,x0z2,x0z3,x0z4,x0z5,x0z6,x0z7
x3tab:  dw x3z0,x3z1,x3z2,x3z3,x3z4,x3z5,x3z6,x3z7
edtab:  dw edz0,edz1,edz2,edz3,edz4,edz5,edz6,edz7
x0z0:   db 4,"NOP",0,"EX AF,AF'",0,"DJNZ ",T_REL,0,"JR ",T_REL,0,"JR ",T_CCY4,",",T_REL,0
x0z1:   db 2,"LD ",T_RP,",",T_NN,0,"ADD ",T_HLX,",",T_RP,0
x0z2:   db 3,"LD (BC),A",0,"LD (DE),A",0,"LD (",T_NN,"),",T_HLX,0,"LD (",T_NN,"),A",0
        db "LD A,(BC)",0,"LD A,(DE)",0,"LD ",T_HLX,",(",T_NN,")",0,"LD A,(",T_NN,")",0
x0z3:   db 2,"INC ",T_RP,0,"DEC ",T_RP,0
x0z4:   db 0,"INC ",T_RY,0
x0z5:   db 0,"DEC ",T_RY,0
x0z6:   db 0,"LD ",T_RY,",",T_N,0
x0z7:   db 1,"RLCA",0,"RRCA",0,"RLA",0,"RRA",0,"DAA",0,"CPL",0,"SCF",0,"CCF",0
x3z0:   db 0,"RET ",T_CCY,0
x3z1:   db 5,"POP ",T_RP2,0,"RET",0,"EXX",0,"JP (",T_HLX,")",0,"LD SP,",T_HLX,0
x3z2:   db 0,"JP ",T_CCY,",",T_NN,0
x3z3:   db 1,"JP ",T_NN,0,"???",0,"OUT (",T_N,"),A",0,"IN A,(",T_N,")",0
        db "EX (SP),",T_HLX,0,"EX DE,HL",0,"DI",0,"EI",0
x3z4:   db 0,"CALL ",T_CCY,",",T_NN,0
x3z5:   db 2,"PUSH ",T_RP2,0,"CALL ",T_NN,0
x3z6:   db 0,T_ALU,T_N,0
x3z7:   db 0,"RST ",T_RST,0
edz0:   db 6,"IN ",T_RY,",(C)",0,"IN (C)",0
edz1:   db 6,"OUT (C),",T_RY,0,"OUT (C),",T_ZERO,0
edz2:   db 2,"SBC HL,",T_RP,0,"ADC HL,",T_RP,0
edz3:   db 2,"LD (",T_NN,"),",T_RP,0,"LD ",T_RP,",(",T_NN,")",0
edz4:   db 0,"NEG",0
edz5:   db 7,"RETN",0,"RETI",0
edz6:   db 0,"IM ",T_IM,0
edz7:   db 1,"LD I,A",0,"LD R,A",0,"LD A,I",0,"LD A,R",0,"RRD",0,"RLD",0,"???",0,"???",0
f_ldrr: db "LD ",T_RY,",",T_RZ,0
f_alur: db T_ALU,T_RZ,0
f_cb:   db T_ROT," ",T_RZ,0,"BIT ",T_YD,",",T_RZ,0,"RES ",T_YD,",",T_RZ,0,"SET ",T_YD,",",T_RZ,0
s_halt: db "HALT",0
s_bad:  db "???",0
rnames: db "B",0,"C",0,"D",0,"E",0,"H",0,"L",0,"(HL)",0,"A",0
rpnames:
        db "BC",0,"DE",0,"HL",0,"SP",0
rp2names:
        db "BC",0,"DE",0,"HL",0,"AF",0
ccnames:
        db "NZ",0,"Z",0,"NC",0,"C",0,"PO",0,"PE",0,"P",0,"M",0
alunames:
        db "ADD A,",0,"ADC A,",0,"SUB ",0,"SBC A,",0,"AND ",0,"XOR ",0,"OR ",0,"CP ",0
rotnames:
        db "RLC",0,"RRC",0,"RL",0,"RR",0,"SLA",0,"SRA",0,"SLL",0,"SRL",0
blinames:
        db "LDI",0,"CPI",0,"INI",0,"OUTI",0,"LDD",0,"CPD",0,"IND",0,"OUTD",0
        db "LDIR",0,"CPIR",0,"INIR",0,"OTIR",0,"LDDR",0,"CPDR",0,"INDR",0,"OTDR",0
imtab:  db "0012"

; ---------------------------------------------------------------- B, S
; B a: a breakpoint at a (up to 4), or off again if there is one; B
; alone lists them. S: one step. A breakpoint is a RST $38 ($FF) in
; place of the instruction's first byte while the program runs (arm,
; on the way out); zx64's IRQ handler tells it from an interrupt and
; enters the monitor there (bp_hit). S puts its own at every place the
; instruction may go next (succ). Going on from a breakpoint steps past
; it first (gostep), then sets it again.
cmd_b:  ld hl,(lptr)
        call getw
        jr c,b_list
        ex de,hl
        call bpok
        jp c,err
        call isubp
        jr z,b_off
        ld a,(ubn)
        cp 4
        jp nc,err               ; four already
        add a,a
        ld e,a
        ld d,0
        push hl
        ld hl,ubp
        add hl,de
        pop de
        ld (hl),e
        inc hl
        ld (hl),d
        ld hl,ubn
        inc (hl)
        jr b_list
b_off:  ld a,(ubn)              ; DE: the one to go; the last one there
        dec a
        ld (ubn),a
        add a,a
        ld l,a
        ld h,0
        ld bc,ubp
        add hl,bc
        ld a,(hl)
        ld (de),a
        inc hl
        inc de
        ld a,(hl)
        ld (de),a
b_list: call lstart
        call putsi
        db "BREAKPOINTS",0
        ld a,(ubn)
        or a
        jr z,bl_end
        ld b,a
        ld hl,ubp
bl1:    call sp1
        ld e,(hl)
        inc hl
        ld d,(hl)
        inc hl
        ex de,hl
        call phex4
        ex de,hl
        djnz bl1
bl_end: jp down

cmd_s:  call succ
        jp c,err
        ld a,1
        ld (stepping),a
        jp leave

; HL: carry if no breakpoint can go there: zx64 and the monitor
; ($2000-$3FFF), the IRQ's JP at $0038, $C000 up.
bpok:   ld a,h
        cp $C0
        jr nc,bk_no
        cp $40
        ret nc
        cp $20
        jr nc,bk_no
        or a
        jr nz,bk_yes
        ld a,l
        cp $38
        jr c,bk_yes
        cp $3B
        jr c,bk_no
bk_yes: and a
        ret
bk_no:  scf
        ret

; HL: Z if it is one of the user's breakpoints, DE at it in ubp.
isubp:  ld a,(ubn)
        or a
        jr z,iu_no
        ld b,a
        ld de,ubp
iu1:    ld a,(de)
        cp l
        jr nz,iu2
        inc de
        ld a,(de)
        dec de
        cp h
        ret z
iu2:    inc de
        inc de
        djnz iu1
iu_no:  or 1
        ret

; On the way out: the breakpoints into zx64's table, as RST $38s.
arm:    ld a,(stepping)
        or a
        jr nz,ar_go
        ld (sbn),a
        ld hl,(r_pc)            ; G from one of them: a step past it first
        call isubp
        jr nz,ar_go
        call succ
        jr c,ar_go              ; it can't be stepped: on without it
        ld a,1
        ld (gostep),a
ar_go:  ld de,BPTAB
        ld c,0
        ld a,(ubn)
        ld b,a
        ld ix,ubp
        call ar_list
        ld a,(sbn)
        ld b,a
        ld ix,sbp
        call ar_list
        ld a,c
        ld (BPCNT),a
        ret
ar_list:
        ld a,b
        or a
        ret z
ar1:    ld l,(ix+0)
        ld h,(ix+1)
        inc ix
        inc ix
        call armone
        djnz ar1
        ret

; HL: a place to stop, into the table at DE (C so far), its byte saved
; and RST $38 there. Not at the PC (going on from there would stop at
; once), and not twice.
armone: push bc
        push de
        ld de,(r_pc)
        ld a,l
        cp e
        jr nz,ao1
        ld a,h
        cp d
        jr z,ao_skip
ao1:    ld a,c
        or a
        jr z,ao_new
        ld b,c
        ld de,BPTAB
ao2:    ld a,(de)
        cp l
        jr nz,ao3
        inc de
        ld a,(de)
        dec de
        cp h
        jr z,ao_skip
ao3:    inc de
        inc de
        inc de
        djnz ao2
ao_new: pop de
        ld a,l
        ld (de),a
        inc de
        ld a,h
        ld (de),a
        inc de
        ld a,(hl)
        ld (de),a
        inc de
        ld (hl),$FF             ; RST $38
        pop bc
        inc c
        ret
ao_skip:
        pop de
        pop bc
        ret

; Entered at a breakpoint (MONWHY): which kind. Past one of the user's
; after G (gostep): straight on, unless it is at one again.
bpwhy:  ld a,(gostep)
        or a
        jr z,bw_step
        xor a
        ld (gostep),a
        ld (stepping),a
        ld hl,(r_pc)
        call isubp
        jp nz,leave_q
        ld a,1
        ld (mmode),a
        ret
bw_step:
        ld a,(stepping)
        or a
        ld a,1                  ; one of the user's
        jr z,bw_set
        xor a
        ld (stepping),a
        ld a,2                  ; a step done
bw_set: ld (mmode),a
        ret

; What the monitor shows there: the registers, the next instruction.
bpshow: ld a,(mmode)
        cp 2
        jr z,bs_step
        call lstart
        call putsi
        db "BREAKPOINT",0
        call down
        call cmd_r
        jr bs_d
bs_step:
        call r_main
bs_d:   xor a
        ld (dbnext),a
        ld hl,(r_pc)
        call dis1
        ld (dnext),hl
        call prompt
        ld a,(mmode)
        cp 2
        ret nz
        ld a,'S'                ; RETURN steps again
        jp pch

; Where the instruction at PC may go next, into sbp (sbn of them): the
; next one, a jump's, a call's or a RST's target, RET's (SP), JP (HL)'s
; HL. Carry if it can't be stepped: a place no breakpoint can go, or
; only the instruction itself (JR to itself, as in Supermon's and SCM's).
succ:   xor a
        ld (sbn),a
        ld (sbad),a
        ld (pfx),a
        ld (dset),a
        ld (idxmem),a
        ld hl,(r_pc)
        ld (daddr),hl
        ld (dptr),hl
        ld de,dtext
        ld (dout),de
        call dec1               ; for its length: the next one at dptr
        ld hl,(r_pc)
        ld a,(hl)
        ld c,a                  ; C: a prefix, or the opcode
        cp $DD
        jr z,sc_x
        cp $FD
        jr nz,sc_op
sc_x:   inc hl
        ld a,(hl)
sc_op:  cp $ED
        jr nz,sc_1
        inc hl
        ld a,(hl)
        and $C7
        cp $45                  ; RETN, RETI
        jr z,sc_ret
        jr sc_next
sc_1:   cp $CB
        jr z,sc_next
        cp $10                  ; DJNZ
        jr z,sc_reln
        cp $18                  ; JR
        jr z,sc_rel
        ld b,a
        and $E7
        cp $20                  ; JR cc
        ld a,b
        jr z,sc_reln
        cp $C9                  ; RET
        jr z,sc_ret
        cp $E9                  ; JP (HL), (IX), (IY)
        jr z,sc_jphl
        cp $C3                  ; JP
        jr z,sc_nn
        cp $CD                  ; CALL
        jr z,sc_nn
        and $C7
        cp $C0                  ; RET cc
        jr z,sc_retn
        cp $C2                  ; JP cc
        jr z,sc_nnn
        cp $C4                  ; CALL cc
        jr z,sc_nnn
        cp $C7                  ; RST
        jr nz,sc_next
        ld a,b
        and $38
        ld l,a
        ld h,0
        jr sc_one
sc_reln:
        call sc_nx
sc_rel: ld hl,(dptr)
        dec hl
        ld a,(hl)
        inc hl
        ld e,a
        ld d,0
        bit 7,a
        jr z,sr1
        dec d
sr1:    add hl,de
        jr sc_one
sc_retn:
        call sc_nx
sc_ret: ld hl,(r_sp)
        ld a,(hl)
        inc hl
        ld h,(hl)
        ld l,a
        jr sc_one
sc_jphl:
        ld hl,(r_hl)
        ld a,c
        cp $DD
        jr nz,sj1
        ld hl,(r_ix)
sj1:    cp $FD
        jr nz,sc_one
        ld hl,(r_iy)
        jr sc_one
sc_nnn: call sc_nx
sc_nn:  ld hl,(dptr)
        dec hl
        ld d,(hl)
        dec hl
        ld e,(hl)
        ex de,hl
        jr sc_one
sc_next:
        call sc_nx
        jr sc_end
sc_one: call sadd
sc_end: ld a,(sbad)
        or a
        scf
        ret nz
        ld a,(sbn)
        or a
        scf
        ret z
        and a
        ret
sc_nx:  ld hl,(dptr)
sadd:   ld de,(r_pc)            ; HL: a place the step may end
        ld a,l
        cp e
        jr nz,sa1
        ld a,h
        cp d
        ret z                   ; the instruction itself: no
sa1:    call bpok
        jr nc,sa2
        ld a,1
        ld (sbad),a
        ret
sa2:    ld a,(sbn)
        add a,a
        ld e,a
        ld d,0
        push hl
        ld hl,sbp
        add hl,de
        pop de
        ld (hl),e
        inc hl
        ld (hl),d
        ld hl,sbn
        inc (hl)
        ret

; ---------------------------------------------------------------- A
; A a text: the instruction assembled at a; its line becomes D's, and
; ".A next " waits for the next (nothing more: the end). A D line
; (".,") changed and RETURN: the same, in place. Numbers in hex, with
; "$" or a leading digit ($FF, 0FF: DE or C could be registers).
; Assembling is searching: every encoding is disassembled, with zeros
; for its numbers, until one reads as the text does (both normalized,
; numbers as '#'); the numbers are then filled in from the text, by the
; kinds the disassembler noted (koff). So A takes back exactly what D
; shows. With IX or IY in the text only those encodings are tried.
cmd_a:  ld hl,(lptr)
        call needw
        ld (aaddr),de
        call skipsp
        or a
        ret z                   ; no instruction: the end
        ld (atext),hl
        call asm1
        jr c,a_err
        call a_show
a_next: call lstart             ; the next one's prompt
        call putsi
        db ".A ",0
        ld hl,(dnext)
        ld (aaddr),hl
        call phex4
        call sp1
        jp quietly
a_err:  call lstart
        ld a,'?'
        call pch
        call down
        ld hl,(aaddr)           ; the same address again
        ld (dnext),hl
        jr a_next

cmd_comma:                      ; ",a bytes text": a D line, changed
        ld hl,(lptr)
        call needw
        ld (aaddr),de
        ld a,(linebuf+19)       ; D's text starts there; a short line
        cp ' '                  ; typed by hand has it after the address
        jr z,cm_typed
        ld hl,linebuf+19
cm_typed:
        call skipsp
        or a
        jp z,quietly
        ld (atext),hl
        call asm1
        jp c,err
        call a_show
        jp quietly

a_show: ld hl,crow              ; the line typed (above the cursor) as D's
        dec (hl)
        xor a
        ld (dbnext),a
        ld hl,(aaddr)
        call dis1
        ld (dnext),hl
        ret

; (atext) assembled at (aaddr); carry if it can't be.
asm1:   ld hl,(atext)
        ld de,ninp
        ld ix,nval
        call norm
        ld a,c
        ld (nvc),a
        call hasix
        or a
        jr nz,as_ix
        ld hl,pu
        call tryp
        ret nc
        ld hl,pcb
        call tryp
        ret nc
        ld hl,ped
        jr tryp
as_ix:  ld (pix1),a
        ld (pix2),a
        ld hl,pix1
        call tryp
        ret nc
        ld hl,pix2
        jr tryp

; Patterns: four bytes, where the opcode goes in them, and which opcodes
; are tried: 0 all, 1 not the prefixes ($CB, $DD, $ED, $FD), 2 only
; those on (IX+d) (DD CB d op: the others also copy to a register,
; undocumented, and read the same).
pu:     db 0,0,0,0, 0,1
pcb:    db $CB,0,0,0, 1,0
ped:    db $ED,0,0,0, 1,0
pix1:   db $DD,0,0,0, 1,1
pix2:   db $DD,$CB,0,0, 3,2

; HL: a pattern: its 256 encodings tried; NC: one fitted, now at aaddr.
tryp:   ld (apat),hl
        ld c,0
tp1:    ld hl,(apat)
        ld de,cbuf
        push bc
        ld bc,4
        ldir
        pop bc
        ld a,(hl)
        inc hl
        ld b,(hl)
        ld e,a
        ld d,0
        ld hl,cbuf
        add hl,de
        ld (hl),c
        ld a,b
        or a
        jr z,tp2
        dec a
        jr z,tp_pfx
        ld a,c                  ; 2: (IX+d) only
        and 7
        cp 6
        jr nz,tp_n
        jr tp2
tp_pfx: ld a,c
        cp $CB
        jr z,tp_n
        cp $DD
        jr z,tp_n
        cp $ED
        jr z,tp_n
        cp $FD
        jr z,tp_n
tp2:    push bc
        call cand
        pop bc
        jr nc,tp_ok
tp_n:   inc c
        jr nz,tp1
        scf
        ret
tp_ok:  ld hl,cbuf              ; to the address
        ld de,(aaddr)
        ld a,(alen)
        ld c,a
        ld b,0
        ldir
        and a
        ret

; cbuf: an encoding, zeros for its numbers. NC if it reads as the text,
; with the numbers filled in and alen its length.
cand:   ld hl,cbuf
        ld (daddr),hl
        ld (dptr),hl
        ld de,dtext
        ld (dout),de
        xor a
        ld (de),a
        ld (pfx),a
        ld (dset),a
        ld (idxmem),a
        call dec1
        ld a,(dtext)            ; quickly: the same first letter?
        ld hl,ninp
        cp (hl)
        scf
        ret nz
        ld hl,dtext
        ld de,ncand
        ld ix,cvals
        call norm
        ld hl,ninp
        ld de,ncand
cn1:    ld a,(de)
        cp (hl)
        scf
        ret nz
        or a
        jr z,cn_same
        inc hl
        inc de
        jr cn1
cn_same:
        ld hl,(dptr)            ; its length
        ld de,cbuf
        and a
        sbc hl,de
        ld a,l
        ld (alen),a
        ld hl,(kptr)            ; as many numbers as the text has?
        ld de,klist
        and a
        sbc hl,de
        srl l
        ld a,(nvc)
        cp l
        scf
        ret nz
        or a
        ret z
        ld b,a
        ld hl,klist
        ld ix,nval
cn2:    ld a,(hl)
        inc hl
        ld c,(hl)
        inc hl
        ld e,(ix+0)
        ld d,(ix+1)
        inc ix
        inc ix
        push hl
        call kfill
        pop hl
        ret c
        djnz cn2
        and a
        ret

; A: a number's kind, C: its place in cbuf (or for K_LIT its value),
; DE: the text's: into cbuf, or carry if it doesn't fit (or, for K_LIT,
; isn't the one).
kfill:  cp K_LIT
        jr nz,kf1
        ld a,d
        or a
        scf
        ret nz
        ld a,e
        cp c
        scf
        ret nz
        and a
        ret
kf1:    ld hl,cbuf
        push af
        ld a,c
        add a,l
        ld l,a
        jr nc,kf2
        inc h
kf2:    pop af
        cp K_WORD
        jr nz,kf3
        ld (hl),e
        inc hl
        ld (hl),d
        and a
        ret
kf3:    cp K_BYTE
        jr nz,kf4
        ld a,d
        or a
        jr nz,kf_bad
        ld (hl),e
        and a
        ret
kf4:    cp K_DISP
        jr z,kf_s8
        push hl                 ; K_REL: from the next instruction
        ld hl,(aaddr)
        ld a,(alen)
        add a,l
        ld l,a
        jr nc,kf5
        inc h
kf5:    ex de,hl
        and a
        sbc hl,de
        ex de,hl
        pop hl
kf_s8:  ld a,e                  ; DE in -128..127?
        rla
        ld a,d
        adc a,0
        jr nz,kf_bad
        ld (hl),e
        and a
        ret
kf_bad: scf
        ret

; HL: text -> DE: as compared (see A), its numbers at IX, C of them.
norm:   ld c,0
nm1:    ld a,(hl)
        cp ' '
        jr nz,nm2
        inc hl
        jr nm1
nm2:    ld a,(hl)               ; the mnemonic
        or a
        jr z,nm_end
        cp ' '
        jr z,nm3
        ld (de),a
        inc de
        inc hl
        jr nm2
nm3:    inc hl                  ; one space after it, if more follows
        ld a,(hl)
        cp ' '
        jr z,nm3
        or a
        jr z,nm_end
        ld a,' '
        ld (de),a
        inc de
nm4:    ld a,(hl)               ; the operands, without spaces
        or a
        jr z,nm_end
        cp ' '
        jr z,nm_sp
        ld b,0
        cp '-'
        jr nz,nm5
        inc hl
        ld a,(hl)
        call isnum
        jr c,nm_min
        inc b                   ; -n: "+#", and n negated
        ld a,'+'
        ld (de),a
        inc de
        ld a,(hl)
nm5:    call isnum
        jr c,nm_ch
        call nmnum
        ld a,'#'
        ld (de),a
        inc de
        jr nm4
nm_min: ld a,'-'
        ld (de),a
        inc de
        jr nm4
nm_sp:  inc hl
        jr nm4
nm_ch:  ld (de),a
        inc de
        inc hl
        jr nm4
nm_end: xor a
        ld (de),a
        ret

isnum:  cp '$'                  ; A: "$" or a digit: NC
        ret z
        cp '0'
        ret c
        cp '9'+1
        ccf
        ret

nmnum:  ld a,(hl)               ; HL: a number: its value at IX (negated
        cp '$'                  ; if B), C counts; HL past it
        jr nz,nu1
        inc hl
nu1:    push de
        ld de,0
nu2:    ld a,(hl)
        call hexval
        jr c,nu3
        ex de,hl
        add hl,hl
        add hl,hl
        add hl,hl
        add hl,hl
        or l
        ld l,a
        ex de,hl
        inc hl
        jr nu2
nu3:    ld a,b
        or a
        jr z,nu4
        xor a
        sub e
        ld e,a
        sbc a,a
        sub d
        ld d,a
nu4:    ld (ix+0),e
        ld (ix+1),d
        inc ix
        inc ix
        inc c
        pop de
        ret

hasix:  ld hl,ninp              ; IX or IY in the text: A $DD or $FD, else 0
hs1:    ld a,(hl)
        or a
        ret z
        inc hl
        cp 'I'
        jr nz,hs1
        ld a,(hl)
        cp 'X'
        ld a,$DD
        ret z
        ld a,(hl)
        cp 'Y'
        ld a,$FD
        ret z
        jr hs1

; ---------------------------------------------------------------- the disk
; $ the directory; L "NAME" a program, as LOAD; L "NAME" a a file to a;
; W "NAME" the program, as SAVE; W "NAME" s e memory to a file (a PRG:
; its load address is the C64's, so LOAD "NAME",8,1 on a C64 puts it
; back); @ the drive's status, @text a DOS command (@S:NAME scratches).
; The 6510 does it (c64/boot.asm, commands 1-8), as for LOAD and SAVE; it
; won't load into its own page or the I/O chips, nor W save from the I/O
; chips.
CMD_LOAD:  equ 1
CMD_SAVE:  equ 2
CMD_PRG:   equ 3
CMD_DIR:   equ 4
CMD_DIRL:  equ 5
CMD_DIRC:  equ 6
CMD_WRITE: equ 7
CMD_DCMD:  equ 8

cmd_dir:
        ld a,1
        ld (MBOX+2),a
        ld a,'$'
        ld (MBOX+3),a
        ld a,CMD_DIR
        call dcall
        jp nz,derr
dr1:    ld a,$7F                ; RUN/STOP: closed first
        call CREAD
        rla
        jr c,dr2
        ld a,CMD_DIRC
        call dcall
        jp st_up
dr2:    ld a,CMD_DIRL
        call dcall
        ret nz                  ; no more lines
        call lstart
        ld hl,(MBOX+$80)        ; the blocks, and a space, as LIST has it
        call pdec
        call sp1
        ld hl,MBOX+$82
        call ppet
        call down
        jr dr1

cmd_l:  ld hl,(lptr)
        call getname
        jp c,err
        call getw
        jr c,l_prog
        ld hl,$1000             ; to a: as the C64 has it
        add hl,de
        ld (MBOX+$22),hl
        ld a,1
        ld (MBOX+$26),a
        ld a,CMD_PRG
        call dcall
        push af
        xor a
        ld (MBOX+$26),a
        pop af
        jp nz,derr
        call lstart
        call putsi
        db "LOADED ",0
        ld hl,(MBOX+$22)
        ld de,-$1000
        add hl,de
        call phex4
        ld a,'-'
        call pch
        ld hl,(MBOX+$24)
        dec hl
        add hl,de
        call phex4
        jp down

; L "NAME": the 6510's LOAD, from the ZX81's own stack (r_sp), so the
; program has to fit below it as for LOAD. Leaving then goes to BASIC,
; as a report (leave_q): what was running is gone.
l_prog: ld (msp),sp
        ld sp,(r_sp)
        ld a,CMD_LOAD
        call dcall
        ld sp,(msp)
        jr z,lp_ok
        cp 2
        jr z,lp_big
        cp 3
        jp nz,derr
        call lstart
        call putsi
        db "? NOT A PROGRAM",0
        jp down
lp_big: call lstart
        call putsi
        db "? TOO BIG",0
        jp down
lp_ok:  ld a,1
        ld (loaded),a
        call lstart
        call putsi
        db "LOADED 4009-",0
        ld hl,($4014)           ; E_LINE
        dec hl
        call phex4
        jp down

cmd_w:  ld hl,(lptr)
        call getname
        jp c,err
        call getw
        jr nc,cw0
        ld a,CMD_SAVE           ; W "NAME": the program, as SAVE
        call dcall
        jr dstat0
cw0:    ld (a1),de
        call needw
        ld (a2),de
        ld hl,(a2)
        ld de,(a1)
        and a
        sbc hl,de
        jp c,err                ; e before s
        ld a,(a1+1)             ; not from the I/O chips (Z80 $C000-$CFFF)
        cp $D0
        jr nc,cw1
        ld a,(a2+1)
        cp $C0
        jp nc,err
cw1:    ld de,$1000
        ld hl,(a1)
        add hl,de
        ld (MBOX+$22),hl
        ld hl,(a2)
        inc hl
        add hl,de
        ld (MBOX+$24),hl
        ld a,CMD_WRITE
        call dcall
        jr dstat0

cmd_at: ld hl,(lptr)            ; the rest of the line, as the command
        ld de,MBOX+3
        ld b,0
at1:    ld a,(hl)
        or a
        jr z,at2
        ld (de),a
        inc de
        inc hl
        inc b
        ld a,b
        cp 24
        jr c,at1
at2:    ld a,b                  ; less the screen's spaces after it
        or a
        jr z,at3
        dec de
        ld a,(de)
        cp ' '
        jr nz,at3
        dec b
        jr at2
at3:    ld a,b
        ld (MBOX+2),a
        jr dstat

derr:   call lstart             ; something went wrong: "?", and what the
        ld a,'?'                ; drive says
        call pch
        call down
dstat0: xor a                   ; no command: just the status
        ld (MBOX+2),a
dstat:  ld a,CMD_DCMD           ; the drive's status line
        call dcall
        jp nz,err
        call lstart
        ld hl,MBOX+$80
        call ppet
        jp down

; A: a command for the 6510, which does it; NZ if it didn't work.
dcall:  ld (MBOX),a
        call CALL6510
        ld a,(MBOX+1)
        or a
        ret

; HL: "NAME" or NAME -> the mailbox (16 characters at most); carry if
; there is none. HL after it.
getname:
        call skipsp
        ld c,0
        cp '"'
        jr nz,gn0
        inc hl
        inc c
gn0:    ld de,MBOX+3
        ld b,0
gn1:    ld a,(hl)
        or a
        jr z,gn_end
        inc hl
        cp '"'
        jr z,gn_end
        cp ' '
        jr nz,gn2
        ld a,c                  ; a space ends a name without quotes
        or a
        ld a,' '
        jr z,gn_end
gn2:    ld (de),a
        inc de
        inc b
        ld a,b
        cp 16
        jr c,gn1
gn_end: ld a,b
        ld (MBOX+2),a
        or a
        scf
        ret z
        and a
        ret

; HL in decimal, as few digits as it takes.
pdec:   ld ix,pow10
        ld c,0
pd1:    ld e,(ix+0)
        ld d,(ix+1)
        ld a,d
        or e
        ret z
        ld b,'0'-1
pd2:    inc b
        and a
        sbc hl,de
        jr nc,pd2
        add hl,de
        inc ix
        inc ix
        ld a,b
        cp '0'
        jr nz,pd3
        ld a,c
        or a
        jr nz,pd3
        ld a,e                  ; nothing yet, and not the last digit
        dec a
        jr nz,pd1
pd3:    ld a,b
        call pch
        ld c,1
        jr pd1
pow10:  dw 10000,1000,100,10,1,0

; HL: PETSCII ended by 0, on the screen: shifted space as space, shifted
; letters as letters, RVS ON and other control codes left out.
ppet:   ld a,(hl)
        inc hl
        or a
        ret z
        cp $A0
        jr nz,pp1
        ld a,' '
pp1:    and $7F
        cp ' '
        jr c,ppet
        call pch
        jr ppet

; ---------------------------------------------------------------- =
; = n: n in hex ($ or nothing before it), decimal (+) or binary (%),
; shown in all three: "= $C000 +49152 %11000000 00000000", 8 bits up to
; 255. RETURN on that line shows it again (what follows a number is left
; alone if a space comes first). Past $FFFF, or not a number: "?".
cmd_eq: ld hl,(lptr)
        call skipsp
        ld c,10
        cp '+'
        jr z,eq_pfx
        ld c,2
        cp '%'
        jr z,eq_pfx
        ld c,16
        cp '$'
        jr nz,eq_num
eq_pfx: inc hl
eq_num: ld de,0
        ld a,(hl)
        call hexval
        jp c,err                ; no digit at all
eq_dig: cp c
        jp nc,err               ; not one in this base
        push hl
        ld h,0
        ld l,a
        ld b,c
eq_mul: add hl,de               ; the digit + DE * the base
        jp c,err
        djnz eq_mul
        ex de,hl
        pop hl
        inc hl
        ld a,(hl)
        call hexval
        jr nc,eq_dig
        ld a,(hl)               ; the number ends with the line or a space
        or a
        jr z,eq_out
        cp ' '
        jp nz,err
eq_out: ex de,hl
        call lstart
        call putsi
        db "= $",0
        call phex4
        call putsi
        db " +",0
        push hl
        call pdec
        pop hl
        call putsi
        db " %",0
        ld a,h
        or a
        jr z,eq_lo
        call pbin
        call sp1
eq_lo:  ld a,l
        call pbin
        jp down

pbin:   ld c,a                  ; A in binary, 8 digits
        ld b,8
pb1:    ld a,'0'
        rl c
        adc a,0
        call pch
        djnz pb1
        ret

monend:

        end
