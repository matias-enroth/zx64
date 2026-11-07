# games/

`.p` files here go on the disks of all three builds, named lowercase
without `.p` (`Mazogs.p` → `LOAD "MAZOGS"`). `tools/pcheck.py` warns about what may
not work on zx64 first; `-v` lists everything. Not in git: they belong
to their authors.

`make test` uses three of them where it finds them: `mazogs.p`,
`BoulderL.p` and `test/aydemo.p` (in `test/`, so it stays off the disks).
Without them, the checks that load them are skipped.
