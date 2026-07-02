#!/usr/bin/env python3
"""epro2kicad — convert EasyEDA Pro (.epro) projects to a KiCad-ready zip.

Uses KiCad's own native EasyEDA Pro importer through its bundled Python
(pcbnew) API, so the PCB conversion quality is identical to KiCad's GUI
"Import Non-KiCad Project" feature — but scriptable.

Usage:
    python3 epro2kicad.py MyProject.epro [-o output_dir] [--zip]

Requirements:
    - KiCad 8/9/10 installed (macOS: KiCad.app; Linux: kicad packages)
    - No other Python dependencies (stdlib only)

Note: EasyEDA Pro *schematics* can only be imported through KiCad's GUI
(File -> Import Non-KiCad Project). This tool converts the PCB headlessly
and packages everything so that step takes 30 seconds.
"""

import argparse
import json
import os
import shutil
import subprocess
import sys
import tempfile
import zipfile
from pathlib import Path

__version__ = "1.0.0"

# ---------------------------------------------------------------------------
# KiCad discovery
# ---------------------------------------------------------------------------

MAC_KICAD_PYTHON_GLOBS = [
    "~/Applications/KiCad/KiCad.app/Contents/Frameworks/Python.framework/Versions/Current/bin/python3",
    "/Applications/KiCad/KiCad.app/Contents/Frameworks/Python.framework/Versions/Current/bin/python3",
]


def find_kicad_python() -> str:
    """Locate a Python interpreter that can import pcbnew."""
    env = os.environ.get("KICAD_PYTHON")
    if env:
        return env

    candidates = [os.path.expanduser(p) for p in MAC_KICAD_PYTHON_GLOBS]
    # On Linux, system python usually has pcbnew if kicad is installed.
    candidates += [sys.executable, "python3"]

    for cand in candidates:
        if not shutil.which(cand) and not os.path.isfile(cand):
            continue
        try:
            r = subprocess.run(
                [cand, "-c", "import pcbnew"], capture_output=True, timeout=60
            )
            if r.returncode == 0:
                return cand
        except Exception:
            continue

    sys.exit(
        "error: could not find a Python with KiCad's pcbnew module.\n"
        "Install KiCad (https://kicad.org) or set KICAD_PYTHON to the\n"
        "python3 bundled with your KiCad installation."
    )


# ---------------------------------------------------------------------------
# .epro handling
# ---------------------------------------------------------------------------


def normalize_epro(src: Path, dst: Path) -> dict:
    """Repack an .epro with normalized line endings.

    Some EasyEDA Pro exports contain CR/LF line endings in their JSON Lines
    documents, which crashes KiCad's parser (std::out_of_range). Repacking
    with clean newlines fixes it. Returns the parsed project.json.
    """
    project = {}
    with zipfile.ZipFile(src) as zin, zipfile.ZipFile(dst, "w") as zout:
        for item in zin.infolist():
            data = zin.read(item.filename)
            if item.filename.endswith(
                (".esch", ".epcb", ".esym", ".efoo", ".json")
            ):
                text = data.decode("utf-8", errors="replace")
                data = "\n".join(text.splitlines()).encode("utf-8")
            if item.filename == "project.json":
                project = json.loads(data)
            zout.writestr(item, data)
    return project


# ---------------------------------------------------------------------------
# PCB conversion (runs inside KiCad's python)
# ---------------------------------------------------------------------------

CONVERT_SNIPPET = r"""
import sys, wx, pcbnew
app = wx.App()
epro, out, pcb_id = sys.argv[1], sys.argv[2], sys.argv[3]
props = None
if pcb_id:
    props = pcbnew.str_utf8_Map()
    props["pcb_id"] = pcbnew.UTF8(pcb_id)
board = pcbnew.PCB_IO_MGR.Load(pcbnew.PCB_IO_MGR.EASYEDAPRO, epro, None, props)
stats = (len(board.GetFootprints()), len(board.GetTracks()), board.GetNetCount())
# NOTE: use PCB_IO_MGR.Save, not SaveBoard -- SaveBoard touches project
# settings and can crash outside a full KiCad session.
pcbnew.PCB_IO_MGR.Save(pcbnew.PCB_IO_MGR.KICAD_SEXP, out, board)
print("STATS %d %d %d" % stats)
"""


