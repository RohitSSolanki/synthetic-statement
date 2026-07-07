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

## What's inside (planned)

- **Generator core** — a library with a clean `options → statement` API (seeded/deterministic).
- **Canonical catalog** — a curated, versioned list of common merchants (name, aliases, statement
  descriptors, category) + a generic person pool for P2P.
- **Realism engine** — per-category income proportions (from household-expenditure surveys) + a
  per-capita-income-by-country table, so amounts are currency-aware.
- **Renderers** — JSON + PDF output across common Indian bank / UPI statement layouts.
- **Local UI** — a small web UI to pick options and download a statement, runnable from a clone.

## Status

Scaffold. Code is being migrated in; see the local `.scratch/` for the design and roadmap.

## License

[MIT](LICENSE) © Rohit Solanki.
