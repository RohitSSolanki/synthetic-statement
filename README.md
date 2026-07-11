# synthetic-statement

Generate realistic **synthetic bank & UPI statements** — as structured **JSON** or rendered **PDF** —
for testing, demos, and local development.

Pick a persona, a country/currency, a date range and a spending profile, and get a believable statement
whose amounts and category mix mimic a real user's — grounded in published household-expenditure
proportions and per-capita income, not random noise.

> ⚠️ **For testing, demos, and development only.** This tool produces **fake, clearly-synthetic** data.
> It is **not** for producing documents that misrepresent a real person's finances. Don't use it to
> deceive anyone.

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
from synthetic_statement import statement_generator
statement_generator.main(["--yes", "--seed", "42", "--output-dir", "out"])
```

Writes `statement.json` (structured records), `statement.csv`, and `meta.json` (version/seed/options
provenance) into the output dir. See `synthetic-statement --help` for currency, date range, income/
expense, bank and profile options.

## What's inside (planned)

- **Generator core** — a library with a clean `options → statement` API (seeded/deterministic).
- **Canonical catalog** — a curated, versioned list of common merchants (name, aliases, statement
  descriptors, category) + a generic person pool for P2P.
- **Realism engine** — per-category income proportions (from household-expenditure surveys) + a
  per-capita-income-by-country table, so amounts are currency-aware.
- **Renderers** — JSON + PDF output across common Indian bank / UPI statement layouts.
- **Local UI** — a small web UI to pick options and download a statement, runnable from a clone.

## Status

Working + `pip install`-able: the generator, renderers, and verifier run, with deterministic seeded
output. Catalog/realism tuning is ongoing; a clean `options → statement` library API is on the roadmap.

## License

[MIT](LICENSE) © Rohit Solanki.
