"""
Content hashing, ID derivation, and slug utilities for the PKM ingest pipeline.

Tech spec §8.1 + §8.3 — id formats:
  source:  src_<sha256hex[:12]>
  chunk:   chk_<source_hash12>_<ordinal:03d>
  concept: cpt_<kebab-slug>

Security note (T-03-04): slugify strips all chars not in [a-z0-9-], preventing
path traversal via malicious titles. Vault writer confines writes to vault_root/wiki/<type>/.
"""

import hashlib
import re


def sha256_content(text: str) -> str:
    """Return the 64-char hex SHA-256 digest of text (UTF-8 encoded).

    Identical text always produces an identical digest.
    """
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def source_id_from_hash(content_hash: str) -> str:
    """Derive a source id from a SHA-256 hex digest.

    Returns "src_" + first 12 hex chars of the digest.
    """
    return "src_" + content_hash[:12]


def slugify(name: str) -> str:
    """Convert a human-readable name to a kebab-case slug.

    Rules (T-03-04 security):
    - Lowercase the entire string
    - Replace any sequence of non-[a-z0-9] chars with a hyphen
    - Strip leading/trailing hyphens
    - Collapse consecutive hyphens to one

    Example: "Operating Leverage" -> "operating-leverage"
             "Hello, World! (2024)" -> "hello-world-2024"
    """
    s = name.lower()
    s = re.sub(r"[^a-z0-9]+", "-", s)
    s = s.strip("-")
    return s


def concept_id(name: str) -> str:
    """Derive a concept id from a concept name.

    Returns "cpt_" + slugify(name).
    Example: "Operating Leverage" -> "cpt_operating-leverage"
    """
    return "cpt_" + slugify(name)


def chunk_id(source_hash12: str, ordinal: int) -> str:
    """Derive a chunk id from the first 12 chars of a source hash and an ordinal.

    Returns "chk_<source_hash12>_<ordinal:03d>".
    Example: chunk_id("a1b2c3d4e5f6", 7) -> "chk_a1b2c3d4e5f6_007"
    """
    return f"chk_{source_hash12}_{ordinal:03d}"