def convert_pcb(kicad_py: str, epro: Path, out_pcb: Path, pcb_id: str) -> tuple:
    r = subprocess.run(
        [kicad_py, "-c", CONVERT_SNIPPET, str(epro), str(out_pcb), pcb_id or ""],
        capture_output=True,
        text=True,
        timeout=600,
    )
    if r.returncode != 0 or "STATS" not in r.stdout:
        sys.exit(f"error: PCB conversion failed:\n{r.stdout}\n{r.stderr}")
    stats = next(l for l in r.stdout.splitlines() if l.startswith("STATS"))
    return tuple(int(x) for x in stats.split()[1:])


KICAD_PRO_TEMPLATE = {
    "board": {"design_settings": {}, "layer_presets": [], "viewports": []},
    "boards": [],
    "libraries": {"pinned_footprint_libs": [], "pinned_symbol_libs": []},
    "meta": {"filename": "", "version": 3},
    "schematic": {"legacy_lib_dir": "", "legacy_lib_list": []},
    "sheets": [],
    "text_variables": {},
}

README_TEMPLATE = """\
{name} — converted from EasyEDA Pro to KiCad
============================================

- {name}.kicad_pcb : converted PCB ({fps} footprints, {tracks} tracks, {nets} nets)
- {name}.kicad_pro : KiCad project file
- {epro}           : original EasyEDA Pro project

Schematic: KiCad imports EasyEDA Pro schematics only through its GUI.
Open KiCad -> File -> Import Non-KiCad Project -> EasyEDA (JLCEDA) Pro
Project -> select the included .epro. Done.

Converted with epro2kicad: https://github.com/enkhbold470/epro2kicad
"""


def main() -> None:
    ap = argparse.ArgumentParser(
        prog="epro2kicad", description=__doc__.splitlines()[0]
    )
    ap.add_argument("epro", type=Path, help="EasyEDA Pro .epro project file")
    ap.add_argument("-o", "--output", type=Path, help="output directory")
    ap.add_argument("--zip", action="store_true", help="also produce a .zip")
    ap.add_argument("--version", action="version", version=__version__)
    args = ap.parse_args()

    if not args.epro.is_file():
        sys.exit(f"error: {args.epro} not found")

    kicad_py = find_kicad_python()
    print(f"using KiCad python: {kicad_py}")

    with tempfile.TemporaryDirectory() as tmp:
        fixed = Path(tmp) / "normalized.epro"
        project = normalize_epro(args.epro, fixed)

        pcbs = project.get("pcbs", {})
        boards = project.get("boards", {})
        name = next(iter(boards), None) or args.epro.stem
        name = "".join(c if c.isalnum() or c in "._-" else "_" for c in name)
        pcb_id = next(iter(pcbs), "") if len(pcbs) == 1 else ""

        if not pcbs:
            sys.exit("error: this .epro contains no PCB")

        outdir = args.output or Path(f"{name}_kicad")
        outdir.mkdir(parents=True, exist_ok=True)

        print(f"converting PCB {pcb_id or '(auto)'} ...")
        out_pcb = outdir / f"{name}.kicad_pcb"
        fps, tracks, nets = convert_pcb(kicad_py, fixed, out_pcb, pcb_id)
        print(f"  footprints: {fps}  tracks: {tracks}  nets: {nets}")

        pro = dict(KICAD_PRO_TEMPLATE)
        pro["meta"] = {"filename": f"{name}.kicad_pro", "version": 3}
        (outdir / f"{name}.kicad_pro").write_text(json.dumps(pro, indent=2))

        shutil.copy(args.epro, outdir / args.epro.name)
        (outdir / "README.txt").write_text(
            README_TEMPLATE.format(
                name=name, fps=fps, tracks=tracks, nets=nets, epro=args.epro.name
            )
        )

    if args.zip:
        zip_path = shutil.make_archive(str(outdir), "zip", outdir.parent, outdir.name)
        print(f"wrote {zip_path}")

    print(f"done: {outdir}/")


if __name__ == "__main__":
    main()
