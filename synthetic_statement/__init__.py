"""synthetic-statement — generate realistic synthetic bank & UPI statements.

Library API (the clean ``options -> statement`` surface):

    from synthetic_statement import generate
    stmt = generate(seed=42, period="monthly", profile="family-expense")
    data = stmt.records          # list of structured txn dicts (in memory)
    stmt.to_json()               # -> str      stmt.to_csv() -> str
    stmt.write("out")            # -> statement.json / statement.csv / meta.json

or via the console script / module runner:

    synthetic-statement --yes --seed 42 --output-dir out
    python -m synthetic_statement --yes --seed 42 --output-dir out

The CLI and ``generate()`` share one path, so their output never diverges. A
fixed ``seed`` gives byte-identical results.
"""

from .statement_generator import InjectedRow, Statement, generate

__all__ = [
    "generate",
    "Statement",
    "InjectedRow",
    "statement_generator",
    "render_statement",
    "verify_statement",
]
