; vdcpic.inc - zx128's ZX81 picture on the VDC, in zx128's own code area
; (z80/zx128.asm). D_FILE's 24 rows of 32 characters at the VDC's rows
; 0-23, columns 0-63: each character two cells of set 0, left = z and
; right = z | $40, the ZX81's pixels doubled, so the picture keeps its
; shape (the fonts: tools/build.py, c128/boot128.asm). Their attributes
; never change.
;
; The VDC's RAM is reached only through $D600/$D601. So a shadow (SHADOW)
; is compared with D_FILE; what differs goes into the shadow at once and,
; as a run (where, how long), onto a queue (pic_q); the runs are written
; from the shadow in the VDC's vertical blank, where the 8563 takes a
; byte as fast as the Z80 gives it (the window: vdclock.inc). The shadow
; is what the VDC shows once the runs waiting are written. pic_step does
; a frame's work, from the IRQ in SLOW mode (vdclock.inc's pic_irq):
;   - the rows where something is likely being printed (the hints:
;     DF_CC's row and the one above it, and while the editor waits for a
;     key, its lower screen; collapsed, after a SCROLL's block operation,
;     the last row it moved) compared first;
;   - the runs waiting written, the last queued first (the hints' first),
;     as many as fit in the window;
;   - then the sweep, through the rows from where it stopped the frame
;     before (in the middle of a row if that is where it stopped), each
;     row's runs written at once while the window lasts, queued after it.
; A row begins only while the clock allows: LIM_Q steps of CIA 2's timer
; B after the blank's rise, or LIM_B while there is much to do (from when
; HOT characters were found in a frame to the end of the next). The
; compare decides what is written; the hints only say where to look
; first, so the picture always ends up as D_FILE is.
;
; Without a window (boot, after LOAD or FAST, an IRQ late or missed, or
; frame's poll: pic_unp 0) a frame is a plain bounded loop: rows for the
; units (BUDGET, COST_ROW each), then FB_CHARS characters of what waits,
; written polled. A collapsed display's own work (finding its rows,
; copying them) costs units too, window or not.
;
;   pic_step  a frame's work (vdclock.inc's pic_irq; frame's pic_poll)
;   pic_all   the whole picture at once, no budget (blit: after LOAD;
;             later after the monitor), the queue with it (vdccore.inc,
;             in the core, as are the CLS and SCROLL hooks). With
;             interrupts off: an IRQ's pic_step would move the VDC's
;             address (hw128.inc's vdc_put).
; Both change AF BC DE HL. A 16K ZX81's display is expanded (33 bytes a
; row); a 1K program's is collapsed, a row ending at its $76, and is
; padded with spaces, as zx64's blit_c does.
;
; The includer provides: DFILE VARS, edit (vars.inc), the vdc_addr and
; vdc_bput macros (hw128.inc), vdclock.inc's lk_t0, lk_left, LK_MODE.
; zentry clears the shadow and the state, which is what the VDC shows at
; the start: boot128 fills the screen with $00, and one code repeated
; draws a row of spaces (both halves of a space are blank).

