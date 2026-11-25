"""Rewrite an EasyEDA Pro 3.x .epro2 project into the older .epro layout.

EasyEDA Pro 3.x exports a zip holding one `.epru` file: every document
(PCB, footprint, device, symbol, schematic page) back to back, one record
per line as `{"type","ticket","id"}||{named fields}|`. KiCad's EasyEDA Pro
importer reads the older .epro layout instead: a `project.json` plus one
file per document, each record a positional JSON array. This module maps
the named fields back to those positions (see KiCad's
pcbnew/pcb_io/easyedapro/pcb_io_easyedapro_parser.cpp for the reader).

PCB and footprint documents are converted. Schematic pages are not yet.
"""

from __future__ import annotations

import json
import zipfile
from pathlib import Path

ALIGN = {
    "LEFT_TOP": 1, "LEFT_MIDDLE": 2, "LEFT_BOTTOM": 3,
    "CENTER_TOP": 4, "CENTER_MIDDLE": 5, "CENTER_BOTTOM": 6,
    "RIGHT_TOP": 7, "RIGHT_MIDDLE": 8, "RIGHT_BOTTOM": 9,
}


def read_epru(data: str) -> list[dict]:
    """Split an .epru into documents: [{'head': {...}, 'recs': [(hdr, body)]}]."""
    docs: list[dict] = []
    for raw in data.splitlines():
        if not raw.strip():
            continue
        a, _, b = raw.partition("||")
        if b.endswith("|"):
            b = b[:-1]
        hdr = json.loads(a)
        body = json.loads(b) if b else None
        if hdr.get("type") == "DOCHEAD":
            docs.append({"head": body, "recs": []})
        elif docs:
            docs[-1]["recs"].append((hdr, body))
    return docs


def _id(hdr: dict):
    """Record id: a plain string, or a JSON-encoded list like ["NET","GND"]."""
    rid = hdr.get("id", "")
    if isinstance(rid, str) and rid.startswith("["):
        try:
            return json.loads(rid)
        except ValueError:
            pass
    return rid


def _pad(rid, b: dict) -> list:
    hole = b.get("hole")
    hole_arr = None
    if hole:
        shape = "SLOT" if hole.get("holeType") == "SLOT" else "ROUND"
        hole_arr = [shape, hole.get("width", 0), hole.get("height", 0)]
    dp = b.get("defaultPad") or {}
    pt = dp.get("padType", "RECT")
    if pt in ("POLY", "POLYGON"):
        shape_arr = ["POLY", dp.get("path", [])]
    elif pt == "RECT":
        shape_arr = ["RECT", dp.get("width", 0), dp.get("height", 0), dp.get("radius", 0) or 0]
    else:  # ELLIPSE, OVAL
        shape_arr = [pt, dp.get("width", 0), dp.get("height", 0)]
    hole_angle = b.get("holeAngle")
    if not isinstance(hole_angle, (int, float)):
        hole_angle = 0
    return ["PAD", rid, b.get("groupId", 0), b.get("netName") or "", b.get("layerId", 1),
            str(b.get("num", "")), b.get("centerX", 0), b.get("centerY", 0),
            b.get("padAngle", 0) or 0, hole_arr, shape_arr,
            b.get("padOffsetX", 0), b.get("padOffsetY", 0), b.get("relativeAngle", 0),
            hole_angle, 1 if b.get("plated", True) else 0]


def _attr(rid, b: dict) -> list:
    return ["ATTR", rid, b.get("groupId", b.get("groupID", 0)), b.get("parentId", ""),
            b.get("layerId", 3), b.get("x"), b.get("y"), b.get("key", ""), b.get("value"),
            1 if b.get("keyVisible") else 0, 1 if b.get("valueVisible") else 0,
            b.get("fontFamily", "default"), b.get("fontSize", 45), b.get("strokeWidth", 6),
            1 if b.get("bold") else 0, 1 if b.get("italic") else 0,
            ALIGN.get(b.get("origin"), 3), b.get("angle", 0) or 0,
            1 if b.get("reverse") else 0, b.get("expansion", 0),
            1 if b.get("mirror") else 0, 1 if b.get("locked") else 0]


