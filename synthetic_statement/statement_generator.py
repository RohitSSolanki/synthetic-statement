"""Synthetic statement generator for UPI / bank statement records.

The generator emits one canonical in-memory record set and serializes it to
both CSV and JSON so the two outputs always stay in sync.
"""

from __future__ import annotations

import argparse
import csv
import io
import json
import random
import sys
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Iterable, Optional


def _load_catalog() -> dict:
    """Load the versioned, region-keyed catalog (merchants / persons / employers).

    Data lives in ``synthetic_statement/data/catalog.json`` — adding a merchant,
    name or employer is a data edit. The default region (``in``) reproduces the
    previous hard-coded lists byte-for-byte; other regions (e.g. ``us``) are
    dormant until a country option selects them (roadmap task 04).
    """
    from importlib.resources import files

    text = (files("synthetic_statement") / "data" / "catalog.json").read_text(encoding="utf-8")
    return json.loads(text)


def _load_currencies() -> dict:
    """Load the currency scaling table (symbol / decimals / income anchors)."""
    from importlib.resources import files

    text = (files("synthetic_statement") / "data" / "currencies.json").read_text(encoding="utf-8")
    return json.loads(text)


_CATALOG = _load_catalog()
_CURRENCIES = _load_currencies()
_REGION = _CATALOG["regions"][_CATALOG["default_region"]]

# `country` selects the beneficiary catalog (merchants / persons / employers /
# banks); `currency` selects the money scale. They are independent — the US
# catalog can be priced in any currency, which is how other economies reuse the
# US set with a different per-capita income.
COUNTRY_TO_REGION = {"india": "in", "usa": "us"}
COUNTRY_DEFAULT_CURRENCY = {"india": "inr", "usa": "usd"}
DEFAULT_COUNTRY = "india"

# Default-region convenience views (India). Generation resolves these per-run
# from the selected region; these module globals back CLI help + the catalog
# tests. A merchant may belong to several categories.
MERCHANTS = [_m["name"] for _m in _REGION["merchants"]]

MERCHANT_GROUPS = {
    _cat: tuple(_m["name"] for _m in _REGION["merchants"] if _cat in _m["categories"])
    for _cat in _REGION["categories"]
}

# Generic person pool for P2P / UPI transfers.
FIRST_NAMES = _REGION["persons"]["first_names"]
LAST_NAMES = _REGION["persons"]["last_names"]

# Employers for the monthly salary inflow. Unlike a P2P credit (a person name),
# a salary credit carries a company name PLUS a token (e.g. "SALARY") so the
# backend categorization engine can separate income from peer transfers /
# refunds — the stable signal in real statements is the token, not the payer.
COMPANIES = _REGION["employers"]["companies"]
SALARY_TOKEN = _REGION["employers"]["salary_token"]

# Default-region (India) banks, single-sourced from the catalog; kept as module
# names for CLI help + validation. Other regions carry their own banks.
ACCOUNT_BANKS = [_b["name"] for _b in _REGION["banks"]]
BANK_HEADER_TEMPLATES = {_b["name"]: _b["header"] for _b in _REGION["banks"]}
BANK_INPUTS = ACCOUNT_BANKS + ["random"]

DEFAULT_MONTHLY_INCOME = 120000.0
DEFAULT_MONTHLY_EXPENSE = 90000.0
DEFAULT_PERIOD = "annually"
DEFAULT_PROFILE = "salary-heavy"
DEFAULT_BANK = "random"
DEFAULT_OUTPUT_ROOT = Path(__file__).resolve().parent / "runs"

GENERATOR_VERSION = "1.0"


@dataclass(frozen=True)
class _ResolvedRegion:
    """A region's beneficiary data, resolved once per run from the catalog."""

    merchants: list[str]
    merchant_groups: dict[str, tuple[str, ...]]
    first_names: list[str]
    last_names: list[str]
    companies: list[str]
    salary_token: str
    bank_names: list[str]
    bank_headers: dict[str, str]
    basket: dict[str, float]


def _resolve_region(country: str) -> "_ResolvedRegion":
    region = _CATALOG["regions"][COUNTRY_TO_REGION[country]]
    return _ResolvedRegion(
        merchants=[m["name"] for m in region["merchants"]],
        merchant_groups={
            cat: tuple(m["name"] for m in region["merchants"] if cat in m["categories"])
            for cat in region["categories"]
        },
        first_names=region["persons"]["first_names"],
        last_names=region["persons"]["last_names"],
        companies=region["employers"]["companies"],
        salary_token=region["employers"]["salary_token"],
        bank_names=[b["name"] for b in region["banks"]],
        bank_headers={b["name"]: b["header"] for b in region["banks"]},
        basket=region["basket"],
    )


@dataclass(frozen=True)
class _Currency:
    """Money-scale for a currency: symbol, rounding and the income anchors."""

    code: str
    symbol: str
    decimals: int
    scale: float
    default_income: float
    default_expense: float


def _resolve_currency(currency: str) -> "_Currency":
    table = _CURRENCIES["currencies"]
    base_income = table[_CURRENCIES["base"]]["default_income"]
    row = table[currency]
    return _Currency(
        code=currency,
        symbol=row["symbol"],
        decimals=int(row["decimals"]),
        scale=row["default_income"] / base_income,
        default_income=float(row["default_income"]),
        default_expense=float(row["default_expense"]),
    )


