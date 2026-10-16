#!/bin/sh
# Headless VICE for automated testing (Linux: needs Xvfb, VICE 3.7+).
# Starts x64sc detached on DISPLAY :99 with the remote monitor on 127.0.0.1:6510.
# ROMS: directory with kernal/basic/chargen/dos1541 images (VICE's own data dir works).
# usage: scripts/vstart.sh -cpmcart -autostart build/zx64.d64
# Note: -limitcycles never fires once the Z80 owns the bus; use vmon.sh to screenshot.
ROMS=${ROMS:-/tmp/vroms}
pkill -x x64sc; pkill -x Xvfb; sleep 1     # -x: not a shell that mentions x64sc
setsid nohup Xvfb :99 -screen 0 1024x768x24 >/dev/null 2>&1 &
sleep 1
DISPLAY=:99 setsid nohup x64sc -default \
  -kernal "$ROMS/kernal-901227-03.bin" -basic "$ROMS/basic-901226-01.bin" \
  -chargen "$ROMS/chargen-901225-01.bin" -dos1541 "$ROMS/dos1541-325302-01+901229-05.bin" \
  -sounddev dummy -drive8type 1541 -drive8truedrive \
  -remotemonitor -remotemonitoraddress ip4://127.0.0.1:6510 "$@" >/tmp/vice.log 2>&1 &
