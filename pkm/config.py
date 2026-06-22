from pydantic_settings import BaseSettings, SettingsConfigDict

from pkm.llm.models import MINI


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8")

    # --- LLM backend ---
    # llm_provider selects the calling module (pkm.llm.factory.build_llm_client):
    #   "gemini" → GeminiClient (Google AI Studio free tier; default)
    #   "openai" → LLMClient (OpenAI SDK; pluggable fallback / comparison)
    llm_provider: str = "gemini"

    # OpenAI backend. Any Anthropic-model usage routes through an OpenAI-compatible
    # endpoint (e.g. CLIProxyAPI) via openai_base_url + llm_model.
    openai_api_key: str = ""
    openai_base_url: str = "https://api.openai.com/v1"
    llm_model: str = MINI  # OpenAI model id; set PKM_LLM_MODEL for local CLIProxyAPI dev

    # Gemini backend (free tier). Create a key at https://aistudio.google.com/apikey.
    # gemini_model defaults to the "auto" sentinel: list Flash models and fall back
    # by version (3.5 → 3.1 → … ). Set PKM_GEMINI_MODEL to pin one concrete model.
    gemini_api_key: str = ""
    gemini_model: str = "gemini-flash-auto"

    # Per-run cost guardrail (T1-02 condition 2): batch_ingest aborts if either is exceeded.
    run_cost_cap_usd: float = 0.50
    run_token_cap: int = 200_000

    turso_url: str = ""
    turso_token: str = ""
    cf_account_id: str = ""
    cf_api_token: str = ""
    db_path: str = "pkm.db"
    vault_path: str = ""  # Path to pkm-vault root; passed to vault writer; set via VAULT_PATH env or CLI flag

    @property
    def active_model(self) -> str:
        """The model id agents pass to the client, resolved from the provider.

        Gemini agents pass the logical "auto" sentinel (stable cache key); the
        client expands it to the version-ordered Flash fallback chain.
        """
        return self.gemini_model if self.llm_provider == "gemini" else self.llm_model


settings = Settings()