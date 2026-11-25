---
name: epro2kicad
description: Convert an EasyEDA Pro project (.epro, or .epro2 from EasyEDA Pro 3.x) into a KiCad board (.kicad_pcb + .kicad_pro) using KiCad's own importer, headlessly. Use when the user has an EasyEDA / JLCEDA Pro export and wants it in KiCad, asks to open, import or migrate an EasyEDA design in KiCad, or hits KiCad import errors on an .epro file.
allowed-tools: Bash(python3 ${CLAUDE_PLUGIN_ROOT}/epro2kicad.py *)
---

# EasyEDA Pro to KiCad

The converter is `${CLAUDE_PLUGIN_ROOT}/epro2kicad.py` (Python stdlib only).
It runs KiCad's bundled Python to do the conversion, so KiCad 8 or newer
must be installed. Run it with `python3`; write output to a directory the
user chooses, or next to their file, never inside the plugin directory.

## 1. List the PCBs first

```bash
python3 ${CLAUDE_PLUGIN_ROOT}/epro2kicad.py "<file>" --list
```

This prints every PCB with its title, uuid and owning board, and needs no
KiCad. Projects often contain old revisions and panelized copies
("no board (panel/standalone)").

## 2. Pick the board

- One PCB: convert it without `--board`.
- Several: if the user named one, use it. Otherwise ask which one, and say
  which looks like the main board (a PCB that belongs to a board, usually
  the most recent title; panels are rarely what they want).

`--board` takes a board title, or a PCB title or uuid for PCBs that belong
to no board. It converts only that PCB; add `--all` only if the user wants
every PCB too.

## 3. Convert

```bash
python3 ${CLAUDE_PLUGIN_ROOT}/epro2kicad.py "<file>" --board "<board>" -o "<out dir>"
```

Add `--zip` if the user wants a shareable archive. The output directory
holds `<name>.kicad_pcb`, `<name>.kicad_pro`, the original file and a
`README.txt`. Report the footprint / track / net counts the script prints.

If it fails with "could not find a Python with KiCad's pcbnew module",
KiCad is missing or in an unusual place: ask the user to install KiCad or
to set `KICAD_PYTHON` to the python3 inside their KiCad install (on macOS:
`/Applications/KiCad/KiCad.app/Contents/Frameworks/Python.framework/Versions/Current/bin/python3`).

## 4. Verify

Find `kicad-cli` (`kicad-cli` on PATH, or
`/Applications/KiCad/KiCad.app/Contents/MacOS/kicad-cli` on macOS) and
render the board so you and the user can see it survived:

```bash
kicad-cli pcb render --side top -o "<out dir>/top.png" "<out dir>/<name>.kicad_pcb"
kicad-cli pcb render --side bottom -o "<out dir>/bottom.png" "<out dir>/<name>.kicad_pcb"
```

Look at the images: the board outline, footprints and tracks should all be
there (parts are often all on one side). Optionally run
`kicad-cli pcb drc --refill-zones -o "<out dir>/drc.rpt" "<out dir>/<name>.kicad_pcb"`
and summarize it; EasyEDA design rules are not carried over, so DRC uses
KiCad defaults and some violations are expected.

## 5. Tell the user about the schematic

Only the PCB is converted headlessly. KiCad has no headless API for
EasyEDA Pro schematics:

- `.epro`: the schematic imports in KiCad's GUI in a few seconds:
  **File > Import Non-KiCad Project > EasyEDA (JLCEDA) Pro Project**, then
  select the `.epro` (a copy is in the output directory).
- `.epro2` (EasyEDA Pro 3.x): schematics are not supported yet, by this
  tool or by KiCad's importer. Say so plainly.

Zones are refilled when the board is opened in KiCad (press B to refill).
