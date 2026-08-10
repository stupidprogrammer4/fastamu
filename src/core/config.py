from __future__ import annotations

from functools import lru_cache
from pathlib import Path
from typing import Literal

import yaml
from pydantic import BaseModel, Field


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


class RateLimitRule(BaseModel):
    """One budget: `limit` calls per `window_seconds`."""

    limit: int = Field(gt=0)
    window_seconds: int = Field(gt=0)


class RateLimitConfig(BaseModel):
    """The rate-limit budgets, all of them tunable without a deploy.

    `general` is the blanket rule the middleware applies to every request;
    `rules` are the named ones a route asks for by name via
    `rate_limit("login")` — a route whose name is missing here is simply not
    limited, so a rule can be dropped from the config to turn it off.

    `trusted_proxies` lists the peers whose ``X-Forwarded-For`` may be
    believed. Leave it empty when nothing sits in front of the app: an unvetted
    header is a free way to spoof a fresh bucket per call."""

    enabled: bool = True
    trusted_proxies: list[str] = Field(default_factory=list)
    general: RateLimitRule
    rules: dict[str, RateLimitRule] = Field(default_factory=dict)


class JWTConfig(BaseModel):
    algorithm: str
    secret_key: str
    access_token_expire_minutes: int = Field(ge=1)
    # long-lived refresh token; trades for a fresh access token at
    # /auth/*/refresh
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


class LoggingConfig(BaseModel):
    """`console` for a readable terminal, `json` for one ECS object per
    line."""

    level: str
    format: Literal["console", "json"]
    service: str


class Settings(BaseModel):
    fastapi: FastAPIConfig
    taskiq: TaskiqConfig
    postgresql: PostgreSQLConfig
    crypto: CryptoConfig
    redis: RedisConfig
    rate_limit: RateLimitConfig
    jwt: JWTConfig
    storage: StorageConfig
    csrf: CSRFConfig
    es: ESConfig
    logging: LoggingConfig


@lru_cache
def get_settings() -> Settings:
    path = Path("config.yml")
    with path.open("r", encoding="utf-8") as f:
        raw = yaml.safe_load(f)
    return Settings.model_validate(raw)
