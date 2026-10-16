#!/bin/sh
# Type into the headless VICE window, one key at a time, held long enough
# for the ZX81 ROM's debounce. Args are xdotool keysyms, e.g.
#   scripts/zkey.sh j shift+p t e t r i s shift+p Return    # LOAD "TETRIS"
export DISPLAY=:99
W=$(xdotool search --name "VICE" | head -1)
xdotool windowfocus "$W" 2>/dev/null
for k in "$@"; do
  xdotool keydown "$k"; sleep 0.12; xdotool keyup "$k"; sleep 0.25
done