def _validate_country(country: str) -> str:
    key = country.lower()
    if key not in COUNTRY_TO_REGION:
        raise SystemExit(f"Unknown country '{country}'. Choose from: {', '.join(COUNTRY_TO_REGION)}")
    return key


def _validate_currency(currency: str) -> str:
    key = currency.lower()
    if key not in _CURRENCIES["currencies"]:
        raise SystemExit(
            f"Unknown currency '{currency}'. Choose from: {', '.join(_CURRENCIES['currencies'])}"
        )
    return key


@dataclass(frozen=True)
class ProfileSpec:
    name: str
    description: str
    merchant_weights: dict[str, float]
    debit_person_prob: float
    credit_extra_chance: float
    credit_extra_split_range: tuple[float, float]
    credit_extra_person_prob: float
    debit_count_divisor_range: tuple[float, float]
    amount_small_range: tuple[float, float]
    amount_medium_range: tuple[float, float]
    amount_large_range: tuple[float, float]
    tier_weights: tuple[float, float, float]
    outlier_boost: float


PROFILE_SPECS = {
    "salary-heavy": ProfileSpec(
        name="salary-heavy",
        description="Salary-like inflows, mostly merchant debits, low person-to-person movement.",
        merchant_weights={
            "groceries": 3.0,
            "food": 2.2,
            "transport": 1.8,
            "shopping": 1.2,
            "bills": 2.0,
            "health": 1.0,
            "fuel": 1.0,
            "entertainment": 0.8,
            "finance": 0.7,
            "other": 0.6,
        },
        debit_person_prob=0.10,
        credit_extra_chance=0.20,
        credit_extra_split_range=(0.72, 0.88),
        credit_extra_person_prob=0.72,
        debit_count_divisor_range=(1800, 4600),
        amount_small_range=(90, 650),
        amount_medium_range=(650, 3200),
        amount_large_range=(3200, 16000),
        tier_weights=(0.22, 0.66, 0.12),
        outlier_boost=2.8,
    ),
    "student": ProfileSpec(
        name="student",
        description="Smaller spends, more food/transport/entertainment, more peer reimbursements.",
        merchant_weights={
            "groceries": 1.0,
            "food": 3.2,
            "transport": 2.4,
            "shopping": 0.9,
            "bills": 0.8,
            "health": 0.6,
            "fuel": 0.4,
            "entertainment": 2.8,
            "finance": 0.4,
            "other": 0.7,
        },
        debit_person_prob=0.24,
        credit_extra_chance=0.40,
        credit_extra_split_range=(0.60, 0.82),
        credit_extra_person_prob=0.84,
        debit_count_divisor_range=(900, 2200),
        amount_small_range=(40, 350),
        amount_medium_range=(350, 1800),
        amount_large_range=(1800, 7000),
        tier_weights=(0.38, 0.52, 0.10),
        outlier_boost=2.2,
    ),
    "family-expense": ProfileSpec(
        name="family-expense",
        description="Groceries, medicines, fuel and bills dominate; some family transfers and travel.",
        merchant_weights={
            "groceries": 3.6,
            "food": 1.6,
            "transport": 1.3,
            "shopping": 1.0,
            "bills": 2.8,
            "health": 2.2,
            "fuel": 2.6,
            "entertainment": 0.7,
            "finance": 0.9,
            "other": 0.9,
        },
        debit_person_prob=0.16,
        credit_extra_chance=0.28,
        credit_extra_split_range=(0.68, 0.86),
        credit_extra_person_prob=0.60,
        debit_count_divisor_range=(1500, 3600),
        amount_small_range=(80, 500),
        amount_medium_range=(500, 2600),
        amount_large_range=(2600, 12000),
        tier_weights=(0.26, 0.62, 0.12),
        outlier_boost=2.5,
    ),
}


@dataclass(frozen=True)
class RunConfig:
    start_date: date
    end_date: date
    monthly_income: float
    monthly_expense: float
    seed: Optional[int]
    profile: str
    bank: str
    country: str = DEFAULT_COUNTRY
    currency: str = "inr"


def _parse_amount(raw: str, label: str) -> float:
    try:
        value = float(raw)
    except ValueError as exc:
        raise argparse.ArgumentTypeError(f"{label} must be numeric") from exc
    if value <= 0:
        raise argparse.ArgumentTypeError(f"{label} must be greater than zero")
    return value


def _parse_date(raw: str, label: str) -> date:
    try:
        return datetime.strptime(raw, "%Y-%m-%d").date()
    except ValueError as exc:
        raise argparse.ArgumentTypeError(
            f"{label} must use YYYY-MM-DD"
        ) from exc


def _parse_range(raw: str) -> tuple[date, date]:
    if ":" not in raw:
        raise argparse.ArgumentTypeError(
            "--range must use START:END in YYYY-MM-DD format"
        )
    start_raw, end_raw = raw.split(":", 1)
    start = _parse_date(start_raw, "range start")
    end = _parse_date(end_raw, "range end")
    if start > end:
        raise argparse.ArgumentTypeError("range start must be <= range end")
    return start, end


def _prompt(message: str, *, default: str | None = None) -> str:
    suffix = f" [{default}]" if default is not None else ""
    value = input(f"{message}{suffix}: ").strip()
    return value or (default or "")


