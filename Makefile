# zx64 - the ZX81 ROM on the Z80 of the C64 CP/M cartridge
#
#   make              build/zx64.d64: the boot file, the monitor, the test
#                     programs and every .p in games/; build/zx128.d64,
#                     the same for a C128 (it boots by itself), and
#                     build/zx128.rom and zx128.crt, the C128's from a
#                     32K function ROM or a cartridge, no disk;
#                     build/zx128vic.d64, the C128's with zx64's picture
#                     on the VIC, and its zx128vic.rom and zx128vic.crt
#                     likewise. Needs rom/zx81.rom (or ROM=...), GNU
#                     z80asm, acme and c1541
#   make P="a.p b.p"  more .p files on the d64
#   make test         zx64's bytes against the blessed sums (tools/zx64.sha256,
#                     the standard ROM only; build.py --bless-zx64 after
#                     a change to zx64 on purpose), both CPUs in emulators,
#                     zx64's and then zx128's and zx128vic's C128 model,
#                     and the Ultimate tool's tests; needs the z80 and
#                     py65 packages
#                     (python3 -m venv .venv &&
#                     .venv/bin/pip install z80 py65)
#   make vice         the d64 in VICE with the CP/M cartridge
#   make vice128      zx128.d64 in VICE's x128; vice128rom, vice128crt:
#                     x128 from the function ROM (internal) or the
#                     cartridge (build/obj/zx128-vice.crt), no disk
#   make vice128vic   build/zx128vic.d64 (zx128 with zx64's picture on the
#                     VIC's 40 columns, made by make too) in x128;
#                     vice128vicrom, vice128viccrt: from its function ROM
#                     or cartridge (build/obj/zx128vic-vice.crt), no disk
#   make jtest        build/jtest.prg, the JiffyDOS probe (not on the d64:
#                     put it on a disk with zx64's files, LOAD and RUN)
#   make memtest128   build/memtest128.d64, a VDC RAM and REU test for the
#                     C128 (extras/memtest128/README.md), and memtest128f.d64, the
#                     same with planted errors

