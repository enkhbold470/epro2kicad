/* epro2kicad web — client-side .epro fixer/packager.
 *
 * Mirrors normalize_epro()/fix_epcb() in epro2kicad.py: normalizes line
 * endings, flattens new-format RULE records, injects NET records, and
 * packages a fixed .epro with a .kicad_pro scaffold and instructions.
 * Everything runs in the browser; no file leaves the machine.
 */
"use strict";

const JSONL_EXTS = [".esch", ".epcb", ".esym", ".efoo", ".json"];

// Record types whose net-name field KiCad reads with FindNet(): type -> index
const EPCB_NET_FIELD = {
  VIA: 3, LINE: 3, ARC: 3, POLY: 3, FILL: 3, POUR: 3,
  PAD: 3, PAD_NET: 3, TEARDROP: 2,
};
const EPCB_HEADER_TYPES = new Set([
  "DOCTYPE", "HEAD", "CANVAS", "LAYER", "ACTIVE_LAYER", "RULE",
]);

function fixEpcb(text, stats) {
  const records = text.split(/\r?\n/).filter((l) => l.trim()).map(JSON.parse);
  const seen = new Set(
    records.filter((r) => r[0] === "NET" && r.length > 1).map((r) => r[1])
  );
  const nets = [];

  for (const rec of records) {
    const rtype = rec[0];
    if (
      rtype === "RULE" && rec.length > 4 && Array.isArray(rec[4]) &&
      rec[4].length > 1 && rec[4][1] !== null &&
      typeof rec[4][1] === "object" && !Array.isArray(rec[4][1])
    ) {
      const sub = Object.values(rec[4][1])[0];
      if (sub !== undefined) {
        if (rec[1] === "1") {            // clearance matrix: table at index 1
          rec[4] = [rec[4][0], sub];
          stats.rulesFixed++;
        } else if (rec[1] === "3") {     // track width: [units, min, opt, max]
          rec[4] = [rec[4][0], ...sub];
          stats.rulesFixed++;
        }
      }
    }
    const idx = EPCB_NET_FIELD[rtype];
    if (idx !== undefined && rec.length > idx && typeof rec[idx] === "string") {
      if (rec[idx] && !seen.has(rec[idx])) {
        seen.add(rec[idx]);
        nets.push(rec[idx]);
      }
    }
  }

  // NET records must precede first use: inject after the leading header run
  let split = 0;
  while (split < records.length && EPCB_HEADER_TYPES.has(records[split][0])) {
    split++;
  }
  records.splice(split, 0, ...nets.map((n) => ["NET", n]));
  stats.netsInjected += nets.length;

  return records.map((r) => JSON.stringify(r)).join("\n");
}

function safeName(name) {
  return Array.from(name)
    .map((c) => (/[A-Za-z0-9._-]/.test(c) ? c : "_"))
    .join("");
}

const KICAD_PRO_TEMPLATE = {
  board: { design_settings: {}, layer_presets: [], viewports: [] },
  boards: [],
  libraries: { pinned_footprint_libs: [], pinned_symbol_libs: [] },
  meta: { filename: "", version: 3 },
  schematic: { legacy_lib_dir: "", legacy_lib_list: [] },
  sheets: [],
  text_variables: {},
};

function readmeText(name, eproName, stats) {
  return `${name} — prepared for KiCad import by epro2kicad web
============================================================

- ${eproName} : your EasyEDA Pro project, repaired for KiCad's importer
    (${stats.rulesFixed} rule record(s) converted to the format KiCad 8/9
    understands, ${stats.netsInjected} net record(s) restored, line endings
    normalized)
- ${name}.kicad_pro : KiCad project file

To import (about 30 seconds):
  1. Open KiCad
  2. File -> Import Non-KiCad Project -> EasyEDA (JLCEDA) Pro Project
  3. Select the included .epro — schematic and PCB import together

Prepared with epro2kicad: https://github.com/enkhbold470/epro2kicad
(The command-line version also converts the PCB to .kicad_pcb headlessly.)
`;
}

