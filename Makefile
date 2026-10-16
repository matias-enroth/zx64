# zx64 - the ZX81 ROM on the Z80 of the C64 CP/M cartridge
#
#   make              build/zx64.d64: the boot file, the monitor, the test
#                     programs and every .p in games/. Needs rom/zx81.rom
#                     (or ROM=...), GNU z80asm, acme and c1541
#   make P="a.p b.p"  more .p files on the d64
#   make test         both CPUs in emulators; needs the z80 and py65
#                     packages (python3 -m venv .venv &&
#                     .venv/bin/pip install z80 py65)
#   make vice         the d64 in VICE with the CP/M cartridge

ROM    ?= rom/zx81.rom
P      ?=
GAMES  := $(sort $(wildcard games/*.p games/*.P))
Z80ASM ?= z80asm
ACME   ?= acme
C1541  ?= c1541
X64    ?= x64sc
# use ./.venv if there is one (see make test)
PYTHON ?= $(if $(wildcard .venv/bin/python),.venv/bin/python,python3)
export Z80ASM ACME C1541

all: build/zx64.d64

build/zx64.d64: z80/zx64.asm z80/mon.asm c64/boot.asm tools/build.py tools/zxbasic.py tools/pcheck.py $(wildcard progs/*.bas progs/*.asm) $(wildcard $(ROM)) $(wildcard games) $(GAMES) $(P)
	$(PYTHON) tools/build.py $(ROM) $(GAMES) $(P)

test: build/zx64.d64
	$(PYTHON) tools/simulate.py

vice: build/zx64.d64
	$(X64) -cpmcart -drive8truedrive -autostart build/zx64.d64

clean:
	rm -rf build

.PHONY: all test vice clean
