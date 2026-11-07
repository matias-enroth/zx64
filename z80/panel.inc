; panel.inc - zx128's panel beside the ZX81's picture (vdcpic.inc): the
; VDC's columns 64-79 of rows 0-23 and all of row 24, in character set 1
; (ASCII text at codes $80-$DF, the ZX81's own characters and their
; inverses at 0-127: tools/build.py's font128). What the F-keys do, the
; settings, and the messages zx64 shows over its top row (show), here at
; rows 13-14, 16 characters each, for as long as zx64 shows them (ovl).
; In common RAM (zx128.asm): the own area has no room for it, but for
; panelhi.inc's parts (show's messages, F2's colours).
;
; What is to be written waits as jobs, a byte a row (pn_d): bit 0 its
; text in columns 0-63 (row 24 only: spaces), bit 1 in columns 64-79
; (pn_row), bit 2 its attributes in columns 0-63 (the picture's; row
; 24's the panel's), bit 3 in columns 64-79 (the panel's). pic_step
; does them first (its pn_hook, a CALL while there are any), after a
; CLS's or SCROLL's block operations (blk_step, which ends with the VDC
; ready), a job at a time while the clock allows (PN_LIM steps after the
; rise, PN_LIMB while the picture is busy); without the window, a job a
; frame for PN_UNITS, while the picture isn't busy. A
; fill (attributes, spaces) is the VDC's block fill, polled, waited for;
; a row's text is written as the picture's runs are: unpolled in the
; window, else polled (pn_wr). R26 (the background) first, polled.
;   panel_all  the whole panel (pn_boot: zentry's, at once)
;   panel_set  the rows that follow a setting: 4, 9, 23, 24 and the
;              messages' (show: each setting's change shows one)
;   pn_col     every attribute, the picture's too, and R26 (F2)
;   pn_rep     both: pw_chk's (a write in a wrong window may have landed
;              anywhere, its address lost: in the panel, the attributes)
; Each changes AF BC HL.
;   (pn_cpu    row 24's CPU at once, polled: zx128.asm's, beside the
;              monitor's code; zsw calls it, com128.inc)

PN_LIM:  equ 10                 ; no job begins this many steps after the rise,
PN_LIMB: equ 2                  ; or this many while the picture is busy,
PN_LEFT: equ 6                  ; or with fewer than this many left
PN_UNITS: equ 32                ; no window: a job's units (polled: 16 bytes,
                                ; FB_COST a character, or a block fill)
pn_d:    equ KPAGE+$C0          ; the jobs, 25 bytes (KPAGE's page is free
pn_buf:  equ KPAGE+$64          ; there; zentry clears it), a row's text (16),
pn_i:    equ KPAGE+$74          ; the rows before this one have none,
pn_r26:  equ KPAGE+$75          ; 1: R26 to be written,
pn_shown: equ KPAGE+$76         ; 1: a message is on the panel,
pn_wait: equ KPAGE+$77          ; frames the jobs wait (pn_rep)
PN_REPW: equ 32                 ; pw_chk's: the picture first (sim128's bound_16k: 27)

panel_all:
        ld hl,pn_d
        ld b,25
pa_l:   ld a,(hl)
        or $0A
        ld (hl),a
        inc hl
        djnz pa_l
        dec hl
        ld (hl),$0F             ; (row 24: all of it)
pn_go:  xor a                   ; (the marks first, then these: the IRQ's
        ld (pn_i),a             ; pn_step may come between)
        ld a,$CD                ; (CALL)
        ld (pn_hook),a
        ret

panel_set:
        ld hl,pn_srow
pnt_l:  ld a,(hl)
        inc hl
        inc a
        jr z,pn_go
        push hl
        ld hl,pn_d-1
        ld c,a
        ld b,0
        add hl,bc
        set 1,(hl)
        pop hl
        jr pnt_l
pn_srow: db 4,9,13,14,23,24,$FF

pn_col: ld hl,pn_d
        ld b,25
pc_l:   ld a,(hl)
        or $0C
        ld (hl),a
        inc hl
        djnz pc_l
        ld a,1
        ld (pn_r26),a
        jr pn_go

