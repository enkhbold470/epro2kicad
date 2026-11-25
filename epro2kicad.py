#!/usr/bin/env python3
"""epro2kicad — convert EasyEDA Pro (.epro / .epro2) projects to a KiCad-ready zip.

Uses KiCad's own native EasyEDA Pro importer through its bundled Python
(pcbnew) API, so the PCB conversion quality is identical to KiCad's GUI
"Import Non-KiCad Project" feature — but scriptable.

Usage:
    python3 epro2kicad.py MyProject.epro [-o output_dir] [--zip]
    python3 epro2kicad.py MyProject.epro2 --list
    python3 epro2kicad.py MyProject.epro2 --board "My Board"

EasyEDA Pro 3.x .epro2 exports are first rewritten into the older .epro
layout that KiCad's importer reads (see epro2_compat.py).

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

__version__ = "1.3.0"

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


# Record types whose net-name field KiCad reads with FindNet(): type -> index
EPCB_NET_FIELD = {
    "VIA": 3, "LINE": 3, "ARC": 3, "POLY": 3, "FILL": 3, "POUR": 3,
    "PAD": 3, "PAD_NET": 3, "TEARDROP": 2,
}
EPCB_HEADER_TYPES = ("DOCTYPE", "HEAD", "CANVAS", "LAYER", "ACTIVE_LAYER", "RULE")


def fix_epcb(text: str) -> str:
    """Rewrite an .epcb document so KiCad 8/9's parser accepts it.

    Newer EasyEDA Pro exports (editorVersion 2.2+) changed the format in two
    ways that break KiCad's importer before KiCad 10.0.4:

    - RULE values moved into an object keyed by sub-rule id, e.g.
      ["mil",{"1":[10,10,1000]}]. KiCad 8/9 expects the flat legacy form and
      aborts with "type must be number, but is array" (gitlab kicad#24303).
    - NET records were dropped (nets are now implicit in PAD_NET/track
      fields). KiCad 9 only creates board nets from NET records, so every
      pad and track imports as <no net>. KiCad 10 creates nets on demand.

    Both forms are converted back to the legacy shape, which every KiCad
    version understands.
    """
    records = [json.loads(l) for l in text.splitlines() if l.strip()]
    nets = []
    seen = {r[1] for r in records if r[0] == "NET" and len(r) > 1}

    for rec in records:
        rtype = rec[0]
        if (
            rtype == "RULE"
            and len(rec) > 4
            and isinstance(rec[4], list)
            and len(rec[4]) > 1
            and isinstance(rec[4][1], dict)
        ):
            sub = next(iter(rec[4][1].values()), None)
            if sub is not None:
                if rec[1] == "1":  # clearance matrix: table goes at index 1
                    rec[4] = [rec[4][0], sub]
                elif rec[1] == "3":  # track width: [units, min, opt, max]
                    rec[4] = [rec[4][0], *sub]
        idx = EPCB_NET_FIELD.get(rtype)
        if idx is not None and len(rec) > idx and isinstance(rec[idx], str):
            if rec[idx] and rec[idx] not in seen:
                seen.add(rec[idx])
                nets.append(rec[idx])

    # NET records must precede first use: inject after the leading header run
    split = 0
    while split < len(records) and records[split][0] in EPCB_HEADER_TYPES:
        split += 1
    records[split:split] = [["NET", n] for n in nets]

    return "\n".join(
        json.dumps(r, separators=(",", ":"), ensure_ascii=False) for r in records
    )


def normalize_epro(src: Path, dst: Path) -> dict:
    """Repack an .epro so KiCad's importer accepts it.

    - Normalizes line endings in all JSON Lines documents: CR/LF endings in
      some exports crash KiCad's parser (std::out_of_range).
    - Applies fix_epcb() to PCB documents (new-format RULE/NET compat).

    Returns the parsed project.json.
    """
    project = {}
    with zipfile.ZipFile(src) as zin, zipfile.ZipFile(dst, "w") as zout:
        for item in zin.infolist():
            data = zin.read(item.filename)
            if item.filename.endswith(
                (".esch", ".epcb", ".esym", ".efoo", ".json")
            ):
                text = data.decode("utf-8", errors="replace")
                text = "\n".join(text.splitlines())
                if item.filename.endswith(".epcb"):
                    text = fix_epcb(text)
                data = text.encode("utf-8")
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

SCHEMATIC_NOTE = """\
Schematic: KiCad imports EasyEDA Pro schematics only through its GUI.
Open KiCad -> File -> Import Non-KiCad Project -> EasyEDA (JLCEDA) Pro
Project -> select the included .epro. Done."""

SCHEMATIC_NOTE_EPRO2 = """\
Schematic: not converted. This is an EasyEDA Pro 3.x (.epro2) project;
epro2kicad converts its PCB only (.epro2 schematic pages are not
supported yet), and KiCad's own importer reads only the older .epro."""

README_TEMPLATE = """\
{name} — converted from EasyEDA Pro to KiCad
============================================

- {name}.kicad_pcb : converted PCB ({fps} footprints, {tracks} tracks, {nets} nets)
- {name}.kicad_pro : KiCad project file
- {epro}           : original EasyEDA Pro project

{schematic}

Converted with epro2kicad: https://github.com/enkhbold470/epro2kicad
"""


def is_epro2(path: Path) -> bool:
    """EasyEDA Pro 3.x exports hold a single .epru document instead of per-file docs."""
    try:
        with zipfile.ZipFile(path) as z:
            return any(n.endswith(".epru") for n in z.namelist())
    except zipfile.BadZipFile:
        return False


def list_pcbs(project: dict) -> list:
    """Every PCB in a (normalized) project.json: uuid, title, owning board."""
    board_of = {v.get("pcb"): k for k, v in project.get("boards", {}).items()}
    return [
        {"uuid": uuid, "title": title, "board": board_of.get(uuid, "")}
        for uuid, title in project.get("pcbs", {}).items()
    ]


def pick_pcb(project: dict, wanted: str):
    """Resolve --board: a board title first, else a PCB title or uuid.

    Returns (pcb_id, output name) or None.
    """
    boards = project.get("boards", {})
    if wanted in boards and boards[wanted].get("pcb"):
        return boards[wanted]["pcb"], wanted
    for p in list_pcbs(project):
        if wanted in (p["uuid"], p["title"]):
            return p["uuid"], p["board"] or p["title"]
    return None


def safe_name(name: str) -> str:
    return "".join(c if c.isalnum() or c in "._-" else "_" for c in name)


def main() -> None:
    ap = argparse.ArgumentParser(
        prog="epro2kicad", description=__doc__.splitlines()[0]
    )
    ap.add_argument("epro", type=Path, help="EasyEDA Pro .epro or .epro2 project file")
    ap.add_argument("--list", action="store_true",
                    help="list the PCBs in the project (title, uuid, board) and exit")
    ap.add_argument("--board",
                    help="board title (or PCB title/uuid) to convert; only that PCB "
                         "is converted unless --all is given")
    ap.add_argument("--all", action="store_true",
                    help="with --board: still convert every other PCB (panels etc.)")
    ap.add_argument("-o", "--output", type=Path, help="output directory")
    ap.add_argument("--zip", action="store_true", help="also produce a .zip")
    ap.add_argument("--version", action="version", version=__version__)
    args = ap.parse_args()

    if not args.epro.is_file():
        sys.exit(f"error: {args.epro} not found")

    with tempfile.TemporaryDirectory() as tmp:
        source = args.epro
        epro2 = is_epro2(source)
        if epro2:
            sys.path.insert(0, str(Path(__file__).resolve().parent))
            from epro2_compat import epro2_to_epro

            print("EasyEDA Pro 3.x (.epro2) project")
            source = Path(tmp) / "from_epro2.epro"
            epro2_to_epro(args.epro, source)
        fixed = Path(tmp) / "normalized.epro"
        project = normalize_epro(source, fixed)

        pcbs = project.get("pcbs", {})  # pcb_id -> pcb name
        boards = project.get("boards", {})  # board name -> {schematic, pcb}
        if not pcbs:
            sys.exit("error: this project contains no PCB")

        if args.list:
            print(f"{len(pcbs)} PCB(s):")
            for p in list_pcbs(project):
                board = f"board: {p['board']}" if p["board"] else "no board (panel/standalone)"
                print(f"  {p['title']}  uuid={p['uuid']}  {board}")
            return

        # The selected (or first board-linked) PCB becomes <name>.kicad_pcb;
        # other PCBs (panels etc.) convert alongside it under their own names
        # unless --board narrowed the run to one PCB.
        # Always pass an explicit pcb_id: with several PCBs and no id,
        # KiCad tries to open a chooser dialog and aborts headlessly.
        if args.board:
            picked = pick_pcb(project, args.board)
            if not picked:
                sys.exit(
                    f"error: no board or PCB named {args.board!r}; "
                    f"run with --list to see them"
                )
            main_pcb_id, name = picked
        else:
            board_info = next(iter(boards.values()), {})
            main_pcb_id = board_info.get("pcb") or next(iter(pcbs))
            name = next(iter(boards), None) or args.epro.stem
        name = safe_name(name)
        todo = {k: v for k, v in pcbs.items()
                if k == main_pcb_id or not args.board or args.all}

        kicad_py = find_kicad_python()
        print(f"using KiCad python: {kicad_py}")

        outdir = args.output or Path(f"{name}_kicad")
        outdir.mkdir(parents=True, exist_ok=True)

        fps = tracks = nets = 0
        for pcb_id, pcb_name in todo.items():
            out_name = name if pcb_id == main_pcb_id else safe_name(pcb_name)
            print(f"converting PCB {pcb_name} ({pcb_id}) ...")
            out_pcb = outdir / f"{out_name}.kicad_pcb"
            f, t, n = convert_pcb(kicad_py, fixed, out_pcb, pcb_id)
            print(f"  footprints: {f}  tracks: {t}  nets: {n}")
            if pcb_id == main_pcb_id:
                fps, tracks, nets = f, t, n
        if len(todo) < len(pcbs):
            print(f"skipped {len(pcbs) - len(todo)} other PCB(s); pass --all to convert them")

        pro = dict(KICAD_PRO_TEMPLATE)
        pro["meta"] = {"filename": f"{name}.kicad_pro", "version": 3}
        (outdir / f"{name}.kicad_pro").write_text(json.dumps(pro, indent=2))

        shutil.copy(args.epro, outdir / args.epro.name)
        (outdir / "README.txt").write_text(
            README_TEMPLATE.format(
                name=name, fps=fps, tracks=tracks, nets=nets, epro=args.epro.name,
                schematic=SCHEMATIC_NOTE_EPRO2 if epro2 else SCHEMATIC_NOTE,
            )
        )

    if args.zip:
        zip_path = shutil.make_archive(str(outdir), "zip", outdir.parent, outdir.name)
        print(f"wrote {zip_path}")

    print(f"done: {outdir}/")


if __name__ == "__main__":
    main()
