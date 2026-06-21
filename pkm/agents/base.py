"""
BaseAgent ABC — shared contract for all PKM pipeline agents.

Every concrete agent subclasses BaseAgent and declares seven ClassVar attributes.
The single run() implementation handles prompt loading, LLMClient delegation,
and cache detection. Repair-retry is handled inside LLMClient._extract_result;
BaseAgent propagates any ValidationError from a second validation failure.
"""

from __future__ import annotations

from abc import ABC
from pathlib import Path
from typing import ClassVar

from pydantic import BaseModel


# Required ClassVar attribute names that every concrete subclass must declare.
_REQUIRED_ATTRS: tuple[str, ...] = (
    "role",
    "model",
    "prompt_template",
    "prompt_version",
    "input_schema",
    "output_schema",
    "memory_tier",
)


class BaseAgent(ABC):
    """
    Abstract base class for all PKM agents.

    Concrete subclasses declare these class-level attributes:

        role: ClassVar[str]                     — agent name key; used as agent_name in LLMClient.call()
        model: ClassVar[str]                    — model string (resolved from settings.llm_model; default gpt-5.4-mini)
        prompt_template: ClassVar[str]          — filename under pkm/prompts/ (e.g. "summarize.v1.md")
        prompt_version: ClassVar[str]           — version string for cache key (e.g. "v1")
        input_schema: ClassVar[type | None]     — pydantic BaseModel or None (documentation only)
        output_schema: ClassVar[type[BaseModel]] — pydantic model class passed to LLMClient.call()
        memory_tier: ClassVar[str]              — "stateless" | "working" | "long"

    No LLMClient import — the client is injected via run() to keep BaseAgent decoupled
    from infrastructure concerns and to make unit testing trivial.
    """

    role: ClassVar[str]
    model: ClassVar[str]
    prompt_template: ClassVar[str]
    prompt_version: ClassVar[str]
    input_schema: ClassVar[type | None]
    output_schema: ClassVar[type[BaseModel]]
    memory_tier: ClassVar[str]

    def __init_subclass__(cls, **kwargs: object) -> None:
        """
        Enforce that every non-abstract concrete subclass declares all required ClassVar
        attributes. Raises TypeError at class-definition time if any are missing.

        Abstract intermediaries (those that declare their own abstract methods or
        have ABC in their bases) are exempt — they will be checked when their own
        subclasses are defined.
        """
        super().__init_subclass__(**kwargs)

        # Skip enforcement for abstract subclasses (those that still have abstract methods
        # or that re-inherit from ABC directly).
        if getattr(cls, "__abstractmethods__", None):
            return

        # For concrete classes: check every required attribute is present.
        missing = [attr for attr in _REQUIRED_ATTRS if not hasattr(cls, attr)]
        if missing:
            raise TypeError(
                f"{cls.__name__} must define the following ClassVar attributes: "
                f"{', '.join(missing)}"
            )

    # ------------------------------------------------------------------
    # Prompt loading
    # ------------------------------------------------------------------

    def _load_prompt(self) -> str:
        """
        Load the prompt file from pkm/prompts/<prompt_template>.

        Path is resolved relative to this file: Path(__file__).parent.parent / "prompts" / prompt_template
        Raises FileNotFoundError if the prompt file does not exist.
        """
        prompt_path = Path(__file__).parent.parent / "prompts" / self.prompt_template
        if not prompt_path.exists():
            raise FileNotFoundError(
                f"Prompt file not found: {prompt_path}. "
                f"Expected under pkm/prompts/{self.prompt_template}"
            )
        return prompt_path.read_text(encoding="utf-8")

    # ------------------------------------------------------------------
    # Main entry point
    # ------------------------------------------------------------------

    def run(
        self,
        llm_client: object,
        input_text: str,
        source_id: str | None = None,
        extra_messages: list[dict] | None = None,
    ) -> BaseModel:
        """
        Execute this agent against the given input text.

        Steps:
          1. Load the prompt via _load_prompt().
          2. Build the messages list: [{"role": "user", "content": "<prompt>\\n\\n<input_text>"}]
             plus any extra_messages appended after.
          3. Delegate to llm_client.call() with all required kwargs.
          4. If the result is a cache hit:
               - when LLMClient restored the prior output (result["result"] present,
                 from agent_runs.output_json — the B-05-02 durable-summary fix),
                 return that validated instance with no API call;
               - otherwise (legacy ok-row with no stored output) raise RuntimeError so
                 the pipeline recovers via its own fallback path.
          5. Return result["result"] — the validated pydantic instance produced by LLMClient.

        Args:
            llm_client: An LLMClient instance (injected; not imported here).
            input_text:  The raw text to process.
            source_id:   Optional source note ID for agent_runs provenance tracking.
            extra_messages: Optional additional messages appended to the user message.

        Returns:
            A validated pydantic BaseModel instance matching self.output_schema.

        Raises:
            FileNotFoundError: If the prompt template file does not exist.
            RuntimeError: If LLMClient returns a cache hit with no restorable output
                          (legacy pre-004 row); caller must fetch/recover from agent_runs.
            ValidationError: If LLMClient's repair-retry also fails schema validation.
        """
        prompt = self._load_prompt()

        messages: list[dict] = [
            {"role": "user", "content": f"{prompt}\n\n{input_text}"}
        ]
        if extra_messages:
            messages.extend(extra_messages)

        result = llm_client.call(
            agent_name=self.role,
            model=self.model,
            prompt_version=self.prompt_version,
            messages=messages,
            input_text=input_text,
            source_id=source_id,
            output_schema=self.output_schema,
        )

        if result.get("cached") is True:
            if "result" in result:
                # B-05-02: LLMClient restored the prior validated output from
                # agent_runs.output_json — return it directly (no API call, no
                # placeholder). The pipeline gets the REAL summary on recovery.
                return result["result"]
            raise RuntimeError(
                "Cache hit — caller must retrieve from agent_runs. "
                f"input_hash={result.get('input_hash')}"
            )

        return result["result"]