def _prompt_float(message: str, default: float) -> float:
    while True:
        raw = _prompt(message, default=f"{default:.2f}")
        try:
            return _parse_amount(raw, message)
        except argparse.ArgumentTypeError as exc:
            print(exc, file=sys.stderr)


def _prompt_date(message: str, default: date) -> date:
    while True:
        raw = _prompt(message, default=default.isoformat())
        try:
            return _parse_date(raw, message)
        except argparse.ArgumentTypeError as exc:
            print(exc, file=sys.stderr)


def _prompt_int(message: str) -> Optional[int]:
    raw = _prompt(message, default="")
    if not raw:
        return None
    try:
        return int(raw)
    except ValueError:
        print(f"{message} must be an integer", file=sys.stderr)
        return _prompt_int(message)


def _choose_period(prompt_enabled: bool, provided: str | None) -> str:
    if provided:
        return provided
    if not prompt_enabled:
        return DEFAULT_PERIOD
    print("Select a period mode:")
    print("  1) weekly")
    print("  2) monthly")
    print("  3) quarterly")
    print("  4) annually")
    print("  5) financial year")
    print("  6) custom range")
    while True:
        choice = _prompt("Period", default="4")
        mapping = {
            "1": "weekly",
            "2": "monthly",
            "3": "quarterly",
            "4": "annually",
            "5": "fiscal",
            "6": "custom",
            "weekly": "weekly",
            "monthly": "monthly",
            "quarterly": "quarterly",
            "annually": "annually",
            "annual": "annually",
            "fiscal": "fiscal",
            "fy": "fiscal",
            "financial": "fiscal",
            "custom": "custom",
        }
        selected = mapping.get(choice.lower())
        if selected:
            return selected
        print("Please choose 1-6, or one of the named options.")


def _choose_profile(prompt_enabled: bool, provided: str | None) -> str:
    if provided:
        value = provided.strip().lower()
        if value not in PROFILE_SPECS:
            raise SystemExit(
                f"Unknown profile '{provided}'. Choose one of: "
                + ", ".join(PROFILE_SPECS)
            )
        return value
    if not prompt_enabled:
        return DEFAULT_PROFILE
    print("Select a profile:")
    for idx, (name, spec) in enumerate(PROFILE_SPECS.items(), start=1):
        print(f"  {idx}) {name} - {spec.description}")
    options = {str(idx): name for idx, name in enumerate(PROFILE_SPECS, start=1)}
    while True:
        choice = _prompt("Profile", default="1")
        if choice.lower() in PROFILE_SPECS:
            return choice.lower()
        selected = options.get(choice)
        if selected:
            return selected
        print("Please choose one of the listed profile numbers or names.")


def _choose_bank(prompt_enabled: bool, provided: str | None) -> str:
    if provided:
        value = provided.strip()
        if value.lower() == "random":
            return DEFAULT_BANK
        canonical = next((name for name in ACCOUNT_BANKS if name.lower() == value.lower()), None)
        if canonical is None:
            raise SystemExit(
                f"Unknown bank '{provided}'. Choose one of: "
                + ", ".join(BANK_INPUTS)
            )
        return canonical
    if not prompt_enabled:
        return DEFAULT_BANK
    print("Select a bank (or random):")
    for idx, name in enumerate(BANK_INPUTS, start=1):
        print(f"  {idx}) {name}")
    options = {str(idx): name for idx, name in enumerate(BANK_INPUTS, start=1)}
    while True:
        choice = _prompt("Bank", default="random")
        if choice.lower() == "random":
            return DEFAULT_BANK
        canonical = next((name for name in ACCOUNT_BANKS if name.lower() == choice.lower()), None)
        if canonical:
            return canonical
        selected = options.get(choice)
        if selected:
            return selected
        print("Please choose one of the listed bank numbers or names.")


def _rolling_start(end_date: date, period: str) -> date:
    days = {"weekly": 6, "monthly": 29, "quarterly": 89, "annually": 364}[period]
    return end_date - timedelta(days=days)


def _fiscal_window(today: date, country: str) -> tuple[date, date]:
    """The most recent COMPLETE fiscal year for the country, as (start, end).

    India runs Apr 1 → Mar 31; elsewhere (US / default) it is the calendar / tax
    year, Jan 1 → Dec 31. "Most recent complete" so the statement is a full twelve
    months, not a partial year-to-date.
    """
    if country == "india":
        if (today.month, today.day) >= (4, 1):
            return date(today.year - 1, 4, 1), date(today.year, 3, 31)
        return date(today.year - 2, 4, 1), date(today.year - 1, 3, 31)
    return date(today.year - 1, 1, 1), date(today.year - 1, 12, 31)


def _month_windows(start: date, end: date) -> list[tuple[date, date]]:
    windows: list[tuple[date, date]] = []
    cursor = date(start.year, start.month, 1)
    while cursor <= end:
        if cursor.month == 12:
            next_month = date(cursor.year + 1, 1, 1)
        else:
            next_month = date(cursor.year, cursor.month + 1, 1)
        window_start = max(start, cursor)
        window_end = min(end, next_month - timedelta(days=1))
        if window_start <= window_end:
            windows.append((window_start, window_end))
        cursor = next_month
    return windows


