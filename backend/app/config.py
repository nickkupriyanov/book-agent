from functools import lru_cache
from typing import Literal
from uuid import UUID

from pydantic import Field, SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    database_url: str = "sqlite:///./book_agent.db"
    demo_user_id: UUID = UUID("00000000-0000-0000-0000-000000000001")
    deepseek_api_key: SecretStr | None = None
    deepseek_base_url: str = "https://api.deepseek.com"
    deepseek_model: str = "deepseek-v4-flash"
    deepseek_timeout_seconds: float = 30.0
    agent_max_steps: int = Field(default=5, ge=1)
    agent_history_max_tool_rounds: int = Field(default=3, ge=1, le=20)
    pending_action_ttl_seconds: int = Field(default=900, ge=1)
    catalog_provider: Literal["local", "open_library"] = "local"
    open_library_base_url: str = "https://openlibrary.org"
    open_library_user_agent: str = "BookAgentLearning/0.1"
    open_library_timeout_seconds: float = Field(default=3.0, gt=0)
    open_library_max_retries: int = Field(default=1, ge=0, le=3)
    open_library_retry_delay_seconds: float = Field(default=0.1, ge=0, le=5)
    catalog_cache_ttl_seconds: float = Field(default=300, gt=0)
    catalog_cache_max_entries: int = Field(default=128, ge=1, le=10_000)

    model_config = SettingsConfigDict(env_file=".env", extra="ignore")


@lru_cache
def get_settings() -> Settings:
    return Settings()
