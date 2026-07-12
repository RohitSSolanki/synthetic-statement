# Statement format specification

**Spec version 1.0** — tracks `statement_generator.GENERATOR_VERSION`. Bump this (and the generator
version) whenever an emitted layout changes; that bump is the signal to any parser targeting the format.

This document describes **everything `synthetic-statement` emits** — the only surface a downstream
consumer's parser sees. It is a description of *output*, not a shared vocabulary: consumers import nothing
from this package. Machine-readable companion: [`statement.schema.json`](statement.schema.json).

> All output is **synthetic**. See the repository README for the usage disclaimer.

---

## 1. Canonical record

Every format below is a rendering of the same in-memory record (`Statement.records`):

```json
{
  "date": "2026-01-05",
  "time": "09:01:28",
  "Transaction Detail": [
    "Paid to ICICI Bank",
    "Transaction ID: TXN2026010510214",
    "UTR No.: UTR202601051022154",
    "Paid by IndusInd Bank A/C XX2283"
  ],
  "type": "debit",
  "amount": 200.78
}
```

| Field | Type | Notes |
|-------|------|-------|
| `date` | string | ISO 8601 `YYYY-MM-DD`. |
| `time` | string | 24-hour `HH:MM:SS`. |
| `Transaction Detail` | array[4] string | Fixed 4-line block — see below. |
| `type` | `"debit"` \| `"credit"` | Direction (redundant with the detail verbs, but explicit). |
| `amount` | number | Positive, in the run's `currency` (major units; see `meta.json`). |

**`Transaction Detail` lines (positional):**
0. `Paid to <name>` (debit) or `Received from <name>` (credit).
1. `Transaction ID: TXN<YYYYMMDD><seq><rand>` — `TXN` + 8-digit date + zero-padded index + digits.
2. `UTR No.: UTR<YYYYMMDD><seq><rand>`.
3. `Paid by <account>` (debit) or `Credited to <account>` (credit). The account format is
   region-specific — India reads `<Bank> A/C XX<4 digits>`, US reads `<Bank> ****<4 digits>`.

Records are sorted by `(date, time)` ascending. A fixed `--seed` yields **byte-identical** output.

---

## 2. `statement.json` — structured JSON

A top-level **array** of canonical records (above). Validated by
[`statement.schema.json`](statement.schema.json) (JSON Schema 2020-12). No envelope, no wrapper object —
the array is the document.

## 3. `statement.csv` — flat CSV

Header row then one row per record. Columns (exact order):

```
date,time,Transaction Detail,type,amount
```

- `Transaction Detail` is the 4-element list **JSON-encoded as a string** inside the cell.
- `amount` is formatted to two decimals (`1200.00`); all other fields mirror the JSON.

## 4. `meta.json` — run provenance

Emitted by `Statement.write()` alongside the data (not part of the records stream).

| Field | Notes |
|-------|-------|
| `generator_version` | `statement_generator.GENERATOR_VERSION`. |
| `seed` | The `--seed` used (may be null). |
| `start_date`, `end_date` | ISO window bounds. |
| `profile`, `bank` | Chosen spending profile / bank. |
| `country`, `currency` | Locale — catalog region (`india` / `usa`) + the amount currency. |
| `monthly_income`, `monthly_expense` | Run inputs (in `currency`). |
| `row_count`, `debit_count`, `credit_count` | Totals (`debit + credit == row`). |

---

## 5. PDF layouts

The PDF renderers reproduce **Indian UPI-app** layouts (PhonePe / Paytm / GPay) and are oriented to INR;
for other currencies, use the currency-aware **JSON / CSV** output. Each rendered PDF is **text-based**
(never an image), so `pdftotext -layout` reproduces the structure a parser reads. All three carry the watermark line `SYNTHETIC SAMPLE - NOT A REAL STATEMENT` and a trailing
`This is a system generated statement.` Amounts drop the `₹`/`Rs.` symbol only if the embedded font can't
render it (a bare number stays parser-valid).

### 5.1 PhonePe — `phonepe.pdf`
Wide 4-column table (`Date` / `Transaction Details` / `Type` / `Amount`). Header: `PhonePe`,
`Transaction Statement`, holder name, `UPI ID`, `Statement Period: <Mon DD, YYYY> - <Mon DD, YYYY>`.
Date cell stacks `Mon DD, YYYY` + `h:MM AM/PM`; type is `DEBIT`/`CREDIT`; amount is `₹1,200.00`
(unsigned — direction from the `Type` column and the `Paid to`/`Received from` verb).

```
Jan 05, 2026   Paid to Amazon India          DEBIT   ₹1,200.00
10:30 AM       Transaction ID: TXN...
               UTR No.: UTR...
               Paid by HDFC Bank A/C XX1234
```

### 5.2 Paytm — `paytm.pdf`
5-column passbook (`Date & Time` / `Transaction Details` / `Notes & Tags` / `Your Account` / `Amount`),
calibrated to a real Paytm "Passbook Payments History". Uses **`Rs.`** not `₹`; **year-less `DD Mon`** rows
with the year in the period header `D MON'YY - D MON'YY`; **signed** amounts — `- Rs.X` for debits,
**unsigned** `Rs.X` for credits. Detail cell adds `UPI ID: <handle>` and `UPI Ref No: <12 digits>`.

```
05 Jan        Paid to Amazon India     Tag:           HDFC Bank      - Rs.1,200.00
1:30 PM       UPI ID: amazon.india@ybl # Payment      XX1234
              UPI Ref No: 412345678901
```

### 5.3 Google Pay — `gpay.pdf`
Stacked list (not a table): five lines per transaction. **Unsigned** amounts — direction comes from the
`Paid to` / `Received from` verb. *Assumed layout — recalibrate against a real GPay statement when
available.*

```
5 Jan 2026, 2:30 PM
Paid to Amazon India
₹1,200.00
HDFC Bank XX1234
Completed - UPI transaction ID: 412345678901
```

---

## 6. Versioning

The spec version at the top of this file tracks `GENERATOR_VERSION`. Any change to a JSON field, CSV
column, or PDF layout (column set, date/amount format, header lines) is a **breaking** change for parsers:
bump both, and note it here.
