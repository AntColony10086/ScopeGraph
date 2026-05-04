"""Tests for the predefined Cypher template catalogue.

The module exposes a single public surface — :data:`CYPHER_TEMPLATES`, a list
of dicts with ``id``, ``description``, ``examples``, ``cypher``, and
``params`` keys. These tests verify the catalogue is structurally consistent,
covers the expected query families, and that every Cypher body is at least
syntactically plausible (non-empty, balanced parameter usage).
"""
from __future__ import annotations

import re

import pytest

from app.knowledge.cypher_templates import CYPHER_TEMPLATES


# ---------------------------------------------------------------------------
# Catalogue-level invariants
# ---------------------------------------------------------------------------


def test_catalogue_is_non_empty_list_of_dicts() -> None:
    """The catalogue must be a non-empty list of dicts."""
    assert isinstance(CYPHER_TEMPLATES, list)
    assert CYPHER_TEMPLATES, "expected at least one template"
    for entry in CYPHER_TEMPLATES:
        assert isinstance(entry, dict), f"non-dict entry: {entry!r}"


def test_template_ids_are_unique() -> None:
    """Each template should have a unique ``id`` so callers can address it."""
    ids = [t["id"] for t in CYPHER_TEMPLATES]
    assert len(ids) == len(set(ids)), f"duplicate ids in: {ids}"


def test_every_template_has_required_keys() -> None:
    """All templates expose the documented fields."""
    required = {"id", "description", "cypher", "params", "examples"}
    for t in CYPHER_TEMPLATES:
        missing = required - t.keys()
        assert not missing, f"template {t.get('id')} missing keys: {missing}"
        assert isinstance(t["id"], str) and t["id"]
        assert isinstance(t["description"], str) and t["description"]
        assert isinstance(t["cypher"], str) and t["cypher"].strip()
        assert isinstance(t["params"], list)
        assert isinstance(t["examples"], list) and t["examples"]


# ---------------------------------------------------------------------------
# Cypher-body sanity
# ---------------------------------------------------------------------------


def test_every_cypher_body_contains_match_and_return() -> None:
    """Every Cypher body should be a read query — has both MATCH and RETURN."""
    for t in CYPHER_TEMPLATES:
        body = t["cypher"]
        assert re.search(r"\bMATCH\b", body), f"{t['id']}: missing MATCH"
        assert re.search(r"\bRETURN\b", body), f"{t['id']}: missing RETURN"


def test_declared_params_appear_in_body() -> None:
    """Every parameter listed in ``params`` must be referenced as ``$name``."""
    for t in CYPHER_TEMPLATES:
        body = t["cypher"]
        for p in t["params"]:
            token = f"${p}"
            assert token in body, f"{t['id']}: param {token!r} not used in body"


def test_no_destructive_clauses_present() -> None:
    """Read-only catalogue: no CREATE / DELETE / SET / MERGE in any body."""
    forbidden = re.compile(r"\b(CREATE|DELETE|MERGE|REMOVE|DROP|SET)\b", re.IGNORECASE)
    for t in CYPHER_TEMPLATES:
        match = forbidden.search(t["cypher"])
        assert match is None, (
            f"{t['id']}: unexpected destructive clause {match.group(0) if match else ''}"
        )


# ---------------------------------------------------------------------------
# Coverage of expected query families
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "prefix",
    [
        "meta_",   # indicator metadata lookups
        "data_",   # enterprise × year × indicator data points
    ],
)
def test_catalogue_covers_required_template_family(prefix: str) -> None:
    """The catalogue must include at least one template per major family."""
    matches = [t for t in CYPHER_TEMPLATES if t["id"].startswith(prefix)]
    assert matches, f"no templates with id prefix {prefix!r}"


def test_examples_are_non_empty_strings() -> None:
    """Every example utterance should be a non-empty string for retrieval."""
    for t in CYPHER_TEMPLATES:
        for ex in t["examples"]:
            assert isinstance(ex, str) and ex.strip(), (
                f"{t['id']}: example {ex!r} is not a non-empty string"
            )