async function processFile(file) {
  const stats = { rulesFixed: 0, netsInjected: 0, filesNormalized: 0 };
  const buf = new Uint8Array(await file.arrayBuffer());
  const entries = fflate.unzipSync(buf);
  const dec = new TextDecoder();
  const enc = new TextEncoder();

  let project = null;
  const fixed = {};
  for (const [path, data] of Object.entries(entries)) {
    let out = data;
    if (JSONL_EXTS.some((e) => path.endsWith(e))) {
      let text = dec.decode(data).split(/\r?\n/).join("\n");
      if (path.endsWith(".epcb")) text = fixEpcb(text, stats);
      out = enc.encode(text);
      stats.filesNormalized++;
    }
    if (path === "project.json") project = JSON.parse(dec.decode(out));
    fixed[path] = out;
  }

  if (!project || !project.pcbs || !Object.keys(project.pcbs).length) {
    throw new Error("This file does not look like an EasyEDA Pro project export (no PCB found).");
  }

  const boards = project.boards || {};
  const rawName = Object.keys(boards)[0] || file.name.replace(/\.epro$/i, "");
  const name = safeName(rawName);
  const eproName = file.name.replace(/\.epro$/i, "") + "_fixed.epro";

  const pro = { ...KICAD_PRO_TEMPLATE, meta: { filename: `${name}.kicad_pro`, version: 3 } };

  const pkg = {};
  pkg[`${name}_kicad/${eproName}`] = fflate.zipSync(fixed, { level: 6 });
  pkg[`${name}_kicad/${name}.kicad_pro`] = enc.encode(JSON.stringify(pro, null, 2));
  pkg[`${name}_kicad/README.txt`] = enc.encode(readmeText(name, eproName, stats));
  const outZip = fflate.zipSync(pkg, { level: 6 });

  return {
    zipName: `${name}_kicad.zip`,
    blob: new Blob([outZip], { type: "application/zip" }),
    stats,
    name: rawName,
    pcbs: Object.values(project.pcbs),
  };
}

// --- UI wiring ---------------------------------------------------------

const drop = document.getElementById("drop");
const fileInput = document.getElementById("file");
const result = document.getElementById("result");

function show(html) {
  result.innerHTML = html;
  result.hidden = false;
}

async function handle(file) {
  if (!file) return;
  if (!/\.(epro|zip)$/i.test(file.name)) {
    show(`<p class="err">Expected an <code>.epro</code> file (EasyEDA Pro:
      File → Export → EasyEDA Pro (Professional) Project).</p>`);
    return;
  }
  show(`<p>Processing <strong>${file.name}</strong>…</p>`);
  try {
    const r = await processFile(file);
    const url = URL.createObjectURL(r.blob);
    show(`
      <p class="ok">✔ <strong>${r.name}</strong> is ready for KiCad.</p>
      <ul>
        <li>${r.stats.rulesFixed} design-rule record(s) converted for KiCad 8/9 compatibility</li>
        <li>${r.stats.netsInjected} net record(s) restored</li>
        <li>${r.stats.filesNormalized} document(s) re-encoded with clean line endings</li>
        <li>PCB document(s): ${r.pcbs.map((p) => `<code>${p}</code>`).join(", ")}</li>
      </ul>
      <p><a class="btn" href="${url}" download="${r.zipName}">Download ${r.zipName}</a></p>
      <p>Then in KiCad: <em>File → Import Non-KiCad Project → EasyEDA (JLCEDA) Pro
      Project</em> and pick the <code>.epro</code> inside the zip — schematic and
      PCB import together in ~30 seconds.</p>`);
  } catch (e) {
    show(`<p class="err">✘ ${e.message || e}</p>`);
  }
}

drop.addEventListener("click", () => fileInput.click());
fileInput.addEventListener("change", () => handle(fileInput.files[0]));
["dragover", "dragenter"].forEach((ev) =>
  drop.addEventListener(ev, (e) => { e.preventDefault(); drop.classList.add("hover"); })
);
["dragleave", "drop"].forEach((ev) =>
  drop.addEventListener(ev, (e) => { e.preventDefault(); drop.classList.remove("hover"); })
);
drop.addEventListener("drop", (e) => handle(e.dataTransfer.files[0]));