; zentry's, at boot: the whole panel at once, polled (no picture yet:
; pic_unp 0), and row 23 again once SLOW or FAST is known (the ROM's
; start sets CDFLAG).
pn_boot:
        call panel_all
pb_l:   call pn_find
        jr z,pb_x
        call pn_job
        jr pb_l
pb_x:   ld hl,pn_d+23
        set 1,(hl)
        jp pn_go

pn_rep: ld a,PN_REPW            ; (the picture first: it has every cell to
        ld (pn_wait),a          ; write again)
        call panel_all
        jr pn_col

; The FAST and SLOW commands (the command table: tools/build.py), and
; LOAD's picture (blit: a loaded program has its own CDFLAG): row 23
; again. Keep every register (the commands). FAST writes it at once,
; polled: SET-FAST turns the interrupts off, and a running program has no
; IRQ to do the job until its next key wait.
fast_hook:
        call $0F23
        push af
        push bc
        push de
        push hl
        ld a,23
        call pn_now
        pop hl
        pop de
        pop bc
        pop af
        ret
slow_hook:
        call $0F2B
sf_mk:  push af
        push hl
        ld hl,pn_d+23
        set 1,(hl)
        call pn_go
        pop hl
        pop af
        ret
pn_blit:
        call pic_all
        jr sf_mk

; ---------------------------------------------------------------- a frame
pn_step:
        ld hl,pn_wait
        ld a,(hl)
        or a
        jr z,pn_sm
        dec (hl)
        ret
pn_sm:  ld a,(pn_shown)         ; a message shown, its time over: its rows
        or a                    ; again, empty
        jr z,pn_s0
        ld a,(ovl)
        or a
        jr nz,pn_s0
        ld (pn_shown),a
        ld (pn_i),a
        ld hl,pn_d+13
        set 1,(hl)
        inc hl
        set 1,(hl)
pn_s0:  ld a,(pn_r26)
        or a
        jr z,pn_s1
        xor a
        ld (pn_r26),a
        call pn_sc
        ld e,(hl)
        ld a,26
        ld bc,VDC
        call bc_w               ; (polled)
pn_s1:  call pn_find
        jr z,pn_done
        ld a,(pic_unp)
        or a
        jr z,pn_nw
        call pn_clk             ; the window: while the clock allows
        ret c
        push bc                 ; still in the blank? (else no window
        ld bc,VDC               ; from here: pw_trip)
        in a,(c)
        pop bc
        and $20
        jr z,pn_tr
        call pn_job
        jr c,pn_x               ; (bit 5 gone: pw_chk)
        jr pn_s1
pn_tr:  call pw_trip
        jr pn_x
pn_nw:  ld a,(pic_bsy)          ; no window: one job, for its units, while
        or a                    ; the picture isn't busy
        ret nz
        ld a,(pic_left)
        sub PN_UNITS
        ret c
        ld (pic_left),a
        call pn_job
        call pn_find
        call z,pn_done
        jr pn_x
pn_done:
        ld a,(pn_shown)         ; none left: the hook an LD DE, nn, unless
        or a                    ; a message is shown (its end is looked
        ret nz                  ; for each frame)
        ld a,$11
        ld (pn_hook),a
        ret
