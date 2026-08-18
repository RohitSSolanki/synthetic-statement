"""Tests for the opt-in rail-reference fixture affordances.

``expose_refs`` and ``inject`` let a consumer build deterministic dedup/reconcile
scenarios (a known-UTR re-upload, a shared-UTR self-transfer pair). Both are
opt-in and must leave the default output shape untouched.

Run with the local venv:

    .venv/bin/pytest tests/test_rail_fixtures.py
"""

from __future__ import annotations

import csv
import io
import sys
from datetime import date
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from synthetic_statement import InjectedRow, generate  # noqa: E402
from synthetic_statement import statement_generator as generator  # noqa: E402

_DEFAULT_KEYS = {"date", "time", "Transaction Detail", "type", "amount"}


def _config(**overrides) -> generator.RunConfig:
    base = dict(
        start_date=date(2026, 1, 1),
        end_date=date(2026, 1, 31),
        monthly_income=120000.0,
        monthly_expense=90000.0,
        seed=42,
        profile="salary-heavy",
        bank="HDFC Bank",
    )
    base.update(overrides)
    return generator.RunConfig(**base)


# --------------------------------------------------------------------------- #
# default output shape is untouched
# --------------------------------------------------------------------------- #
def test_default_records_carry_no_ref_fields():
    records = generator._generate_records(_config())
    assert records, "expected a non-empty statement"
    for row in records:
        assert set(row) == _DEFAULT_KEYS


def test_defaults_do_not_perturb_seeded_output():
    # Adding the (defaulted-off) options must not change a seeded run byte-for-byte.
    plain = generator._generate_records(_config(seed=7))
    with_defaults = generator._generate_records(
        _config(seed=7, expose_refs=False, inject=())
    )
    assert plain == with_defaults


# --------------------------------------------------------------------------- #
# expose_refs — surface the seeded refs for read-back
# --------------------------------------------------------------------------- #
def test_expose_refs_surfaces_utr_and_txn_id():
    records = generator._generate_records(_config(expose_refs=True))
    for row in records:
        assert "utr" in row and "txn_id" in row
        # the surfaced value is exactly what the detail block carries
        detail = " ".join(row["Transaction Detail"])
        assert row["utr"] in detail
        assert row["txn_id"] in detail


def test_expose_refs_is_stable_across_runs():
    a = generator._generate_records(_config(seed=99, expose_refs=True))
    b = generator._generate_records(_config(seed=99, expose_refs=True))
    assert [r["utr"] for r in a] == [r["utr"] for r in b]


# --------------------------------------------------------------------------- #
# inject — caller-supplied rows
# --------------------------------------------------------------------------- #
def test_injected_row_is_present_and_self_exposes_refs():
    stmt = generate(
        seed=1,
        start="2026-01-01",
        end="2026-01-31",
        inject=[
            InjectedRow(
                direction="debit",
                amount=1234.0,
                counterparty="Coffee House",
                utr="RRN000000000001",
                txn_id="T2601010001",
                date="2026-01-15",
            )
        ],
    )
    injected = [r for r in stmt.records if r.get("utr") == "RRN000000000001"]
    assert len(injected) == 1
    row = injected[0]
    assert row["txn_id"] == "T2601010001"
    assert row["type"] == "debit"
    assert row["amount"] == 1234.0
    # renderer/parser invariant: still a 4-line detail block
    assert len(row["Transaction Detail"]) == 4
    assert "Coffee House" in row["Transaction Detail"][0]


def test_injected_rows_expose_even_when_expose_refs_off():
    # Injected rows always carry refs; the generated rows around them do not.
    stmt = generate(
        seed=1,
        start="2026-01-01",
        end="2026-01-31",
        expose_refs=False,
        inject=[InjectedRow(direction="debit", amount=50.0, counterparty="Kiosk", utr="RRNX")],
    )
    exposed = [r for r in stmt.records if "utr" in r]
    assert len(exposed) == 1 and exposed[0]["utr"] == "RRNX"


def test_shared_utr_cross_leg_pair():
    # A self-transfer: one debit + one credit sharing a single UTR, opposite dirs.
    shared = "RRN555555555555"
    stmt = generate(
        seed=1,
        start="2026-01-01",
        end="2026-01-31",
        inject=[
            InjectedRow(direction="debit", amount=8000.0, counterparty="Self A/C 2", utr=shared),
            InjectedRow(direction="credit", amount=8000.0, counterparty="Self A/C 1", utr=shared),
        ],
    )
    pair = [r for r in stmt.records if r.get("utr") == shared]
    assert len(pair) == 2
    assert {r["type"] for r in pair} == {"debit", "credit"}


def test_injected_utr_defaults_are_deterministic():
    # An omitted UTR is minted deterministically, so it is stable across runs.
    a = generate(seed=1, start="2026-01-01", end="2026-01-31",
                 inject=[InjectedRow(direction="debit", amount=10.0, counterparty="X")])
    b = generate(seed=1, start="2026-01-01", end="2026-01-31",
                 inject=[InjectedRow(direction="debit", amount=10.0, counterparty="X")])
    ua = next(r["utr"] for r in a.records if "utr" in r)
    ub = next(r["utr"] for r in b.records if "utr" in r)
    assert ua == ub


# --------------------------------------------------------------------------- #
# CSV surface is unchanged; internal markers never leak
# --------------------------------------------------------------------------- #
def test_csv_columns_unchanged_with_fixtures():
    stmt = generate(
        seed=1,
        start="2026-01-01",
        end="2026-01-31",
        expose_refs=True,
        inject=[InjectedRow(direction="credit", amount=99.0, counterparty="Y", utr="RRNY")],
    )
    reader = csv.reader(io.StringIO(stmt.to_csv()))
    header = next(reader)
    assert header == ["date", "time", "Transaction Detail", "type", "amount"]


def test_no_internal_markers_leak_into_records():
    stmt = generate(
        seed=1,
        start="2026-01-01",
        end="2026-01-31",
        inject=[InjectedRow(direction="debit", amount=10.0, counterparty="X", utr="RRNZ")],
    )
    for row in stmt.records:
        assert "_sort_key" not in row
        assert "_utr" not in row and "_txn_id" not in row
        assert "_injected" not in row


# --------------------------------------------------------------------------- #
# guards
# --------------------------------------------------------------------------- #
def test_ref_echo_is_deferred():
    with pytest.raises(NotImplementedError):
        generate(
            seed=1,
            start="2026-01-01",
            end="2026-01-31",
            inject=[InjectedRow(direction="debit", amount=1.0, counterparty="X", ref="abc")],
        )


def test_invalid_direction_rejected():
    with pytest.raises(ValueError):
        generate(
            seed=1,
            start="2026-01-01",
            end="2026-01-31",
            inject=[InjectedRow(direction="sideways", amount=1.0, counterparty="X")],
        )


def test_inject_accepts_plain_dicts():
    stmt = generate(
        seed=1,
        start="2026-01-01",
        end="2026-01-31",
        inject=[{"direction": "debit", "amount": 5.0, "counterparty": "X", "utr": "RRND"}],
    )
    assert any(r.get("utr") == "RRND" for r in stmt.records)
