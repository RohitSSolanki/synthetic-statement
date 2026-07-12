"""Country / currency locale tests (roadmap task 04a).

Region threading (merchants / persons / banks) + currency scaling. Default
(india / inr) stays byte-identical — guarded by the golden test in
tests/test_catalog.py; here we exercise the non-default locales.

    .venv/bin/pytest tests/test_locale.py
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from synthetic_statement import generate  # noqa: E402
from synthetic_statement import statement_generator as g  # noqa: E402


def _counterparties(records):
    out = []
    for r in records:
        first = r["Transaction Detail"][0]
        for verb in ("Paid to ", "Received from "):
            if first.startswith(verb):
                out.append(first[len(verb):])
    return out


# --------------------------------------------------------------------------- #
# region threading
# --------------------------------------------------------------------------- #
def test_usa_uses_us_catalog_not_india():
    stmt = generate(seed=42, start="2026-01-01", end="2026-03-31", country="usa")
    assert stmt.meta["country"] == "usa"
    india_only = {"Swiggy", "Flipkart", "Jio", "Zomato", "BigBasket", "IRCTC"}
    assert not (set(_counterparties(stmt.records)) & india_only)
    # Account bank is a US bank; salary carries the US PAYROLL token.
    account = stmt.records[0]["Transaction Detail"][3]
    us_banks = {b["name"] for b in g._CATALOG["regions"]["us"]["banks"]}
    assert any(account.startswith("Paid by " + b) or account.startswith("Credited to " + b) for b in us_banks)
    salary = next(r["Transaction Detail"][0] for r in stmt.records if r["type"] == "credit")
    assert salary.endswith("PAYROLL")


def test_india_default_uses_india_catalog():
    stmt = generate(seed=42, start="2026-01-01", end="2026-01-31")
    assert stmt.meta["country"] == "india" and stmt.meta["currency"] == "inr"
    salary = next(r["Transaction Detail"][0] for r in stmt.records if r["type"] == "credit")
    assert salary.endswith("SALARY")


# --------------------------------------------------------------------------- #
# currency scaling
# --------------------------------------------------------------------------- #
def test_currency_defaults_from_country():
    assert generate(seed=1, start="2026-01-01", end="2026-01-31", country="usa").meta["currency"] == "usd"


def test_usd_amounts_are_plausibly_scaled():
    stmt = generate(seed=42, start="2026-01-01", end="2026-03-31", country="usa")
    amts = sorted(r["amount"] for r in stmt.records)
    median = amts[len(amts) // 2]
    # A US household median txn is tens-to-low-hundreds of dollars, not lakhs.
    assert 10 < median < 1500
    assert stmt.meta["monthly_income"] == 7000 and stmt.meta["monthly_expense"] == 5250


def test_zero_decimal_currency_rounds_to_whole_units():
    stmt = generate(seed=3, start="2026-01-01", end="2026-01-31", country="usa", currency="jpy")
    assert all(float(r["amount"]).is_integer() for r in stmt.records)


def test_currency_independent_of_country():
    # US catalog priced in EUR — the "reuse the US set for another economy" path.
    stmt = generate(seed=2, start="2026-01-01", end="2026-01-31", country="usa", currency="eur")
    assert stmt.meta["currency"] == "eur" and stmt.meta["country"] == "usa"


# --------------------------------------------------------------------------- #
# validation
# --------------------------------------------------------------------------- #
def test_unknown_country_and_currency_rejected():
    with pytest.raises(SystemExit):
        generate(country="atlantis")
    with pytest.raises(SystemExit):
        generate(currency="xyz")


def test_currencies_table_integrity():
    table = g._CURRENCIES["currencies"]
    assert g._CURRENCIES["base"] in table
    for code, row in table.items():
        assert {"symbol", "decimals", "per_capita_annual", "default_income", "default_expense"} <= set(row)
        assert row["default_income"] > 0 and row["default_expense"] > 0