def _string(rid, b: dict) -> list:
    return ["STRING", rid, b.get("groupId", 0), b.get("layerId", 3), b.get("x", 0), b.get("y", 0),
            b.get("text", ""), b.get("fontFamily", "default"), b.get("fontSize", 45),
            b.get("strokeWidth", 6), 1 if b.get("bold") else 0, 1 if b.get("italic") else 0,
            ALIGN.get(b.get("origin"), 3), b.get("angle", 0) or 0,
            1 if b.get("reverse") else 0, b.get("expansion", 0), 1 if b.get("mirror") else 0,
            1 if b.get("locked") else 0]


def _region_flags(b: dict) -> list:
    rt = b.get("ruleType")
    if isinstance(rt, list):
        return [int(x) for x in rt if isinstance(x, (int, float))]
    return [7]


def convert_record(hdr: dict, b: dict | None):
    """One new-format record -> one old-format array, or None to drop it."""
    t = hdr.get("type")
    rid = _id(hdr)
    if b is None:
        return None
    if t == "LAYER":
        num = rid[1] if isinstance(rid, list) else 0
        return ["LAYER", num, b.get("layerType", ""), b.get("layerName", ""),
                3 if b.get("use") else 0, b.get("activeColor", "#FFFFFF"),
                b.get("activateTransparency", 1), b.get("inactiveColor", "#FFFFFF"),
                b.get("inactiveTransparency", 1)]
    if t == "NET":
        name = rid[1] if isinstance(rid, list) else ""
        return ["NET", name, b.get("netType"), b.get("specialColor")] if name else None
    if t == "LINE":
        return ["LINE", rid, b.get("groupId", 0), b.get("netName") or "", b.get("layerId", 1),
                b["startX"], b["startY"], b["endX"], b["endY"], b.get("width", 10),
                1 if b.get("locked") else 0]
    if t == "ARC":
        return ["ARC", rid, b.get("groupId", 0), b.get("netName") or "", b.get("layerId", 1),
                b["startX"], b["startY"], b["endX"], b["endY"], b.get("arcAngle", 0),
                b.get("width", 10), 1 if b.get("locked") else 0]
    if t == "VIA":
        return ["VIA", rid, b.get("groupId", 0), b.get("netName") or "", b.get("ruleName", ""),
                b["centerX"], b["centerY"], b["holeDiameter"], b["viaDiameter"], 0,
                b.get("topSolderExpansion"), b.get("bottomSolderExpansion"),
                1 if b.get("locked") else 0]
    if t == "POLY":
        return ["POLY", rid, b.get("groupId", 0), b.get("netName") or "", b.get("layerId", 1),
                b.get("width", 10), b.get("path", []), 1 if b.get("locked") else 0]
    if t == "FILL":
        return ["FILL", rid, b.get("groupId", 0), b.get("netName") or "", b.get("layerId", 1),
                b.get("width", 0), 0, b.get("path", []), 1 if b.get("locked") else 0]
    if t == "POUR":
        return ["POUR", rid, b.get("groupId", 0), b.get("netName") or "", b.get("layerId", 1),
                b.get("width", 0.2), b.get("name", ""), b.get("order", 0), b.get("path", []),
                ["SOLID", 0, 0, 0], 0, 0]
    if t == "REGION":
        return ["REGION", rid, b.get("groupId", 0), b.get("layerId", 12), b.get("width", 0),
                _region_flags(b), b.get("path", []), 1 if b.get("locked") else 0]
    if t == "PAD":
        return _pad(rid, b)
    if t == "COMPONENT":
        return ["COMPONENT", rid, b.get("groupId", 0), b.get("layerId", 1), b.get("x", 0),
                b.get("y", 0), b.get("angle", 0) or 0, b.get("attrs") or {},
                1 if b.get("locked") else 0]
    if t == "ATTR":
        return _attr(rid, b)
    if t == "PAD_NET":
        if not isinstance(rid, list) or len(rid) < 3:
            return None
        return ["PAD_NET", rid[1], str(rid[2]), b.get("padNet") or "",
                rid[3] if len(rid) > 3 else ""]
    if t == "STRING":
        return _string(rid, b)
    # RULE, POURED, CANVAS, PREFERENCE, DIMENSION, OBJ, ...: KiCad either
    # ignores them or recomputes them (zones are refilled on open).
    return None


