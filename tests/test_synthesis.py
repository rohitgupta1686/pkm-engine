"""
Synthesis layer test suite — Phase 8 synthesis feature.

Covers:
  A. SummarizerOutput.synthesis field (backward compat + rendering)
  B. Source page rendering (Summary section, Supporting Claims heading, null anchors)
  C. Concept page synthesis (write_concept_page with ConceptSynthesisOutput)
  D. ConceptSynthesisAgent contract
"""
import pathlib
import tempfile

import pytest

from pkm.store.registry import connect
from pkm.config import Settings


# ---------------------------------------------------------------------------
# Fixtures (same pattern as test_vault.py)
# ---------------------------------------------------------------------------

@pytest.fixture(scope="function")
def db_conn():
    """Fresh auto-migrated DB per test."""
    with tempfile.TemporaryDirectory() as tmp_dir:
        db_path = str(pathlib.Path(tmp_dir) / "test.db")
        s = Settings(openai_api_key="test-key", db_path=db_path)
        conn = connect(s)
        yield conn


@pytest.fixture()
def vault_root(tmp_path):
    """Create a minimal vault directory tree in tmp_path."""
    (tmp_path / "wiki" / "sources").mkdir(parents=True)
    (tmp_path / "wiki" / "concepts").mkdir(parents=True)
    log = tmp_path / "log.md"
    log.write_text("")
    return tmp_path


# ---------------------------------------------------------------------------
# Shared helpers
# ---------------------------------------------------------------------------

def _make_source_record(content_hash="aabbccdd112233"):
    from pkm.ingest.hashing import source_id_from_hash
    return {
        "id": source_id_from_hash(content_hash),
        "content_hash": content_hash,
        "type": "Article",
        "title": "Test Article on Synthesis",
        "author": "Jane Smith",
        "url": "https://example.com/synthesis",
        "publisher": "Test Publisher",
        "date_published": "2026-01-01",
        "date_saved": "2026-01-01T00:00:00Z",
        "raw_path": "raw/2026/01/test-article.md",
        "status": "summarized",
        "created_at": "2026-01-01T00:00:00Z",
        "updated_at": "2026-01-01T00:00:00Z",
    }


def _make_summary_with_synthesis():
    from pkm.schemas.agent_io import SummarizerOutput, KeyClaim
    return SummarizerOutput(
        thesis="Synthesis demonstrates readable prose output.",
        synthesis="This is the first synthesis paragraph. It covers the main theme.\n\nThis is the second paragraph. It covers the tensions and nuances.",
        key_claims=[
            KeyClaim(
                statement="High fixed costs create operating leverage.",
                subject="fixed costs",
                predicate="create",
                object="operating leverage",
                claim_type="fact",
                chunk_id="chk_aabbccdd1122_000",
                confidence=0.9,
            ),
            KeyClaim(
                statement="Scale benefits compound over time.",
                subject="scale",
                predicate="compounds",
                object="benefits",
                claim_type="causal",
                chunk_id="null",  # sentinel — should NOT produce #null anchor
                confidence=0.4,
            ),
        ],
        caveats=["Assumes stable revenue mix."],
        summary_confidence=0.85,
    )


def _make_concept_synthesis_output():
    from pkm.schemas.agent_io import ConceptSynthesisOutput
    return ConceptSynthesisOutput(
        definition="Operating leverage is the amplification of revenue changes into larger operating income changes.",
        explanation="Operating leverage arises when fixed costs dominate the cost structure. As revenue grows, the fixed base is spread across more units, causing operating income to grow faster than revenue.\n\nThis dynamic makes high-leverage businesses attractive during growth but dangerous during downturns.",
        related_concepts=["Gross Margin", "Fixed Costs", "SaaS Unit Economics"],
        evidence_claims=[
            "High fixed costs create operating leverage.",
            "Scale benefits compound over time.",
        ],
    )


# ---------------------------------------------------------------------------
# A. SummarizerOutput backward compat
# ---------------------------------------------------------------------------

