from __future__ import annotations

from functools import lru_cache
from pathlib import Path

import yaml
from pydantic import BaseModel, Field, SecretStr


class FastAPIConfig(BaseModel):
    title: str
    description: str
    version: str

class TaskiqConfig(BaseModel):
    redis_url: str
    max_connection_pool_size: int

class PostgreSQLConfig(BaseModel):
    test_dsn: str
    dsn: str
    pool_timeout: int = Field(ge=0)
    pool_recycle: int = Field(ge=0)
    pool_size: int
    max_overflow: int

class CryptoConfig(BaseModel):
    encryption_key: str
    password_salt: str

class RedisConfig(BaseModel):
    url: str
    max_connections: int = Field(ge=1)
    socket_timeout: float = Field(ge=0)
    socket_connect_timeout: float = Field(ge=0)
    health_check_interval: int = Field(ge=0)

class JWTConfig(BaseModel):
    algorithm: str
    secret_key: str
    access_token_expire_minutes: int = Field(ge=1)
    # long-lived refresh token; trades for a fresh access token at /auth/*/refresh
    refresh_token_expire_minutes: int = Field(default=60 * 24 * 14, ge=1)
    api_secret: str


class StorageConfig(BaseModel):
    path: str
    temp_dir: str
    max_file_size: int = Field(ge=1)
    allowed_extensions: list[str]

class CSRFConfig(BaseModel):
    secret_key: str

class ESConfig(BaseModel):
    hosts: list[str]
    username: str | None = None
    password: str | None = None
    api_key: str | None = None
    verify_certs: bool = True
    ca_certs: str | None = None


class Settings(BaseModel):
    fastapi: FastAPIConfig
    taskiq: TaskiqConfig
    postgresql: PostgreSQLConfig
    crypto: CryptoConfig
    redis: RedisConfig
    jwt: JWTConfig
    storage: StorageConfig
    csrf: CSRFConfig
    es: ESConfig


@lru_cache
def get_settings() -> Settings:
    path = Path("config.yml")
    with path.open("r", encoding="utf-8") as f:
        raw = yaml.safe_load(f)
    return Settings.model_validate(raw)
