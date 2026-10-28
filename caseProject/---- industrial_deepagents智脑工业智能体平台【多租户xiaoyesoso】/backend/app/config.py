"""Application settings loaded from the project-root .env file."""
from __future__ import annotations

import os
import secrets
from functools import lru_cache
from pathlib import Path

from dotenv import load_dotenv
from pydantic_settings import BaseSettings, SettingsConfigDict

# backend/app/config.py -> project root is three levels up
PROJECT_ROOT = Path(__file__).resolve().parents[2]
BACKEND_ROOT = Path(__file__).resolve().parents[1]

load_dotenv(PROJECT_ROOT / ".env", override=False)


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=str(PROJECT_ROOT / ".env"), extra="ignore")

    # Zhipu GLM (OpenAI-compatible) credentials
    api_key: str = ""
    base_url: str = "https://open.bigmodel.cn/api/paas/v4/"
    llm_model: str = "GLM-5.3-Flash"
    flash_llm_model: str = "GLM-5.3-Flash"
    embedding_model: str = "embedding-3"
    reranker_model: str = "rerank"

    # Auth
    jwt_secret: str = ""
    jwt_expire_hours: int = 72

    # Optional Langfuse integration
    langfuse_public_key: str = "" ##===================================
    langfuse_secret_key: str = "" ##===================================
    langfuse_host: str = "" ##===================================

    # Storage
    data_dir: str = str(BACKEND_ROOT / "data")
    minio_endpoint: str = "localhost:9000"
    minio_access_key: str = ""
    minio_secret_key: str = ""
    minio_bucket: str = "industrial-files"
    minio_secure: bool = False
    max_upload_size: int = 20 * 1024 * 1024

    # Sandbox hardening
    sandbox_timeout: int = 60
    sandbox_max_output: int = 20000

    @property
    def data_path(self) -> Path:
        p = Path(self.data_dir)##str(BACKEND_ROOT / "data")
        p.mkdir(parents=True, exist_ok=True)
        return p

    @property
    def db_path(self) -> Path:
        return self.data_path / "platform.db"

    @property
    def fs_root(self) -> Path:
        p = self.data_path / "fs"
        p.mkdir(parents=True, exist_ok=True)
        return p

    @property
    def jwt_secret_resolved(self) -> str:
        """JWT secret from env, or a persistent random value under data/."""
        if self.jwt_secret:
            return self.jwt_secret
        secret_file = self.data_path / ".jwt_secret"
        if secret_file.exists():
            return secret_file.read_text().strip()
        value = secrets.token_urlsafe(48)
        secret_file.write_text(value)
        try:
            os.chmod(secret_file, 0o600)
        except OSError:
            pass
        return value

    @property
    def langfuse_enabled(self) -> bool:
        return bool(self.langfuse_public_key and self.langfuse_secret_key and self.langfuse_host)


@lru_cache
def get_settings() -> Settings:
    return Settings()