class TestSummarizerOutputBackwardCompat:
    def test_summarizer_output_synthesis_field_default(self):
        """SummarizerOutput without 'synthesis' still validates (backward compat)."""
        from pkm.schemas.agent_io import SummarizerOutput, KeyClaim
        # Simulate a cached JSON that doesn't have the synthesis field
        import json
        old_json = json.dumps({
            "thesis": "Old thesis without synthesis.",
            "key_claims": [],
            "caveats": [],
            "summary_confidence": 0.75,
        })
        output = SummarizerOutput.model_validate_json(old_json)
        assert output.thesis == "Old thesis without synthesis."
        assert output.synthesis == ""  # default empty string


# ---------------------------------------------------------------------------
# B. Source page rendering
# ---------------------------------------------------------------------------

class TestSourcePageSynthesisRendering:
    def test_source_page_has_summary_section(self, db_conn, vault_root):
        """When SummarizerOutput.synthesis is non-empty, page has ## Summary section."""
        from pkm.store.vault import write_source_page
        from pkm.store.registry import upsert_source
        record = _make_source_record()
        upsert_source(db_conn, record)
        summary = _make_summary_with_synthesis()
        claims = [{"statement": c.statement, "chunk_id": c.chunk_id} for c in summary.key_claims]
        wiki_path = write_source_page(db_conn, vault_root, record, summary, claims, ["Operating Leverage"])
        content = (vault_root / wiki_path).read_text()
        assert "## Summary" in content
        assert "This is the first synthesis paragraph" in content

    def test_source_page_renders_bulleted_synthesis(self, db_conn, vault_root):
        """A scannable bullet-list synthesis (v3 format) renders as bullets under
        ## Summary, with a blank line before the first bullet so markdown lists work."""
        from pkm.store.vault import write_source_page
        from pkm.store.registry import upsert_source
        record = _make_source_record()
        upsert_source(db_conn, record)
        summary = _make_summary_with_synthesis()
        summary.synthesis = (
            "- **Strong quarter:** Margins hit 87%.\n"
            "- **Why it matters:** Demand for cutting-edge capacity is high.\n"
            "- **The risk:** Geopolitics threatens 2026."
        )
        claims = [{"statement": c.statement, "chunk_id": c.chunk_id} for c in summary.key_claims]
        wiki_path = write_source_page(db_conn, vault_root, record, summary, claims, [])
        content = (vault_root / wiki_path).read_text()
        # Blank line between the heading and the first bullet (markdown list renders).
        assert "## Summary\n\n- **Strong quarter:**" in content
        assert "- **The risk:** Geopolitics threatens 2026." in content

    def test_source_page_no_null_anchors(self, db_conn, vault_root):
        """The rendered source page contains no '#null' in any claim bullet."""
        from pkm.store.vault import write_source_page
        from pkm.store.registry import upsert_source
        record = _make_source_record()
        upsert_source(db_conn, record)
        summary = _make_summary_with_synthesis()
        claims = [{"statement": c.statement, "chunk_id": c.chunk_id} for c in summary.key_claims]
        wiki_path = write_source_page(db_conn, vault_root, record, summary, claims, ["Operating Leverage"])
        content = (vault_root / wiki_path).read_text()
        assert "#null" not in content, "Found '#null' anchor in source page — should be omitted"

    def test_source_page_source_paths_no_double_raw(self, db_conn, vault_root):
        """When raw_path already starts with 'raw/', source_paths must not double it."""
        from pkm.store.vault import write_source_page
        from pkm.store.registry import upsert_source
        record = _make_source_record()
        # raw_path already starts with "raw/"
        assert record["raw_path"].startswith("raw/")
        upsert_source(db_conn, record)
        summary = _make_summary_with_synthesis()
        claims = [{"statement": c.statement, "chunk_id": c.chunk_id} for c in summary.key_claims]
        wiki_path = write_source_page(db_conn, vault_root, record, summary, claims, [])
        content = (vault_root / wiki_path).read_text()
        # Should contain the path once, not doubled
        assert "raw/raw/" not in content, "Found doubled 'raw/raw/' in source page frontmatter"
        assert "raw/2026/01/test-article.md" in content, "Expected raw path in frontmatter"

    def test_source_page_supporting_claims_heading(self, db_conn, vault_root):
        """The page uses '## Supporting Claims' not '## Key Claims'."""
        from pkm.store.vault import write_source_page
        from pkm.store.registry import upsert_source
        record = _make_source_record()
        upsert_source(db_conn, record)
        summary = _make_summary_with_synthesis()
        claims = [{"statement": c.statement, "chunk_id": c.chunk_id} for c in summary.key_claims]
        wiki_path = write_source_page(db_conn, vault_root, record, summary, claims, [])
        content = (vault_root / wiki_path).read_text()
        assert "## Supporting Claims" in content
        assert "## Key Claims" not in content

    def test_source_page_no_summary_when_empty_synthesis(self, db_conn, vault_root):
        """When synthesis is empty string, no ## Summary section is rendered."""
        from pkm.store.vault import write_source_page
        from pkm.store.registry import upsert_source
        from pkm.schemas.agent_io import SummarizerOutput
        record = _make_source_record()
        upsert_source(db_conn, record)
        # Summary with no synthesis (empty default)
        summary = SummarizerOutput(
            thesis="A thesis without synthesis.",
            key_claims=[],
            caveats=[],
            summary_confidence=0.7,
        )
        wiki_path = write_source_page(db_conn, vault_root, record, summary, [], [])
        content = (vault_root / wiki_path).read_text()
        assert "## Summary" not in content


