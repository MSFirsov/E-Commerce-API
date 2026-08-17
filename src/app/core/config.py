from functools import lru_cache
from pathlib import Path
from typing import Literal
from urllib.parse import quote

from pydantic import SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict

BASE_DIR = Path(__file__).resolve().parents[3]


class Settings(BaseSettings):
    environment: Literal["local", "ci", "production"]
    log_level: str = "INFO"

    secret_key: SecretStr

    postgres_user: str
    postgres_password: SecretStr
    postgres_host: str
    postgres_port: int = 5432
    postgres_db: str

    redis_url: str

    model_config = SettingsConfigDict(
        env_file=BASE_DIR / ".env",
        extra="forbid",
    )

    @property
    def database_url(self) -> str:
        user = quote(self.postgres_user, safe="")
        password = quote(self.postgres_password.get_secret_value(), safe="")
        return (
            f"postgresql+asyncpg://{user}:{password}"
            f"@{self.postgres_host}:{self.postgres_port}/{self.postgres_db}"
        )


@lru_cache
def get_settings() -> Settings:
    return Settings()
