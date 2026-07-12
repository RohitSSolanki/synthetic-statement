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