def _meta(doc: dict) -> dict:
    for hdr, body in doc["recs"]:
        if hdr.get("type") == "META" and isinstance(body, dict):
            return body
    return {}


def _lines(doc: dict, doctype: str, uuid: str, title: str) -> str:
    out = [json.dumps(["DOCTYPE", doctype, "1.8"]),
           json.dumps(["HEAD", {"editorVersion": "2.2.D", "importFlag": 0,
                                "uuid": uuid, "title": title}])]
    for hdr, body in doc["recs"]:
        arr = convert_record(hdr, body)
        if arr is not None:
            out.append(json.dumps(arr, ensure_ascii=False))
    return "\n".join(out) + "\n"


def list_boards(docs: list[dict]) -> list[dict]:
    """PCB documents with their title and the title of the board that owns them."""
    boards = {d["head"]["uuid"]: _meta(d).get("title", "")
              for d in docs if d["head"]["docType"] == "BOARD"}
    out = []
    for d in docs:
        if d["head"]["docType"] == "PCB":
            m = _meta(d)
            out.append({"uuid": d["head"]["uuid"], "title": m.get("title", ""),
                        "board": boards.get(m.get("board", ""), "")})
    return out


def epro2_to_epro(src: Path, dst: Path) -> list[dict]:
    """Write an old-layout .epro at dst. Returns the PCBs found (list_boards)."""
    with zipfile.ZipFile(src) as z:
        epru = [n for n in z.namelist() if n.endswith(".epru")]
        if not epru:
            raise ValueError(f"{src} has no .epru document")
        docs = read_epru(z.read(epru[0]).decode("utf-8"))
        prj_title = json.loads(z.read("project2.json")).get("title", src.stem) \
            if "project2.json" in z.namelist() else src.stem

    project = {"name": prj_title, "schematics": {}, "pcbs": {}, "panels": {}, "boards": {},
               "symbols": {}, "footprints": {}, "devices": {}}
    with zipfile.ZipFile(dst, "w", zipfile.ZIP_DEFLATED) as zout:
        for d in docs:
            dt, uuid = d["head"]["docType"], d["head"]["uuid"]
            m = _meta(d)
            title = m.get("title", uuid)
            ver = str(d["head"].get("version", ""))
            if dt == "FOOTPRINT":
                project["footprints"][uuid] = {"source": m.get("source", ""), "title": title,
                                               "desc": m.get("description", ""),
                                               "version": ver, "type": 4}
                zout.writestr(f"FOOTPRINT/{uuid}.efoo", _lines(d, "FOOTPRINT", uuid, title))
            elif dt == "DEVICE":
                project["devices"][uuid] = {"source": m.get("source", ""), "title": title,
                                            "description": m.get("description", ""),
                                            "version": ver,
                                            "attributes": m.get("attributes") or {}}
            elif dt == "PCB":
                project["pcbs"][uuid] = title
                board = next((b["board"] for b in list_boards(docs) if b["uuid"] == uuid), "")
                if board:
                    project["boards"][board] = {"pcb": uuid, "schematic": m.get("schematic", "")}
                zout.writestr(f"PCB/{uuid}.epcb", _lines(d, "PCB", uuid, title))
        zout.writestr("project.json", json.dumps(project, ensure_ascii=False, indent=1))
    return list_boards(docs)
