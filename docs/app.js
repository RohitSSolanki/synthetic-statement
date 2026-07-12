/* synthetic-statement — hosted demo controller.
 *
 * Loads Pyodide (Python in WebAssembly) from the CDN, installs THIS package's
 * wheel (vendored next to the page — no PyPI dependency), and runs the real
 * generator in the visitor's browser. Nothing is uploaded; compute is 100%
 * client-side. reportlab (for PDF) is installed lazily on first PDF request.
 *
 * The Python below is the single source of truth for the in-browser build and
 * is exercised verbatim by tools/verify (see .scratch): keep it self-contained.
 */

const PYODIDE_VERSION = "0.28.3";
const WHEEL = "vendor/synthetic_statement-0.1.0-py3-none-any.whl";

const PY_BOOTSTRAP = `
import json, base64
from pathlib import Path
from synthetic_statement import generate

def _build(opts_json):
    o = json.loads(opts_json)
    kw = {}
    if o.get("seed") not in (None, ""):
        kw["seed"] = int(o["seed"])
    if o.get("profile"):
        kw["profile"] = o["profile"]
    if o.get("bank"):
        kw["bank"] = o["bank"]
    if o.get("income") not in (None, ""):
        kw["income"] = float(o["income"])
    if o.get("expense") not in (None, ""):
        kw["expense"] = float(o["expense"])
    if o.get("start") and o.get("end"):
        kw["start"] = o["start"]
        kw["end"] = o["end"]
    elif o.get("period"):
        kw["period"] = o["period"]

    stmt = generate(**kw)
    fmt = o.get("format", "json")
    rows = len(stmt.records)

    if fmt == "json":
        return json.dumps({"kind": "text", "filename": "statement.json",
                           "mime": "application/json", "text": stmt.to_json(), "rows": rows})
    if fmt == "csv":
        return json.dumps({"kind": "text", "filename": "statement.csv",
                           "mime": "text/csv", "text": stmt.to_csv(), "rows": rows})

    # reportlab (installed lazily by the page before a PDF request) — imported
    # here, not at module load, so the package stays pure-stdlib until PDF is used.
    from synthetic_statement.renderers import phonepe, paytm, gpay
    renderers = {"phonepe": phonepe.render, "paytm": paytm.render, "gpay": gpay.render}
    app = o.get("app", "phonepe")
    out = Path("/tmp/statement.pdf")
    renderers[app](stmt.records, out, holder="Sample User")
    data = out.read_bytes()
    return json.dumps({"kind": "binary", "filename": app + ".pdf", "mime": "application/pdf",
                       "b64": base64.b64encode(data).decode("ascii"), "rows": rows, "bytes": len(data)})
`;

// --- browser wiring (skipped under Node verification — no document) ------------
if (typeof document !== "undefined") {
  const $ = (id) => document.getElementById(id);
  const statusEl = $("status");
  const genBtn = $("generate");
  const form = $("gen-form");
  const appField = $("app-field");
  const resultEl = $("result");
  const previewEl = $("preview");
  const titleEl = $("result-title");
  const noteEl = $("result-note");
  const downloadEl = $("download");

  let pyodide = null;
  let reportlabReady = false;
  let downloadUrl = null;

  const setStatus = (msg, isErr = false) => {
    statusEl.textContent = msg;
    statusEl.classList.toggle("err", isErr);
  };

  // Toggle the PDF-only "app" picker.
  form.addEventListener("change", (e) => {
    if (e.target.name === "format") {
      appField.hidden = form.format.value !== "pdf";
    }
  });

  async function init() {
    try {
      pyodide = await loadPyodide({
        indexURL: `https://cdn.jsdelivr.net/pyodide/v${PYODIDE_VERSION}/full/`,
      });
      setStatus("Installing generator…");
      await pyodide.loadPackage("micropip");
      const micropip = pyodide.pyimport("micropip");
      const wheelUrl = new URL(WHEEL, document.baseURI).href;
      await micropip.install(wheelUrl);
      await pyodide.runPythonAsync(PY_BOOTSTRAP);
      genBtn.disabled = false;
      setStatus("Ready — pick options and generate.");
    } catch (err) {
      setStatus("Failed to load the runtime: " + err.message, true);
      console.error(err);
    }
  }

  async function ensureReportlab() {
    if (reportlabReady) return;
    setStatus("Installing PDF renderer (first time)…");
    const micropip = pyodide.pyimport("micropip");
    await micropip.install("reportlab");
    reportlabReady = true;
  }

  function collectOptions() {
    const fd = new FormData(form);
    return {
      profile: fd.get("profile"),
      bank: fd.get("bank"),
      period: fd.get("period"),
      seed: fd.get("seed"),
      start: fd.get("start"),
      end: fd.get("end"),
      income: fd.get("income"),
      expense: fd.get("expense"),
      format: fd.get("format"),
      app: fd.get("app"),
    };
  }

  function offerDownload(res) {
    if (downloadUrl) URL.revokeObjectURL(downloadUrl);
    let blob;
    if (res.kind === "binary") {
      const bin = atob(res.b64);
      const bytes = new Uint8Array(bin.length);
      for (let i = 0; i < bin.length; i++) bytes[i] = bin.charCodeAt(i);
      blob = new Blob([bytes], { type: res.mime });
    } else {
      blob = new Blob([res.text], { type: res.mime });
    }
    downloadUrl = URL.createObjectURL(blob);
    downloadEl.href = downloadUrl;
    downloadEl.download = res.filename;
    downloadEl.textContent = "Download " + res.filename;
  }

  function showPreview(res) {
    titleEl.textContent = res.filename;
    if (res.kind === "binary") {
      previewEl.textContent =
        `[ ${res.filename} — ${(res.bytes / 1024).toFixed(1)} KB, ${res.rows} transactions ]\n\n` +
        "Binary PDF — use the Download button to open it.\n" +
        "The rendered statement carries a “SYNTHETIC SAMPLE” watermark.";
    } else if (res.mime === "text/csv") {
      const lines = res.text.split("\n");
      previewEl.textContent =
        lines.slice(0, 16).join("\n") + (lines.length > 16 ? `\n… (${res.rows} rows total)` : "");
    } else {
      const head = res.text.slice(0, 1600);
      previewEl.textContent = head + (res.text.length > 1600 ? `\n… (${res.rows} transactions total)` : "");
    }
    noteEl.textContent = `${res.rows} transactions generated in your browser — nothing was uploaded.`;
    resultEl.hidden = false;
  }

  form.addEventListener("submit", async (e) => {
    e.preventDefault();
    if (!pyodide) return;
    genBtn.disabled = true;
    const opts = collectOptions();
    try {
      if (opts.format === "pdf") await ensureReportlab();
      setStatus("Generating…");
      pyodide.globals.set("OPTS_JSON", JSON.stringify(opts));
      const raw = await pyodide.runPythonAsync("_build(OPTS_JSON)");
      const res = JSON.parse(raw);
      offerDownload(res);
      showPreview(res);
      setStatus("Done.");
    } catch (err) {
      setStatus("Generation failed: " + err.message, true);
      console.error(err);
    } finally {
      genBtn.disabled = false;
    }
  });

  init();
}

// Exposed for the Node verification harness.
if (typeof module !== "undefined") module.exports = { PY_BOOTSTRAP, WHEEL, PYODIDE_VERSION };
