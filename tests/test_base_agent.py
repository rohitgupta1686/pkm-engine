"""
Tests for pkm.agents.base.BaseAgent ABC.

RED phase: these tests should FAIL before implementation.
GREEN phase: all tests pass after pkm/agents/base.py is created.
"""

import pytest
from pathlib import Path
from unittest.mock import MagicMock
from pydantic import BaseModel


# ---------------------------------------------------------------------------
# Helper: a minimal concrete subclass used across tests
# ---------------------------------------------------------------------------

def make_concrete_agent_class():
    """Import BaseAgent and return a valid concrete subclass."""
    from pkm.agents.base import BaseAgent
    from pkm.schemas.agent_io import SummarizerOutput
    from pkm.llm.models import MINI

    class ConcreteAgent(BaseAgent):
        role = "test_summarizer"
        model = MINI
        prompt_template = "summarize.v1.md"
        prompt_version = "v1"
        input_schema = None
        output_schema = SummarizerOutput
        memory_tier = "stateless"

    return ConcreteAgent


# ---------------------------------------------------------------------------
# Test 1: BaseAgent is importable
# ---------------------------------------------------------------------------

def test_base_agent_importable():
    from pkm.agents.base import BaseAgent  # noqa: F401


# ---------------------------------------------------------------------------
# Test 2: Concrete subclass with all attributes instantiates without error
# ---------------------------------------------------------------------------

def test_concrete_subclass_instantiation():
    ConcreteAgent = make_concrete_agent_class()
    agent = ConcreteAgent()
    assert agent is not None


# ---------------------------------------------------------------------------
# Test 3: Subclass missing `role` raises TypeError at class-definition time
# ---------------------------------------------------------------------------

def test_missing_role_raises_type_error():
    from pkm.agents.base import BaseAgent
    from pkm.schemas.agent_io import SummarizerOutput
    from pkm.llm.models import MINI

    with pytest.raises(TypeError):
        class MissingRoleAgent(BaseAgent):
            # role is intentionally omitted
            model = MINI
            prompt_template = "summarize.v1.md"
            prompt_version = "v1"
            input_schema = None
            output_schema = SummarizerOutput
            memory_tier = "stateless"


# ---------------------------------------------------------------------------
# Test 4: Subclass missing `output_schema` raises TypeError
# ---------------------------------------------------------------------------

def test_missing_output_schema_raises_type_error():
    from pkm.agents.base import BaseAgent
    from pkm.llm.models import MINI

    with pytest.raises(TypeError):
        class MissingOutputSchemaAgent(BaseAgent):
            role = "test"
            model = MINI
            prompt_template = "summarize.v1.md"
            prompt_version = "v1"
            input_schema = None
            # output_schema intentionally omitted
            memory_tier = "stateless"


# ---------------------------------------------------------------------------
# Test 5: _load_prompt returns non-empty string for summarize.v1.md
# ---------------------------------------------------------------------------

def test_load_prompt_returns_nonempty_string():
    ConcreteAgent = make_concrete_agent_class()
    agent = ConcreteAgent()
    prompt = agent._load_prompt()
    assert isinstance(prompt, str)
    assert len(prompt) > 50


# ---------------------------------------------------------------------------
# Test 6: _load_prompt raises FileNotFoundError for nonexistent template
# ---------------------------------------------------------------------------

def test_load_prompt_raises_for_missing_file():
    from pkm.agents.base import BaseAgent
    from pkm.schemas.agent_io import SummarizerOutput
    from pkm.llm.models import MINI

    class BadPromptAgent(BaseAgent):
        role = "bad_agent"
        model = MINI
        prompt_template = "nonexistent_prompt.v99.md"
        prompt_version = "v99"
        input_schema = None
        output_schema = SummarizerOutput
        memory_tier = "stateless"

    agent = BadPromptAgent()
    with pytest.raises(FileNotFoundError):
        agent._load_prompt()


# ---------------------------------------------------------------------------
# Test 7: run() calls llm_client.call() with correct keyword arguments
# ---------------------------------------------------------------------------

def test_run_calls_llm_client_with_correct_kwargs():
    from pkm.schemas.agent_io import SummarizerOutput, KeyClaim

    ConcreteAgent = make_concrete_agent_class()
    agent = ConcreteAgent()

    # Build a valid SummarizerOutput instance for the mock to return
    mock_output = SummarizerOutput(
        thesis="Test thesis",
        key_claims=[
            KeyClaim(
                statement="Test claim",
                subject="A",
                predicate="does",
                object="B",
                claim_type="fact",
                chunk_id="chunk_001",
                confidence=0.9,
            )
        ],
        caveats=[],
        summary_confidence=0.85,
    )

    mock_client = MagicMock()
    mock_client.call.return_value = {
        "cached": False,
        "input_hash": "abc123",
        "result": mock_output,
        "tokens_in": 100,
        "tokens_out": 50,
    }

    result = agent.run(mock_client, input_text="Some raw note text", source_id="src_001")

    # Verify call() was invoked once
    mock_client.call.assert_called_once()
    call_kwargs = mock_client.call.call_args

    # Check keyword arguments
    assert call_kwargs.kwargs.get("agent_name") == "test_summarizer"
    assert call_kwargs.kwargs.get("prompt_version") == "v1"
    assert call_kwargs.kwargs.get("output_schema") is SummarizerOutput
    assert call_kwargs.kwargs.get("source_id") == "src_001"
    assert call_kwargs.kwargs.get("input_text") == "Some raw note text"

    # run() should return the pydantic instance
    assert result is mock_output


# ---------------------------------------------------------------------------
# Test 8: run() raises RuntimeError on cache hit
# ---------------------------------------------------------------------------

def test_run_raises_on_cache_hit():
    ConcreteAgent = make_concrete_agent_class()
    agent = ConcreteAgent()

    mock_client = MagicMock()
    mock_client.call.return_value = {
        "cached": True,
        "input_hash": "abc123",
    }

    with pytest.raises(RuntimeError, match="Cache hit"):
        agent.run(mock_client, input_text="Some text")


# ---------------------------------------------------------------------------
# Test 9: run() includes prompt content in messages
# ---------------------------------------------------------------------------

def test_run_includes_prompt_in_messages():
    from pkm.schemas.agent_io import SummarizerOutput, KeyClaim

    ConcreteAgent = make_concrete_agent_class()
    agent = ConcreteAgent()

    mock_output = SummarizerOutput(
        thesis="Test",
        key_claims=[
            KeyClaim(
                statement="Claim",
                claim_type="fact",
                chunk_id="c1",
                confidence=0.8,
            )
        ],
        caveats=[],
        summary_confidence=0.8,
    )

    mock_client = MagicMock()
    mock_client.call.return_value = {
        "cached": False,
        "input_hash": "xyz",
        "result": mock_output,
        "tokens_in": 10,
        "tokens_out": 5,
    }

    agent.run(mock_client, input_text="hello world")

    call_kwargs = mock_client.call.call_args.kwargs
    messages = call_kwargs.get("messages", [])
    assert len(messages) >= 1
    # First message should contain the prompt text and input
    first_content = messages[0]["content"]
    assert "hello world" in first_content
