# epro2kicad

**Convert your EasyEDA Pro projects to a KiCad-ready zip — from the command line.**

[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)
[![Python 3.8+](https://img.shields.io/badge/python-3.8+-blue.svg)](https://www.python.org)
[![KiCad 8/9/10](https://img.shields.io/badge/KiCad-8%20%7C%209%20%7C%2010-314cb0.svg)](https://kicad.org)

KiCad ships an excellent native EasyEDA Pro importer — but it's buried in the
GUI. `epro2kicad` drives that same importer headlessly through KiCad's bundled
Python API, so you get GUI-quality conversion in one command. No cloud
uploads, no re-drawing, no dependencies beyond KiCad itself.

```
$ python3 epro2kicad.py MyProject.epro --zip
using KiCad python: /Applications/KiCad/KiCad.app/.../python3
converting PCB a7363ec0... ...
  footprints: 45  tracks: 1068  nets: 63
wrote MyProject_kicad.zip
done: MyProject_kicad/
```

## Example

The [`examples/`](examples/) folder contains a real conversion: the
**Daaga V1.3** sumo-robot board (Arduino Nano + TB6612FNG motor driver +
QRE1113 line sensors), exported from EasyEDA Pro and converted with this tool:

![Daaga 1.3 board rendered by KiCad after conversion](examples/daaga_board_top.png)

*This render was produced by `kicad-cli pcb render` from the converted
`.kicad_pcb` — every footprint, track, zone and the breakaway sensor panel
survived the round trip.*

## Features

- ✅ **Full PCB conversion** — footprints, tracks, vias, zones, nets, board
  outline, silkscreen, all via KiCad's own EasyEDA Pro parser
- ✅ **Fixes broken exports** — normalizes line endings that crash KiCad's
  importer (`std::out_of_range: map::at` — if you've seen it, this is why)
- ✅ **Fixes new-format exports (EasyEDA 2.2+)** — flattens new-style design
  rules that abort KiCad 8/9 with `type must be number, but is array`
  ([kicad#24303](https://gitlab.com/kicad/code/kicad/-/work_items/24303)) and
  restores the `NET` records newer exports dropped (without them, KiCad 9
  imports every pad and track as `<no net>`)
- ✅ **EasyEDA Pro 3.x (`.epro2`)** — rewrites the new single-file format
  into the layout KiCad's importer reads (see [below](#easyeda-pro-3x-epro2))
- ✅ **Multi-PCB projects** — `--list` shows every PCB, `--board` picks one;
  by default every PCB (panels, variants) is converted. Headless KiCad would
  otherwise abort trying to open a chooser dialog
- ✅ **Web version** — [`docs/`](docs/) is a client-side GitHub Pages app that
  repairs and packages `.epro` files in the browser (nothing is uploaded);
  final import is one GUI step in KiCad, since KiCad's C++ importer can't run
  in a browser
- ✅ **KiCad project scaffold** — generates a `.kicad_pro` so the output opens
  as a proper project
- ✅ **Zip output** — `--zip` produces a ready-to-share archive with the
  original `.epro` and instructions included
- ✅ **Zero dependencies** — Python stdlib only; uses the Python bundled with
  your KiCad install
- ✅ **Claude Code skill** — install it as a plugin and ask Claude to convert
  your file (see [Install as a Claude skill](#install-as-a-claude-skill))

## Install

No install. Just KiCad ≥ 8 ([kicad.org](https://kicad.org)) and this script:

```bash
git clone https://github.com/enkhbold470/epro2kicad.git
cd epro2kicad
python3 epro2kicad.py path/to/YourProject.epro --zip
```

If KiCad's Python isn't auto-detected, point at it explicitly:

```bash
export KICAD_PYTHON="/Applications/KiCad/KiCad.app/Contents/Frameworks/Python.framework/Versions/Current/bin/python3"
```

## Install as a Claude skill

The repo is also a [Claude Code](https://claude.com/claude-code) plugin with
an `epro2kicad` skill. Inside Claude Code:

```
/plugin marketplace add enkhbold470/epro2kicad
/plugin install epro2kicad@epro2kicad
```

(or from a shell: `claude plugin marketplace add enkhbold470/epro2kicad` then
`claude plugin install epro2kicad@epro2kicad`). Then just say *"convert
~/Downloads/MyProject.epro2 to KiCad"*: Claude lists the boards, asks which
one if there are several, converts it, and checks the result with
`kicad-cli`. KiCad ≥ 8 must be installed on the machine.

## Getting your .epro out of EasyEDA Pro

In EasyEDA Pro: **File → Export → EasyEDA Pro (Professional) Project** — that
`.epro` (or `.epro2`, from EasyEDA Pro 3.x) file is what this tool eats.

## Usage

```
python3 epro2kicad.py PROJECT.epro[2] [--list] [--board NAME [--all]] [-o OUTPUT_DIR] [--zip]

  PROJECT        EasyEDA Pro project export (.epro or .epro2)
  --list         list the PCBs in the project (title, uuid, board) and exit
  --board NAME   convert only this board; NAME is a board title, or a PCB
                 title/uuid for PCBs that belong to no board
  --all          with --board: also convert every other PCB
  -o, --output   output directory (default: <name>_kicad/)
  --zip          also produce <name>_kicad.zip
  --version      print version
```

Without `--board`, every PCB is converted and the first board's PCB becomes
`<name>.kicad_pcb`; the others are written under their own PCB titles.

Projects often hold more than one PCB (old revisions, panelized copies), so
start with `--list`:

```
$ python3 epro2kicad.py ProPrj_badge.epro2 --list
EasyEDA Pro 3.x (.epro2) project
4 PCB(s):
  PCB2  uuid=6d8ad368ef4a548f  board: badge-touchscreen
  PCB1  uuid=bcc5d3c035c84466  board: Board1
  PCB_Tinker2_v5.3_PANEL_JLC  uuid=84e161c30e38a67c  no board (panel/standalone)
  PCB_Tinker2_v5.3  uuid=ce89e677e117c9b1  no board (panel/standalone)

$ python3 epro2kicad.py ProPrj_badge.epro2 --board badge-touchscreen
EasyEDA Pro 3.x (.epro2) project
using KiCad python: /Applications/KiCad/KiCad.app/.../python3
converting PCB PCB2 (6d8ad368ef4a548f) ...
  footprints: 72  tracks: 1356  nets: 52
skipped 3 other PCB(s); pass --all to convert them
done: badge-touchscreen_kicad/
```

## EasyEDA Pro 3.x (.epro2)

EasyEDA Pro 3.x exports `.epro2` files in a new format that KiCad (up to
10.0.x) cannot import: a zip holding `project2.json` and a single `.epru`
file with every document (PCBs, footprints, devices, symbols, schematic
pages) back to back, one record per line as
`{"type","ticket","id"}||{named fields}|`. KiCad's importer reads the older
`.epro` layout: a `project.json` plus one file per document, each record a
positional JSON array.

`epro2kicad` detects `.epro2` files automatically and rewrites their PCB and
footprint documents into the old layout (`epro2_compat.py`) before handing
them to KiCad. What carries over: footprints, pads, tracks, arcs, vias,
zones, board outline, nets and silkscreen text. Zones are refilled by KiCad
when you open the board.

Limits:

- **Schematics are not converted** from `.epro2` yet: the schematic pages
  are dropped, and KiCad's GUI importer reads only the older `.epro`
  layout, so the "import the schematic in the GUI" step below does not
  apply to `.epro2` files. The output `README.txt` says so.
- Design rules (RULE records), dimensions and embedded images are dropped;
  KiCad uses its own defaults.

## What about schematics?

KiCad's EasyEDA Pro *schematic* importer is GUI-only (there is no headless
API for it, and no third-party tool supports the Pro format). The output zip
includes your original `.epro` plus instructions — the one manual step is:

> KiCad → **File → Import Non-KiCad Project → EasyEDA (JLCEDA) Pro Project**
> → select the `.epro`

That imports the schematic (and PCB) in about 30 seconds.

## How it works

0. **Upgrade `.epro2`** (EasyEDA Pro 3.x only) — `epro2_compat.py` rewrites
   the single `.epru` document into a per-document `.epro`.
1. **Normalize** — repacks the `.epro` zip with clean `\n` line endings in
   every JSON Lines document (`.esch`, `.epcb`, `.esym`, `.efoo`). Some
   EasyEDA exports carry CR/LF endings that hard-crash KiCad's parser.
2. **Convert** — invokes KiCad's bundled Python and calls
   `pcbnew.PCB_IO_MGR.Load(EASYEDAPRO, ...)`, then saves with
   `PCB_IO_MGR.Save(KICAD_SEXP, ...)` (not `SaveBoard`, which touches
   project settings and crashes outside a full KiCad session).
3. **Package** — writes a `.kicad_pro`, copies the original `.epro`, adds a
   README, and optionally zips it all.

## Compatibility

| Platform | Status |
|----------|--------|
| macOS (KiCad.app) | ✅ tested (KiCad 10.0.4, 10.0.6) |
| Linux (system KiCad) | ✅ should work — pcbnew is on the system Python |
| Windows | ⚠️ untested — set `KICAD_PYTHON` to KiCad's `python.exe` |

## Contributing

Issues and PRs welcome. Ideas that would be great to have:

- Headless schematic conversion (requires upstream KiCad API work)
- `.epro2` schematic pages
- Windows testing
- Batch mode for multiple `.epro` files

## License

[MIT](LICENSE) © 2026 Enkhbold Ganbold
