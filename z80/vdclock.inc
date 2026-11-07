; vdclock.inc - the Z80's tick locked to the VDC's frame, so
; the picture's writes go into the VDC's vertical blank (status $D600 bit
; 5), where the 8563 takes a byte as fast as the Z80 can give it
; (measured on the C128).
;
; The VDC's frame (19,674 cycles on the C128: 312 lines of 64 us) is a
; little longer than the VIC's (19,656): its blank starts ~0.28 raster
; lines later each VIC frame (measured on the C128). So the VIC's raster
; compare is moved every frame, to LK_LEAD lines before where the next
; blank will start; the IRQ (irq.inc's irq_early: first in irqh)
; then waits for bit 5 to rise (bounded), notes the raster line it rose
; on (the next compare is that, less the drift and LK_LEAD), and runs
; pic_step at once with the window open (pic_unp): the picture's writes
; then cost what the Z80 takes, up to LK_WIN steps of timer B after the
; rise (5.46 ms of the 7.17 ms blank). One IRQ a VDC frame: FRAMES counts
; at 50.08 Hz.
;
; The window opens only on a rise of bit 5 seen in this IRQ: whatever
; the lock does, the writes start at the blank's start. Arrived with bit
; 5 set already (late: interrupts were off, or the lock is wrong), or no
; rise within the bound: today's polled writes this frame, and the
; compare is moved (once late: on as predicted; twice, or no rise: the
; search). The search (at boot, after LOAD or FAST, which stop the IRQ):
; in the blank, LK_BACK lines earlier next frame; else waits up to
; LK_SRCHN for the rise, then on from where it gave up.

LK_MODE: equ 1                  ; pic_unp in the window: its writes unpolled
                                ; (vdcpic.inc's pw_run)
LK_LEAD: equ 3                  ; lines before the blank the IRQ is aimed
LK_WIN:  equ 21                 ; the window's length, in timer B steps (below)
LK_WAITN: equ 14                ; locked: the wait's bound (2 polls, ~71 T, each)
LK_SRCHN: equ 112               ; searching: ~64 lines
LK_BACK: equ 56                 ; searching, in the blank: this much earlier
LK_DRIFT: equ 0                 ; lines the VDC's blank moves up a VIC frame
                                ; (-0.28 on the C128: the wait steers it)

lk_on:   equ PSTATE+42          ; 1: locked (0 at boot: zentry clears PSTATE)
lk_late: equ PSTATE+43          ; locked, arrived late this many times running
lk_cmp:  equ PSTATE+44          ; the compare line set last (2 bytes)
lk_rb:   equ PSTATE+46          ; searching: the line bit 5 rose on (2 bytes)
lk_t0:   equ PSTATE+$A0         ; CIA 2 timer B's high byte as it rose (in
                                ; pic_ops' room, which nothing else uses)
lk_wcut: equ PSTATE+$A1         ; steps trips have cut off the window's end
                                ; (vdcpic.inc's pw_trip; 0 at boot and when
                                ; a lock is found; a step back after 256
                                ; frames with no trip: a C128 whose blank is
                                ; shorter than LK_WIN pays a trip frame
                                ; every 256 or so)
lk_wok:  equ PSTATE+$A2         ; frames since a trip or the last step back
LK_WMIN: equ 12                 ; a window shorter than this: polled instead
                                ; (a frame's own work and hints take ~9)
lk_rel:  equ PSTATE+$A4         ; 0: lk_rb is the line it rose on; else the
                                ; lines the next compare moves up, plus 2
LK_WLO:  equ 1                  ; locked: waited fewer turns: a line earlier,
LK_WHI:  equ 4                  ; this many or more: a line later
; In the window the picture's time is CIA 2's timer B (free running, 256
; cycles a step of its high byte), not its units: no run goes past LK_WIN
; steps (5.46 ms) after the rise (vdcpic.inc's LIM_Q and LIM_B end its
; compares).

; irq_early: the picture first, in the blank if the lock has it.
pic_irq:
        ld a,(lk_wcut)          ; cut (pw_cut): a step back after 256 frames
        or a                    ; with no trip (lk_wok), to LK_WIN
        jr z,pi_0
        ld hl,lk_wok
        inc (hl)
        jr nz,pi_0
        dec a
        ld (lk_wcut),a
        neg
        add a,LK_WIN
        call lk_wset
pi_0:   call lk_sync
        or a
        jr z,pi_u
        ld a,(lk_wcut)          ; the window cut below LK_WMIN steps by
        cp LK_WIN-LK_WMIN+1     ; trips (vdcpic.inc's pw_trip): the picture
        ld a,LK_MODE            ; polled, the lock kept
        jr c,pi_u
        xor a
        ld (pic_unp),a
        call pic_step
        jr pi_k
pi_u:   ld (pic_unp),a          ; (pic_step jumped to or called with nothing
        or a                    ; pushed first: vdcpic.inc's pic_mvd finds
                                ; irq_early's return 6 or 8 bytes up; sim128's
                                ; pic_mvd_slots sees only the call's 8)
        jp z,pic_step           ; (no window: polled, as before)
        call pic_step
pi_k:   xor a
        ld (pic_unp),a
        ld hl,(lk_rb)           ; the window was open: the next IRQ LK_LEAD
        ld a,(lk_rel)           ; lines before the next blank
        or a
        jr z,pi_s
        ld hl,(lk_cmp)          ; locked: on from this one's (lk_rb: the
        sub 2                   ; drift, give or take a line; signed, kept
        ld e,a                  ; plus 2: 0 means just found)
        add a,a
        sbc a,a
        ld d,a
        and a
        sbc hl,de
        call l_norm
        jp lk_set
pi_s:   ld de,LK_DRIFT+LK_LEAD  ; just found: from the line it rose on
        call l_sub
        jp lk_set

; A: LK_MODE if bit 5 rose just now, else 0 (and the next compare set).
lk_sync:
        ld bc,VDC
        in a,(c)
        and $20
        jr nz,lk_inb            ; in the blank already
        ld e,LK_WAITN
        ld a,(lk_on)
        or a
        jr nz,lk_w
        ld e,LK_SRCHN
lk_w:   in a,(c)
        and $20
        jr nz,lk_edge
        in a,(c)
        and $20
        jr nz,lk_edge
        dec e
        jr nz,lk_w
lk_miss:                        ; no rise: it is later. Searching from here
        call lk_tb
        xor a
        ld (lk_on),a
        ld (lk_late),a
        call rline
        ld de,LK_DRIFT+LK_LEAD
        jr lk_sub
lk_inb: ld a,(lk_on)            ; late
        or a
        jr z,lk_back
        ld hl,lk_late
        inc (hl)
        ld a,(hl)
        cp 2
        jr nc,lk_lost
        ld hl,(lk_cmp)          ; once: as predicted (the IRQ was held up?)
        ld de,LK_DRIFT
        jr lk_sub
lk_lost:
        xor a
        ld (lk_on),a
        ld (lk_late),a
lk_back:
        call lk_tb
        call rline              ; searching, in the blank: earlier
        ld de,LK_DRIFT+LK_BACK
lk_sub: call l_sub
        call lk_set
        xor a
        ret
lk_edge:
        ld bc,CIA2+7            ; the window's clock
        in a,(c)
        ld (lk_t0),a
        ld a,(lk_on)
        or a
        jr z,lk_found
        xor a                   ; locked: the wait says where the next goes
        ld (lk_late),a
        ld a,e                  ; (E: the wait's turns left)
        cp LK_WAITN-LK_WHI
        ld a,(LK_DRIFT-1)&$FF   ; waited long: aim a line later
        jr c,lk_rel1
        ld a,e
        cp LK_WAITN-LK_WLO+1
        ld a,LK_DRIFT           ; about right
        jr c,lk_rel1
        inc a                   ; hardly: a line earlier
lk_rel1:
        add a,2
        ld (lk_rel),a
        ld a,LK_MODE
        ret
lk_found:
        call rline              ; searching: the line it rose on
        ld (lk_rb),hl
        ld bc,CIA2+$0F          ; the window's clock never started yet (a
        in a,(c)                ; first IRQ found the rise, with no search
        rra                     ; before it)? From now, then
        jr c,lk_fd
        call lk_tb
        ld a,$FF
        ld (lk_t0),a
lk_fd:
        xor a                   ; (a new lock: the window as long as it may,
        ld (lk_wcut),a          ; whatever trips cut from the last)
        ld a,LK_WIN
        call lk_wset
        xor a
        ld (lk_rel),a
        ld (lk_late),a
        inc a
        ld (lk_on),a
        ld a,LK_MODE
        ret

; CIA 2's timer B from $FFFF, running on (searching: before any window).
lk_tb:
        push bc
        ld bc,CIA2+6
        ld a,$FF
        out (c),a
        inc c
        out (c),a
        ld c,$0F
        ld a,$11                ; start, load, continuous, phi2
        out (c),a
        pop bc
        ret

; The window's steps left (LK_WIN - lk_wcut - those since the rise, carry
; if none).
; Changes AF BC.
lk_left:
        ld bc,CIA2+7
        in b,(c)
        ld a,(lk_t0)
        sub b                   ; (it counts down)
        ld b,a
lkl_w:  ld a,LK_WIN             ; (less what trips have cut: lk_wset)
        sub b
        ret

; The window's end (A steps after the rise) into the code that looks at it:
; lk_left, vdcpic.inc's pde_k (the fit) and psm_w (the window has time).
; (Immediates: they cost nothing at each run.) Changes AF.
lk_wset:
        ld (lkl_w+1),a
        dec a
        ld (pde_wc+1),a
        ld (pde_wd+1),a
        dec a
        ld (psm_wc+1),a
        ret

; The raster compare (and lk_cmp) <- line HL (0-311). Changes AF BC.
lk_set: ld (lk_cmp),hl
        ld bc,VIC+$12
        out (c),l
        dec c
        in a,(c)
        and $7F
        bit 0,h
        jr z,ls_lo
        or $80
ls_lo:  out (c),a
        ret

; HL: the raster line now (0-311). Changes AF BC.
rline:  ld bc,VIC+$12
        in l,(c)
        dec c
        in h,(c)                ; $D011: bit 7 is the line's bit 8
        inc c
        in a,(c)
        cp l
        jr nz,rline             ; moved on meanwhile: again
        ld a,h
        rlca
        and 1
        ld h,a
        ret

; HL (-312 to 623) to 0-311. Changes F, DE.
l_norm: bit 7,h
        jr z,ln_p
        ld de,312
        add hl,de
        ret
ln_p:   ld de,-312
        add hl,de
        ret c
        ld de,312               ; (was below 312)
        add hl,de
        ret

; HL = HL - DE, mod 312 (both 0-311). Changes F, DE.
l_sub:  and a
        sbc hl,de
        ret nc
        ld de,312
        add hl,de
        ret