# ---------------------------------------------------------------------------
# C. Concept page synthesis
# ---------------------------------------------------------------------------

class TestConceptPageSynthesis:
    def _setup_concept(self, db_conn):
        from pkm.store.registry import upsert_concept
        from pkm.ingest.hashing import concept_id
        cid = concept_id("Operating Leverage")
        upsert_concept(db_conn, {
            "id": cid,
            "name": "Operating Leverage",
            "definition": "Ratio of fixed to variable costs.",
            "domain": "finance",
            "wiki_path": "wiki/concepts/operating-leverage.md",
            "created_at": "2026-01-01T00:00:00Z",
            "updated_at": "2026-01-01T00:00:00Z",
        })
        return cid

    def test_concept_page_with_synthesis(self, db_conn, vault_root):
        """write_concept_page with ConceptSynthesisOutput renders all populated sections."""
        from pkm.store.vault import write_concept_page
        from pkm.ingest.hashing import concept_id
        cid = self._setup_concept(db_conn)
        synthesis = _make_concept_synthesis_output()
        wiki_path = write_concept_page(
            db_conn, vault_root, cid, "Operating Leverage", "test-article",
            synthesis=synthesis,
        )
        content = (vault_root / wiki_path).read_text()
        assert "## One-sentence Definition" in content
        assert synthesis.definition in content
        assert "## Explanation" in content
        assert "Operating leverage arises when fixed costs dominate" in content
        assert "## Related Concepts" in content
        assert "## Instances/Evidence" in content
        # Evidence claims must be rendered as bullets
        assert "- High fixed costs create operating leverage." in content

    def test_concept_page_synthesis_wikilinks(self, db_conn, vault_root):
        """Related concepts are rendered as [[slug]] wikilinks."""
        from pkm.store.vault import write_concept_page
        from pkm.ingest.hashing import concept_id, slugify
        cid = self._setup_concept(db_conn)
        synthesis = _make_concept_synthesis_output()
        wiki_path = write_concept_page(
            db_conn, vault_root, cid, "Operating Leverage", "test-article",
            synthesis=synthesis,
        )
        content = (vault_root / wiki_path).read_text()
        # "Gross Margin" -> slug "gross-margin" -> [[gross-margin]]
        assert "[[gross-margin]]" in content
        assert "[[fixed-costs]]" in content
        assert "[[saas-unit-economics]]" in content

    def test_concept_page_synthesis_idempotent(self, db_conn, vault_root):
        """Calling write_concept_page twice with same synthesis gives identical bytes."""
        from pkm.store.vault import write_concept_page
        from pkm.ingest.hashing import concept_id
        cid = self._setup_concept(db_conn)
        synthesis = _make_concept_synthesis_output()
        wiki_path = write_concept_page(
            db_conn, vault_root, cid, "Operating Leverage", "test-article",
            synthesis=synthesis,
        )
        bytes1 = (vault_root / wiki_path).read_bytes()
        wiki_path2 = write_concept_page(
            db_conn, vault_root, cid, "Operating Leverage", "test-article",
            synthesis=synthesis,
        )
        bytes2 = (vault_root / wiki_path2).read_bytes()
        assert bytes1 == bytes2, "write_concept_page produced different bytes on second call with same synthesis"

    def test_concept_page_provenance_preserved_on_synthesis(self, db_conn, vault_root):
        """When re-rendered with synthesis, existing provenance links are preserved."""
        from pkm.store.vault import write_concept_page
        from pkm.ingest.hashing import concept_id
        cid = self._setup_concept(db_conn)
        # First create the page without synthesis (adds first-source link)
        write_concept_page(db_conn, vault_root, cid, "Operating Leverage", "first-source")
        # Now re-render with synthesis (from a different source)
        synthesis = _make_concept_synthesis_output()
        wiki_path = write_concept_page(
            db_conn, vault_root, cid, "Operating Leverage", "second-source",
            synthesis=synthesis,
        )
        content = (vault_root / wiki_path).read_text()
        # Both source links must be in the provenance section
        assert "[[first-source]]" in content
        assert "[[second-source]]" in content

    def test_concept_page_no_synthesis_still_works(self, db_conn, vault_root):
        """write_concept_page with synthesis=None uses existing empty template (backward compat)."""
        from pkm.store.vault import write_concept_page
        from pkm.ingest.hashing import concept_id
        cid = self._setup_concept(db_conn)
        wiki_path = write_concept_page(
            db_conn, vault_root, cid, "Operating Leverage", "test-article"
        )
        content = (vault_root / wiki_path).read_text()
        assert "[[test-article]]" in content
        assert "## Provenance" in content


