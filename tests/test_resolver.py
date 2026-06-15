"""
Unit tests for graph/resolver.py (three-tier entity resolution) and
graph/confidence.py (noisy-OR formula).

Uses the db_conn fixture from conftest.py (auto-imported by pytest).
"""

from __future__ import annotations

import datetime

import pytest

from pkm.graph.confidence import noisy_or
from pkm.graph.resolver import resolve


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def insert_entity(conn, entity_id: str, entity_type: str, name: str) -> None:
    """Insert a row into the entities table for resolver tests."""
    now = datetime.datetime.now(datetime.UTC).isoformat().replace("+00:00", "Z")
    conn.execute(
        "INSERT OR IGNORE INTO entities (id, type, name, created_at, updated_at) "
        "VALUES (?, ?, ?, ?, ?)",
        (entity_id, entity_type, name, now, now),
    )
    conn.commit()


def insert_alias(conn, alias: str, entity_id: str) -> None:
    """Insert a row into the entity_aliases table for resolver tests."""
    conn.execute(
        "INSERT OR IGNORE INTO entity_aliases (alias, entity_id) VALUES (?, ?)",
        (alias, entity_id),
    )
    conn.commit()


# ---------------------------------------------------------------------------
# TestResolver
# ---------------------------------------------------------------------------


class TestResolver:
    def test_exact_match(self, db_conn):
        """Tier 1: resolve returns entity id for an exact name match."""
        insert_entity(db_conn, "ent_company_tsmc", "Company", "TSMC")
        result = resolve(db_conn, "TSMC", "Company")
        assert result == "ent_company_tsmc"

    def test_alias_match(self, db_conn):
        """Tier 2: resolve returns entity id when the name matches an alias."""
        insert_entity(db_conn, "ent_company_tsmc", "Company", "TSMC")
        insert_alias(db_conn, "Taiwan Semiconductor", "ent_company_tsmc")
        result = resolve(db_conn, "Taiwan Semiconductor", "Company")
        assert result == "ent_company_tsmc"

    def test_miss_returns_none(self, db_conn):
        """Tier 3 stub: resolve returns None when neither exact nor alias match."""
        result = resolve(db_conn, "Unknown Corp XYZ", "Company")
        assert result is None

    def test_wrong_type_returns_none(self, db_conn):
        """Type mismatch: entity exists but under a different type — returns None."""
        insert_entity(db_conn, "ent_author_john", "Author", "John Smith")
        result = resolve(db_conn, "John Smith", "Company")
        assert result is None


# ---------------------------------------------------------------------------
# TestNoisyOr
# ---------------------------------------------------------------------------


class TestNoisyOr:
    def test_formula_values(self):
        """Verify noisy-OR formula against known values (AD-6)."""
        assert abs(noisy_or(0.5, 0.5) - 0.75) < 1e-9
        assert abs(noisy_or(0.0, 0.8) - 0.8) < 1e-9
        assert abs(noisy_or(1.0, 0.0) - 1.0) < 1e-9
        assert abs(noisy_or(0.3, 0.4) - (1.0 - 0.7 * 0.6)) < 1e-9
