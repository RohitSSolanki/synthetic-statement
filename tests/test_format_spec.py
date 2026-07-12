"""The emitted JSON must validate against the published format spec (task 05).

Keeps spec/statement.schema.json executable — it can't silently drift from the
generator's output. Run with the local venv:

    .venv/bin/pytest tests/test_format_spec.py
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from synthetic_statement import generate  # noqa: E402

SCHEMA_PATH = Path(__file__).resolve().parent.parent / "spec" / "statement.schema.json"


def test_schema_file_is_valid_json():
    schema = json.loads(SCHEMA_PATH.read_text(encoding="utf-8"))
    assert schema["type"] == "array"


@pytest.mark.parametrize("profile", ["salary-heavy", "family-expense", "student"])
def test_generated_records_validate_against_schema(profile):
    jsonschema = pytest.importorskip("jsonschema")
    schema = json.loads(SCHEMA_PATH.read_text(encoding="utf-8"))
    records = generate(
        seed=42, start="2026-01-01", end="2026-03-31", profile=profile
    ).records
    assert records
    jsonschema.validate(records, schema)  # raises jsonschema.ValidationError on drift


def test_to_json_output_validates():
    jsonschema = pytest.importorskip("jsonschema")
    schema = json.loads(SCHEMA_PATH.read_text(encoding="utf-8"))
    payload = json.loads(generate(seed=7, start="2026-02-01", end="2026-02-28").to_json())
    jsonschema.validate(payload, schema)
