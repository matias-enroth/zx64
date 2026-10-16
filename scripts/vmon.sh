#!/bin/sh
# Send commands to the VICE remote monitor, then resume emulation.
# e.g. scripts/vmon.sh 'screenshot "/tmp/shot.png" 2'
{ for c in "$@"; do echo "$c"; done; echo "x"; sleep 1; } | nc -q 2 127.0.0.1 6510
