"""
Entity resolution for the PKM knowledge graph (AD-5).

Three-tier resolution strategy:
  Tier 1: Exact match on entities(type, name)
  Tier 2: Alias match via entity_aliases table
  Tier 3: Embedding similarity (MVP stub — returns None)
"""

import logging

logger = logging.getLogger(__name__)


def resolve(conn, name: str, entity_type: str) -> str | None:
    """
    Three-tier entity resolution (AD-5). Returns entity id or None.

    Args:
        conn:        libsql connection with entities + entity_aliases tables.
        name:        Entity name or alias to resolve.
        entity_type: Entity type (e.g. "Company", "Author", "Industry").

    Returns:
        Entity id string if resolved, None if no match found.
    """
    # Tier 1: exact match on (type, name) — fastest path
    row = conn.execute(
        "SELECT id FROM entities WHERE type = ? AND name = ?",
        (entity_type, name),
    ).fetchone()
    if row is not None:
        return row[0]

    # Tier 2: alias match — name is a known alias for an entity of this type
    row = conn.execute(
        "SELECT e.id FROM entities e "
        "JOIN entity_aliases ea ON ea.entity_id = e.id "
        "WHERE e.type = ? AND ea.alias = ?",
        (entity_type, name),
    ).fetchone()
    if row is not None:
        return row[0]

    # Tier 3: embedding similarity — MVP stub
    logger.debug(
        "resolve: embedding tier not implemented for MVP; returning None for '%s' (%s)",
        name,
        entity_type,
    )
    return None
