# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## What this is

`epro2kicad` is a single-file, stdlib-only Python CLI (`epro2kicad.py`) that converts EasyEDA Pro `.epro` project exports into KiCad-ready output by driving KiCad's own native EasyEDA Pro importer headlessly. There is no package manifest, no test suite, and no lint config — the entire tool is `epro2kicad.py`.

## Running

```bash
python3 epro2kicad.py PROJECT.epro [-o OUTPUT_DIR] [--zip]
```

Requires KiCad ≥ 8 installed. The script auto-detects a Python interpreter that can `import pcbnew` (checks macOS KiCad.app paths, then the system Python); override with the `KICAD_PYTHON` env var. A real end-to-end test is converting `examples/Daaga1.3V.epro` and checking the reported footprint/track/net counts.

## Architecture

The conversion is a three-stage pipeline in `main()`:

1. **Normalize** (`normalize_epro` + `fix_epcb`) — repacks the `.epro` zip, rewriting the JSON Lines documents (`.esch`, `.epcb`, `.esym`, `.efoo`, `.json`) with clean `\n` line endings (CR/LF hard-crashes KiCad's parser with `std::out_of_range: map::at`). For `.epcb` documents, `fix_epcb` additionally converts new-format (EasyEDA editor 2.2+) exports to the legacy shape KiCad 8/9 parses: flattens object-keyed RULE values (else `type must be number, but is array`, kicad#24303) and injects `["NET",name]` records synthesized from PAD_NET/track net fields (KiCad 9 only creates nets from NET records; KiCad 10 creates them on demand). It also parses `project.json` to discover board/PCB names. `main()` always passes an explicit `pcb_id` per PCB — with multiple PCBs and no id, KiCad tries to open a GUI chooser and aborts headlessly with `std::bad_function_call`.

2. **Convert** (`convert_pcb` + `CONVERT_SNIPPET`) — the script never imports `pcbnew` itself. It spawns KiCad's bundled Python as a subprocess running `CONVERT_SNIPPET`, which loads the board via `pcbnew.PCB_IO_MGR.Load(EASYEDAPRO, ...)` and saves with `PCB_IO_MGR.Save(KICAD_SEXP, ...)`. Two constraints inside the snippet matter: a `wx.App()` must exist before loading, and you must use `PCB_IO_MGR.Save`, **not** `SaveBoard` — `SaveBoard` touches project settings and crashes outside a full KiCad session. Results come back through a `STATS <footprints> <tracks> <nets>` line on stdout.

3. **Package** — writes a minimal `.kicad_pro` (from `KICAD_PRO_TEMPLATE`), copies the original `.epro`, and adds a `README.txt` explaining the one manual step: schematics can only be imported through KiCad's GUI (no headless API exists), so the user opens the bundled `.epro` via File → Import Non-KiCad Project.

## Web version (`docs/`)

`docs/index.html` + `docs/app.js` is a client-side GitHub Pages port of the normalize/package stages (`fixEpcb` in app.js must stay in sync with `fix_epcb` in the Python script). It repairs the `.epro` and bundles it with a `.kicad_pro` and instructions; it cannot produce `.kicad_pcb` because KiCad's C++ importer has no browser/WASM build. `docs/fflate.min.js` is vendored (no CDN). To test headlessly: load fflate with `(0,eval)`, split `app.js` at the `// --- UI wiring` marker, and wrap the top half in `new Function("fflate", core + "; return processFile;")` — running app.js in a `node:vm` context hangs on cross-realm promises.

## Constraints

- **Stdlib only** — the README advertises "zero dependencies"; do not add third-party imports.
- `.epro` files, `*_kicad/` output dirs, and `*_kicad.zip` archives in the repo root are conversion artifacts, mostly gitignored (`examples/Daaga1.3V.epro` is the committed sample).
