"""synthetic-statement — generate realistic synthetic bank & UPI statements.

Public surface (thin, over the existing code):

    from synthetic_statement import statement_generator
    statement_generator.main(["--yes", "--seed", "42", "--output-dir", "out"])

or via the console script / module runner:

    synthetic-statement --yes --seed 42 --output-dir out
    python -m synthetic_statement --yes --seed 42 --output-dir out

The clean ``options -> statement`` library API is roadmap task 02; this package
just makes the current CLI importable + installable.
"""

__all__ = ["statement_generator", "render_statement", "verify_statement"]
