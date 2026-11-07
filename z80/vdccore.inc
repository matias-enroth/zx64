; vdccore.inc - the part of zx128's picture (z80/vdcpic.inc) the ROM's
; patches call, in the core below KPAGE (z80/zx128.asm) rather than the own
; area, which has no room for it: the CLS and SCROLL commands' hooks and
; LOAD's picture at once (blit). Nothing here is reached by a JR from
; vdcpic.inc or reaches it by one, so where it sits costs no time.
; (Only code: an EQU here naming what vdcpic.inc defines later would be 0.)

; The command table's CLS and SCROLL: the ROM's, the picture held
; meanwhile (blk_hold: no compare of a D_FILE half moved, to be moved or
; filled again), then noted (blk_pend), with interrupts off (an IRQ's
; pic_step takes it). Keep every register.
bh_hold:
        ld a,BLK_HOLD           ; (A: the ROM's CLS and SCROLL take nothing
        ld (blk_hold),a         ; in it)
        ld a,$C3                ; (pic_step's ps_blk: JP blk_step)
        ld (ps_blk),a
        ret

bh_scr: ld a,(pic_exp)          ; (expanded: a CLS leaves it so, the rows
        or a                    ; as they were for pic_x33)
        jr z,bh_sc
        ld a,b
        cp c
        ret c
        xor a
        ld (pic_sk),a
        ret
bh_sc:  call pm_wh
        ret nz
        jp pic_scr

cls_hook:
        call bh_hold
        call $0A2A
        push af
        push bc
        ld bc,24*256+24         ; B: rows up, C: within these
        jr bh_set
scr_hook:
        call bh_hold
        call $0C0E
        push af
        push bc
        ld a,(DF_SZ)
        ld b,a
        ld a,24
        sub b
        ld c,a
        ld b,1
        jr nc,bh_set
        ld c,0                  ; (DF_SZ past 24: no rows; whatever waited
                                ; dropped, else an empty operation noted)
bh_set: push hl
        ld a,i                  ; (P/V: interrupts on; read again if it says
        jp pe,bh_ie             ; off: an NMOS Z80 reads 0 if an interrupt
        ld a,i                  ; is taken during it)
bh_ie:  push af
        di
        ld hl,pic_su            ; the table's note (pic_scr): a SCROLL adds
        ld a,(pic_sk)           ; to one of the same rows (all of them at
        or a                    ; most); one of other rows, or a CLS after
        jr z,bh_tn              ; one, leaves it no use (u 0)
        ld a,(hl)
        cp c
        jr z,bh_ts
        ld (hl),0
        jr bh_tx
bh_ts:  ld a,(pic_sk)
        add a,b
        cp c
        jr c,bh_tk
        ld a,c
        jr bh_tk
bh_tn:  ld (hl),c
        ld a,b
bh_tk:  ld (pic_sk),a
bh_tx:  push bc                 ; the table scrolled with the display now,
        push de                 ; if it is whole (else pic_mode drops it)
        call bh_scr
        pop de
        pop bc
        ld a,(blk_pend)
        or a
        jr z,bh_new             ; nothing waiting
        ld a,c
        or a
        jr z,bh_drop
        ld a,b
        cp c
        jr nc,bh_new            ; all filled (a CLS): instead
        ld a,(blk_pu)
        cp c
        jr nz,bh_oth
        ld a,(blk_pend)         ; the same rows: k more, all at most
        add a,b
        cp c
        jr c,bh_k
        ld a,c
bh_k:   ld (blk_pend),a
        jr bh_x
bh_oth: jr c,bh_drop            ; fewer rows waiting: can't
        ld b,a                  ; more: if they are all filled, so are these
        ld a,(blk_pend)
        cp b
        jr nc,bh_x
bh_drop:
        xor a
        ld (blk_pend),a
        ld hl,(blk_nd)
        inc hl
        ld (blk_nd),hl
        jr bh_x
bh_new: ld a,b
        ld (blk_pend),a
        ld a,c
        ld (blk_pu),a
        ld a,$C3                ; (pic_step's ps_blk: JP blk_step)
        ld (ps_blk),a
bh_x:   xor a
        ld (blk_hold),a
        pop af
        jp po,bh_di
        ei
bh_di:  pop hl
        pop bc
        pop af
        ret

; pic_step from frame's poll (zx128.asm's pic_poll), pic_nirq set
; meanwhile: not the IRQ's, for pic_mvd.
pic_pstep:
        ld a,1
        ld (pic_nirq),a
        call pic_step
        xor a
        ld (pic_nirq),a
        ret

; ---------------------------------------------------------------- at once
; Every row written as D_FILE has it (whatever the shadow says: the VDC
; may show something else, the monitor's screen), and the shadow with it;
; then nothing waits.
pic_all:
        ld a,1                  ; (pic_nirq: not from the IRQ, pic_mvd)
        ld (pic_nirq),a
        call pa_go
        xor a
        ld (pic_nirq),a
        ret
pa_go:  ld a,255                ; (no budget: more than enough)
        ld (pic_left),a
        call pic_mode
        ret c
        xor a                   ; (block operations waiting or going: the
        ld (blk_pend),a         ; whole picture is written over them)
        ld (blk_k),a
        ld a,$11                ; (ps_blk: LD DE, nn)
        ld (ps_blk),a
        xor a
pa_row: ld (pic_crow),a
        ld a,255                ; (pic_src's walk: more than enough)
        ld (pic_left),a
        ld a,(pic_crow)
        call pic_src
        push hl
        ld a,(pic_crow)
        ld l,a                  ; the VDC's row: x 80
        ld h,0
        add hl,hl
        add hl,hl
        add hl,hl
        add hl,hl
        ld d,h
        ld e,l
        add hl,hl
        add hl,hl
        add hl,de
        vdc_addr
        ld a,(pic_crow)
        ld c,a
        call pic_shp
        pop hl
        ld bc,VDC
pa_ch:  ld a,(hl)
        ld (de),a
        vdc_bput
        or $40
        vdc_bput
        inc hl
        inc e
        ld a,e
        and 31
        jr nz,pa_ch
        ld a,(pic_crow)
        inc a
        cp 24
        jr c,pa_row
        xor a                   ; (the queue: written over)
        ld (pic_qn),a
        ret
