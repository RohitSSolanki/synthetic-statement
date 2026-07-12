# Realism model

How `synthetic-statement` makes amounts and merchants believable — the reference
for the realism engine and how to extend it. (User quickstart: the
[README](README.md). Output formats: [`spec/`](spec/format-spec.md).)

## Two axes: country and currency

A run is parameterised by two **independent** options:

- **`country`** (`india` | `usa`) selects the **catalog** — the merchants,
  person names, employers, banks and consumption basket for that locale.
- **`currency`** (12 supported) selects the **money scale** — the symbol,
  rounding and the income anchor that sizes amounts.

They are independent on purpose: the US catalog can be priced in any currency,
which is how other economies are approximated — reuse the US merchant set with a
different per-capita income, rather than authoring a full new catalog. Defaults:
`india`→INR, `usa`→USD.

## Amount allocation — basket × frequency

Each month's expense budget is split across categories by **two** signals:

- **Amount** per category tracks the region's **expenditure basket**
  (`data/catalog.json` → `regions.<r>.basket`): `category → share of spend`,
  summing to 1. Sourced from published surveys (India **MoSPI HCES**, US **BLS
  Consumer Expenditure**). This keeps category *totals* realistic — groceries
  and bills dominate, entertainment is small — so there are no
  "utilities > groceries" anomalies.
- **Count** per category tracks the profile's **frequency weights**
  (`PROFILE_SPECS[...].merchant_weights`): many small food / grocery txns, a few
  large finance / EMI ones.

Per category: `budget = share × merchant_expense`, `count` from frequency, then
`_generate_amounts` distributes `count` amounts summing to `budget` with a
small / medium / large tier shape (plus the occasional outlier). A P2P
person-transfer slice (`profile.debit_person_prob`) is carved off first.

## Currency scaling — per-capita anchored

`data/currencies.json` gives each currency
`{symbol, decimals, per_capita_annual, default_income, default_expense}`.
`default_income` / `default_expense` are a plausible affluent-household monthly
budget, **anchored on** the economy's per-capita income. The scale applied to the
INR-tuned internals is `scale = default_income / default_income[base]`
(base = INR). Amounts round to the currency's `decimals` (e.g. whole yen for
JPY), and the transaction-count divisor scales with the currency so counts stay
comparable. Result: amounts read plausibly in the target currency — no INR
magnitudes shown under a foreign symbol.

## Recurring commitments

Beyond the recurring salary credit, each run has fixed monthly debit series
(`_RECURRING_SPECS`): two subscriptions, a utility bill and an EMI. Each is a
fixed merchant + amount + day-of-month, constant across the run, **carved from**
its category budget, with its merchant **excluded from random draws** so the
series stays clean — enough for a downstream recurring-inference engine to lock
onto.

## Determinism

A fixed `--seed` yields **byte-identical** output for the same options. The suite
pins this with golden sha256 hashes (`tests/test_catalog.py`); re-pin them
**only** on an intentional generator / data change.

## Extending

A **data edit** (no code) unless noted:

- **Add / retune a merchant, person, employer or bank** → `data/catalog.json`
  under the region.
- **Tune a consumption basket** → `regions.<r>.basket` (keep it summing to 1).
- **Add a currency** → `data/currencies.json` (supply `per_capita_annual` and a
  proportional `default_income` / `default_expense`, plus `decimals` / `symbol`).
- **Add a region / country** → a new `regions.<key>` block + entries in
  `COUNTRY_TO_REGION` / `COUNTRY_DEFAULT_CURRENCY` (code).
- **Change a recurring commitment** → `_RECURRING_SPECS` (code).

After any change that shifts seeded output, **re-pin the golden hashes**.

> All figures (per-capita incomes, basket shares) are **approximations** for
> plausible synthetic data, not authoritative economic statistics.
