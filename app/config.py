from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    app_name: str = "wk15-assistant"

    gemini_api_key: str = ""
    gemini_model: str = "gemini-2.5-flash"
    gemini_base_url: str = "https://generativelanguage.googleapis.com/v1beta/openai/"

    vllm_base_url: str = "http://localhost:8001/v1"
    vllm_model: str = "qwen2.5-1.5b-instruct"
    vllm_api_key: str = "EMPTY"

    ollama_base_url: str = "http://localhost:11434/v1"
    ollama_model: str = "qwen2.5:1.5b-instruct"
    ollama_api_key: str = "ollama"

    provider_order: str = "gemini,vllm,ollama"

    temperature: float = 0.2
    top_p: float = 0.9
    max_output_tokens: int = 1024
    request_timeout_s: float = 90.0

    data_docs_dir: str = "data/docs"
    qdrant_path: str = "data/qdrant"
    qdrant_url: str = ""
    collection_name: str = "wk15_kb"
    embedding_model: str = "sentence-transformers/all-MiniLM-L6-v2"

    chunk_size_chars: int = 900
    chunk_overlap_chars: int = 150
    top_k: int = 4

    retry_attempts: int = 3
    retry_backoff_s: float = 0.5
    breaker_failure_threshold: int = 3
    breaker_reset_timeout_s: float = 30.0

    rate_limit_rpm: int = 60
    rate_limit_burst: int = 20

    cache_ttl_s: int = 300
    cache_max_items: int = 512

    # --- W16 agentic loop -------------------------------------------------
    agent_max_iterations: int = 8
    agent_max_tool_calls_per_iter: int = 4
    agent_max_total_tokens: int = 60_000
    agent_tool_timeout_s: float = 10.0
    agent_max_verification_retries: int = 2
    agent_enable_clearing: bool = True
    agent_keep_last_tool_rounds: int = 1
    agent_retrieval_k: int = 4
    agent_min_relevance: float = 0.15
    agent_snippet_chars: int = 600
    agent_notes_max_chars: int = 1500
    agent_prompt_version: str = "v1"
    agent_fault_mode: str = ""
    skills_dir: str = "skills"


@lru_cache
def get_settings() -> Settings:
    return Settings()
