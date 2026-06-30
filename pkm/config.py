from pydantic_settings import BaseSettings, SettingsConfigDict

from pkm.llm.models import GPT54


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8")

    # --- OpenAI (the locked provider for single-call synthesis) ---
    openai_api_key: str = ""
    openai_base_url: str = "https://api.openai.com/v1"

    # Single-call note synthesis runs on the full model. Override PKM_SYNTHESIS_MODEL.
    synthesis_model: str = GPT54
    # Vault subdir the single-call path reads existing notes from / writes notes to.
    notes_dirname: str = "notes"

    # Per-run cost guardrail (T1-02): batch-ingest aborts before exceeding this.
    run_cost_cap_usd: float = 0.50
    run_token_cap: int = 200_000

    # Vault root (a git checkout). Notes are written under <vault>/<notes_dirname>.
    vault_path: str = ""

    # Source-notes capture folder (books/podcasts/lectures), typically an Obsidian
    # vault synced via iCloud, e.g.
    #   ~/Library/Mobile Documents/iCloud~md~obsidian/Documents/Sources
    # Read by `pkm ingest-notes`. Override PKM_SOURCES_DIR.
    sources_dir: str = ""


settings = Settings()
