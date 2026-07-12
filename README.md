# synthetic-statement

Generate realistic **synthetic bank & UPI statements** — as structured **JSON** or rendered **PDF** —
for testing, demos, and local development.

Pick a persona, a country/currency, a date range and a spending profile, and get a believable statement
whose amounts and category mix mimic a real user's — grounded in published household-expenditure
proportions and per-capita income, not random noise.

> ⚠️ **For testing, demos, and development only.** This tool produces **fake, clearly-synthetic** data.
> It is **not** for producing documents that misrepresent a real person's finances. Don't use it to
> deceive anyone.

## Try it — no install

**[▶ Generate a statement in your browser](https://synth.rohitsolanki.in/)** — pick a country, currency,
persona and date range, and download **JSON / CSV / PDF**. It runs entirely in your browser (Pyodide);
nothing is uploaded, no setup. Prefer code? Read on.

## Why

Realistic test data is hard: hand-rolled fixtures look fake (a ₹50,000 water bill, groceries larger than
rent), and real statements can't be shared (PII). This generates statements that are **structurally and
proportionally realistic** — so anything that consumes bank/UPI statements (parsers, budgeting tools,
categorizers, dashboards) can be built and demoed against data that behaves like the real thing.

## Install

```bash
pip install "git+https://github.com/RohitSSolanki/synthetic-statement@main"   # or pin a commit/tag
pip install "synthetic-statement[pdf] @ git+https://github.com/RohitSSolanki/synthetic-statement@main"  # + PDF rendering
```

The generator core is pure standard library (no runtime deps); the optional `[pdf]` extra pulls
`reportlab` for the PDF renderers. Determinism is guaranteed: a fixed `--seed` yields byte-identical
JSON for the same options, so a consumer can commit a stable fixture and diff refreshes cleanly.

## Usage

```bash
# console script (installed) — or `python -m synthetic_statement …`
synthetic-statement --yes --seed 42 --profile family-expense --output-dir out
```

```python
from synthetic_statement import generate

stmt = generate(seed=42, period="monthly", profile="family-expense")
stmt.records        # list of structured txn dicts (in memory — no files written)
stmt.to_json()      # -> str      stmt.to_csv() -> str
stmt.write("out")   # -> statement.json / statement.csv / meta.json

# Locale-aware: country picks the merchants/persons/banks; currency scales the
# amounts (per-capita-anchored) and sets rounding. Amounts read plausibly for
# the locale — no INR numbers shown under a foreign symbol.
generate(seed=42, country="usa", currency="usd")
```

`generate()` returns a `Statement` in memory (great for embedding or an in-browser build); `.write()`
persists the three files, with `meta.json` recording version/seed/options provenance. A fixed `seed` gives
**byte-identical** output. The CLI is a thin caller of the same path — see `synthetic-statement --help` for
date range, income/expense, bank and profile options.

## Statement format

The emitted formats — the surface a downstream parser sees — are documented in
[`spec/format-spec.md`](spec/format-spec.md), with a machine-readable JSON Schema at
[`spec/statement.schema.json`](spec/statement.schema.json). A consumer can build a parser for any layout
(JSON / CSV / the PhonePe / Paytm / GPay PDFs) from the spec alone.

## What's inside

- **Generator core** — a library with a clean `options → statement` API (seeded/deterministic).
- **Versioned catalog** — region-keyed merchants / persons / employers / banks (India + US) as
  editable data (`data/catalog.json`); adding a merchant is a data edit.
- **Realism engine** — amounts allocated by a per-country **expenditure basket** (India MoSPI HCES /
  US BLS), **per-capita-anchored currency scaling** (12 currencies), and **recurring** salary /
  subscription / bill / EMI series so downstream recurring inference fires.
- **Renderers** — JSON / CSV + PDF across common Indian bank / UPI statement layouts (PhonePe / Paytm /
  GPay); the emitted formats are documented in [`spec/`](spec/format-spec.md).
- **Hosted demo** — a client-side (Pyodide) GitHub Pages UI to pick options and download a statement,
  no backend.

## Status

Working + `pip install`-able: deterministic seeded output, locale-aware amounts, versioned catalog,
documented formats, and a hosted client-side demo.

## License

[MIT](LICENSE) © Rohit Solanki.