def _pick_weekday(rng: random.Random, start: date, end: date) -> date:
    candidates = []
    current = start
    while current <= end:
        candidates.append(current)
        current += timedelta(days=1)
    weekdays = [d for d in candidates if d.weekday() < 5]
    pool = weekdays or candidates
    return rng.choice(pool)


def _pick_date(rng: random.Random, start: date, end: date) -> date:
    current = start + timedelta(days=rng.randint(0, (end - start).days))
    return current


def _pick_time(rng: random.Random) -> str:
    hour = rng.choices(
        population=[8, 9, 11, 13, 15, 18, 20, 22],
        weights=[2, 5, 8, 7, 8, 6, 4, 2],
        k=1,
    )[0]
    minute = rng.randint(0, 59)
    second = rng.randint(0, 59)
    return f"{hour:02d}:{minute:02d}:{second:02d}"


def _build_person_pool(
    rng: random.Random, first_names: list[str], last_names: list[str], size: int = 40
) -> list[str]:
    names: list[str] = []
    seen: set[str] = set()
    while len(names) < size:
        candidate = f"{rng.choice(first_names)} {rng.choice(last_names)}"
        if candidate not in seen:
            seen.add(candidate)
            names.append(candidate)
    return names


def _account_header(
    rng: random.Random,
    bank: str,
    bank_names: list[str],
    bank_headers: dict[str, str],
) -> str:
    bank_name = rng.choice(bank_names) if bank == DEFAULT_BANK else bank
    suffix = "".join(str(rng.randint(0, 9)) for _ in range(4))
    template = bank_headers.get(bank_name, "{bank} A/C XX{suffix}")
    return template.format(bank=bank_name, suffix=suffix)


def _txn_id(rng: random.Random, current_date: date, index: int) -> str:
    return f"TXN{current_date.strftime('%Y%m%d')}{index:03d}{rng.randint(10, 99)}"


def _utr_no(rng: random.Random, current_date: date, index: int) -> str:
    return f"UTR{current_date.strftime('%Y%m%d')}{index:03d}{rng.randint(1000, 9999)}"


def _detail_block(
    *,
    direction: str,
    counterparty: str,
    txn_id: str,
    utr_no: str,
    account_header: str,
) -> list[str]:
    if direction == "debit":
        first = f"Paid to {counterparty}"
        fourth = f"Paid by {account_header}"
    else:
        first = f"Received from {counterparty}"
        fourth = f"Credited to {account_header}"
    return [first, f"Transaction ID: {txn_id}", f"UTR No.: {utr_no}", fourth]


def _choice_weighted(rng: random.Random, items: list[str], weights: list[float]) -> str:
    return rng.choices(items, weights=weights, k=1)[0]


