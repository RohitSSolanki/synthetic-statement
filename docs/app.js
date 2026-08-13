/* synthetic-statement — hosted demo controller.
 *
 * Loads Pyodide (Python in WebAssembly) from the CDN, installs THIS package's
 * wheel (vendored next to the page — no PyPI dependency), and runs the real
 * generator in the visitor's browser. Nothing is uploaded; compute is 100%
 * client-side. reportlab (for PDF) is installed lazily on first PDF request.
 *
 * The runtime itself is loaded lazily too — only when the generator modal opens
 * — so the landing paints instantly and the ~10 MB download waits until engaged.
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
    if o.get("country"):
        kw["country"] = o["country"]
    if o.get("currency"):
        kw["currency"] = o["currency"]
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

  // Global error boundary — any UNCAUGHT error surfaces a friendly overlay
  // instead of a silently-broken page. (Generation errors are handled inline.)
  const boundary = $("error-boundary");
  const showBoundary = (msg) => {
    if (!boundary) return;
    $("eb-msg").textContent =
      (msg ? msg + " " : "") + "Your data never left your browser. Reloading fixes most issues.";
    boundary.hidden = false;
  };
  window.addEventListener("error", (e) => showBoundary(e.message));
  window.addEventListener("unhandledrejection", (e) =>
    showBoundary(e.reason && e.reason.message ? e.reason.message : "")
  );
  $("eb-reload").addEventListener("click", () => location.reload());

  const modal = $("gen-modal");
  const form = $("gen-form");
  const genBtn = $("generate");
  const statusEl = $("status");
  const runtimeHint = $("runtime-hint");
  const busySub = $("busy-sub");
  const previewEl = $("preview");
  const previewBtn = $("preview-btn");
  const titleEl = $("result-title");
  const noteEl = $("result-note");
  const downloadEl = $("download");
  const errMsgEl = $("err-msg");

  const setView = (v) => { modal.dataset.view = v; };
  const setStatus = (msg, isErr = false) => {
    statusEl.textContent = msg;
    statusEl.classList.toggle("err", isErr);
  };

  // ---- lazy runtime -----------------------------------------------------------
  let pyodide = null;
  let reportlabReady = false;
  let downloadUrl = null;
  let runtimePromise = null; // in-flight/settled load; null = not started or reset

  const loadScript = (src) =>
    new Promise((res, rej) => {
      const s = document.createElement("script");
      s.src = src;
      s.onload = res;
      s.onerror = () => rej(new Error("Could not load the Python runtime (network?)."));
      document.head.appendChild(s);
    });

  function ensureRuntime() {
    if (runtimePromise) return runtimePromise;
    runtimeHint.classList.remove("err");
    runtimeHint.textContent = "Preparing the runtime…";
    setStatus("Preparing runtime…");
    runtimePromise = (async () => {
      await loadScript(`https://cdn.jsdelivr.net/pyodide/v${PYODIDE_VERSION}/full/pyodide.js`);
      pyodide = await loadPyodide({
        indexURL: `https://cdn.jsdelivr.net/pyodide/v${PYODIDE_VERSION}/full/`,
      });
      await pyodide.loadPackage("micropip");
      const micropip = pyodide.pyimport("micropip");
      await micropip.install(new URL(WHEEL, document.baseURI).href);
      await pyodide.runPythonAsync(PY_BOOTSTRAP);
    })();
    runtimePromise.then(
      () => { runtimeHint.textContent = ""; setStatus("Ready — nothing is uploaded."); },
      (err) => {
        runtimePromise = null; // allow a retry
        runtimeHint.textContent = "Runtime failed to load — you can still open it and retry.";
        runtimeHint.classList.add("err");
        setStatus(err.message || "Runtime failed to load.", true);
      }
    );
    return runtimePromise;
  }

  async function ensureReportlab() {
    if (reportlabReady) return;
    busySub.textContent = "Installing the PDF renderer (first time)…";
    const micropip = pyodide.pyimport("micropip");
    await micropip.install("reportlab");
    reportlabReady = true;
  }

  // ---- modal open/close -------------------------------------------------------
  const openModal = () => {
    setView("form");
    modal.showModal();
    genBtn.disabled = false;
    ensureRuntime(); // warm it while they pick options
  };
  const closeModal = () => modal.close();

  $("open-gen").addEventListener("click", openModal);
  $("close-gen").addEventListener("click", closeModal);
  // click on the backdrop (the dialog element itself, outside its content) closes it
  modal.addEventListener("click", (e) => { if (e.target === modal) closeModal(); });

  // ---- collect + generate -----------------------------------------------------
  function collectOptions() {
    const fd = new FormData(form);
    return {
      profile: fd.get("profile"), bank: fd.get("bank"), country: fd.get("country"),
      currency: fd.get("currency"), period: fd.get("period"), seed: fd.get("seed"),
      start: fd.get("start"), end: fd.get("end"), income: fd.get("income"),
      expense: fd.get("expense"), format: fd.get("format"), app: fd.get("app"),
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

  function fillPreview(res) {
    if (res.kind === "binary") {
      previewEl.textContent =
        `[ ${res.filename} — ${(res.bytes / 1024).toFixed(1)} KB, ${res.rows} transactions ]\n\n` +
        "Binary PDF — use Download to open it.\n" +
        "The rendered statement carries a “SYNTHETIC SAMPLE” watermark.";
    } else if (res.mime === "text/csv") {
      const lines = res.text.split("\n");
      previewEl.textContent =
        lines.slice(0, 16).join("\n") + (lines.length > 16 ? `\n… (${res.rows} rows total)` : "");
    } else {
      const head = res.text.slice(0, 1600);
      previewEl.textContent = head + (res.text.length > 1600 ? `\n… (${res.rows} transactions total)` : "");
    }
  }

  async function runGenerate() {
    setView("busy");
    busySub.textContent = "Running Python in your browser — nothing leaves your machine.";
    const opts = collectOptions();
    try {
      if (!runtimePromise) ensureRuntime();
      busySub.textContent = "Preparing the runtime…";
      await runtimePromise;
      if (opts.format === "pdf") await ensureReportlab();
      busySub.textContent = "Generating…";
      pyodide.globals.set("OPTS_JSON", JSON.stringify(opts));
      const res = JSON.parse(await pyodide.runPythonAsync("_build(OPTS_JSON)"));
      offerDownload(res);
      fillPreview(res);
      titleEl.textContent = res.filename + " is ready";
      noteEl.textContent = `${res.rows} transactions generated in your browser — nothing was uploaded.`;
      previewEl.hidden = true;
      previewBtn.textContent = "Preview";
      setView("result");
    } catch (err) {
      errMsgEl.textContent = err && err.message ? err.message : "Generation failed unexpectedly.";
      setView("error");
      console.error(err);
    }
  }

  form.addEventListener("submit", (e) => { e.preventDefault(); runGenerate(); });

  // ---- result / error controls ------------------------------------------------
  previewBtn.addEventListener("click", () => {
    previewEl.hidden = !previewEl.hidden;
    previewBtn.textContent = previewEl.hidden ? "Preview" : "Hide preview";
  });
  $("back-form").addEventListener("click", () => setView("form"));
  $("back-form-2").addEventListener("click", () => setView("form"));
  $("retry").addEventListener("click", runGenerate);
}

// Exposed for the Node verification harness.
if (typeof module !== "undefined") module.exports = { PY_BOOTSTRAP, WHEEL, PYODIDE_VERSION };
