# Contributing

Thanks for your interest in `synthetic-statement`.

## Setup

```bash
python -m venv .venv && source .venv/bin/activate
pip install -e ".[pdf,dev]"   # core is pure-stdlib; [pdf]=reportlab, [dev]=pytest+jsonschema
```

## Tests

```bash
.venv/bin/pytest              # full suite
./selftest.sh                 # end-to-end smoke (generate + verify)
```

### Browser demo (`site/`)

The hosted demo runs the generator in-browser via Pyodide. A browser smoke test
drives the real page (modal flow → JSON/CSV/PDF generation) and validates the
downloaded bytes — it covers what pytest can't (the Pyodide load, the wheel
install, and the modal state machine):

```bash
npm install                   # dev-only: puppeteer-core (no bundled Chrome)
npm run test:e2e              # needs a Chrome/Chromium + network (CDN); ~2–4 min
```

It uses a system Chrome (auto-detected, or set `CHROME_PATH`). It's a manual
pre-deploy check, **not** a per-push CI gate — the ~10 MB Pyodide download makes
it too slow to run on every commit. The deployed site is static `site/` only;
`node_modules/` never ships.

## Conventions

- **Data over code.** Merchants, persons, employers, banks and consumption
  baskets live in `data/catalog.json`; currencies in `data/currencies.json`.
  Adding or tuning these is a data edit — see [REALISM.md](REALISM.md).
- **Pure-stdlib core.** The generator core has no runtime dependencies;
  `reportlab` (PDF) and the test tools live in optional extras. Keep it that way.
- **Determinism.** A fixed `--seed` must yield byte-identical output. Seeded
  output is pinned by golden sha256 hashes in `tests/test_catalog.py`; if a
  change intentionally shifts output, **re-pin** the goldens in the same change.
- **Output is a contract.** The emitted formats are documented in
  [`spec/`](spec/format-spec.md) with a JSON Schema; a format change bumps the
  spec version.
- **Synthetic only.** Everything this tool produces is clearly fake — keep the
  disclaimers intact (README, PDF watermark).

## Commits

Commit author: **Rohit Solanki**. Keep messages descriptive.
