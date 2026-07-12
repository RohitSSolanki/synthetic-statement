"""Realism tests for basket-based amount allocation (roadmap task 04b).

Category *amount* share tracks the region's expenditure basket; category *count*
tracks the profile's frequency weights; a slice goes to P2P transfers.

    .venv/bin/pytest tests/test_realism.py
"""

from __future__ import annotations

import random
import sys
from collections import defaultdict
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from synthetic_statement import generate  # noqa: E402
from synthetic_statement import statement_generator as g  # noqa: E402


# --------------------------------------------------------------------------- #
# basket data
# --------------------------------------------------------------------------- #
@pytest.mark.parametrize("region_key", ["in", "us"])
def test_basket_sums_to_one_over_the_regions_categories(region_key):
    region = g._CATALOG["regions"][region_key]
    basket = region["basket"]
    assert set(basket) == set(region["categories"])
    assert abs(sum(basket.values()) - 1.0) < 1e-9


# --------------------------------------------------------------------------- #
# _plan_merchant_debits — budget conservation
# --------------------------------------------------------------------------- #
def test_merchant_debit_budget_is_conserved():
    region = g._resolve_region("india")
    currency = g._resolve_currency("inr")
    profile = g.PROFILE_SPECS["family-expense"]
    lines = g._plan_merchant_debits(
        random.Random(0), merchant_expense=100000.0, merchant_count=40,
        region=region, currency=currency, profile=profile,
    )
    assert lines
    assert sum(amount for _, amount in lines) == pytest.approx(100000.0, abs=1.0)


# --------------------------------------------------------------------------- #
# realized distribution over a full run
# --------------------------------------------------------------------------- #
def _debit_category_totals(records, region):
    """Total debit amount per category (by the merchant's group), plus a
    'person' bucket for P2P transfers. Merchants shared across categories fall
    to their first group — fine for coarse ordering checks."""
    merchant_to_cat = {}
    for cat, names in region.merchant_groups.items():
        for n in names:
            merchant_to_cat.setdefault(n, cat)
    totals = defaultdict(float)
    for r in records:
        if r["type"] != "debit":
            continue
        name = r["Transaction Detail"][0].removeprefix("Paid to ")
        totals[merchant_to_cat.get(name, "person")] += r["amount"]
    return totals


def test_high_basket_category_outweighs_low_one():
    region = g._resolve_region("india")
    stmt = generate(seed=42, start="2026-01-01", end="2026-03-31", profile="family-expense")
    totals = _debit_category_totals(stmt.records, region)
    # groceries (basket 0.24, unique merchants) clearly outweighs entertainment
    # (0.05, unique merchants) — the anomaly ("Netflix > a month of groceries")
    # the basket allocation removes.
    assert totals["groceries"] > 2 * totals["entertainment"]


def test_recurring_commitments_form_stable_monthly_series():
    # Over a 3-month run each recurring commitment appears once per month at a
    # fixed amount on a fixed day — so downstream recurring inference fires.
    stmt = generate(seed=42, start="2026-01-01", end="2026-03-31", profile="family-expense")
    by_merchant = defaultdict(list)
    for r in stmt.records:
        if r["type"] == "debit":
            m = r["Transaction Detail"][0].removeprefix("Paid to ")
            by_merchant[m].append((r["date"][-2:], r["amount"]))
    clean_series = [
        m for m, hits in by_merchant.items()
        if len(hits) == 3 and len({a for _, a in hits}) == 1 and len({d for d, _ in hits}) == 1
    ]
    # At least the bill + EMI + a subscription (spec defines four commitments).
    assert len(clean_series) >= 3


def test_person_transfer_slice_tracks_profile_probability():
    region = g._resolve_region("india")
    stmt = generate(seed=42, start="2026-01-01", end="2026-03-31", profile="family-expense")
    totals = _debit_category_totals(stmt.records, region)
    debit_total = sum(totals.values())
    person_share = totals["person"] / debit_total
    prob = g.PROFILE_SPECS["family-expense"].debit_person_prob
    assert prob - 0.06 < person_share < prob + 0.06
