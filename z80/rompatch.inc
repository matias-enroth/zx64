; rompatch.inc - the ROM's display and key wait, as zx64 patches them
; (tools/build.py's patches): frame (DISPLAY-1's picture), slowfast
; (SLOW/FAST), keywait (the editor's key wait), and notbad. Shared by zx64
; and zx128. The includer provides:
;
;   equates   CDFLAG DEBOUNCE LASTK KALL KALL_ROM
;   variables monreq d1active tick irqseen hello edit eframes kbuf
;             (vars.inc)
;   code      mon_call (F5), ovl_tick, show and msg_hello (the
;             version, once), frames_dec, mykbd, kq_pop, kq_flush
;             (kbd.inc), and the vic_rd/vic_wr macros
;   macro     kb_lkhold: as keywait hands the ROM a key from the type-
;             ahead queue (may change A): see irq.inc's irq_lastk
;   macro     kw_hello: at the first key wait after power on, before the
;             version is shown (may change A, F, BC, DE and HL)
;   macro     pic_poll: pic_tick (the picture's work for a frame, see
;             irq.inc) from here, where interrupts are on (frame's EI): an
;             IRQ may still come in the middle of it

; ---------------------------------------------------------------- frame
; Replaces the picture part of the ROM's DISPLAY-1 ($0277): wait for the
; next frame, then the ROM loops back to $0229 (FRAMES, keyboard).
frame:  ld a,(monreq)           ; F5 (seen by KEYBOARD): the monitor
        or a
        call nz,mon_call
        ld a,2
        ld (d1active),a
        ei
        ld hl,tick
        ld c,(hl)
        ld b,0
fr_wait:
        ld a,(hl)
        cp c
        ret nz                  ; the IRQ has been: next frame
        vic_rd $19              ; the raster flag, which the VIC latches at
        rra                     ; line 250 even with its IRQ masked
        jr nc,fr_clr
        call notbad             ; (but see notbad)
        jr c,fr_wait
        ld a,(irqseen)
        or a
        jr z,fr_poll            ; no IRQ so far: do its picture work here
        inc b                   ; /INT has worked, so the IRQ should take
        ld a,b                  ; the flag at once. Still set at the next
        cp 2                    ; read: no IRQs come (irqseen was set by a
        jr c,fr_wait            ; call, USR 8192, or the wire came loose):
        xor a                   ; poll from now on
        ld (irqseen),a
fr_poll:
        ld a,$FF
        vic_wr $19
        inc (hl)
        call ovl_tick
        pic_poll                ; (interrupts on: see pic_poll)
        ret
fr_clr: ld b,0                  ; clear: the count starts again
        jr fr_wait

; The raster flag ($D019 bit 0) can read as set when it isn't, just
; after a bad line, when the VIC has had the bus: seen on hardware, the
; monitor's frame wait came back every 32 lines. A flag read while the
; raster is where there are no bad lines is believed: line 250 (where
; it is set) to the end of the frame, and the top border. Carry: not
; there, don't believe it. Keeps all but A and the flags.
notbad: vic_rd $11              ; bit 7: the line's bit 8, so 256-311
        rla
        ccf
        ret nc
        vic_rd $12
        cp 250
        ret nc                  ; 250-255
        cp 48                   ; 0-47: NC, believed; 48-249: carry
        ccf
        ret

; ---------------------------------------------------------------- SLOW/FAST
; Replaces ROM $0207, which starts or stops the display to suit CDFLAG
; bit 6. SLOW: interrupts on, the IRQ does the display's work. FAST: off,
; as a ZX81 takes none in FAST mode. (SET-FAST, $02E7, is patched to DI.)
slowfast:
        ld hl,CDFLAG
        res 7,(hl)
        bit 6,(hl)
        jr z,sf_fast
        ei
        ret
sf_fast:
        di
        ret

; The editor's key wait (DISPLAY-6): $04CC, CALL Z,DISPLAY-1, patched to
; call here. INPUT waits here too. Returns as DISPLAY-1 does with a key:
; LAST_K set, CDFLAG bit 0 set, HL = CDFLAG.
; frame() has the interrupts on while the ROM waits; in FAST mode they go
; off again once the key is taken, before anything runs.
; With kbuf (F1), keys come from the type-ahead queue instead of through
; the ROM's debounce (see edges).
keywait:
        push af
        ld a,(hello)            ; the first time after power on: the version
        or a                    ; on the top row
        jr z,kw_go
        xor a
        ld (hello),a
        push hl
        kw_hello
        ld hl,msg_hello
        call show
        pop hl
kw_go:  ld a,(edit)             ; back from a program: what was typed
        or a                    ; meanwhile was for it, not the editor
        call z,kq_flush
        ld a,1
        ld (edit),a
        ld a,KALL_ROM           ; the ROM's byte back, for graphics mode
        ld (KALL),a
        xor a
        ld (eframes),a
        ld a,(kbuf)
        or a
        jr nz,kw_buf
        pop af
kw_call:
        call $0229
        push af                 ; what was queued meanwhile was the ROM's key
        call kq_flush           ; too (F1 back on during its wait): or it
        pop af                  ; would come twice
kw_end: push af
        ld a,(CDFLAG)
        bit 6,a
        jr nz,kw_done
        di
kw_done:
        pop af
        ret

kw_buf: pop af
kb_loop:
        xor a                   ; as if the ROM's debounce had run down,
        ld (DEBOUNCE),a         ; for when F1 switches back to it
        call mykbd              ; a scan: new key presses into the queue
        call kq_pop
        jr nz,kb_key
        ld a,(kbuf)             ; F1 just now: the ROM's own way from here
        or a
        jr z,kw_call
        call frames_dec         ; FRAMES, as DISPLAY-1 counts it
        call frame
kw_frame:
        jr kb_loop
kb_key: kb_lkhold               ; (the IRQ's LAST_K held back a while,
        ld (LASTK),hl           ; from before this store)
        xor a
        ld (d1active),a         ; the IRQ scans again from the next frame
        ld hl,CDFLAG
        set 0,(hl)              ; a key, as DISPLAY-1 says it
        jr kw_end
