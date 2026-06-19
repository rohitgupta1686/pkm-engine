from pydantic_settings import BaseSettings, SettingsConfigDict

from pkm.llm.models import MINI


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8")

    # --- LLM backend (OpenAI) ---
    # The OpenAI SDK is the sole client. Any Anthropic-model usage routes through
    # an OpenAI-compatible endpoint (e.g. CLIProxyAPI) via openai_base_url + llm_model.
    openai_api_key: str = ""
    openai_base_url: str = "https://api.openai.com/v1"
    llm_model: str = MINI  # cloud default; set PKM_LLM_MODEL for local CLIProxyAPI dev

    # Per-run cost guardrail (T1-02 condition 2): batch_ingest aborts if either is exceeded.
    run_cost_cap_usd: float = 0.50
    run_token_cap: int = 200_000

    turso_url: str = ""
    turso_token: str = ""
    cf_account_id: str = ""
    cf_api_token: str = ""
    db_path: str = "pkm.db"
    vault_path: str = ""  # Path to pkm-vault root; passed to vault writer; set via VAULT_PATH env or CLI flag


settings = Settings()