def _generate_amounts(
    rng: random.Random,
    target: float,
    count: int,
    *,
    profile: ProfileSpec,
    decimals: int = 2,
) -> list[float]:
    if count <= 0:
        return []

    raw: list[float] = []
    for _ in range(count):
        tier = rng.choices(
            population=["small", "medium", "large"],
            weights=list(profile.tier_weights),
            k=1,
        )[0]
        if tier == "small":
            value = rng.uniform(*profile.amount_small_range)
        elif tier == "medium":
            value = rng.uniform(*profile.amount_medium_range)
        else:
            value = rng.uniform(*profile.amount_large_range)
        raw.append(value)

    if count >= 6:
        for idx in rng.sample(range(count), k=max(1, count // 8)):
            raw[idx] *= rng.uniform(profile.outlier_boost * 0.6, profile.outlier_boost * 1.4)

    scale = target / sum(raw)
    amounts = [round(value * scale, decimals) for value in raw]
    # Spread the rounding residual one minor-unit at a time across rows rather
    # than dumping the whole remainder onto the last amount (which can visibly
    # skew one row). The total residual is only a few minor units, so it stays
    # subtle. ``unit`` is the currency's smallest unit (paise, cents, whole yen).
    unit = 10 ** (-decimals)
    residual_units = round((target - sum(amounts)) / unit)
    step = unit if residual_units > 0 else -unit
    for offset in range(abs(residual_units)):
        idx = offset % len(amounts)
        amounts[idx] = round(amounts[idx] + step, decimals)
    return amounts


# Recurring monthly commitments, carved from the expense budget so a downstream
# recurring-inference engine sees stable series. (category, fraction of monthly
# expense, day-of-month). Each fraction stays under its category's basket share.
_RECURRING_SPECS = [
    ("bills", 0.04, 5),           # a monthly utility / telecom bill
    ("entertainment", 0.012, 2),  # subscription
    ("entertainment", 0.010, 3),  # subscription
    ("finance", 0.05, 7),         # an EMI / loan instalment
]


def _recurring_plan(
    rng: random.Random,
    *,
    region: "_ResolvedRegion",
    currency: "_Currency",
    monthly_expense: float,
) -> list[dict]:
    """Fixed monthly commitments (merchant + amount + day), stable across the run
    so recurring inference fires. Each is carved from its category's budget."""
    plan: list[dict] = []
    for category, fraction, day in _RECURRING_SPECS:
        pool = region.merchant_groups.get(category)
        amount = round(monthly_expense * fraction, currency.decimals)
        if not pool or amount <= 0:
            continue
        plan.append(
            {"category": category, "merchant": rng.choice(pool), "amount": amount, "day": day}
        )
    return plan


def _recurring_date(day: int, segment_start: date, segment_end: date):
    """The recurring day resolved within this (single-month) segment, or None if
    it falls outside the window."""
    import calendar

    last = calendar.monthrange(segment_start.year, segment_start.month)[1]
    candidate = date(segment_start.year, segment_start.month, min(day, last))
    return candidate if segment_start <= candidate <= segment_end else None


def _plan_merchant_debits(
    rng: random.Random,
    *,
    merchant_expense: float,
    merchant_count: int,
    region: "_ResolvedRegion",
    currency: "_Currency",
    profile: ProfileSpec,
    reserved: dict[str, float] | None = None,
    exclude: set[str] | None = None,
) -> list[tuple[str, float]]:
    """Split merchant debits across categories: **amount** share per category
    tracks the region's expenditure ``basket`` (so category totals are realistic),
    **count** tracks the profile's frequency weights (many small food txns, a few
    large finance/EMI ones). Returns ``(merchant, amount)`` pairs.
    """
    categories = [c for c in region.basket if region.merchant_groups.get(c)]
    if not categories or merchant_count <= 0 or merchant_expense <= 0:
        return []
    freq = profile.merchant_weights
    freq_sum = sum(freq.get(c, 0.5) for c in categories) or 1.0
    counts = {c: int(round(merchant_count * freq.get(c, 0.5) / freq_sum)) for c in categories}
    present = [c for c in categories if counts[c] > 0]
    if not present:  # tiny segment — collapse to the single most frequent category
        top = max(categories, key=lambda c: freq.get(c, 0.5))
        present, counts[top] = [top], merchant_count
    reserved = reserved or {}
    exclude = exclude or set()
    basket_sum = sum(region.basket[c] for c in present) or 1.0
    lines: list[tuple[str, float]] = []
    for category in present:
        budget = merchant_expense * region.basket[category] / basket_sum - reserved.get(category, 0.0)
        if budget <= 0:  # recurring commitments already cover this category's share
            continue
        amounts = _generate_amounts(
            rng, budget, counts[category], profile=profile, decimals=currency.decimals
        )
        # Keep recurring merchants out of random draws so their series stay clean.
        pool = [m for m in region.merchant_groups[category] if m not in exclude]
        pool = pool or list(region.merchant_groups[category])
        lines.extend((rng.choice(pool), amount) for amount in amounts)
    return lines


def _generate_month_segment(
    rng: random.Random,
    *,
    segment_start: date,
    segment_end: date,
    account_header: str,
    person_pool: list[str],
    monthly_income: float,
    monthly_expense: float,
    region: "_ResolvedRegion",
    currency: "_Currency",
    profile: ProfileSpec,
    recurring: list[dict],
) -> list[dict[str, object]]:
    days = (segment_end - segment_start).days + 1
    proration = days / 30.4375
    income_target = max(0.01, monthly_income * proration)
    expense_target = max(0.01, monthly_expense * proration)

    txns: list[dict[str, object]] = []

    # Credits are intentionally few: mostly one salary-style inflow and, only
    # sometimes, a second peer refund / reimbursement line.
    credit_count = 1 + int(rng.random() < profile.credit_extra_chance)
    credit_amounts: list[float]
    if credit_count == 1:
        credit_amounts = [round(income_target, currency.decimals)]
    else:
        first = round(income_target * rng.uniform(*profile.credit_extra_split_range), currency.decimals)
        second = round(max(0.01, income_target - first), currency.decimals)
        credit_amounts = [first, second]

    # Salary inflow: a company name + a SALARY token (NOT a person), so income
    # is separable from P2P credits / merchant refunds at categorization time.
    salary_source = f"{rng.choice(region.companies)} {region.salary_token}"
    peer_source = rng.choice(person_pool)
    refund_source = rng.choice(region.merchants)
    another_peer = rng.choice(
        [name for name in person_pool if name != peer_source] or person_pool
    )
    credit_dates = sorted(
        _pick_weekday(rng, segment_start, min(segment_end, segment_start + timedelta(days=6)))
        for _ in range(credit_count)
    )
    for index, amount in enumerate(credit_amounts, start=1):
        if index == 1:
            counterparty = salary_source
        else:
            merchant_refund_weight = 0.12 if profile.name == "salary-heavy" else 0.10
            peer_weight = profile.credit_extra_person_prob
            other_peer_weight = max(0.0, 1.0 - peer_weight - merchant_refund_weight)
            counterparty = _choice_weighted(
                rng,
                [peer_source, refund_source, another_peer],
                [peer_weight, merchant_refund_weight, other_peer_weight],
            )
        txn_day = credit_dates[min(index - 1, len(credit_dates) - 1)]
        txn_id = _txn_id(rng, txn_day, index)
        utr_no = _utr_no(rng, txn_day, index)
        txns.append(
            {
                "date": txn_day.isoformat(),
                "time": _pick_time(rng),
                "Transaction Detail": _detail_block(
                    direction="credit",
                    counterparty=counterparty,
                    txn_id=txn_id,
                    utr_no=utr_no,
                    account_header=account_header,
                ),
                "type": "credit",
                "amount": amount,
                "_sort_key": f"{txn_day.isoformat()} {index:03d} {index:03d}",
            }
        )

    # Consumption debits: amount split across categories by the region's basket,
    # count by the profile's frequency weights, plus a P2P person-transfer slice.
    debit_target = max(0.01, expense_target * rng.uniform(0.96, 1.04))
    # The divisor (an implicit average txn size) scales with the currency so the
    # transaction *count* stays comparable across currencies.
    divisor = rng.uniform(*profile.debit_count_divisor_range) * currency.scale
    total_count = max(8, int(round(debit_target / divisor)))
    person_count = int(round(total_count * profile.debit_person_prob))
    merchant_count = max(1, total_count - person_count)
    merchant_expense = debit_target * (1 - profile.debit_person_prob)
    person_expense = max(0.0, debit_target - merchant_expense)

    # Recurring commitments (fixed merchant / amount / day), carved from budgets.
    reserved: dict[str, float] = {}
    recurring_lines: list[tuple[date, str, float]] = []
    for item in recurring:
        day = _recurring_date(item["day"], segment_start, segment_end)
        if day is None:
            continue
        reserved[item["category"]] = reserved.get(item["category"], 0.0) + item["amount"]
        recurring_lines.append((day, item["merchant"], item["amount"]))
    recurring_merchants = {item["merchant"] for item in recurring}

    debit_lines = _plan_merchant_debits(
        rng,
        merchant_expense=merchant_expense,
        merchant_count=merchant_count,
        region=region,
        currency=currency,
        profile=profile,
        reserved=reserved,
        exclude=recurring_merchants,
    )
    if person_count > 0 and person_expense > 0:
        person_amounts = _generate_amounts(
            rng, person_expense, person_count, profile=profile, decimals=currency.decimals
        )
        debit_lines.extend((rng.choice(person_pool), amount) for amount in person_amounts)

    # Recurring rows keep their fixed day; the rest get a (weekday-biased) date.
    dated_lines: list[tuple["date | None", str, float]] = [
        (day, merchant, amount) for (day, merchant, amount) in recurring_lines
    ]
    dated_lines += [(None, counterparty, amount) for (counterparty, amount) in debit_lines]
    for index, (fixed_day, counterparty, amount) in enumerate(dated_lines, start=1):
        if fixed_day is not None:
            txn_day = fixed_day
        else:
            txn_day = _pick_date(rng, segment_start, segment_end)
            if txn_day.weekday() < 5 and rng.random() < 0.75:
                txn_day = _pick_weekday(rng, segment_start, segment_end)
        txn_id = _txn_id(rng, txn_day, 100 + index)
        utr_no = _utr_no(rng, txn_day, 100 + index)
        txns.append(
            {
                "date": txn_day.isoformat(),
                "time": _pick_time(rng),
                "Transaction Detail": _detail_block(
                    direction="debit",
                    counterparty=counterparty,
                    txn_id=txn_id,
                    utr_no=utr_no,
                    account_header=account_header,
                ),
                "type": "debit",
                "amount": amount,
                "_sort_key": f"{txn_day.isoformat()} {100 + index:03d} {index:03d}",
            }
        )

    return txns


def _generate_records(config: RunConfig) -> list[dict[str, object]]:
    rng = random.Random(config.seed)
    region = _resolve_region(config.country)
    currency = _resolve_currency(config.currency)
    person_pool = _build_person_pool(rng, region.first_names, region.last_names, size=40)
    profile = PROFILE_SPECS[config.profile]
    account_header = _account_header(rng, config.bank, region.bank_names, region.bank_headers)
    recurring = _recurring_plan(
        rng, region=region, currency=currency, monthly_expense=config.monthly_expense
    )

    records: list[dict[str, object]] = []
    for segment_start, segment_end in _month_windows(config.start_date, config.end_date):
        records.extend(
            _generate_month_segment(
                rng,
                segment_start=segment_start,
                segment_end=segment_end,
                account_header=account_header,
                person_pool=person_pool,
                monthly_income=config.monthly_income,
                monthly_expense=config.monthly_expense,
                region=region,
                currency=currency,
                profile=profile,
                recurring=recurring,
            )
        )

    records.sort(key=lambda row: (row["date"], row["time"], row["_sort_key"]))
    for row in records:
        row.pop("_sort_key", None)
    return records


def _build_meta(config: RunConfig, records: list[dict[str, object]]) -> dict:
    """The reproducibility/provenance header for a generated statement."""
    debit_count = sum(1 for row in records if row["type"] == "debit")
    return {
        "generator_version": GENERATOR_VERSION,
        "seed": config.seed,
        "start_date": config.start_date.isoformat(),
        "end_date": config.end_date.isoformat(),
        "profile": config.profile,
        "bank": config.bank,
        "country": config.country,
        "currency": config.currency,
        "monthly_income": config.monthly_income,
        "monthly_expense": config.monthly_expense,
        "row_count": len(records),
        "debit_count": debit_count,
        "credit_count": len(records) - debit_count,
    }


@dataclass(frozen=True)
class Statement:
    """A generated statement held in memory: structured ``records`` + ``meta``.

    The library return value (see :func:`generate`). Serialize with
    :meth:`to_json` / :meth:`to_csv`, or persist all three files with
    :meth:`write`. Purely in-memory — no file I/O until you ask for it — so it
    runs anywhere, including in-browser (Pyodide).
    """

    records: list[dict]
    meta: dict

    def to_json(self) -> str:
        return json.dumps(self.records, indent=2, ensure_ascii=False) + "\n"

    def meta_json(self) -> str:
        return json.dumps(self.meta, indent=2) + "\n"

    def to_csv(self) -> str:
        buf = io.StringIO()
        _write_csv_rows(buf, self.records)
        return buf.getvalue()

    def write(self, output_dir) -> Path:
        """Write ``statement.json`` / ``statement.csv`` / ``meta.json`` into ``output_dir``."""
        output_dir = Path(output_dir).expanduser().resolve()
        output_dir.mkdir(parents=True, exist_ok=True)
        with (output_dir / "statement.csv").open("w", newline="", encoding="utf-8") as handle:
            _write_csv_rows(handle, self.records)
        (output_dir / "statement.json").write_text(self.to_json(), encoding="utf-8")
        (output_dir / "meta.json").write_text(self.meta_json(), encoding="utf-8")
        return output_dir


def _config_from_options(
    *,
    seed: Optional[int] = None,
    start: str | None = None,
    end: str | None = None,
    range: str | None = None,
    period: str | None = None,
    profile: str | None = None,
    bank: str | None = None,
    income: float | None = None,
    expense: float | None = None,
    country: str | None = None,
    currency: str | None = None,
    today: date | None = None,
) -> RunConfig:
    """Resolve library options into a :class:`RunConfig` — non-interactive, pure."""
    today = today or datetime.now().date()
    country_key = _validate_country(country) if country else DEFAULT_COUNTRY
    if range:
        start_date, end_date = _parse_range(range)
    elif start or end:
        if not (start and end):
            raise ValueError("both `start` and `end` are required together")
        start_date = _parse_date(start, "start")
        end_date = _parse_date(end, "end")
        if start_date > end_date:
            raise ValueError("`start` must be <= `end`")
    else:
        resolved_period = _choose_period(False, period)
        if resolved_period == "custom":
            start_date, end_date = today - timedelta(days=29), today
        elif resolved_period in ("fiscal", "fy", "financial"):
            start_date, end_date = _fiscal_window(today, country_key)
        else:
            end_date = today
            start_date = _rolling_start(end_date, resolved_period)
    currency_key = _validate_currency(currency) if currency else COUNTRY_DEFAULT_CURRENCY[country_key]
    cur = _resolve_currency(currency_key)
    return RunConfig(
        start_date=start_date,
        end_date=end_date,
        monthly_income=cur.default_income if income is None else income,
        monthly_expense=cur.default_expense if expense is None else expense,
        seed=seed,
        profile=_choose_profile(False, profile),
        bank=_choose_bank(False, bank),
        country=country_key,
        currency=currency_key,
    )


def generate(
    *,
    seed: Optional[int] = None,
    start: str | None = None,
    end: str | None = None,
    range: str | None = None,
    period: str | None = None,
    profile: str | None = None,
    bank: str | None = None,
    income: float | None = None,
    expense: float | None = None,
    country: str | None = None,
    currency: str | None = None,
    today: date | None = None,
) -> Statement:
    """Generate a synthetic statement in memory — the library entry point.

    Options mirror the CLI flags (``seed``, ``start``/``end`` or ``range`` or a
    rolling ``period``, ``profile``, ``bank``, ``income``, ``expense``,
    ``country``, ``currency``); all have sensible defaults. ``country`` selects
    the merchant/person/bank set (``india`` / ``usa``); ``currency`` sets the
    money scale and defaults from the country. A fixed ``seed`` yields
    **byte-identical** output for the same options. ``today`` overrides the
    reference date for rolling periods (deterministic tests/screenshots).
    Returns a :class:`Statement`.

    The CLI (:func:`main`) and any programmatic caller (a consumer app, the
    in-browser Pyodide UI) share this one path, so they can never diverge.
    """
    config = _config_from_options(
        seed=seed, start=start, end=end, range=range, period=period,
        profile=profile, bank=bank, income=income, expense=expense,
        country=country, currency=currency, today=today,
    )
    records = _generate_records(config)
    return Statement(records=records, meta=_build_meta(config, records))


def _write_csv_rows(handle, records: Iterable[dict[str, object]]) -> None:
    writer = csv.DictWriter(
        handle, fieldnames=["date", "time", "Transaction Detail", "type", "amount"]
    )
    writer.writeheader()
    for row in records:
        writer.writerow(
            {
                "date": row["date"],
                "time": row["time"],
                "Transaction Detail": json.dumps(row["Transaction Detail"], ensure_ascii=False),
                "type": row["type"],
                "amount": f"{float(row['amount']):.2f}",
            }
        )


def _write_csv(path: Path, records: Iterable[dict[str, object]]) -> None:
    with path.open("w", newline="", encoding="utf-8") as handle:
        _write_csv_rows(handle, records)


def _write_json(path: Path, records: list[dict[str, object]]) -> None:
    path.write_text(json.dumps(records, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")


def _write_meta(path: Path, config: RunConfig, records: list[dict[str, object]]) -> None:
    """Persist the run parameters so a statement can be reproduced/verified later."""
    path.write_text(json.dumps(_build_meta(config, records), indent=2) + "\n", encoding="utf-8")


def _print_summary(config: RunConfig, records: list[dict[str, object]], output_dir: Path) -> None:
    debit_total = sum(float(row["amount"]) for row in records if row["type"] == "debit")
    credit_total = sum(float(row["amount"]) for row in records if row["type"] == "credit")
    debit_count = sum(1 for row in records if row["type"] == "debit")
    credit_count = len(records) - debit_count
    print(f"Wrote {len(records)} rows to {output_dir}")
    print(f"  CSV : {output_dir / 'statement.csv'}")
    print(f"  JSON: {output_dir / 'statement.json'}")
    print(
        "  Mix : "
        f"{debit_count} debit / {credit_count} credit, "
        f"debit total={debit_total:.2f}, credit total={credit_total:.2f}"
    )
    print(
        f"  Range: {config.start_date.isoformat()} -> {config.end_date.isoformat()}, "
        f"profile={config.profile}, bank={config.bank}, "
        f"country={config.country}, currency={config.currency}"
    )
    print(f"  Seed : {config.seed if config.seed is not None else 'random (not reproducible)'}")


def _build_config(args: argparse.Namespace) -> RunConfig:
    today = datetime.now().date()
    explicit_range = bool(args.range or (args.start and args.end))
    period = "custom" if explicit_range else _choose_period(not args.yes, args.period)
    profile = _choose_profile(not args.yes, args.profile)
    bank = _choose_bank(not args.yes, args.bank)
    country = _validate_country(args.country) if args.country else DEFAULT_COUNTRY
    currency = _validate_currency(args.currency) if args.currency else COUNTRY_DEFAULT_CURRENCY[country]
    cur = _resolve_currency(currency)

    if args.range:
        start_date, end_date = _parse_range(args.range)
    elif args.start or args.end:
        if not (args.start and args.end):
            raise SystemExit("Both --start and --end are required together")
        start_date = _parse_date(args.start, "--start")
        end_date = _parse_date(args.end, "--end")
        if start_date > end_date:
            raise SystemExit("--start must be <= --end")
    elif period == "custom":
        if args.yes:
            start_date = today - timedelta(days=29)
            end_date = today
        else:
            start_date = _prompt_date("Custom range start", today - timedelta(days=29))
            end_date = _prompt_date("Custom range end", today)
    elif period in ("fiscal", "fy", "financial"):
        start_date, end_date = _fiscal_window(today, country)
    else:
        end_date = today
        start_date = _rolling_start(end_date, period)

    if args.income is not None:
        monthly_income = args.income
    elif args.yes:
        monthly_income = cur.default_income
    else:
        monthly_income = _prompt_float("Average monthly income", cur.default_income)

    if args.expense is not None:
        monthly_expense = args.expense
    elif args.yes:
        monthly_expense = cur.default_expense
    else:
        monthly_expense = _prompt_float("Average monthly expense", cur.default_expense)

    if args.seed is not None:
        seed = args.seed
    elif args.yes:
        seed = None
    else:
        seed = _prompt_int("Optional seed (blank for random)")

    return RunConfig(
        start_date=start_date,
        end_date=end_date,
        monthly_income=monthly_income,
        monthly_expense=monthly_expense,
        seed=seed,
        profile=profile,
        bank=bank,
        country=country,
        currency=currency,
    )


def _resolve_output_dir(args: argparse.Namespace) -> Path:
    """Where the CLI writes — an explicit ``--output-dir`` or a timestamped run folder."""
    if args.output_dir:
        return Path(args.output_dir).expanduser().resolve()
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    return DEFAULT_OUTPUT_ROOT / stamp


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Generate synthetic UPI / bank statement records as CSV and JSON."
    )
    parser.add_argument("-y", "--yes", action="store_true", help="Use defaults without prompting")
    parser.add_argument(
        "--period",
        choices=["weekly", "monthly", "quarterly", "annually", "fiscal", "custom"],
        help="Period to generate when no explicit date range is provided "
        "(fiscal = most recent complete financial year, country-aware)",
    )
    parser.add_argument(
        "--profile",
        choices=sorted(PROFILE_SPECS),
        help="Preset mix profile that tunes merchant/person balance and amount patterns",
    )
    parser.add_argument(
        "--bank",
        choices=BANK_INPUTS,
        help="Account bank to stamp into the statement header",
    )
    parser.add_argument(
        "--country",
        choices=sorted(COUNTRY_TO_REGION),
        help="Country for merchants / persons / banks (default: india)",
    )
    parser.add_argument(
        "--currency",
        choices=sorted(_CURRENCIES["currencies"]),
        help="Currency for amount scaling (default: the country's currency)",
    )
    parser.add_argument(
        "--range",
        help="Explicit date range in START:END form, both YYYY-MM-DD",
    )
    parser.add_argument("--start", help="Explicit start date, YYYY-MM-DD")
    parser.add_argument("--end", help="Explicit end date, YYYY-MM-DD")
    parser.add_argument("--income", type=lambda raw: _parse_amount(raw, "--income"))
    parser.add_argument("--expense", type=lambda raw: _parse_amount(raw, "--expense"))
    parser.add_argument("--seed", type=int, help="Optional RNG seed for reproducible output")
    parser.add_argument(
        "--output-dir",
        help="Write files into this directory instead of a timestamped run folder",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    config = _build_config(args)  # interactive/CLI resolution
    output_dir = _resolve_output_dir(args)
    records = _generate_records(config)
    statement = Statement(records=records, meta=_build_meta(config, records))
    statement.write(output_dir)  # same in-memory path as generate() → identical files
    _print_summary(config, records, output_dir)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