ROM    ?= rom/zx81.rom
P      ?=
GAMES  := $(sort $(wildcard games/*.p games/*.P))
Z80ASM ?= z80asm
ACME   ?= acme
C1541  ?= c1541
X64    ?= x64sc
X128   ?= x128
# use ./.venv if there is one (see make test)
PYTHON ?= $(if $(wildcard .venv/bin/python),.venv/bin/python,python3)
export Z80ASM ACME C1541

ZX128 := build/zx128.d64 build/zx128.rom build/zx128.crt build/obj/zx128-vice.crt
ZX128VIC := build/zx128vic.d64 build/zx128vic.rom build/zx128vic.crt build/obj/zx128vic-vice.crt

all: build/zx64.d64 $(ZX128) $(ZX128VIC)

SHARED := z80/kbd.inc z80/irq.inc z80/msgx.inc z80/rompatch.inc z80/reset.inc z80/romkbd.inc z80/loadsave.inc z80/setname.inc z80/vars.inc z80/bp.inc

build/zx64.d64: z80/zx64.asm z80/vicpic.inc z80/mon.asm z80/hw64.inc $(SHARED) c64/boot.asm c64/stub.asm c64/jcore.asm tools/build.py extras/zxbasic/zxbasic.py tools/pcheck.py $(wildcard progs/*.bas progs/*.asm) $(wildcard $(ROM)) $(wildcard games) $(GAMES) $(P)
	$(PYTHON) tools/build.py --target zx64 $(ROM) $(GAMES) $(P)

# zx128vic's four as zx128's below (one run, a pattern rule; after
# zx128's, order only: both write build/obj's generated .inc files). Before
# zx128's rule: build/zx128%rom matches build/zx128vic.rom too (the stem
# "vic."), and make 3.81 takes the first pattern rule that fits
build/zx128vic%d64 build/zx128vic%rom build/zx128vic%crt build/obj/zx128vic-vice%crt: z80/zx128vic.asm z80/hwvic128.inc z80/mon.asm z80/monvic.inc z80/monin.inc z80/mon6510.inc z80/io128.inc z80/k2scan.inc z80/k2mon.inc z80/call128.inc z80/com128.inc z80/vidpal.inc z80/vicpic.inc $(SHARED) c128/boot128.asm c128/from.asm tools/build.py extras/zx0/zx0.py extras/zxbasic/zxbasic.py $(wildcard progs/*.bas progs/*.asm) $(wildcard $(ROM)) $(wildcard games) $(GAMES) $(P) | build/zx128.d64
	$(PYTHON) tools/build.py --target zx128vic $(ROM) $(GAMES) $(P)

# after zx64's (order only): both write build/obj's generated .inc files,
# so make -j mustn't run them at once. One run makes all four of ZX128
# (the function ROM, its two .crt files): a pattern rule (the stem is the
# "."), so make runs it once for them all, and again if any is missing
build/zx128%d64 build/zx128%rom build/zx128%crt build/obj/zx128-vice%crt: z80/zx128.asm z80/mon.asm z80/monvdc.inc z80/monin.inc z80/mon6510.inc z80/hw128.inc z80/io128.inc z80/k2scan.inc z80/k2mon.inc z80/call128.inc z80/com128.inc z80/vidpal.inc z80/vdcpic.inc z80/vdccore.inc z80/vdclock.inc z80/panel.inc z80/panelhi.inc $(SHARED) c128/boot128.asm c128/from.asm tools/build.py extras/zx0/zx0.py extras/zxbasic/zxbasic.py $(wildcard progs/*.bas progs/*.asm) $(wildcard $(ROM)) $(wildcard games) $(GAMES) $(P) | build/zx64.d64
	$(PYTHON) tools/build.py --target zx128 $(ROM) $(GAMES) $(P)

test: build/zx64.d64 $(ZX128) $(ZX128VIC)
	$(PYTHON) tools/build.py --check-zx64
	$(PYTHON) tools/simulate.py
	$(PYTHON) tools/sim128.py
	$(PYTHON) tools/sim128vic.py
	$(PYTHON) -m unittest extras/ultimate/test_ultimate.py

vice: build/zx64.d64
	$(X64) -cpmcart -drive8truedrive -autostart build/zx64.d64

vice128: build/zx128.d64
	$(X128) -80col -drive8type 1571 -drive8truedrive -8 build/zx128.d64

vice128rom: build/zx128.rom
	$(X128) -80col -intfunc 1 -intfrom build/zx128.rom

vice128crt: build/obj/zx128-vice.crt
	$(X128) -80col -cartcrt build/obj/zx128-vice.crt

vice128vic: build/zx128vic.d64
	$(X128) -40col -drive8type 1571 -drive8truedrive -8 build/zx128vic.d64

vice128vicrom: build/zx128vic.rom
	$(X128) -40col -intfunc 1 -intfrom build/zx128vic.rom

vice128viccrt: build/obj/zx128vic-vice.crt
	$(X128) -40col -cartcrt build/obj/zx128vic-vice.crt

jtest: build/jtest.prg

build/jtest.prg: extras/jtest/jtest.asm c64/jcore.asm
	mkdir -p build
	$(ACME) -f cbm -I c64 -o $@ extras/jtest/jtest.asm

memtest128: build/memtest128.d64 build/memtest128f.d64

build/memtest128.d64: extras/memtest128/memtest128.asm
	mkdir -p build/obj
	$(ACME) -f cbm -o build/obj/memtest128.prg -l build/obj/memtest128.lbl extras/memtest128/memtest128.asm
	$(C1541) -format "memtest128,mt" d64 $@ -write build/obj/memtest128.prg memtest128 >/dev/null

build/memtest128f.d64: extras/memtest128/memtest128.asm
	mkdir -p build/obj
	$(ACME) -DFAULT=1 -f cbm -o build/obj/memtest128f.prg extras/memtest128/memtest128.asm
	$(C1541) -format "memtest128f,mt" d64 $@ -write build/obj/memtest128f.prg memtest128f >/dev/null

clean:
	rm -rf build

.PHONY: all test vice vice128 vice128rom vice128crt vice128vic vice128vicrom vice128viccrt jtest memtest128 clean