# ---------------------------------------------------------------------------
# D. ConceptSynthesisAgent contract
# ---------------------------------------------------------------------------

class TestConceptSynthesisAgent:
    def test_concept_synthesis_agent_role(self):
        """ConceptSynthesisAgent.role == 'concept_synthesis_agent'."""
        from pkm.agents.concept_synthesis_agent import ConceptSynthesisAgent
        assert ConceptSynthesisAgent.role == "concept_synthesis_agent"

    def test_concept_synthesis_agent_prompt_template(self):
        """ConceptSynthesisAgent.prompt_template == 'concept_synthesis.v1.md'."""
        from pkm.agents.concept_synthesis_agent import ConceptSynthesisAgent
        assert ConceptSynthesisAgent.prompt_template == "concept_synthesis.v1.md"

    def test_concept_synthesis_agent_output_schema(self):
        """ConceptSynthesisAgent.output_schema is ConceptSynthesisOutput."""
        from pkm.agents.concept_synthesis_agent import ConceptSynthesisAgent
        from pkm.schemas.agent_io import ConceptSynthesisOutput
        assert ConceptSynthesisAgent.output_schema is ConceptSynthesisOutput

    def test_concept_synthesis_agent_prompt_file_exists(self):
        """Prompt file concept_synthesis.v1.md exists on disk."""
        from pkm.agents.concept_synthesis_agent import ConceptSynthesisAgent
        from pathlib import Path
        prompt_path = Path(__file__).parent.parent / "pkm" / "prompts" / ConceptSynthesisAgent.prompt_template
        assert prompt_path.exists(), f"Prompt file not found: {prompt_path}"