; Too few units left for the rest (a trip: none; no window, a job's):
; the frame ends there, as blk_step's does (pic_mode takes its own
; unchecked).
pn_x:   ld a,(pic_left)
        cp COST_MODE+COST_ROW
        ret nc
        pop hl                  ; (pn_hook's return)
        jp ps_end

; HL: the next job's row in pn_d, C the row (pn_i on to it). Z: none.
pn_find:
        ld a,(pn_i)
        ld c,a
        ld b,0
        ld hl,pn_d
        add hl,bc
pf_l:   ld a,c
        cp 25
        jr nc,pf_x
        ld a,(hl)
        or a
        jr nz,pf_x
        inc hl
        inc c
        jr pf_l
pf_x:   ld a,c
        ld (pn_i),a
        sub 25                  ; (Z: none)
        ret

; NC: a job may begin (the window's frame): before PN_LIM steps after the
; rise (PN_LIMB while the picture is busy) and PN_LEFT left. Keeps BC DE
; HL.
pn_clk: push bc
        ld bc,CIA2+7            ; (timer B counts down)
        in b,(c)
        ld a,(lk_t0)
        sub b
        ld b,a
        ld c,PN_LIM
        ld a,(pic_bsy)
        or a
        jr z,pk_1
        ld c,PN_LIMB
pk_1:   ld a,b
        cp c
        ccf
        jr c,pk_x
        call lk_left
        jr c,pk_x
        cp PN_LEFT
pk_x:   pop bc
        ret

; Row C's job at HL (pn_d + C): its lowest bit's, then cleared. Carry:
; bit 5 was gone at its end (pw_chk done). Changes AF BC DE HL.
pn_job: ld a,(hl)
        ld b,1                  ; B: the bit, D: its number (bit 0: the
        ld d,0                  ; panel's columns, bit 1: attributes)
pj_s:   rra
        jr c,pj_b
        sla b
        inc d
        jr pj_s
pj_b:   ld a,b
        cpl
        and (hl)
        ld (hl),a
        ld a,c
        call bo_r80             ; HL: the row's VDC address (keeps DE)
        bit 1,d
        jr z,pj_t
        set 3,h                 ; (+ $800: its attributes)
pj_t:   ld e,64
        bit 0,d
        jr z,pj_a
        ld a,l
        add a,64
        ld l,a
        jr nc,$+3
        inc h
        ld e,16
pj_a:   bit 1,d
        jr z,pj_tx
        push hl                 ; attributes: the picture's (columns 0-63
        call pn_sc              ; of rows 0-23), else the panel's
        inc hl
        ld a,c
        cp 24
        jr z,pj_p
        bit 0,d
        jr z,pj_f
pj_p:   inc hl
pj_f:   ld d,(hl)
        pop hl
        jr pn_wr
pj_tx:  bit 0,d                 ; text: row 24's columns 0-63 spaces, else
        ld d,$80                ; the row's (pn_row)
        jr z,pn_wr
        push hl
        ld a,c
        call pn_row
        pop hl
        ld de,$FF10

; E bytes to the VDC at HL: D the byte, or $FF: pn_buf's. 64 of a byte
; by the VDC's block fill (blk_cfg: if boot128 found it works), polled,
; waited for; else in the window (LK_MODE 1) unpolled, each access 22 T
; or more after the one before, as vdcpic.inc's pw_one; else polled
; (pn_pol). Carry: bit 5 gone at the end (pw_chk: its writes may be lost,
; its address's too).
pn_wr:  ld bc,VDC
        ld a,e
        cp 64
        jr nz,pw_s
        ld a,(blk_cn)
        or a
        jr z,pw_s
        ld a,(blk_r24)          ; (R24: fills)
        call bo_m24
        ld e,d                  ; R18/R19, then R31's byte, then R30
        ld a,31
        call bc_hl
        ld a,(blk_fn)
        ld e,a
        ld a,30
        call bc_w
        call bc_rdy             ; (done)
        and a
        ret
pw_s:   ld a,(pic_unp)
        dec a
        jr nz,pn_pol
        in f,(c)                ; (ready: after a block operation, polled)
        jp p,$-2
        ld a,18
        out (c),a
        inc c
        out (c),h
        dec c
        ld a,19
        nop
        out (c),a
        inc c
        out (c),l
        dec c
        ld a,31
        nop
        out (c),a
        inc c
        ld hl,pn_buf
        ld a,d
        inc a
        jr z,pw_c
pw_f:   out (c),d               ; (26 T a byte)
        dec e
        jp nz,pw_f
        jr pw_e
pw_c:   ld a,(hl)               ; (39 T)
        out (c),a
        inc hl
        dec e
        jp nz,pw_c
pw_e:   dec c                   ; bit 5 still set?
        in a,(c)
        and $20
        ret nz
        call pw_chk
        scf
        ret
pn_pol: push de                 ; polled (no carry)
        ld bc,VDC
        ld e,h
        ld a,18
        call bc_w
        ld e,l
        inc a
        call bc_w
        ld a,31
        out (c),a
        pop de
        ld hl,pn_buf
pp_l:   ld a,d
        inc a
        ld a,d
        jr nz,pp_b
        ld a,(hl)
pp_b:   vdc_bput
        inc hl
        dec e
        jr nz,pp_l
        and a
        ret

; ---------------------------------------------------------------- a row
; pn_buf: row A's 16 characters (set 1). Changes AF BC DE HL.
pn_row: ld c,a
        ld hl,pn_buf
        ld b,16
pr_sp:  ld (hl),$80             ; (a space)
        inc hl
        djnz pr_sp
        ld hl,pn_txt
pr_t:   ld a,(hl)               ; the row's text, if it has one
        inc hl
        cp c
        jr z,pr_got
        inc a
        jr z,pr_dyn             ; ($FF: the end)
        ld a,(hl)               ; (past it)
        inc a
        add a,l
        ld l,a
        jr nc,pr_t
        inc h
        jr pr_t
pr_got: ld de,pn_buf
        call pn_asc
pr_dyn: ld a,c                  ; then the settings
        cp 4
        jr z,pr_joy
        cp 9
        jr z,pr_mem
        cp 23
        jr z,pr_23
        cp 24
        jr z,pr_cpu
        sub 13
        cp 2
        ret nc
        ld e,a                  ; rows 13 and 14: the message's halves
        ld a,(ovl)
        or a
        ret z
        ld (pn_shown),a
        ld hl,(ovl_msg)
        ld a,e
        or a
        jr z,pr_m
        ld de,16
        add hl,de
pr_m:   ld de,pn_buf
        ld b,16
pr_mc:  ld a,(hl)               ; ZX81 codes, set 1's: inverse ones at 64-127
        and $BF
        bit 7,a
        jr z,pr_mp
        xor $C0
pr_mp:  ld (de),a
        inc hl
        inc de
        djnz pr_mc
        ret
pr_joy: ld a,(joyidx)           ; F3's: 5678+0, or the keys taught
        ld hl,pn_jtx
        ld de,pn_buf+8
        jr pn_nas
pr_cpu: ld a,(MBOX)              ; row 24's CPU: the 8502 while a command
        add a,$FF               ; waits in the mailbox for it (from zsw's
        sbc a,a                 ; first pn_cpu to its answer, which clears
        and 1                   ; it), else the Z80
        ld hl,pn_ctx
        ld de,pn_buf+1
        jr pn_nas
pr_mem: ld de,pn_buf+10         ; F8's
pr_sz:  ld a,(ramsize)
        ld hl,pn_stx
        jr pn_nas
pr_23:  ld a,(CDFLAG)           ; SLOW or FAST (bit 6), under row 24's
        rlca                    ; CPU (the size is F8's, row 9)
        rlca
        cpl
        and 1
        ld hl,pn_ftx
        ld de,pn_buf+1
; (pn_nas) the A-th text from HL on to DE, as pn_asc. Changes AF BC DE HL.
pn_nas: or a
        jr z,pn_asc
        ld b,a
pn_ns:  ld a,(hl)
        inc a
        add a,l
        ld l,a
        jr nc,$+3
        inc h
        djnz pn_ns
; The text at HL (its length, then ASCII) to DE, as set 1's codes. Keeps
; C.
pn_asc: ld b,(hl)
pn_ac:  inc hl
        ld a,(hl)
        add a,$60
        ld (de),a
        inc de
        djnz pn_ac
        ret

pn_txt:                         ; (each: its row, its length, its text)
        include "ver128.inc"    ; (row 0: " zx128 " and build.py's VERSION)
        db 2,13,"F1 type-ahead"
        db 3,10,"F2 colours"
        db 4,6,"F3 joy"
        db 6,11,"F5 debugger"
        db 8,8,"F7 reset"
        db 9,9,"F8 memory"
        db $FF
pn_jtx: db 6,"5678+0",8,"own keys"
pn_stx: db 4,"  1K",4," 16K",4," 32K"
pn_ftx: db 4,"SLOW",4,"FAST"
pn_ctx: db 3,"Z80",4,"8502"
