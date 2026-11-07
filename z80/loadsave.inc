; loadsave.inc - LOAD and SAVE, as zx64 patches them: the name to the
; mailbox and the other CPU does the disk I/O (call6510). Shared by zx64
; and zx128. The includer provides:
;
;   equates   NAMEFN ERR_F MBOX CMD_LOAD CMD_SAVE ST_TOOBIG
;   code      bp_off (the monitor's breakpoints out), lstat (the progress
;             bar; keeps DE and C), txt_load txt_save (msgs.inc),
;             setname (setname.inc), call6510, blit (the whole picture
;             at once), slowfast

; ---------------------------------------------------------------- LOAD/SAVE
; Replace ROM LOAD ($0340) and SAVE ($02F6). In syntax-checking mode NAME
; returns straight to our caller's caller, as it does for the ROM.
myload: call NAMEFN
        jr c,io_err             ; LOAD "": no name (a tape would load the next program)
        call bp_off             ; the monitor's breakpoints out first
        ld hl,txt_load
        call lstat
        call setname
        ld a,CMD_LOAD
do_io:  ld (MBOX),a
        call call6510
        call blit               ; the picture over the top row at once
        ld a,(MBOX+1)
        or a
        jp z,slowfast           ; done: interrupts back as SLOW/FAST says,
        cp ST_TOOBIG            ; as the ROM's LOAD ends (the loaded
        jr z,io_big             ; program may have the other mode)
io_err: rst 8
        db $0C                  ; report D
io_big: rst 8
        db $03                  ; report 4, no room

mysave: call NAMEFN
        jp c,ERR_F              ; SAVE "": report F, as the ROM does
        ld hl,txt_save
        call lstat
        call setname
        ld a,CMD_SAVE
        jr do_io
