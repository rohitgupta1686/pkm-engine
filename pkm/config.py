from pydantic_settings import BaseSettings, SettingsConfigDict

from pkm.llm.models import GLM52


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8")

    # --- OpenAI-compatible LLM endpoint (Z.AI GLM-5.2 by default) ---
    openai_api_key: str = ""
    openai_base_url: str = "https://api.z.ai/api/paas/v4/"

    # Single-call note synthesis model. Override via env SYNTHESIS_MODEL.
    # Settings has no env_prefix, so PKM_SYNTHESIS_MODEL does not bind.
    synthesis_model: str = GLM52
    # Vault subdir the single-call path reads existing notes from / writes notes to.
    notes_dirname: str = "notes"

    # Per-run cost guardrail (T1-02): batch-ingest defers sources before a batch's
    # projected (batch-rate) cost would exceed this. Env: RUN_COST_CAP_USD.
    run_cost_cap_usd: float = 0.50
    run_token_cap: int = 200_000

    # Batch API polling (article ingest). The Actions job blocks-polls the submitted
    # batch until it completes; on timeout the batch is cancelled and the next
    # dispatch/nightly run re-submits (idempotent via --new-only). Env:
    # BATCH_POLL_INTERVAL_SEC / BATCH_TIMEOUT_SEC.
    batch_poll_interval_sec: int = 20
    batch_timeout_sec: int = 5400  # 90 min; well under the job's timeout-minutes ceiling

    # Vault root (a git checkout). Notes are written under <vault>/<notes_dirname>.
    vault_path: str = ""

    # Source-notes capture folder (books/podcasts/lectures), typically an Obsidian
    # vault synced via iCloud, e.g.
    #   ~/Library/Mobile Documents/iCloud~md~obsidian/Documents/Sources
    # Read by `pkm ingest-notes`. Override SOURCES_DIR.
    sources_dir: str = ""

    # Opt-in, Mac-local OCR pre-pass for image embeds in source notes. This key is
    # intentionally never used by a GitHub Actions workflow.
    gemini_api_key: str = ""
    gemini_base_url: str = "https://generativelanguage.googleapis.com/v1beta/openai/"
    ocr_model: str = "gemini-2.5-flash"
    ocr_enabled: bool = False


settings = Settings()
