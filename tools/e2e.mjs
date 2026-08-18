/* End-to-end smoke test for the browser demo (site/).
 *
 *   npm install           # installs puppeteer-core (devDep)
 *   npm run test:e2e       # drives a real browser through JSON/CSV/PDF generations
 *
 * It self-serves site/ from Node, opens the page in Chrome, walks the modal
 * flow for each output format, and validates the ACTUAL downloaded bytes
 * (JSON parses, CSV has a header row, PDF has a %PDF- header). This exercises
 * the browser layer the pytest suite can't: the Pyodide runtime load, the wheel
 * install, the modal state machine, and the blob download path.
 *
 * Chrome: uses puppeteer-core (no bundled download). Point it at a browser via
 * $CHROME_PATH, or it auto-detects a common system install. Needs network — it
 * fetches Pyodide + the reportlab wheel from the CDN, so the run takes a couple
 * of minutes. Intended as a manual pre-deploy check, not a per-push CI gate.
 */
import puppeteer from "puppeteer-core";
import http from "http";
import fs from "fs";
import path from "path";
import { fileURLToPath } from "url";

const DOCS = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "..", "site");
const PORT = Number(process.env.PORT) || 8092;
const MIME = {
  ".html": "text/html", ".css": "text/css", ".js": "text/javascript",
  ".json": "application/json", ".png": "image/png", ".wasm": "application/wasm",
  ".whl": "application/octet-stream",
};

function findChrome() {
  if (process.env.CHROME_PATH) return process.env.CHROME_PATH;
  const candidates = [
    "/usr/bin/google-chrome", "/usr/bin/google-chrome-stable",
    "/usr/bin/chromium", "/usr/bin/chromium-browser",
    "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome",
    "/Applications/Chromium.app/Contents/MacOS/Chromium",
  ];
  for (const c of candidates) if (fs.existsSync(c)) return c;
  throw new Error("No Chrome/Chromium found. Set CHROME_PATH=/path/to/chrome and retry.");
}

const log = (m) => console.log(m);
const results = [];

const server = http.createServer((req, res) => {
  let p = decodeURIComponent(req.url.split("?")[0]);
  if (p === "/") p = "/index.html";
  const file = path.join(DOCS, p);
  if (!file.startsWith(DOCS) || !fs.existsSync(file) || fs.statSync(file).isDirectory()) {
    res.writeHead(404); return res.end("not found");
  }
  res.writeHead(200, { "content-type": MIME[path.extname(file)] || "application/octet-stream" });
  fs.createReadStream(file).pipe(res);
});
await new Promise((r) => server.listen(PORT, r));
const URL = `http://localhost:${PORT}/`;

const browser = await puppeteer.launch({
  executablePath: findChrome(),
  headless: "new",
  args: ["--no-sandbox", "--disable-gpu"],
});
const page = await browser.newPage();
page.on("pageerror", (e) => log("  ! pageerror: " + e.message));

try {
  await page.goto(URL, { waitUntil: "domcontentloaded" });
  await page.waitForSelector("#open-gen", { timeout: 10000 });
  results.push(["landing CTA present",
    (await page.$eval("#open-gen", (el) => el.textContent.trim())) === "Generate a statement"]);

  await page.click("#open-gen");
  await page.waitForFunction(
    () => document.getElementById("gen-modal").dataset.view === "form", { timeout: 5000 });
  results.push(["modal opens to form view", true]);

  const setFormat = (fmt) => page.evaluate((f) => {
    const el = document.querySelector(`input[name="format"][value="${f}"]`);
    el.checked = true; el.dispatchEvent(new Event("change", { bubbles: true }));
  }, fmt);

  const waitTerminal = (timeout) => page.waitForFunction(
    () => ["result", "error"].includes(document.getElementById("gen-modal").dataset.view),
    { timeout, polling: 500 });

  async function runFormat(fmt, timeout, validate) {
    await setFormat(fmt);
    await page.click("#generate");
    await waitTerminal(timeout);
    if ((await page.$eval("#gen-modal", (el) => el.dataset.view)) === "error") {
      results.push([`${fmt}: generate`, false,
        "error view: " + (await page.$eval("#err-msg", (el) => el.textContent))]);
      return;
    }
    const data = await page.evaluate(async () => {
      const a = document.getElementById("download");
      const buf = new Uint8Array(await (await fetch(a.href)).arrayBuffer());
      let text = "";
      if (buf.length < 500000) text = new TextDecoder().decode(buf);
      return {
        name: a.getAttribute("download"), bytes: buf.length,
        head: String.fromCharCode(...buf.slice(0, 5)), text,
        title: document.getElementById("result-title").textContent,
      };
    });
    const ok = validate(data);
    results.push([`${fmt}: ${data.name} (${data.bytes} B) — "${data.title}"`, ok,
      ok ? "" : JSON.stringify(data).slice(0, 180)]);
    await page.click("#back-form");
    await page.waitForFunction(
      () => document.getElementById("gen-modal").dataset.view === "form", { timeout: 5000 });
  }

  log("· JSON (first run — loading Pyodide + wheel)…");
  await runFormat("json", 180000, (d) => {
    try {
      const j = JSON.parse(d.text);
      const recs = j.records || j.transactions || j;
      return Array.isArray(recs) ? recs.length > 0 : typeof j === "object";
    } catch { return false; }
  });

  log("· CSV…");
  await runFormat("csv", 60000, (d) => {
    const lines = d.text.trim().split("\n");
    return lines.length > 1 && lines[0].includes(",");
  });

  log("· PDF (installs reportlab on first run)…");
  await runFormat("pdf", 120000, (d) => d.head === "%PDF-" && d.bytes > 1000);
} catch (err) {
  results.push(["harness", false, err.message]);
} finally {
  await browser.close();
  server.close();
}

log("\n================ E2E RESULTS ================");
let pass = 0;
for (const [name, ok, detail] of results) {
  log(`${ok ? "PASS" : "FAIL"}  ${name}${detail ? "  — " + detail : ""}`);
  if (ok) pass++;
}
log(`\n${pass}/${results.length} checks passed`);
process.exit(pass === results.length ? 0 : 1);
