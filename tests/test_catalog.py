"""Tests for the versioned, region-keyed catalog (roadmap task 03).

Run with the local venv:

    .venv/bin/pytest tests/test_catalog.py
"""

from __future__ import annotations

import hashlib
import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from synthetic_statement import generate  # noqa: E402
from synthetic_statement import statement_generator as g  # noqa: E402

_CATALOG = g._CATALOG
_REGION_KEYS = {
    "label", "currency", "categories", "merchants", "persons", "employers", "banks", "basket",
}


# --------------------------------------------------------------------------- #
# structure
# --------------------------------------------------------------------------- #
def test_catalog_top_level_shape():
    assert _CATALOG["version"] == 1
    assert _CATALOG["default_region"] == "in"
    assert set(_CATALOG["regions"]) == {"in", "us"}


@pytest.mark.parametrize("region_key", ["in", "us"])
def test_region_has_required_keys(region_key):
    region = _CATALOG["regions"][region_key]
    assert _REGION_KEYS <= set(region)
    assert region["merchants"] and region["categories"]
    assert region["persons"]["first_names"] and region["persons"]["last_names"]
    assert region["employers"]["companies"] and region["employers"]["salary_token"]


@pytest.mark.parametrize("region_key", ["in", "us"])
def test_every_merchant_category_is_declared(region_key):
    region = _CATALOG["regions"][region_key]
    declared = set(region["categories"])
    for merchant in region["merchants"]:
        assert merchant["name"]
        assert "aliases" in merchant
        assert set(merchant["categories"]) <= declared, merchant["name"]


def test_us_region_is_distinct_placeholder():
    us = _CATALOG["regions"]["us"]
    assert us["currency"] == "USD"
    assert us["employers"]["salary_token"] == "PAYROLL"
    in_names = {m["name"] for m in _CATALOG["regions"]["in"]["merchants"]}
    us_names = {m["name"] for m in us["merchants"]}
    # A real, largely-distinct set (a few global brands like Nike/Netflix overlap).
    assert len(us_names - in_names) >= 20


# --------------------------------------------------------------------------- #
# default region drives the live constants (India, unchanged)
# --------------------------------------------------------------------------- #
def test_default_region_constant_counts():
    assert len(g.MERCHANTS) == 50
    assert len(g.MERCHANT_GROUPS) == 10
    assert len(g.FIRST_NAMES) == 20 and len(g.LAST_NAMES) == 20
    assert len(g.COMPANIES) == 10 and g.SALARY_TOKEN == "SALARY"


def test_merchant_groups_reconstructed_from_catalog():
    region = _CATALOG["regions"]["in"]
    for category, members in g.MERCHANT_GROUPS.items():
        expected = [m["name"] for m in region["merchants"] if category in m["categories"]]
        assert list(members) == expected


# --------------------------------------------------------------------------- #
# behaviour pin: fixed-seed India/INR output. Re-pinned at task 04c (basket
# allocation + recurring commitments changed the default distribution). Bump
# only on an intentional generator/data change.
# --------------------------------------------------------------------------- #
GOLDEN = {
    (42, "2026-01-01", "2026-03-31", "family-expense", "HDFC Bank"):
        "7ace4866ec3dfb618753e2471aadb1f8ac29ca3a499facf48210995062209bbe",
    (7, "2026-01-01", "2026-02-28", "student", "ICICI Bank"):
        "646753ed893cddee4f1b7a0fac5a4f9a18dc944045d11320e81cd3c32f4b34ed",
    (99, "2025-11-01", "2026-01-31", "salary-heavy", "Axis Bank"):
        "1d59748d5a13bb31dbe6153debaac2939aeb94a9f2aff983fb065cc1d6781d0a",
}


@pytest.mark.parametrize("params,digest", list(GOLDEN.items()))
def test_seeded_output_matches_golden(params, digest):
    seed, start, end, profile, bank = params
    out = generate(seed=seed, start=start, end=end, profile=profile, bank=bank).to_json()
    assert hashlib.sha256(out.encode()).hexdigest() == digest


def test_catalog_json_is_valid_and_shipped_in_package():
    # The loader reads it via importlib.resources; confirm it parses standalone.
    from importlib.resources import files

    text = (files("synthetic_statement") / "data" / "catalog.json").read_text(encoding="utf-8")
    assert json.loads(text)["default_region"] == "in"