SHADOW:  equ $C000              ; 24 rows x 32: the ZX81 codes, (row & 7) << 5 | row >> 3 << 8
PSTATE:  equ $C300              ; the picture's state, a page:
pic_row: equ PSTATE             ;  the sweep's next row
pic_left: equ PSTATE+1          ;  units left in this frame
pic_used: equ PSTATE+2          ;  units the last pic_step spent
pic_stamp: equ PSTATE+3         ;  pic_step's count: pic_mark's mark
pic_exp: equ PSTATE+4           ;  1: the display is expanded, 0 collapsed
pic_known: equ PSTATE+5         ;  collapsed: rows 0 to this have pic_rtab
pic_scol: equ PSTATE+8          ;  the sweep's row goes on from this column
pic_from: equ PSTATE+9          ;  pic_do starts at this column,
pic_stop: equ PSTATE+10         ;  and stopped at this one (carry)
pic_crow: equ PSTATE+11         ;  the row pic_do is comparing
pic_e0:  equ PSTATE+12          ;  where a run started (the shadow's low byte)
pic_want: equ PSTATE+13         ;  collapsed: the row pic_start is after
pic_tdf: equ PSTATE+14          ;  collapsed: D_FILE as pic_rtab was made,
pic_tvar: equ PSTATE+16         ;  VARS last frame,
pic_blen: equ PSTATE+20         ;  pic_buf's length before its spaces
pic_odd: equ PSTATE+21          ;  collapsed: a line had no $76 (pic_mode)
pic_lst: equ PSTATE+22          ;  src_c: where the line starts (2 bytes)
pic_hres: equ PSTATE+24         ;  the sweep's units while the hints work
pic_stall: equ PSTATE+25        ;  collapsed: the sweep got no row done last frame
pic_hback: equ PSTATE+27        ;  1: the hints' rows, found back from VARS
pic_sback: equ PSTATE+28        ;  src_c: this row was
pic_brow: equ PSTATE+29         ;  pic_bstart: this row starts at
pic_bpos: equ PSTATE+30         ;  this (2 bytes)
pic_bend: equ PSTATE+34         ;  pic_bstart: the row after it starts here
pic_llim: equ PSTATE+36         ;  pic_line looks at this many bytes at most
pic_walked: equ PSTATE+37       ;  collapsed: every row of the table walked
pic_nirq: equ PSTATE+38         ;  1: pic_step not from the IRQ (frame's poll,
                                ;  pic_all; pic_mvd)
pic_fwd: equ PSTATE+40          ;  1: rows found on from D_FILE only
pic_unp: equ PSTATE+41          ;  the VDC's blank: 0 not (no window), else
                                ;  LK_MODE (vdclock.inc): how its writes go
pic_mark: equ PSTATE+$30        ;  24: pic_stamp as the row was last done
pic_rtab: equ PSTATE+$48        ;  25 x 2: collapsed: where each row starts
pic_qn:  equ PSTATE+$7A         ;  runs waiting in pic_q (redraw8l.asm reads it)
pic_qp:  equ PSTATE+$7B         ;  where the next one goes (2 bytes)
pic_hot: equ PSTATE+$7D         ;  characters found this frame (255 at most)
pic_bsy: equ PSTATE+$7E         ;  frames the busy limit still holds
pic_wn:  equ PSTATE+$7F         ;  characters the writes may still take
pic_buf: equ PSTATE+$80         ;  a collapsed row, padded: 32 codes
                                ; ($A0-$A4: vdclock.inc's)
pic_erot: equ PSTATE+$A5        ;  the editor's row a frame couldn't do (0 none)
blk_pend: equ PSTATE+$A8        ;  block operations (blk_step): waiting, rows up
                                ;  (0: none; as many as blk_pu: all filled)
blk_pu:  equ PSTATE+$A9         ;  within this many rows from the top,
blk_k:   equ PSTATE+$AA         ;  being done: rows up (0: none),
blk_u:   equ PSTATE+$AB         ;  within these rows,
blk_i:   equ PSTATE+$AC         ;  the next row
pic_sk:  equ PSTATE+$AD         ;  collapsed: SCROLLs since the table, rows
pic_su:  equ PSTATE+$AE         ;  up (0: none), within these (pic_scr)
pic_srow: equ PSTATE+$AF        ;  collapsed: blk_step's row first, + 1 (0:
                                ;  none); bit 7: its frame, no sweep
blk_ns:  equ PSTATE+$B0         ;  block operations begun (2 bytes),
blk_nd:  equ PSTATE+$B2         ;  waiting ones dropped (2 bytes)
blk_md:  equ PSTATE+$B4         ;  R24's mode now: 1 copy, 2 fill, else not known
blk_hold: equ PSTATE+$B5        ;  frames the picture holds for a CLS or SCROLL
blk_j:   equ PSTATE+$B8         ;  being done: the shadow's next row
pic_btab: equ PSTATE+$C0        ;  25 x 2: rows found back from VARS (pic_bstart)
pic_lim: equ PSTATE+$F2         ;  no row begins this many steps after the rise
pic_hlo: equ PSTATE+$F3         ;  the hints' rows this frame: from this one,
pic_hn:  equ PSTATE+$F4         ;  this many
pic_e1:  equ PSTATE+$F5         ;  where a run ends (the shadow's low byte)
pic_pend: equ PSTATE+$F6        ;  1: the run pic_e0 to pic_e1 is pending
pic_rm:  equ PSTATE+$FA         ;  the row: bit 0, its runs look at the clock
                                ;  (HARD); bit 1, begun in the window; bit 2,
                                ;  the run begun 2 steps before HARD
pic_hcc: equ PSTATE+$F7         ;  DF_CC as its hint last looked (2 bytes),
pic_hcl: equ PSTATE+$F9         ;  1: and its rows were the shadow's then
                                ;  (collapsed, row + 2: its own looked at)
pic_lf:  equ PSTATE+$FB         ;  pic_scn: the lowest row not after a $76,
pic_hg:  equ PSTATE+$FC         ;  the highest (pic_fix: the highest not
pic_ns:  equ PSTATE+$FD         ;  after one moved), the rows looked at + 1

; A collapsed display's costs, and the rows' without the window, in units
; of ~92 T (50 us at the C128's ~1.85 MHz), from the Z80's T-states
; (tools/sim128.py's pic_t).
; (An equ may use only those above it: z80asm takes a later one as 0.)
BUDGET:  equ 120                ; units a frame (6 ms)
COST_STEP: equ 9                ; a frame's own (the display's kind, the hints)
COST_ROW: equ 17                ; comparing a row (and finding it, expanded)
COST_WALK: equ 4                ; collapsed: bytes looked through a unit (4:
                                ; pic_start divides by shifting), and
WALK_ROW: equ 4                 ; a row's start found, and
COST_SYNC: equ 4                ; a row more walked for DF_CC's (pcc_w; and
WALK_MAX: equ WALK_ROW+33/COST_WALK+COST_SYNC ; a walk's margin): so at most
                                ; this for a line
BACK_ROW: equ WALK_ROW+COST_SYNC+3 ; a row's start found back from VARS (with
BACK_MAX: equ BACK_ROW+34/COST_WALK ; its callers' loops), at most this
COST_COPY: equ 14               ; a collapsed row's line found and copied,
COPY_MAX: equ COST_COPY+33/2+32/4 ; + its bytes / 2 and the spaces after it
                                ; / 4: at most this
CHK_MAX: equ 5+24/2             ; the collapsed table checked: 5 + 1/2 a row
FIX_SCN: equ 5+25               ; the table carried over (pic_fix): rows
                                ; looked at moved, from row 24 down (~95 T
                                ; a row), and below where they were (1/2),
FIX_MAX: equ FIX_SCN+24/2+1     ; then those past the change moved (~57 T
                                ; each): at most this, and the rows between
                                ; found back (BACK_MAX each)
SCR_MAX: equ 28                 ; the SCROLLs noted done to it (pic_scr)
X33_MAX: equ 14                 ; an expanded display's rows as it (pic_x33)
COST_MODE: equ 10               ; a collapsed display's own, each frame
CLK_U:   equ 5                  ; units a step (~5.5: a unit ~92 T, a step
                                ; ~500), for pic_clk (as x 5 there)
COST_SEG: equ 5                 ; no window: a run or a part of one, its own
                                ; work (~450 T: pd_diff, the join, ldi's
                                ; setup, back into the compare)
SWEEP_COL: equ COST_ROW+COPY_MAX+WALK_MAX
                                ; collapsed: the sweep's share, whatever the
                                ; hints take, after a frame where it got no
                                ; row done: a row found, copied and compared

; The queue, the clock (steps of timer B's high byte, 256 cycles, from
; bit 5's rise: LK_WIN, vdclock.inc, ends the writes)
QMAX:    equ 64                 ; runs the queue holds
GAP:     equ 31                 ; a run goes on through this many equal
                                ; characters if one after them differs (a
                                ; run's own work, ~550 T, is more than
                                ; writing them: 52 T each)
LIM_Q:   equ 19                 ; no row begins this many steps after the rise,
LIM_B:   equ 31                 ; or this many from when HOT characters were
HOT:     equ 8                  ; found in a frame, for the next BSY_N:
                                ; a row's compare and its runs take ~2
                                ; steps, so the picture's share of the frame
                                ; is ~5.5 ms, ~9 ms at most
BSY_N:   equ 2
WR_SETUP: equ 11                ; the window: characters a run's own work
                                ; costs (~290 cycles; a character ~27, so
                                ; 9 a step, unpolled)
FB_CHARS: equ 16                ; no window: characters written a frame at most,
FB_COST: equ 3                  ; units each (polled: ~150 us)
HARD:    equ LIM_B              ; the window's frame: no run begins or goes on
                                ; this many steps after the rise (the row
                                ; waits there), and one begun 2 steps before
LATE_N:  equ 8                  ; copies this many at most: a frame's tail
                                ; past HARD is ~2 steps
CAP:     equ HARD-2             ; (from this many steps on)
LATE:    equ HARD-16            ; a row begun this many steps after the rise
                                ; or later looks at the clock at each run
                                ; (a row can take ~16: columns differing
                                ; and the same in turn)


; Block operations (blk_step), as measured on the C128: a fill writes
; R31's byte and R30 more, a copy R30 (0: 256); in the blank a fill takes
; 0.52 cycles a byte, a copy 1.04; in the display 2.7 and 5.6, plus a
; start that grows through the frame (a copy of 64: 174 cycles 1.2 ms in,
; 369 at 9.2 ms); busy shows at the first status read. A write while one
; is busy does harm (R18/R19 and R32/R33 are its live counters, R24 turns
; a copy into a fill, an R31 write lands in it), so the code polls the VDC
; ready before every access after an operation, and boot128 tries the
; counts again at boot (vblk: one more or less than these moves them in
; blk_cfg; anything else turns block operations off).
BLK_COPYN: equ 64               ; R30 for a copy of 64 bytes (a copy writes R30)
BLK_FILLN: equ 63               ; R30 after R31's byte for a fill of 64 (a fill
                                ; writes R31's byte and R30 more)
BLK_CYC: equ 2                  ; an operation's cycles a byte at most, in the
                                ; blank: a copy's 1.04, half as much again
BLK_STEPS: equ 1                ; in the window a row begins only with this
                                ; many steps left (the clock's grain), as a
                                ; run does: its operation, BLK_OPS steps at
                                ; most, ends in the steps between the
                                ; window's end and the blank's (bit 5: 6 on
                                ; the C128; 4 at least once trips cut it,
                                ; pw_cut); if not, bit 5 at the next poll
                                ; says so (pw_trip)
BLK_OPS: equ (64*BLK_CYC+255)/256+1
        if BLK_OPS > 4
        error "BLK_CYC: a row's operation would outlast the blank"
        endif
BLK_UNITS: equ 22               ; no window: a row's units on the VDC, polled
                                ; in the display (the C128's polled scroll:
                                ; ~860 us a row; a copy of 64 late in the
                                ; frame 375 us of it), and a quarter more
BLK_SUNITS: equ 8               ; a row's in the shadow (16 x LDI twice, its
                                ; addresses: ~720 T)
BLK_SLIM: equ LIM_B             ; in the window's frame: the shadow's rows
                                ; begin up to this many steps after the rise
BLK_HOLD: equ 20                ; frames a CLS or SCROLL may hold the picture
                                ; (a 16K CLS ~8-11; SCROLL's RECLAIM moves
                                ; all past the display, ~9 for 16K of it;
                                ; a report inside leaves the hold to run out)
BLK_AT:  equ $1F00              ; vblk's 40 bytes of VDC RAM, at boot only:
                                ; later the monitor's attributes (monvdc.inc's
                                ; screen at $1000, $1800): no use while it runs

DF_CC:   equ $400E
DF_SZ:   equ $4022
DSIZE:   equ 24*33+1            ; VARS - D_FILE of an expanded display

; (blk_step's) register reg <- src: pol, the select polled before its data
; (else unpolled: as pw_one's, 22 T or more after the access before).
bo_wr:  macro reg src pol
        ld a,reg
        nop
        out (c),a
        if pol
        in f,(c)
        jp p,$-2
        endif
        inc c
        out (c),src
        dec c
        endm

; ---------------------------------------------------------------- a frame
pic_step:
        ld a,BUDGET-COST_STEP
        ld (pic_left),a
        ld hl,pic_bsy           ; much found last frame: the busy limit,
        ld a,(pic_hot)          ; this frame and the next BSY_N - 1
        cp HOT
        jr c,ps_b
        ld (hl),BSY_N
ps_b:   ld a,LIM_Q
        inc (hl)
        dec (hl)
        jr z,ps_l
        dec (hl)
        ld a,LIM_B
ps_l:   ld (pic_lim),a
        xor a
        ld (pic_hot),a
        ld (pic_hn),a           ; (no hints' rows yet)
        ld (pic_rm),a           ; (then pic_may's or psf_may's; no window: 8)
        ld a,(pic_unp)
        or a
        jr nz,ps_w
        ld a,8
        ld (pic_rm),a
ps_w:   xor a
        dec a
        ld (pic_hlo),a
ps_blk: ld de,blk_step          ; (JP blk_step while a CLS's or a SCROLL's
                                ; block operations wait or go on: the hooks
                                ; make it one)
ps_bk1:
pn_hook: call pn_step           ; the panel's jobs (panel.inc), before the
                                ; picture's (an LD DE, nn once there are
                                ; none: pn_step makes it one)
        ld a,(pic_qn)           ; an empty queue starts at pic_q (zentry
        or a                    ; clears PSTATE)
        jr nz,ps_m
        ld hl,pic_q
        ld (pic_qp),hl
ps_m:   ld a,(pic_unp)          ; no window: what waits first, polled
        or a
        call z,pic_pfl
        call pic_mode           ; (a collapsed display's check: paid first)
        jp c,ps_fl              ; no display to show: only what waits
        ld hl,pic_stamp         ; this frame's mark
        inc (hl)
        xor a                   ; hints: whole rows
        ld (pic_from),a
        ld (pic_hres),a
        ld a,(pic_unp)          ; (in the window, expanded: the clock
        or a                    ; rules, not the units)
        jr z,ps_u
        ld a,(pic_exp)
        or a
        jr nz,ps_hb
ps_u:   ld b,COST_ROW           ; the hints' units: all but the sweep's, a
        ld a,(pic_exp)          ; row (that matters without the window
        or a                    ; only); collapsed, after a frame where it
        jr nz,ps_r              ; got no row done, a collapsed row at its
        ld a,(pic_srow)         ; dearest, else none: it can't start one
        or a                    ; with less, and it has every other frame
        call nz,ps_sr           ; (pic_stall); a block operation's row
        ld b,0                  ; before either (pic_srow, ps_sr)
        ld a,(pic_stall)
        or a
        jr z,ps_r
        ld b,SWEEP_COL
ps_r:   ld a,(pic_left)
        sub b
        jr nc,ps_h
        xor a
ps_h:   ld b,a
        ld a,(pic_left)
        sub b
        ld (pic_hres),a         ; (the sweep's, meanwhile)
        ld a,b
        ld (pic_left),a
ps_hb:  ld a,(pic_exp)          ; collapsed: what waits first (its rows
        or a                    ; are dear: their runs would come after the
        jr nz,ps_e              ; window); the sweep's frame (pic_stall: it
        call pic_wfl            ; got no row done the frame before), it
        ld a,(pic_stall)        ; next, from the frame's start, so the
        or a                    ; clock's share (pic_clk) covers its dearest
        jp nz,ps_s0             ; row; the hints have the frames between
ps_e:   ld a,(lk_wcut)          ; the window cut short (pw_trip), or the
        or a                    ; queue nearly full: what waits first (the
        jr nz,ps_f              ; hints' runs need room)
        ld a,(pic_qn)
        cp QMAX-16
        jr c,ps_g
ps_f:   call pic_wfl
ps_g:
        ld a,1                  ; (a collapsed one's hint rows the table
        ld (pic_hback),a        ; doesn't have yet: found back, pic_bstart)
        ld a,(edit)             ; the editor's lower screen, from row 23 up
        or a                    ; (the edit line is low)
        jr z,ps_cc
        ld a,(DF_SZ)
        cp 5
        jr c,pe_n
        ld a,4                  ; (more are the sweep's)
pe_n:   or a
        jr z,ps_cc
        ld (pic_hn),a
        ld b,a
        neg
        add a,24
        ld (pic_hlo),a
        ld c,a                  ; (collapsed, a row each frame may be all
        ld hl,pic_erot          ; they can: from the one a frame before
        ld a,(hl)               ; couldn't do, round, else row 23 first;
        ld (hl),0               ; pic_erot the first not done now)
        cp c
        jr nc,pe_row
        ld a,23
pe_row: push af
        push bc
        call pic_try
        pop bc
        pop hl
        jr nc,pe_ok
        ld a,(pic_erot)
        or a
        jr nz,pe_ok
        ld a,h
        ld (pic_erot),a
pe_ok:  ld a,h
        dec a
        cp c
        jr nc,pe_d
        ld a,23
pe_d:   djnz pe_row
ps_cc:  ld a,(edit)             ; DF_CC's row, and the one above (not in
        or a                    ; the editor: DF_CC is in its rows, or
        jr nz,ps_sweep          ; past them), unless DF_CC is where it was
        ld hl,(DF_CC)           ; and they were looked at and the same as
        ld de,(pic_hcc)         ; the shadow then (pic_hcl 1): the sweep's
        ld (pic_hcc),hl         ; (a PRINT moves it)
        and a
        sbc hl,de
        jr nz,ps_c1
        ld a,(pic_hcl)
        dec a
        jr z,ps_sweep
        jr ps_c0
ps_c1:  xor a
        ld (pic_hcl),a
ps_c0:  ld a,(pic_unp)          ; (the window: its walk in the clock's share)
        or a
        jr z,ps_c2
        ld bc,CIA2+7
        in b,(c)
        ld a,(lk_t0)
        sub b
        call pic_clk
ps_c2:  call pic_ccrow
        jr c,ps_sweep
        ld (pic_hlo),a
        ld b,1
        or a
        jr z,ps_h1
        dec a
        ld (pic_hlo),a
        inc b
ps_h1:  ld a,b
        ld (pic_hn),a
        ld a,(pic_hlo)
        add a,b
        dec a
        push af
        call pic_try
        pop bc
        jr c,ps_sweep           ; (not looked at: the queue full, the clock,
        ld a,b                  ; the units)
        dec a
        call p,pic_try
        jr c,ps_hx
        ld a,(pic_hot)          ; (the first found this frame: nothing, they
        or a                    ; were the same)
        jr nz,ps_sweep
        inc a
        ld (pic_hcl),a
ps_s0:  xor a                   ; (the sweep first: its units back)
        ld (pic_hback),a
        ld a,(pic_hres)
        ld b,a
        ld a,(pic_left)
        add a,b
        ld (pic_left),a
        jr ps_sw
ps_hx:  ld a,(pic_exp)          ; (collapsed, DF_CC's row looked at, not
        or a                    ; the one above: next time that one, while
        jr nz,ps_sweep          ; DF_CC stays: pic_hcl the row + 2, pd_coll)
        ld a,b
        add a,2
        ld (pic_hcl),a
ps_sweep:                       ; on from where it stopped, round once at
        xor a                   ; most; a row that doesn't get done stops
        ld (pic_hback),a        ; it there, at the column it got to
        ld a,(pic_hres)
        ld b,a
        ld a,(pic_left)
        add a,b
        ld (pic_left),a
        call pic_wfl            ; (the window: the hints' runs, what waits)
ps_sw:  ld a,(pic_scol)
        ld (pic_from),a
        ld a,(pic_row)
        cp 24
        jr c,psw_go
        xor a
        ld (pic_from),a
psw_go: ld c,a
        ld b,24
        ld a,(pic_exp)          ; (expanded: psf_go)
        or a
        ld a,c
        jp nz,psf_go
        ld hl,pic_srow          ; (a block operation's frame: its row, not
        ld a,(hl)               ; the sweep; the hints' turn next)
        res 7,(hl)
        rla
        jr nc,psw_s
        xor a
        ld (pic_stall),a
        ld a,c
        jp psw_end
psw_s:  ld a,c
        ld hl,pic_stall         ; (until a row is done this frame, but not
        ld a,1                  ; after a frame it was: so the hints have
        xor (hl)                ; every other frame)
        ld (hl),a
        ld a,c
psw_row:
        ld c,a
        push bc
        call pic_try
        push af
        call pic_wfl            ; (the window: its runs at once)
        pop af
        pop bc
        jr c,psw_stop
        xor a                   ; done: the next row from its start
        ld (pic_scol),a
        ld (pic_from),a
        ld (pic_stall),a
        ld a,c
        inc a
        cp 24
        jr c,psw_next
        xor a
psw_next:
        djnz psw_row
        jr psw_end
psw_stop:
        ld a,(pic_stop)
        ld (pic_scol),a
        ld a,c
psw_end:
        ld (pic_row),a
ps_fl:  call pic_wfl            ; what waits: the window's last
ps_end: ld a,(pic_left)
        ld b,a
        ld a,BUDGET
        sub b
        ld (pic_used),a
        ret

; Collapsed: blk_step's row first (pic_srow - 1), till it is done.
ps_sr:  and $7F
        ret z
        dec a
        call pic_try
        ret c
        ld hl,pic_srow
        ld a,(hl)
        and $80
        ld (hl),a
        ret

; Row A, unless it is done this frame already (NC then): pic_do.
pic_try:
        ld c,a
        add a,pic_mark&$FF
        ld l,a
        ld h,PSTATE/256
        ld a,(pic_stamp)
        cp (hl)
        ld a,c
        ret z
; Row A compared with the shadow from column pic_from, what differs into
; the shadow and onto the queue, a run at a time. NC: done, and marked
; so. Carry: not now (pic_may, the units, the queue full: at column
; pic_stop; what is left waits).
pic_do: ld (pic_crow),a
        ld c,a
        ld a,(pic_from)
        ld (pic_stop),a
        call pic_may
        ret c
        call pd_row
        ret c
        ld a,(pic_crow)         ; done: marked so
        add a,pic_mark&$FF
        ld l,a
        ld h,PSTATE/256
        ld a,(pic_stamp)
        ld (hl),a
        and a
        ret
pd_row: ld a,(pic_exp)
        or a
        jr z,pd_coll
        ld a,(pic_unp)          ; expanded: units only without the window
        or a
        jr nz,pd_x
        ld a,(pic_left)
        sub COST_ROW
        ret c
        ld (pic_left),a
pd_x:   ld b,0                  ; D_FILE + 1 + row x 33
        ld hl,pic_r33
        add hl,bc
        add hl,bc
        ld a,(hl)
        inc hl
        ld h,(hl)
        ld l,a
        ld de,(pic_rtab)
        add hl,de
pd_go:
        call pic_shp            ; DE: the row in the shadow
        ld a,(pic_from)
        or a
        jp z,pd_cmp
        ld c,a                  ; on from a column: HL and DE there
        ld b,0
        add hl,bc
        add a,e
        ld e,a
        ld a,c
        jp pd_at
pd_coll:
        ld a,(pic_hback)        ; (DF_CC's row, the hints' and not the
        or a                    ; editor's, looked at since DF_CC moved:
        jr z,pdc_0              ; pic_hcl it + 2: done, so the one above has
        ld a,(edit)             ; the units)
        or a
        jr nz,pdc_0
        ld a,(pic_hcl)
        sub 2
        cp c
        ret z
pdc_0:  ld a,(pic_left)         ; collapsed: the row copied first (if the
        sub COST_ROW            ; budget can't, say so before looking)
        ret c
        cp COST_COPY+32/4
        ret c
        ld a,c
        call pic_src
        ret c
        ld a,(pic_unp)          ; (the window's frame: the late test again,
        or a                    ; the copy done: its compare may yet take
        jr z,pdc_u              ; ~16 steps)
        ld bc,CIA2+7
        in b,(c)
        ld a,(lk_t0)
        sub b
        cp LATE
        jr c,pdc_u
        ld a,(pic_rm)
        or 1
        ld (pic_rm),a
pdc_u:  ld a,(pic_left)         ; (src_c left it)
        sub COST_ROW
        ret c
        ld (pic_left),a
        ld a,(pic_crow)
        ld c,a
        jp pd_go

; In the window's frame, a collapsed display's units no more than the
; clock's share: CLK_U a step left to HARD - 2 (its walks and copies
; stop there; the compare after a copy looks at the clock itself, pd_coll).
; A: the steps since the rise (kept). Changes F.
pic_clk:
        push af
        push bc
        ld b,a
        ld a,(pic_exp)
        or a
        jr nz,pck_x
        ld a,HARD-2
        sub b
        jr nc,pck_1
        xor a
pck_1:  ld b,a                  ; x CLK_U (5)
        add a,a
        add a,a
        add a,b
        ld b,a
        ld a,(pic_left)
        cp b
        jr c,pck_x
        ld a,b
        ld (pic_left),a
pck_x:  pop bc
        pop af
        ret

pic_r33:                        ; row x 33
        dw 0*33,1*33,2*33,3*33,4*33,5*33,6*33,7*33
        dw 8*33,9*33,10*33,11*33,12*33,13*33,14*33,15*33
        dw 16*33,17*33,18*33,19*33,20*33,21*33,22*33,23*33

; NC: a row may begin: the queue has room, and in the window's frame the
; clock allows (pic_lim steps after the rise; pic_rm for the row), else
; there are a row's units (none after pw_trip). Changes AF, keeps BC DE
; HL.
pic_may:
        ld a,(pic_qn)
        cp QMAX
        ccf
        ret c
        ld a,(pic_unp)
        or a
        jr z,pmy_u
        push bc
        ld bc,CIA2+7
        in b,(c)
        ld a,(lk_t0)
        sub b                   ; steps since the rise (it counts down)
        call pic_clk
        call psm_w              ; (carry: as many as pic_lim, or more)
        pop bc
        ret
pmy_u:  ld a,(pic_left)
        cp COST_ROW
        ret

cmp1:   macro                   ; a column: the same, or a run starts
        ld a,(de)
        cp (hl)
        jr nz,pd_tr
        inc hl
        inc e                   ; (a shadow row is in one page)
        endm
cmp4:   macro
        cmp1
        cmp1
        cmp1
        cmp1
        endm

; The row compared from its start (HL in D_FILE or pic_buf, DE in the
; shadow), or from column A (pd_at), what differs into the shadow and
; onto the queue. NC: done, HL and DE past the row (E + 32). Carry: the
; queue is full, at column pic_stop.
pd_cmp: cmp4                    ; columns 0-15: 6 bytes each
        cmp4
        cmp4
        cmp4
        jr pd_c16
pd_tr:  jp pd_diff              ; (in jr's reach of all 32)
pd_c16: cmp4                    ; columns 16-31
        cmp4
        cmp4
        cmp4
pd_done:
        ld a,(pic_pend)         ; (the run pending)
        or a
        call nz,pdd_emit
        and a
        ret

pd_at:  ld b,0                  ; into pd_cmp's column A
        cp 16
        jr c,pa_lo
        ld b,pd_c16-pd_cmp-6*16
pa_lo:  ld c,a
        add a,a
        add a,c
        add a,a
        add a,b
        add a,pd_cmp&$FF
        ld c,a
        ld a,pd_cmp/256
        adc a,0
        ld b,a
        push bc
        ret

; A run starts at column E & 31 (HL, DE there, and they differ): the
; characters into the shadow while they differ (ldi), then on comparing
; with the run pending (pic_pend: pic_e0 to pic_e1). A run within GAP
; after it joins it (the ones between are the same: written again); one
; further, or the row's end, has it written in the window if it fits
; there, else queued (pdd_emit). With the queue full, the row waits
; here (carry: pd_stop).
pd_diff:
        ld a,(pic_rm)           ; (bit 0: a row begun late in the window's
        and 9                   ; frame, no more HARD steps after the rise;
        jr z,pdd_1              ; bit 3: no window)
        rra
        jr nc,pdd_0
        ld bc,CIA2+7
        in b,(c)
        ld a,(lk_t0)
        sub b
        cp HARD
        jp nc,pdd_x
        cp CAP                  ; (CAP steps on: LATE_N copied at most,
        ld a,(pic_rm)           ; the rest waits; pic_rm bit 2)
        res 2,a
        jr c,pdd_l
        set 2,a
pdd_l:  ld (pic_rm),a
        jr pdd_1
pdd_0:  ld a,(pic_left)         ; (no window: COST_SEG a run or a part of
                                ; one, the row waiting here without)
        sub COST_SEG
        jp c,pdd_x
        ld (pic_left),a
pdd_1:  ld a,(pic_pend)
        or a
        jr z,pdd_s
        ld a,(pic_e1)           ; within GAP after the one pending?
        ld b,a
        ld a,e
        sub b
        cp GAP+1
        jr c,pdd_go             ; (it goes on)
        call pdd_emit
pdd_s:  ld a,(pic_qn)
        cp QMAX
        jp nc,pd_stop
        ld a,e
        ld (pic_e0),a
        ld a,1
        ld (pic_pend),a
pdd_go: ld a,e                  ; BC: the columns to the row's end (or
        and 31                  ; LATE_N, pic_rm bit 2)
        cpl
        add a,33
        ld c,a
        ld b,0
        ld a,(pic_rm)
        and 4
        jr z,pdd_c
        ld a,c
        cp LATE_N+1
        jr c,pdd_c
        ld c,LATE_N
pdd_c:  ldi                     ; differs: into the shadow
        jp po,pdd_e             ; (the row's end)
        ld a,(de)
        cp (hl)
        jp nz,pdd_c
        ld a,e                  ; the same: the run ends here so far, on
        ld (pic_e1),a           ; comparing (a late row: not past HARD)
        ld a,(pic_rm)
        rra
        jr c,pdd_h
pdd_on: ld a,e
        and 31
        jp pd_at
pdd_h:  ld bc,CIA2+7
        in b,(c)
        ld a,(lk_t0)
        sub b
        cp HARD
        jr c,pdd_on
        jp pdd_x
pdd_e:  ld a,e                  ; the row's end, and the run's (ldi went on
        ld (pic_e1),a           ; to the next page past a row 7's end:
        and 31                  ; back), or LATE_N's (the rest waits)
        jp nz,pdd_x
        ld a,e
        or a
        jr nz,pdd_e1
        dec d
pdd_e1: call pdd_emit
        and a
        ret

; The run pending, pic_e0 to pic_e1 in the shadow's page D: written now
; in the window if it fits there, else queued. Keeps DE HL.
pdd_emit:
        push hl
        xor a
        ld (pic_pend),a
        ld hl,pic_e0            ; C: its characters
        ld a,(pic_e1)
        sub (hl)
        ld c,a
        ld hl,pic_hot           ; to this frame's finds (till they are HOT:
        ld a,(hl)               ; the busy limit)
        cp HOT
        jr nc,pde_k
        add a,c
        ld (hl),a
        cp HOT
        jr c,pde_k
        ld a,LIM_B
        ld (pic_lim),a
pde_k:  ld a,(pic_unp)
        or a
        jr z,pde_u
        ld a,(pic_rm)           ; (a row begun past the window: queued)
        and 2
        jr z,pde_q
        push bc                 ; the window: now, from its start, if it
        ld bc,CIA2+7            ; ends by LK_WIN steps after the rise (9
        in b,(c)                ; characters a step, WR_SETUP its own work;
        ld a,(lk_t0)            ; the clock's grain a step), else queued
        sub b
        pop bc
pde_wc: cp LK_WIN-1               ; (LK_WIN less what trips have cut: lk_wset)
        jr nc,pde_q
        neg
pde_wd: add a,LK_WIN-1
        ld b,a
        add a,a
        add a,a
        add a,a
        add a,b
        sub WR_SETUP
        jr c,pde_q
        cp c
        jr c,pde_q
        push de
        ld a,(pic_e0)
        ld e,a
        ld a,c
        call pw_one
        pop de
        pop hl
        ret
pde_u:  ld a,c                  ; no window: its copy, a unit 2 of them
        srl a
        ld l,a
        ld a,(pic_left)
        sub l
        jr nc,pde_v
        xor a
pde_v:  ld (pic_left),a
pde_q:  ld hl,(pic_qp)          ; onto the queue: its start, page and end in
        ld a,(pic_e0)           ; the shadow
        ld (hl),a
        inc hl
        ld (hl),d
        inc hl
        ld a,(pic_e1)
        ld (hl),a
        inc hl
        ld (pic_qp),hl
        ld hl,pic_qn
        inc (hl)
        pop hl
        ret
pdd_x:  ld a,(pic_pend)         ; (the one pending first)
        or a
        call nz,pdd_emit
pd_stop:
        ld a,e                  ; the queue is full, or the time is up: the
        and 31                  ; rest waits
        ld (pic_stop),a
        scf
        ret

; The sweep through an expanded display (from psw_go: A the row, B 24,
; pic_from the first row's column): as psw_row's loop with pic_try and
; pic_do, but each row's start in D_FILE and the shadow carried on from
; the one before (HL, DE; C the row), and the hints' rows of this frame
; passed over.
psf_go: ld c,a
        add a,a
        ld e,a
        ld d,0
        ld hl,pic_r33
        add hl,de
        ld a,(hl)
        inc hl
        ld h,(hl)
        ld l,a
        ld de,(pic_rtab)
        add hl,de               ; HL: the row in D_FILE,
        call pic_shp            ; DE: in the shadow
        xor a
        ld (pic_scol),a
        ld a,(pic_from)         ; the first from pic_from
        or a
        jr z,psf_row
        push bc
        call psf_may
        jp c,psf_late
        ld a,(pic_from)
        ld c,a
        ld b,0
        add hl,bc
        add a,e
        ld e,a
        ld a,c
        call pd_at
        jp c,psf_stop
        pop bc
        xor a
        ld (pic_from),a
        jr psf_nx
psf_row:
        ld a,(pic_hlo)          ; the hints' first row: past them
        cp c
        jp z,psf_sk
        push bc
        call psf_may
        jp c,psf_late
        call pd_cmp
        jp c,psf_stop
        pop bc
psf_nx: inc hl                  ; past the row's $76: the next row
        ld a,e                  ; (in the shadow: the next page, past rows
        or a                    ; 7 and 15)
        jr nz,psf_w
        inc d
psf_w:  ld a,(pic_qn)           ; the window: its runs at once
        or a
        jr z,psf_d
        ld a,(pic_rm)
        and 2
        call nz,psf_fl
psf_d:
        inc c
        ld a,c
        cp 24
        jr c,psf_n
        ld c,0                  ; (round to row 0)
        ld hl,(pic_rtab)
        ld de,SHADOW
psf_n:  djnz psf_row
psf_end:
        ld a,c
        jp psw_end
psf_sk: ld a,(pic_hn)           ; (each: HL + 33, DE + 32)
psk_l:  push af
        push bc
        ld bc,33
        add hl,bc
        pop bc
        ld a,e
        add a,32
        ld e,a
        jr nz,psk_1
        inc d
psk_1:  inc c
        ld a,c
        cp 24
        jr c,psk_2
        ld c,0
        ld hl,(pic_rtab)
        ld de,SHADOW
psk_2:  pop af
        dec b
        jr z,psf_end
        dec a
        jr nz,psk_l
        jp psf_row
psf_late:
        ld a,(pic_from)         ; out of time: this row waits, as it is
        ld (pic_stop),a
psf_stop:
        pop bc
        jp psw_stop

; NC: a row may begin (pic_may's, the queue's room left to pd_diff): the
; window's clock, else a row's units, paid. Changes AF BC.
psf_may:
        ld a,(pic_unp)
        or a
        jr z,psm_u
        ld bc,CIA2+7
        in b,(c)
        ld a,(lk_t0)
        sub b
psm_w:  ld b,a                  ; (pic_may's too: A, B the steps since the
        ld c,0                  ; rise) pic_rm: bit 1, the window has time
psm_wc: cp LK_WIN-2             ; yet (less what trips cut: lk_wset); bit 0,
        jr nc,psm_1             ; begun LATE steps after the rise or later:
        ld c,2                  ; its runs look at the clock
psm_1:  cp LATE
        jr c,psm_2
        inc c
psm_2:  ld a,c
        ld (pic_rm),a
        ld a,(pic_lim)
        dec a
        cp b
        ret
psm_u:  ld a,(pic_left)
        sub COST_ROW
        ret c
        ld (pic_left),a
        ret

psf_fl: ld a,(pic_unp)          ; (keeps BC DE HL)
        or a
        ret z
        push bc
        push de
        push hl
        call pw_run
        pop hl
        pop de
        pop bc
        ret

; ---------------------------------------------------------------- writes
; The runs waiting written from the shadow, the last queued first:
; pic_wfl in the window, pic_pfl without. Change AF BC DE HL.
pic_wfl:
        ld a,(pic_unp)
        or a
        ret z
; In the window: as many characters as fit before LK_WIN steps after the
; rise (9 a step, WR_SETUP of them a run's own work; the clock's grain a
; step), the last run cut short if need be (the rest waits). If the
; blank has ended (it can't, unless the window is wrong), the frame has
; no window from there (pw_trip; pw_one's pw_chk looks again after each
; run). LK_MODE 1 writes unpolled, each access 22 T or more after the one
; before (on the C128: 18 T landed; a stream 26 T a byte), 2 polled.
pw_run: ld a,(pic_qn)
        or a
        ret z
        call lk_left            ; the steps left
        ret c
        ret z
        dec a                   ; (the clock's grain)
        ret z
        ld c,a
        add a,a                 ; x 9
        add a,a
        add a,a
        add a,c
        ld (pic_wn),a
        ld bc,VDC               ; still in the blank?
        in a,(c)
        and $20
        jp z,pw_trip
pw_nx:  ld a,(pic_qn)
        or a
        ret z
        ld a,(pic_wn)
        sub WR_SETUP
        ret c
        ret z
        ld c,a
        call pq_take            ; DE: its start in the shadow, A: characters
        ld b,a
        ld a,(pic_wn)
        sub b
        sub WR_SETUP
        ld (pic_wn),a
        ld a,b
        call pw_one
        jr pw_nx

; The run of A characters (not 0) from the shadow's DE written in the
; window: unpolled (LK_MODE 1), each access 22 T or more after the one
; before; polled (2). Changes AF BC DE HL.
pw_one:
        ld b,a                  ; the writer's entry, wr_end - 10 x A, for
        add a,a                 ; the ret below (the writer's ret is this
        add a,a                 ; one's)
        add a,b
        ld l,a
        ld h,0
        add hl,hl
        ld b,h
        ld c,l
        ld hl,wr_end
        and a
        sbc hl,bc
        push hl
        call pic_va             ; HL: the VDC's address
        ld bc,VDC               ; set unpolled: each access 25 T or more
        ld a,18                 ; after the one before (measured on the C128)
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
        inc c                   ; (BC = the data)
        ex de,hl                ; HL: the shadow
        ret                     ; into the writer
; A run written unpolled and bit 5 gone at its end (wr_end): it can't
; be, unless the window is wrong. Its writes may be lost, its address's
; too (so they may have landed anywhere): the whole shadow made unlike
; any code ($FF), so the compare writes every cell again, the queue
; dropped (the compare has it all), the panel and every attribute written
; again (panel.inc's pn_rep), and no window from here (pw_trip). (~16,000
; T, once.)
pw_chk: call pw_cut             ; (the cut from now, before the fill)
        call pn_rep             ; (marks only: its jobs later)
        ld hl,SHADOW
        ld de,SHADOW+1
        ld bc,$2FF
        ld (hl),$FF
        ldir
        xor a
        ld (pic_qn),a
        ld hl,pic_q
        ld (pic_qp),hl
pw_trip:
        call pw_cut             ; the blank is over: the window shorter,
        xor a                   ; and no window, and no more rows or runs,
        ld (pic_unp),a          ; this frame
        ld (pic_left),a
        ld a,8
        ld (pic_rm),a
        ret

; The window ends 4 steps before now from here on (lk_wcut, for good;
; LK_WMIN steps or less: polled), unless it is shorter already. Changes
; AF BC.
pw_cut: xor a                   ; (a trip: lk_wok counts from it)
        ld (lk_wok),a
        ld bc,CIA2+7
        in b,(c)
        ld a,(lk_t0)
        sub b
        ld b,a
        ld a,LK_WIN+4
        sub b
        ret c                   ; (later than that: as it was)
        ld b,a
        ld a,(lk_wcut)
        cp b
        ret nc
        ld a,b
        ld (lk_wcut),a
        ld b,a                  ; the window's end in the code: LK_WIN - cut
        ld a,LK_WIN
        sub b
        jp lk_wset

wru:    macro                   ; a character: (HL) and (HL) | $40
        ld a,(hl)
        out (c),a               ; left
        inc l
        or $40
        out (c),a               ; right, 23 T after
        nop
        nop                     ; (27 T to the next left)
        endm
wru4:   macro
        wru
        wru
        wru
        wru
        endm
wr_32:  wru4                    ; 10 bytes a character
        wru4
        wru4
        wru4
        wru4
        wru4
        wru4
        wru4
wr_end: dec c                   ; bit 5 still set? (else pw_chk)
        in a,(c)
        and $20
        ret nz
        jp pw_chk

; No window: FB_CHARS characters of what waits, polled, FB_COST units
; each (pic_step's first: there are as many).
pic_pfl:
        ld a,FB_CHARS
        ld (pic_wn),a
pp_run: ld a,(pic_qn)
        or a
        ret z
        ld a,(pic_wn)
        or a
        ret z
        ld c,a
        call pq_take
        ld c,a
        ld a,(pic_wn)
        sub c
        ld (pic_wn),a
        ld b,c                  ; (the units)
        ld a,(pic_left)
pp_u:   sub FB_COST
        djnz pp_u
        ld (pic_left),a
        push bc
        call pic_va
        vdc_addr
        pop bc
        ld a,c
        call pic_put
        jr pp_run

; The last run waiting, C characters of it at most (C not 0): DE its start
; in the shadow, A how many; off the queue, or, if it is longer, its start
; moved on (the rest waits).
pq_take:
        ld hl,(pic_qp)
        dec hl
        ld a,(hl)               ; its end
        dec hl
        ld d,(hl)
        dec hl
        ld e,(hl)
        sub e                   ; its length
        cp c
        jr c,pqt_all
        jr z,pqt_all
        ld a,e
        add a,c
        ld (hl),a
        ld a,c
        ret
pqt_all:
        ld (pic_qp),hl
        ld hl,pic_qn
        dec (hl)
        ret

; HL: the VDC's address of the shadow's DE, row x 80 + column x 2 = (DE -
; SHADOW) x 2 + row x 16, where row x 16 = (DE - SHADOW) & ~31 / 2.
; Keeps DE.
pic_va: ld a,d
        and $03
        ld h,a
        ld b,a
        ld l,e
        ld a,e
        and $E0
        ld c,a
        srl b
        rr c
        add hl,hl
        add hl,bc
        ret

; A characters (not 0) from the shadow's DE to the VDC, polled.
pic_put:
        ld h,a
        ld bc,VDC
pp_c:   ld a,(de)
        vdc_bput
        or $40
        vdc_bput
        inc e
        dec h
        jr nz,pp_c
        ret

; DE: row C's 32 bytes in the shadow. Keeps BC HL.
pic_shp:
        ld a,c
        rrca
        rrca
        rrca                    ; (row & 7) << 5 | row >> 3
        ld e,a
        and $03
        or SHADOW/256
        ld d,a
        ld a,e
        and $E0
        ld e,a
        ret

; ---------------------------------------------------------------- D_FILE
; Is there a display, and which kind: pic_exp. Carry: VARS - D_FILE is
; not a display's (25 for an empty collapsed one, DSIZE expanded), or a
; collapsed one's frame that can't pay for its table, or waits (pic_fix).
;
; A collapsed display's rows are found through pic_rtab, where rows 0 to
; pic_known start, found by walking its $76s from D_FILE (pic_start). A
; display has 24 line ends after D_FILE's own $76, the last at VARS - 1,
; so 24 rows in order, each just after a $76, the last ending at VARS,
; are its rows. So the whole table is carried from frame to frame
; (pic_fix), proven each time that way, as the ROM changes the display:
; a PRINT or the editor puts characters in or takes them out at one
; place, the rows before it where they were, those past it moved as VARS
; has; a few between, if two places changed, found back. The SCROLLs the
; hooks note are done to it first (pic_scr); a 16K display that a SCROLL
; leaves collapsed starts from the expanded one's rows (pic_x33). A
; frame whose IRQ came while the ROM was moving memory (pic_mvd: D_FILE
; half moved) waits. If the table can't be carried, D_FILE moved, or a
; walk ran out (pic_odd: a line with no $76 within 33 bytes, not a
; display's), it is made again from row 0, a row at a time as rows are
; needed, over as many frames as that takes; while it isn't whole, it is
; kept only while VARS stays where it was and every row in it still has
; a $76 just before it (pic_chk). A row's copy (src_c) also checks its
; line against the table: a $76 POKEd into a line makes it again. (A
; table walked whole is the display as the ZX81 shows it even with a $76
; too many: it needn't end at VARS, pic_walked, and then isn't carried.
; Once a copy or a walk has shown it isn't a display's, rows are found
; from D_FILE only till it moves, pic_fwd: its lines counted back aren't
; its rows.)
pic_mode:
        ld hl,(VARS)
        ld de,(DFILE)
        and a
        sbc hl,de
        ret c
        ld bc,25
        sbc hl,bc
        ret c
        ld bc,DSIZE-25
        sbc hl,bc
        jp z,pm_exp
        ccf
        ret c                   ; longer than an expanded one
        xor a
        ld (pic_exp),a
        ld a,(pic_left)         ; (first in a frame: there is that much)
        sub COST_MODE
        ld (pic_left),a
        ld hl,(VARS)            ; (no rows found back yet: pic_bstart)
        ld (pic_bpos),hl
        ld a,24
        ld (pic_brow),a
        ld hl,(pic_tdf)
        sbc hl,de
        jr z,pm_df
        ld a,(pic_tdf+1)        ; an expanded display last frame (pm_exp:
        or a                    ; no D_FILE, its row 0) and D_FILE where
        jr nz,pm_dm             ; it was: its rows are the table (pic_x33;
        ld hl,(pic_rtab)        ; a frame that can't pay for it and what
        dec hl                  ; follows has only what waits)
        sbc hl,de
        jr nz,pm_dm
        ld a,(pic_left)
        cp X33_MAX+FIX_MAX+SCR_MAX
        ret c
        sub X33_MAX
        ld (pic_left),a
        call pic_x33
        jr pm_df
pm_dm:  ld (pic_tdf),de         ; D_FILE moved: row 0 with it
        inc de
        ld (pic_rtab),de
        xor a
        ld (pic_fwd),a
        ld (pic_sk),a           ; (no SCROLL of this display's yet)
        ld a,(pic_odd)
        or a
        jp nz,pm_none
        jr pm_new
pm_df:  ld a,(pic_odd)          ; a walk ran out (not a display's): from
        or a                    ; row 0, nothing kept
        jr nz,pm_none
        call pm_wh              ; the table whole: carried over to the
        jr nz,pm_dv             ; display as it is now (pic_fix), the
        ld a,(pic_left)         ; SCROLLs noted first if the hook couldn't
        cp FIX_MAX+SCR_MAX      ; (pic_scr); a frame that can't pay for that
        ret c                   ; has nothing else
        ld a,(pic_sk)
        or a
        call nz,pm_scr
        jr c,pm_dv              ; (it can't: the table dropped)
        call pic_fix
        ret nc
        ret z                   ; (not now)
        jr pm_mv
pm_dv:  ld a,(pic_sk)           ; (a SCROLL since the table was begun: no
        or a                    ; row of it is any use)
        jr z,pm_dv1
        xor a
        ld (pic_sk),a
        ld (pic_known),a
pm_dv1: ld hl,(VARS)            ; VARS moved, or a check fails: again
        ld de,(pic_tvar)
        and a
        sbc hl,de
        jr nz,pm_mv
        call pic_chk
        ld a,b
        or a
        jr z,pm_ok
pm_mv:  xor a                   ; (the display moved: rows may be found
        ld (pic_fwd),a          ; back from VARS again)
        jr pm_new
pm_none:
        xor a                   ; (and from D_FILE only, till it moves:
        ld (pic_odd),a          ; not a display's, its lines counted back
        inc a                   ; aren't its rows)
        ld (pic_fwd),a
pm_new: xor a                   ; made again from row 0
        ld (pic_known),a
        inc a
        ld (pic_walked),a
pm_ok:  ld hl,(VARS)
        ld (pic_tvar),hl
        and a
        ret
pm_exp: ld a,1
        ld (pic_exp),a
        inc de
        ld (pic_rtab),de        ; (pic_ccrow's row 0)
        ld (pic_tdf),hl         ; (HL 0: the next collapsed one is new)
        ret
; Z: the table is whole and the display's (pic_known 24, not pic_fwd),
; right at pic_tvar (no $76 too many). Changes AF DE HL.
pm_wh:  ld a,(pic_fwd)
        or a
        ret nz
        ld a,(pic_known)
        cp 24
        ret nz
        ld hl,(pic_rtab+48)
        ld de,(pic_tvar)
        sbc hl,de
        ret


; B: the highest of rows 1 to pic_known that has no $76 just before it,
; or 24 if all 24 are there, some taken over (pic_walked 0), and the last
; doesn't end at VARS; 0: none (pic_scn).
; Costs 1/2 unit a row, and 5 (CHK_MAX at most: the callers have it).
; Changes AF BC DE HL.
pic_chk:
        ld b,0
        ld a,(pic_known)
        or a
        ret z
        ld e,a
        srl a
        add a,5
        ld c,a
        ld a,(pic_left)
        sub c
        ld (pic_left),a
        ld a,e
        cp 24
        jr nz,pk_go
        ld a,(pic_walked)       ; all 24, some taken over: the last ends at
        or a                    ; VARS
        jr nz,pk_go
        ld hl,(VARS)
        ld bc,(pic_rtab+48)
        and a
        sbc hl,bc
        ld b,24
        ret nz
pk_go:  ld b,e
        call pic_scn
        ld a,(pic_hg)
        ld b,a
        ret

; Rows 1 to B (1-24) looked at, each just after a $76 where the table
; has it or not: pic_lf the lowest not (else B + 1), pic_hg the highest
; (else 0). SP runs through the table meanwhile (interrupts are off:
; pic_step, pic_all). Changes AF BC HL.
pic_scn:
        ld a,b
        inc a
        ld (pic_ns),a
        ld (pic_hg),a           ; (B as it counts down: none is row 0,
        xor a                   ; and B + 1)
        ld (pic_lf),a
        ld (bo_sp),sp
        ld sp,pic_rtab+2
        ld c,$76
psc_l:  pop hl
        dec hl
        ld a,(hl)
        cp c
        jr nz,psc_f
psc_n:  djnz psc_l
        ld sp,(bo_sp)
        ld hl,pic_ns            ; the rows: B + 1 less the Bs
        ld a,(hl)
        dec l
        sub (hl)
        ld (hl),a               ; (pic_hg)
        ld a,(pic_ns)
        dec l
        sub (hl)
        ld (hl),a               ; (pic_lf)
        ret
psc_f:  ld a,b
        ld (pic_hg),a
        ld a,(pic_lf)
        or a
        jr nz,psc_n
        ld a,b
        ld (pic_lf),a
        jr psc_n

; The whole table (pic_known 24, right at VARS pic_tvar: pm_wh) carried
; over to the display as it is now. The ROM puts characters in or takes
; them out at one place (MAKE-ROOM, RECLAIM: a PRINT, the editor), so the
; rows before it are where they were and those past it moved as VARS
; has: from row 24 down, the highest row not moved (hg; the change is
; low, so few are looked at), and below it the lowest not where it was
; (lf, pic_scn's look); each row taken where it was up to hg or past it,
; the first that the next, moved, is past, each where it was (a line
; taken out leaves short ones that pass both looks). If no one place
; fits, rows lf to hg are found back from row hg + 1 (pic_bstart) to
; past row lf - 1 (two places changed: VARS where it was and a $76
; moved, or the edit line and DF_CC's). Each row is then just after a
; $76, in order, the last at VARS: 24 line ends in order are the
; display's, so the table is whole (pic_tvar its VARS). NC: so. Carry:
; not, Z then if the IRQ came with D_FILE half moved (pic_mvd: a frame's
; wait, nothing changed), else made again (rows found back may be in
; it). Costs FIX_SCN less hg / 2 (CHK_MAX if VARS is where it was), the
; rows moved / 2 + 1 (FIX_MAX in hand), and a row found back's for each
; (BACK_MAX in hand for each). Changes AF BC DE HL.
pic_fix:
        call pic_mvd            ; (the ROM in the middle of moving it: a
        scf                     ; frame's wait, Z)
        ret z
        ld hl,(VARS)
        ld de,(pic_rtab+48)
        and a
        sbc hl,de
        ex de,hl                ; DE: what it moved by
        ld a,d
        or e
        jr nz,pfx_s
        ld b,24                 ; (not: each row where it was, pic_chk's
        call pic_scn            ; look)
        ld a,CHK_MAX
        jr pfx_u
pfx_s:  ld hl,pic_rtab+49       ; moved: from row 24 down, the highest not
        ld bc,24*256+$76        ; moved (the change is low: a PRINT's,
pfg_l:  ld a,(hl)               ; the editor's)
        dec l
        push hl
        ld l,(hl)
        ld h,a
        add hl,de
        dec hl
        ld a,(hl)
        pop hl
        cp c
        jr nz,pfg_x
        dec l
        djnz pfg_l
pfg_x:  ld a,b                  ; hg; below it, the lowest not where it
        ld (pic_hg),a           ; was (none: 25)
        ld a,25
        ld (pic_lf),a
        inc b
        dec b
        jr z,pfg_0
        push de
        call pic_scn
        pop de
        ld hl,pic_ns
        ld a,(hl)
        dec a
        dec l
        ld (hl),a               ; (pic_hg)
        inc a
        dec l
        cp (hl)                 ; (pic_lf)
        jr nz,pfg_0
        ld (hl),25
pfg_0:  ld a,(pic_hg)           ; (rows moved looked at, a unit each; the
        srl a                   ; rest 1/2)
        neg
        add a,FIX_SCN
pfx_u:  ld b,a
        ld a,(pic_left)
        sub b
        ld (pic_left),a
        ld hl,pic_lf            ; C: the lowest not where it was (24 at
        ld a,(hl)               ; most: row 24 is VARS)
        cp 24
        jr c,pfx_1
        ld a,24
pfx_1:  ld c,a
        inc l
        ld a,(hl)               ; A: the highest not moved, so the last
pfx_k:  cp c                    ; where it was at the least; on to the
        jr nc,pfx_w             ; first that the next moved is past, each
        ld (pic_want),a         ; where it was
        push bc
        call pic_rt
        ld c,(hl)
        inc l
        ld b,(hl)
        inc l
        ld a,(hl)
        inc l
        ld h,(hl)
        ld l,a
        add hl,de
        scf
        sbc hl,bc
        jr nc,pfx_ok
        pop bc
        ld a,(pic_want)
        inc a
        push af
        call pic_rt
        ld a,(hl)
        inc l
        ld h,(hl)
        ld l,a
        dec hl
        ld a,(hl)
        cp $76
        pop hl
        ld a,h
        jr z,pfx_k
        jp pfx_no
pfx_ok: pop bc                  ; rows A + 1 on moved (VARS where it was:
        ld a,(pic_want)         ; none is)
pfx_mv: ld b,a
        ld a,d
        or e
        jr z,pfx_d
        ld a,b
        inc a
        call pic_rt
        ld a,24
        sub b
        ld b,a
        srl a
        inc a
        ld c,a
        ld a,(pic_left)
        sub c
        ld (pic_left),a
        call pic_add
pfx_d:  ld hl,(pic_rtab+48)     ; (the table's VARS)
        ld (pic_tvar),hl
        xor a
        ld (pic_walked),a
        ret
pfx_w:  ld a,(pic_hg)           ; rows lf to hg found back (pic_bstart)
        cp 24                   ; from the first moved (hg + 1), to past
        jr nc,pfx_no            ; row lf - 1 (no $76 at VARS - 1: the ROM
        ld hl,pic_lf            ; moving it, a frame's wait)
        cp (hl)
        jr c,pfx_no
        inc a
        ld (pic_brow),a
        call pic_rt
        ld a,(hl)
        inc l
        ld h,(hl)
        ld l,a
        add hl,de
        ld (pic_bpos),hl
        push de
        ld a,(pic_lf)
        call pic_bstart
        jr c,pfx_b
        ex de,hl                ; DE: row lf's start
        ld a,(pic_lf)
        dec a
        call pic_rt
        ld a,(hl)
        inc l
        ld h,(hl)
        ld l,a
        and a
        sbc hl,de
        jr nc,pfx_b
        ld a,(pic_lf)           ; rows lf to hg into the table
        call pic_bt
        push hl
        ld a,(pic_lf)
        ld b,a
        call pic_rt
        ex de,hl
        pop hl
        ld a,(pic_hg)
        sub b
        inc a
        add a,a
        ld c,a
        ld b,0
        ldir
        call pfx_br
        pop de
        ld a,(pic_hg)
        jp pfx_mv
pfx_b:  call pfx_br
        pop de
pfx_no: or 1                    ; (not: NZ, carry)
        scf
        ret
pfx_br: ld hl,(VARS)            ; (no rows found back from VARS now)
        ld (pic_bpos),hl
        ld a,24
        ld (pic_brow),a
        ret

; Z: the IRQ came while the ROM was moving memory, D_FILE half moved:
; just back in PRINT's or LOC-ADDR's from MAKE-ROOM, the new bytes not
; stored yet (copies of what was there, a $76 among them: a row too
; many); in MAKE-ROOM's or RECLAIM's pointers or block move (the pointers
; first, then LDDR or LDIR). Where the ROM was: past irqh's HL DE BC AF,
; above irq_early's return (pic_iret), 6 bytes up from here when pic_irq
; jumps to pic_step (no window), 8 when it calls it: fixed depths, so
; nothing may be pushed on the way (pic_irq, pic_step, pic_mode, pm_df,
; pic_fix); sim128's pic_mvd_slots checks the call's only. Not from the
; IRQ (pic_nirq): NZ.
; Changes AF BC HL.
pic_mvd:
        ld a,(pic_nirq)
        or a
        ret nz
        ld hl,6
        add hl,sp
        ld b,2
pmv_l:  ld a,(hl)
        inc hl
        cp pic_iret&$FF
        jr nz,pmv_n
        ld a,(hl)
        cp pic_iret/256
        jr z,pmv_f
pmv_n:  inc hl
        djnz pmv_l
        ret                     ; (NZ)
pmv_f:  ld bc,9                 ; irqh's HL DE BC AF, then where the ROM
        add hl,bc               ; was
        ld a,(hl)
        inc hl
        ld h,(hl)
        ld l,a
        ld bc,-$083D            ; PRINT's after its CALL ONE-SPACE: its EX
        add hl,bc               ; DE,HL and LD (HL),A ($083D-$083E)
        ld c,$100-($083F-$083D)
        call pmv_r
        ret z
        ld bc,$083D-$093C       ; LOC-ADDR's after its CALL MAKE-ROOM, the
        add hl,bc               ; gap filled with $00 ($093C-$0944)
        ld c,$100-($0945-$093C)
        call pmv_r
        ret z
        ld bc,$093C-$09A6       ; MAKE-ROOM's from its CALL POINTERS on,
        add hl,bc               ; POINTERS itself ($09A6-$09D7)
        ld c,$100-($09D8-$09A6)
        call pmv_r
        ret z
        ld bc,$09A6-$0A6B       ; RECLAIM's after its CALL POINTERS to the
        add hl,bc               ; LDIR ($0A6B-$0A6F)
        ld c,$100-($0A70-$0A6B)
pmv_r:  ld a,h                  ; Z: HL less than 256 - C
        or a
        ret nz
        ld a,l
        add a,c
        sbc a,a
        cpl
        inc a
        ret

; B rows' starts from HL's entry on moved by DE. Changes AF B HL.
pic_add:
        ld a,(hl)
        add a,e
        ld (hl),a
        inc l
        ld a,(hl)
        adc a,d
        ld (hl),a
        inc l
        djnz pic_add
        ret

; The SCROLLs noted since the table was right (pic_sk rows up, within
; pic_su rows: the hooks) done to it as the ROM did them to the display
; (each a $76 put in at row u's start, row 0 taken out): rows k to u - 1
; up to row 0 on, then k empty lines (a $76 each), then rows u on, all
; less rows 0 to k - 1's bytes (k u at most: a CLS is 24 within 24).
; pic_tvar as if nothing else changed: pic_fix proves it. NC: done.
; Carry: no use (u 0): the table dropped. Costs SCR_MAX (in hand; the
; hooks' call, outside pic_step, doesn't pay). Changes AF BC DE HL.
pm_scr: ld a,(pic_left)
        sub SCR_MAX
        ld (pic_left),a
pic_scr:
        ld hl,pic_sk
        ld a,(hl)
        ld (hl),0
        ld (pic_want),a         ; (k)
        inc l
        ld c,(hl)               ; C: u (pic_su; 0: no use)
        inc c
        dec c
        jr z,psr_no
        cp c                    ; (k u or more: all of them)
        jr c,psr_k
        ld a,c
        ld (pic_want),a
psr_k:  call pic_rt             ; rows k to 24 less rows 0 to k - 1's bytes
        push hl
        ld e,(hl)
        inc l
        ld d,(hl)
        ld hl,(pic_rtab)
        and a
        sbc hl,de
        ex de,hl
        pop hl
        push hl
        ld a,(pic_want)
        sub 25
        neg
        ld b,a
        call pic_add
        pop hl                  ; rows k to u - 1 up to 0 on
        ld a,(pic_want)
        ld b,a
        ld a,c
        sub b
        add a,a
        ld de,pic_rtab
        jr z,psr_1
        push bc
        ld c,a
        ld b,0
        ldir                    ; (HL: row u's entry, DE: row u - k's)
        pop bc
psr_1:  push hl
        ld a,(hl)
        inc l
        ld h,(hl)
        ld l,a
        ex de,hl                ; k empty lines from where row u was
psr_e:  ld (hl),e
        inc l
        ld (hl),d
        inc l
        inc de
        djnz psr_e
        pop hl                  ; rows u to 24 past them
        ld a,(pic_want)
        ld e,a
        ld d,0
        ld a,25
        sub c
        ld b,a
        call pic_add
        ld hl,(pic_rtab+48)
        ld (pic_tvar),hl
        and a
        ret
psr_no: xor a                   ; (dropped)
        ld (pic_known),a
        scf
        ret

; From an expanded display last frame, D_FILE (DE) where it was: its rows
; (D_FILE + 1 + row x 33) are the table, right at its VARS (D_FILE +
; DSIZE). Costs X33_MAX. Changes AF B DE HL.
pic_x33:
        ld (pic_tdf),de
        ld hl,pic_rtab
        ld b,25
        inc de
px_l:   ld (hl),e
        inc l
        ld (hl),d
        inc l
        ld a,e
        add a,33
        ld e,a
        jr nc,px_1
        inc d
px_1:   djnz px_l
        ld hl,(pic_rtab+48)
        ld (pic_tvar),hl
        xor a
        ld (pic_walked),a
        ld (pic_odd),a
        ld (pic_fwd),a
        ld a,24
        ld (pic_known),a
        ret

; HL: the 32 codes of row A: D_FILE's own bytes when it is expanded, a
; collapsed row padded with spaces in pic_buf. Carry: not now (the
; budget can't pay for a collapsed row, or the table turned out wrong).
; Changes BC DE.
pic_src:
        ld c,a
        ld a,(pic_exp)
        or a
        jr z,src_c
        ld l,c                  ; D_FILE + 1 + row x 33
        ld h,0
        ld d,h
        ld e,l
        add hl,hl
        add hl,hl
        add hl,hl
        add hl,hl
        add hl,hl
        add hl,de
        ld de,(DFILE)
        add hl,de
        inc hl
        and a
        ret

; Collapsed (pic_crow is the row; the hints' rows from VARS back when
; the table doesn't reach them, pic_hback): its line to its $76, looked
; for by cpir (to where the next row starts if that is known, else 33
; bytes; to VARS at most), into pic_buf, the rest spaces; only with the
; copy and the row's compare in hand, so it is never cut short. Where
; the line ends the next row starts: the table takes it if that is the
; next row it needs (pic_ext); if the table has that row already
; somewhere else, the table isn't the display's (a $76 POKEd into a
; line, say): it is made again from row 0 and this row waits. Costs
; COST_COPY + the bytes looked at / 2 + the spaces put back / 4.
src_c:  ld a,(pic_fwd)          ; the hints' rows, if the table doesn't
        ld b,a                  ; reach them: from VARS back (not pic_fwd)
        ld a,(pic_hback)
        sub b
        jr z,sr_f
        jr c,sr_f
        ld a,(pic_known)
        cp c
        ld a,0
        jr nc,sr_f
        ld a,c
        call pic_bstart
        ret c
        ld a,1
        jr sr_h
sr_f:   ld a,c
        call pic_start          ; HL: where the row starts
        ret c
        xor a
sr_h:   ld (pic_sback),a
        ld (pic_lst),hl
        or a                    ; what the copy looks at: to where the next
        jr nz,sr_hb             ; row starts, if that is known, else 33
        ld a,(pic_crow)
        ld e,a
        ld a,(pic_known)
        cp e
        ld a,33
        jr z,sr_lim
        ld a,e
        inc a
        push hl
        call pic_rt
        ld a,(hl)
        inc l
        ld h,(hl)
        ld l,a
        pop de
        and a
        sbc hl,de
        ex de,hl                ; (HL: the start again)
        ld a,d
        or a
        jr nz,sr_33
        ld a,e
        cp 34
        jr c,sr_lim
sr_33:  ld a,33
        jr sr_lim
sr_hb:  push hl                 ; (found back: to the next row's start)
        ex de,hl
        ld hl,(pic_bend)
        and a
        sbc hl,de
        ld a,l
        pop hl
sr_lim: ld (pic_llim),a         ; only with the copy and the compare in
        srl a                   ; hand: COST_ROW + COST_COPY + that / 2 +
        add a,COST_ROW+COST_COPY+32/4 ; the spaces
        ld e,a
        ld a,(pic_left)
        cp e
        ret c
        call pic_line           ; HL: past it, C: bytes looked at, carry
        push hl                 ; if its $76 was found
        sbc a,a
        ld b,a                  ; B: $FF found, 0 not
        ld a,c                  ; COST_COPY + bytes / 2
        srl a
        add a,COST_COPY
        ld e,a
        ld a,(pic_left)
        sub e
        ld (pic_left),a
        ld a,c                  ; the line's length, without its $76
        add a,b                 ; (B: -1 if found)
        cp 33
        jr c,sr_l
        ld a,32
sr_l:   ld c,a
        pop de                  ; DE: past the line
        ld a,(pic_sback)
        or a
        jr nz,sr_copy           ; (found back: not the table's)
        ld a,(pic_crow)
        ld hl,pic_known
        cp (hl)
        jr nz,sr_old
        inc b                   ; the next row: the table takes it (a line
        jr z,sr_ext             ; without its $76: it isn't a display's)
        ld a,1
        ld (pic_odd),a
sr_ext: push bc
        call pic_ext
        pop bc
        jr sr_copy
sr_old: inc a                   ; known already: the same?
        call pic_rt
        ld a,(hl)
        cp e
        jr nz,sr_bad
        inc l
        ld a,(hl)
        cp d
        jr z,sr_copy
sr_bad: xor a                   ; no: made again, from row 0, and on
        ld (pic_known),a        ; from D_FILE only till the display moves
        inc a                   ; (a $76 too many: its lines counted back
                                ; aren't its rows)
        ld (pic_walked),a
        ld (pic_fwd),a
        scf
        ret
sr_copy:
        ld hl,(pic_lst)         ; C bytes of it, then spaces over what the
        ld de,pic_buf           ; one before left
        ld a,(pic_blen)
        sub c
        push af
        ld a,c
        ld (pic_blen),a
        ld b,0
        or a
        jr z,sr_0
        ldir
sr_0:   pop af
        jr c,sr_done
        jr z,sr_done
        ld b,a
        srl a                   ; the spaces: 1/4 unit each (8 at most,
        srl a                   ; within COPY_MAX)
        ld c,a
        ld a,(pic_left)
        sub c
        ld (pic_left),a
        xor a
sr_p:   ld (de),a
        inc e
        djnz sr_p
sr_done:
        ld hl,pic_buf
        and a
        ret

; The line from HL: HL past its $76 (carry), or past the pic_llim bytes
; looked at or at VARS (no carry: no $76 there); C: the bytes looked at.
pic_line:
        ex de,hl
        ld hl,(VARS)
        and a
        sbc hl,de               ; to VARS, pic_llim (33 at most) at most
        ld a,(pic_llim)
        ld c,a
        ld a,h
        or a
        jr nz,pl_n
        ld a,l
        cp c
        jr nc,pl_n
        ld c,l
pl_n:   ld b,0
        ex de,hl
        ld a,b
        or c
        ret z                   ; at VARS (no carry: or)
        push hl
        ld a,$76
        cpir
        pop bc                  ; (flags kept)
        push af
        ld a,l                  ; C: HL - the start (33 at most)
        sub c
        ld c,a
        pop af
        scf
        ret z
        ccf
        ret

; HL: where collapsed row A (0-24) starts, the table taken on as far as
; that: each row past pic_known walked to its $76 (cpir, 33 bytes at
; most), WALK_ROW + its bytes / COST_WALK units, WALK_MAX in hand for
; each. A line with no $76 there, or past VARS, isn't a display's: the
; rows after it start at VARS, and pic_odd tells pic_mode. Carry: the
; budget can't pay for the next (the rows found so far stay found).
pic_start:
        ld (pic_want),a
        ld hl,pic_known
        cp (hl)
        jr c,pst_got
        jr z,pst_got
        ld a,(hl)
        call pic_rt
        ld e,(hl)
        inc l
        ld d,(hl)
        inc l
        ex de,hl                ; HL: row known's start, DE: the next entry
pst_l:  ld a,(pic_left)
        cp WALK_MAX
        ret c
        push hl
        ld bc,33
        ld a,$76
        cpir
        pop bc                  ; BC: where it started
        jr nz,pst_x
        ld a,(VARS)             ; (past the $76: VARS at most)
        sub l
        ld a,(VARS+1)
        sbc a,h
        ld a,l
        jr nc,pst_c
pst_x:  ld a,1
        ld (pic_odd),a
        ld a,l
        ld hl,(VARS)
pst_c:  sub c                   ; the bytes looked at
        srl a
        srl a
        add a,WALK_ROW
        ld c,a
        ld a,(pic_left)
        sub c
        ld (pic_left),a
        ex de,hl                ; the next row's start into the table
        ld (hl),e
        inc l
        ld (hl),d
        inc l
        ex de,hl
        ld a,(pic_known)
        inc a
        ld (pic_known),a
        ld c,a
        ld a,(pic_want)
        cp c
        jr nz,pst_l
        and a                   ; (HL: its start)
        ret
pst_got:
        ld a,(pic_want)
        call pic_rt
        ld a,(hl)
        inc l
        ld h,(hl)
        ld l,a
        and a
        ret

; HL: where collapsed row A (a hint's: the editor's, DF_CC's) starts,
; found back from VARS (the last line ends at VARS - 1) with cpdr, a row
; at a time (BACK_ROW + its bytes / COST_WALK, BACK_MAX in hand for
; each); the rows found this frame stay found (pic_brow, pic_bpos, each
; in pic_btab; pic_fix's from another row, then from VARS again). A
; display's lines counted back are its rows counted on (24 line ends).
; Carry: the budget can't, or no $76 within 33 bytes back (not a
; display's).
pic_bstart:
        ld (pic_want),a
pbs_l:  ld a,(pic_want)
        ld hl,pic_brow
        cp (hl)
        jp nc,pbs_got
        ld a,(pic_left)
        cp BACK_MAX
        ret c
        ld hl,(pic_bpos)        ; row brow starts here: the line before
        dec hl                  ; ends at HL - 1; looked for back from the
        dec hl                  ; byte before that $76
        push hl
        ld de,(DFILE)
        and a
        sbc hl,de               ; to D_FILE's own $76, 33 at most
        jr c,pbs_no
        inc hl
        ld b,h
        ld c,l
        ld a,h
        or a
        jr nz,pbs_33
        ld a,l
        cp 33
        jr c,pbs_n
pbs_33: ld bc,33
pbs_n:  pop hl
        ld a,$76
        cpdr
        scf
        ret nz                  ; none
        inc hl
        inc hl                  ; past it: the row's start
        ld de,(pic_bpos)
        ld (pic_bend),de
        ld (pic_bpos),hl
        ex de,hl
        and a
        sbc hl,de               ; the bytes looked at (and the $76)
        ld a,l
        srl a
        srl a
        add a,BACK_ROW
        ld b,a
        ld a,(pic_left)
        sub b
        ld (pic_left),a
        ld hl,pic_brow
        dec (hl)
        ld a,(hl)               ; into pic_btab
        call pic_bt
        ld de,(pic_bpos)
        ld (hl),e
        inc l
        ld (hl),d
        jr pbs_l
pbs_no: pop hl
        scf
        ret

pic_bt: ld hl,pic_btab          ; HL: row A's entry in pic_btab
        add a,a
        add a,l
        ld l,a
        ret

pbs_got:
        ld hl,(pic_bpos)
        and a
        ret

pic_rt: ld hl,pic_rtab          ; HL: row A's entry in pic_rtab
        add a,a
        add a,l
        ld l,a                  ; (in one page)
        ret

; DE: where row pic_known + 1 starts, just found (src_c): it is known
; now.
pic_ext:
        ld a,(pic_known)
        inc a
        ld c,a
        call pic_rt             ; HL: its entry
        ld (hl),e
        inc l
        ld (hl),d
        ld a,c
        ld (pic_known),a
        ret

; A: the row DF_CC is in. Carry: none (outside the display), or the
; budget can't pay for finding it in a collapsed one.
pic_ccrow:
        ld de,(DF_CC)
        ld hl,(pic_rtab)        ; row 0's start: D_FILE + 1
        ex de,hl
        and a
        sbc hl,de               ; DF_CC - D_FILE - 1
        ret c
        ld a,(pic_exp)
        or a
        jp z,pcc_c
        ld de,24*33             ; expanded: none past row 23 (the editor's
        sbc hl,de               ; DF_CC is), else / 33: the row of its
        ccf                     ; 16-byte block (pcc_tab), or the next if
        ret c                   ; it starts past that row's end
        add hl,de
        push hl
        srl h                   ; / 16: a table's entry
        rr l
        srl h
        rr l
        srl h
        rr l
        srl h
        rr l
        ld de,pcc_tab
        add hl,de
        ld c,(hl)
        ld a,c                  ; HL: that row + 1's start (row x 33 + 33)
        add a,a
        ld e,a
        ld d,0
        ld hl,pic_r33
        add hl,de
        ld e,(hl)
        inc hl
        ld d,(hl)
        ld hl,33
        add hl,de
        ex de,hl
        pop hl
        and a
        sbc hl,de
        ld a,c
        jr c,pcc_t
        inc a
pcc_t:  and a
        ret
pcc_tab:                        ; (16 x n) / 33, n 0-49
        db 0,0,0,1,1,2,2,3,3,4,4,5,5,6,6,7,7,8,8,9,9,10,10,11,11,12,12,13,13,14,14,15,15,16,16,16,17,17,18,18,19,19,20,20,21,21,22,22,23,23
pcc_c:  add hl,de               ; collapsed: the last row starting at DF_CC
        ex de,hl                ; or before it (DE: DF_CC)
        ld hl,(VARS)
        dec hl
        and a
        sbc hl,de
        ret c                   ; past the last $76
        ld a,(pic_left)         ; 12 units, first (and any walk on top)
        sub 12
        ret c
        ld (pic_left),a
        ld a,(pic_known)        ; the table past DF_CC already: search it
        cp 24
        jr nc,pcc_s
        call pic_rt
        ld a,(hl)
        inc l
        ld h,(hl)
        ld l,a
        and a
        sbc hl,de
        jr nc,pcc_s
        ld a,(pic_fwd)          ; else walked from the nearer end: from
        or a                    ; the table's last row, or back from VARS
        jr nz,pcc_w             ; (pic_bstart)
        ld b,h
        ld c,l
        ld hl,(VARS)
        and a
        sbc hl,de
        add hl,bc               ; (carry: VARS no nearer)
        jr c,pcc_w
pcc_b:  ld a,(pic_brow)         ; back: rows up, to the one starting at
        dec a                   ; DF_CC or before
        push de
        call pic_bstart
        pop de
        ret c
        and a
        sbc hl,de
        jr z,pcc_bx
        jr nc,pcc_b
pcc_bx: ld a,(pic_brow)
        and a
        ret
pcc_w:  ld a,(pic_known)        ; the table on to a row starting at DF_CC
        cp 24                   ; or past it (or to its end)
        jr nc,pcc_s
        call pic_rt
        ld a,(hl)
        inc l
        ld h,(hl)
        ld l,a
        and a
        sbc hl,de
        jr nc,pcc_s
        ld a,(pic_left)         ; a row more: COST_SYNC on top of its walk
        sub COST_SYNC
        ret c
        ld (pic_left),a
        ld a,(pic_known)
        inc a
        push de
        call pic_start
        pop de
        ret c
        jr pcc_w
pcc_s:  inc de                  ; DE: DF_CC + 1 (a start at DF_CC or before
        ld b,0                  ; is below it). B: such a row, C: past them
        ld a,(pic_known)        ; (or the last)
        ld c,a
        call pcc_le
        ld a,c
        jr c,pcc_x              ; the last starts at DF_CC or before
pcc_bs: ld a,c                  ; halves, to rows next to each other
        sub b
        cp 2
        ld a,b
        jr c,pcc_x
        add a,c
        rra
        push af
        call pcc_le
        pop hl                  ; H: the middle (flags kept)
        jr nc,pcc_h
        ld b,h
        jr pcc_bs
pcc_h:  ld c,h
        jr pcc_bs
pcc_x:  cp 24
        jr c,pcc_y
        ld a,23
pcc_y:  and a
        ret
pcc_le: call pic_rt             ; row A's start - DE: carry if below
        ld a,(hl)
        sub e
        inc l
        ld a,(hl)
        sbc a,d
        ret

; ---------------------------------------------------------------- block operations
; The ROM's CLS and SCROLL commands (the command table points at
; cls_hook and scr_hook, vdccore.inc: tools/build.py) only note what they did, for the
; next pic_step: blk_pend rows up within the top blk_pu rows. A SCROLL is
; 1 up within 24 - DF_SZ (the lower screen stays), a CLS all 24 filled
; (as many up as rows: none is copied). Scrolls before the next frame add
; up (the same rows; all filled at most), a CLS replaces whatever waited,
; and anything else that can't be said so drops it (the compare redraws).
;
; blk_step does it, first in pic_step. The VDC (bo_vdc): its own block
; copy and fill, a row's 64 picture columns at a time (never the panel's
; columns 64-79 or row 24): row r copied from row r + k (R24 bit 7,
; R32/R33 the source) while r + k is within the rows, the rest filled with
; spaces ($00: both halves blank; R31's byte, then R30). Before each row's
; registers the VDC is polled ready (an operation's time is never
; assumed) and, in the window, its blank must still be on (else pw_trip).
; In the window the registers go unpolled (LK_MODE 1) and a row begins
; only with BLK_STEPS left (its operation charged at BLK_CYC cycles a
; byte); without one polled, for BLK_UNITS. Then the shadow (bo_shd), the
; same way, a row while the clock allows (BLK_SLIM steps after the rise),
; or for BLK_SUNITS: it needs no window. The runs waiting are written
; first, where they are. So the VDC and the shadow change alike and the
; compare stays right: it only has less to do. Whatever doesn't fit goes
; on next frame, which does nothing else meanwhile (no compare while the
; shadow moves). While the ROM's CLS or SCROLL runs the picture holds
; (blk_hold: the hooks).

; From pic_step's ps_blk, made a JP here by the hooks (else an LD DE, nn:
; nothing waiting costs a frame 10 T, no more). Back to ps_bk1, or to
; ps_end while an operation goes on (nothing else this frame). Changes AF
; BC DE HL.
blk_step:
        call bo_step
        jp c,ps_end
        ld a,(pic_left)         ; (without the window an operation may have
        cp COST_MODE+COST_ROW   ; left too few units for the rest: pic_mode
        jp c,ps_end             ; takes its own unchecked)
        ld hl,blk_hold          ; a CLS or SCROLL under way (D_FILE half
        ld a,(hl)               ; done): nothing else, BLK_HOLD frames at most
        or a                    ; (the ROM may stop it with a report)
        jr z,bs_1
        dec (hl)
        jp ps_end
bs_1:   ld a,(blk_k)            ; nothing more: ps_blk back to LD DE, nn
        ld hl,blk_pend
        or (hl)
        jp nz,ps_bk1
        ld a,$11
        ld (ps_blk),a
        jp ps_bk1

; Carry: an operation is going on.
bo_step:
        ld a,(blk_k)
        or a
        jr nz,bo_go
        ld a,(blk_pend)
        or a
        ret z
        ld a,(blk_cn)
        or a
        jr nz,bo_q
        ld (blk_pend),a         ; no block operations (blk_cfg): dropped
        ld hl,(blk_nd)
        inc hl
        ld (blk_nd),hl
        ret
bo_q:   ld a,(pic_qn)           ; the runs waiting written first, where they
        or a                    ; are (the window's, or FB_CHARS polled);
        jr z,bo_new             ; till then nothing else. All 24 rows filled
        ld a,(blk_pu)           ; (a CLS): they are dropped instead
        cp 24
        jr c,bo_qw
        ld hl,blk_pend
        cp (hl)
        jr z,bo_qd
        jr nc,bo_qw
bo_qd:  xor a
        ld (pic_qn),a
        ld hl,pic_q
        ld (pic_qp),hl
        jr bo_new
bo_qw:  call pic_wfl
        ld a,(pic_unp)
        or a
        call z,pic_pfl
        ld a,(pic_qn)
        or a
        scf
        ret nz
bo_new: ld a,(blk_pend)
        ld (blk_k),a
        xor a
        ld (blk_pend),a
        ld a,(blk_pu)
        ld (blk_u),a
        xor a
        ld (blk_i),a
        ld (blk_j),a
        ld (pic_hcl),a          ; (DF_CC's rows: looked at again)
        ld hl,(blk_ns)
        inc hl
        ld (blk_ns),hl
bo_go:  ld a,(lk_t0)            ; the window's clock (bv_clk): steps since
        ld (bv_t0+1),a          ; the rise (timer B counts down) a row may
        ld a,(lkl_w+1)          ; begin at: the window's last (lk_left's,
        sub BLK_STEPS           ; less what trips cut), less BLK_STEPS
        ld (bv_lim+1),a
        call bo_vdc
        push af
        ld a,(blk_k)            ; (dropped: bv_lost)
        or a
        jr nz,bg_s
        pop af
        scf
        ret
bg_s:   call bo_shd
        pop bc
        ret c                   ; the shadow not done
        bit 0,c
        scf
        ret nz                  ; the VDC not done
        call bo_rdy             ; done: the VDC ready (the writes may follow)
        ld a,(blk_k)            ; collapsed: the last row moved up, u - k -
        ld b,a                  ; 1, compared first (pic_srow: + 1; it may
        ld a,(blk_u)            ; show D_FILE's of a moment before, a
        sub b                   ; PRINT's), and not the sweep this frame
        ld b,a                  ; (bit 7: the hints have the next)
        xor a
        ld (blk_k),a
        ld a,(pic_exp)
        or a
        ret nz
        ld a,b
        or $80
        ld (pic_srow),a
        xor a
        ret

; The VDC's rows from blk_i on: copies (U - k - i of them), then fills.
; In the window (LK_MODE 1) a tight loop: a row's registers unpolled once
; the VDC is ready (and still in its blank), then, while it works, the
; next row's addresses, the count, the clock. Carry: not all done.
; Changes AF BC DE HL (and keeps BC', used: B' the rows left).
bo_vdc: exx
        push bc
        exx
        call bv_go
        exx
        pop bc
        exx
        ret
bv_go:  ld a,(blk_i)
        ld hl,blk_u
        cp (hl)
        ret nc
        ld e,a                  ; copies left: U - (i + k)
        ld a,(blk_k)
        add a,e
        ld d,a                  ; (D: the source row)
        ld a,(hl)
        sub d
        jp c,bv_f0
        jp z,bv_f0
        exx
        ld b,a                  ; B': the rows
        exx
        ld a,(blk_r24)          ; R24: copies
        or $80
        call bo_m24
        ld a,d
        call bo_r80
        ex de,hl                ; DE: the source's VDC address
        ld a,(blk_i)
        call bo_r80             ; HL: the row's
        ld bc,VDC
        ld a,(pic_unp)
        dec a
        jp nz,bv_cp
        call bv_clk
        jp c,bv_ce
bv_cw:  in a,(c)                ; the VDC ready, in its blank
        jp p,bv_cw
        and $20
        jp z,bv_ctr
        bo_wr 18 h 0
        bo_wr 19 l 0
        bo_wr 32 d 0
        bo_wr 33 e 0
        ld a,30
        out (c),a
        inc c
        ld a,(blk_cn)
        out (c),a               ; (it goes: the rest while the VDC works)
        dec c
        in a,(c)                ; its registers all in the blank? (a status
        and $20                 ; read is harmless while it works)
        jp z,bv_lost
        ld a,80
        add a,l
        ld l,a
        jr nc,$+3
        inc h
        ld a,80
        add a,e
        ld e,a
        jr nc,$+3
        inc d
        exx
        dec b
        exx
        jr z,bv_cx
        call bv_clk
        jr nc,bv_cw
        jr bv_ce
bv_ctr: call pw_trip            ; (the blank over under an operation)
bv_ce:  call bo_rdy             ; (the last one done, and in the blank: else
        call bv_ci              ; a trip, bo_rdy's)
        scf
        ret
bv_cx:  call bv_ci
        jr bv_f0
bv_ci:  ld a,(blk_u)            ; blk_i: U - k - the rows left
        ld hl,blk_k
        sub (hl)
        exx
        sub b
        exx
        ld (blk_i),a
        ret
bv_cp:  call bv_may             ; polled
        jr c,bv_ce
        push de
        ld e,d
        ld a,32
        call bc_hl
        pop de
        ld a,33
        call bc_w
        push de
        ld a,(blk_cn)
        ld e,a
        ld a,30
        call bc_w
        pop de
        ld a,80
        add a,l
        ld l,a
        jr nc,$+3
        inc h
        ld a,80
        add a,e
        ld e,a
        jr nc,$+3
        inc d
        exx
        dec b
        exx
        jr nz,bv_cp
        jr bv_cx

bv_f0:  ld a,(blk_i)            ; fills, to row U - 1
        ld hl,blk_u
        sub (hl)
        ret nc
        neg
        exx
        ld b,a
        exx
        ld a,(blk_r24)
        call bo_m24
        ld a,(blk_i)
        call bo_r80
        ld bc,VDC
        ld a,(pic_unp)
        dec a
        jr nz,bv_fp
        call bv_clk
        jr c,bv_fe
bv_fw:  in a,(c)
        jp p,bv_fw
        and $20
        jr z,bv_ftr
        bo_wr 18 h 0
        bo_wr 19 l 0
        ld a,31
        nop
        out (c),a
        inc c
        xor a
        out (c),a
        dec c
        ld a,30
        out (c),a
        inc c
        ld a,(blk_fn)
        out (c),a
        dec c
        in a,(c)
        and $20
        jp z,bv_lost
        ld a,80
        add a,l
        ld l,a
        jr nc,$+3
        inc h
        exx
        dec b
        exx
        jr z,bv_fx
        call bv_clk
        jr nc,bv_fw
        jr bv_fe
bv_ftr: call pw_trip
bv_fe:  call bo_rdy
        call bv_fi
        scf
        ret
bv_fx:  call bv_fi
        and a
        ret
bv_fi:  ld a,(blk_u)            ; blk_i: U - the rows left
        exx
        sub b
        exx
        ld (blk_i),a
        ret
bv_fp:  call bv_may
        jr c,bv_fe
        ld e,0
        ld a,31
        call bc_hl
        ld a,(blk_fn)
        ld e,a
        ld a,30
        call bc_w
        ld a,80
        add a,l
        ld l,a
        jr nc,$+3
        inc h
        exx
        dec b
        exx
        jr nz,bv_fp
        jr bv_fx

; A row's registers not all in the blank: any of them may be lost, and
; the operation with them, or gone from another address: as pw_chk, the
; whole shadow unknown (the compare writes every cell again), the queue
; dropped, no window from here; and the operation dropped, with whatever
; waited. The sweep goes on from the row before blk_i, the first row of
; this frame's batch (not the row lost: blk_i moves on only at the batch's
; end): an operation from a stale address (the last one's end) hits that
; row or one after it, so the rows hit come early in the sweep (else they
; can be its last).
bv_lost:
        call pw_chk
        ld a,(blk_i)
        or a
        jr z,bvl_r
        dec a
bvl_r:  ld (pic_row),a
        xor a
        ld (pic_scol),a
        ld (blk_k),a
        ld (blk_pend),a
        scf
        ret

; NC: in the window the next row may begin (bv_t0, bv_lim: blk_step's).
; Changes AF.
bv_clk: ld a,CIA2/256           ; (port CIA2+7: timer B's high byte)
        in a,(7)
        cpl
        inc a
bv_t0:  add a,0                 ; steps since the rise,
bv_lim: cp 0                    ; past the last row's
        ccf
        ret

; NC: the next row may begin, polled: in the window's frame by
; the clock, else for BLK_UNITS; once the VDC is ready (in the window, in
; its blank: else pw_trip, Carry). BC = VDC. Changes AF.
bv_may: ld a,(pic_unp)
        or a
        jr z,bv_un
        call bv_clk
        ret c
        jr bo_rdy
bv_un:  ld a,(pic_left)
        sub BLK_UNITS
        ret c
        ld (pic_left),a
; Until the VDC is ready (BC <- VDC). Carry: in the window, its blank is
; over (pw_trip done: the frame stops). Changes AF BC.
bo_rdy: ld bc,VDC
br_l:   in a,(c)
        jp p,br_l
        and $20
        ret nz
        ld a,(pic_unp)
        or a
        ret z
        push de
        push hl
        call pw_trip
        pop hl
        pop de
        ld bc,VDC
        scf
        ret

; R24 <- A (polled), unless it holds that already (blk_md, from the
; operation's start unknown). Changes AF; BC <- VDC.
bo_m24: ld bc,VDC
        push hl
        ld hl,blk_md
        cp (hl)
        jr z,bm_x
        ld (hl),a
        push de
        ld e,a
        ld a,24
        call bc_w
        pop de
bm_x:   pop hl
        ret

; The shadow's rows from blk_j on: the copies (row r from row r + k: one
; move on through the rows, 32 x LDI a row), then the fills (spaces: 16 x
; PUSH of 0, SP borrowed: interrupts are off), each row while the clock
; allows (BLK_SLIM steps after the rise) or for BLK_SUNITS. Carry: not
; all done. Changes AF BC DE HL (and keeps BC', used: B' the rows left).
bo_shd: exx
        push bc
        exx
        call bs_go
        exx
        pop bc
        exx
        ret
bs_go:  ld a,(blk_j)
        ld hl,blk_u
        cp (hl)
        ret nc
        ld c,a
        ld a,(hl)               ; copies left: U - k - j
        ld hl,blk_k
        sub (hl)
        sub c
        jr c,bs_f0
        jr z,bs_f0
        exx
        ld b,a
        exx
        ld a,c
        call bo_r32
        ex de,hl                ; DE: row j
        ld a,(blk_j)
        ld hl,blk_k
        add a,(hl)
        call bo_r32             ; HL: row j + k
bs_cl:  call bs_may
        jr c,bs_ce
        call bo_ldi             ; (HL, DE on to the next rows)
        exx
        dec b
        exx
        jr nz,bs_cl
        call bs_ci
bs_f0:  ld a,(blk_j)            ; the fills: to row U - 1
        ld hl,blk_u
        sub (hl)
        ret nc
        neg
        exx
        ld b,a
        exx
        ld a,(blk_j)
        call bo_r32
        ex de,hl
bs_fl:  call bs_may
        jr c,bs_fe
        ld hl,32
        add hl,de
        ld (bo_sp),sp
        ld sp,hl
        ex de,hl                ; (DE: the next row)
        ld hl,0
        push hl
        push hl
        push hl
        push hl
        push hl
        push hl
        push hl
        push hl
        push hl
        push hl
        push hl
        push hl
        push hl
        push hl
        push hl
        push hl
        ld sp,(bo_sp)
        exx
        dec b
        exx
        jr nz,bs_fl
        ld a,(blk_u)
        ld (blk_j),a
        and a
        ret
bs_ce:  call bs_ci              ; (not now: blk_j as far as they got)
        scf
        ret
bs_ci:  ld a,(blk_u)            ; blk_j: U - k - the copies left
        ld hl,blk_k
        sub (hl)
        exx
        sub b
        exx
        ld (blk_j),a
        ret
bs_fe:  ld a,(blk_u)            ; U - the fills left
        exx
        sub b
        exx
        ld (blk_j),a
        scf
        ret

; NC: a shadow row may begin: the window's frame by the clock (BLK_SLIM
; steps after the rise), else for BLK_SUNITS. Changes AF B.
bs_may: ld a,(pic_unp)
        or a
        jr z,bsm_u
        ld a,CIA2/256           ; (port CIA2+7: timer B's high byte)
        in a,(7)
        ld b,a
        ld a,(lk_t0)
        sub b
        cp BLK_SLIM
        ccf
        ret
bsm_u:  ld a,(pic_left)
        sub BLK_SUNITS
        ret c
        ld (pic_left),a
        ret

bo_sp:  dw 0                    ; bo_shd: SP meanwhile

; HL <- row A x 80 (the VDC's address). Changes AF.
bo_r80: push de
        ld l,a
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
        pop de
        ret

; HL <- SHADOW + row A x 32. Changes AF.
bo_r32: ld l,a
        ld h,0
        add hl,hl
        add hl,hl
        add hl,hl
        add hl,hl
        add hl,hl
        ld a,h
        add a,SHADOW/256
        ld h,a
        ret

; R18/R19 <- HL, then register A <- E, polled. BC = VDC. Changes AF.
bc_hl:  push de
        push af
        ld e,h
        ld a,18
        call bc_w
        ld e,l
        inc a
        call bc_w
        pop af
        pop de
        jp bc_w

; 32 bytes from HL to DE (a shadow row): LDI, 16 a turn. Changes F BC.
bo_ldi: ld bc,32
bl_l:   ldi
        ldi
        ldi
        ldi
        ldi
        ldi
        ldi
        ldi
        ldi
        ldi
        ldi
        ldi
        ldi
        ldi
        ldi
        ldi
        jp pe,bl_l
        ret

; What c128/boot128.asm's vblk found the VDC's block operations do (it
; writes them here before this code goes to bank 1): R30 for a copy of a
; row (64 bytes) and for a fill of one after R31's byte (blk_cn 0: no
; block operations: none was tried, or they weren't one of the counts
; expected), R24 for a fill (bit 7 set: a copy), and its counts: the
; copy's bytes and the fill's (tools/sim128.py shows them).
blk_cfg:
blk_cn:  db 0
blk_fn:  db 0
blk_r24: db 0
blk_cal0: db 0,0

; Register A <- E, polled (ready before, and after the select). BC = VDC.
bc_w:   call bc_rdy
        out (c),a
        call bc_rdy
        inc c
        out (c),e
        dec c
        ret
bc_rdy: in f,(c)
        jp p,bc_rdy
        ret

; Until the VDC's blank has just begun (status bit 5: the display, then
; the blank). BC = VDC. Changes AF.
bc_vb:  in a,(c)
        and $20
        jr nz,bc_vb
bv_b:   in a,(c)
        and $20
        jr z,bv_b
        ret
