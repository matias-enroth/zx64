; vidpal.inc - the VIC's PAL or NTSC, for both C128 builds' SPEED
; (progs/speed.bas's {vidpal}), measured once by the Z80 at the start
; (the includer's zentry_more). The C128 kernal's own flag (PALNTS,
; $0A03) is in bank 0's bottom 4K, where the Z80 sees its BIOS ROM
; instead, and boot128 has no room to copy it
; across. A PAL VIC draws 312 lines, an NTSC one 263 (0-262): PAL if the
; raster is seen past line 262 (bit 8 set and $D012 7 or more) within
; 1024 polls of 64 T (73 with bit 8 set): ~66K T, ~1.7 PAL frames (PAL's
; last 49 lines come once a frame). One sighting decides. The two reads
; aren't one: line 255's bit 8 with line 256's $D012 (0), or line 262's
; with the wrap's (0), is never taken for PAL.
; Interrupts off. Changes AF BC DE.
vidm:   ld bc,VIC+$11
        ld de,$0400
vm_l:   in a,(c)                ; ($D011: bit 7 the line's bit 8)
        inc c
        rla
        in a,(c)                ; ($D012)
        dec c
        jr nc,vm_n
        cp 7
        jr nc,vm_pal
vm_n:   dec e
        jr nz,vm_l
        dec d
        jr nz,vm_l
        ret                     ; (NTSC: vidpal stays 0)
vm_pal: ld (vidpal),a           ; (PAL: $D012 there, 7 or more)
        ret
vidpal: db 0                    ; 0: NTSC, else PAL
