from __future__ import annotations

from functools import lru_cache
from pathlib import Path
from typing import Literal

import yaml
from pydantic import BaseModel, Field, model_validator


class AppConfig(BaseModel):
    """What this application *is* — the packages its modules live in.

    The bootstrapper walks these and finds everything else. List your own
    package first; add `fastamu.modules` to adopt the framework's `ops`
    reference modules (jobs, messages, storage, system) as they are.
    """

    modules: list[str] = Field(min_length=1)


class FastAPIConfig(BaseModel):
    title: str
    description: str
    version: str


type Broker = Literal["redis", "rabbitmq"]
"""Supported broker names."""


class EventsConfig(BaseModel):
    """Connection settings for the event broker."""

    broker: Broker
    url: str = Field(min_length=1)


class SchedulersConfig(BaseModel):
    """Jobs and the cron that starts them, on whichever broker you name.

    No retry policy here on purpose. Whether repeating a job is safe is a
    property of the job, not of the framework, so a module declares its own
    on the task it registers.
    """

    broker: Literal["redis"] = "redis"
    url: str = Field(min_length=1)
    max_connection_pool_size: int = Field(default=25, ge=1)
    result_ex_time: int = Field(default=86_400, gt=0)


class ProjectionConfig(BaseModel):
    broker: Literal["rabbitmq"] = "rabbitmq"
    url: str = Field(min_length=1)
    prefetch: Literal[1] = 1
    max_retries: int = Field(default=3, ge=0)
    retry_delay: float = Field(default=1.0, gt=0)


class TasksConfig(BaseModel):
    # Omitted/null sections are disabled; no connection settings are required.
    events: EventsConfig | None = None
    projection: ProjectionConfig | None = None
    schedulers: SchedulersConfig | None = None


class DatabaseConfig(BaseModel):
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


class HTTPConfig(BaseModel):
    """The outbound client's pool and timeouts — see `HTTPConnection`."""

    max_connections: int = Field(ge=1)
    max_keepalive_connections: int = Field(ge=0)
    keepalive_expiry: float = Field(ge=0)
    timeout: float = Field(gt=0)
    connect_timeout: float = Field(gt=0)
    follow_redirects: bool = True


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
    app: AppConfig = AppConfig(modules=["fastamu.modules"])
    fastapi: FastAPIConfig
    tasks: TasksConfig = Field(default_factory=TasksConfig)
    db: DatabaseConfig
    crypto: CryptoConfig
    redis: RedisConfig
    rate_limit: RateLimitConfig
    jwt: JWTConfig
    storage: StorageConfig
    csrf: CSRFConfig
    es: ESConfig | None = None
    http: HTTPConfig
    logging: LoggingConfig

    @model_validator(mode="after")
    def validate_cqrs(self):
        if self.tasks.projection is not None and self.es is None:
            raise ValueError("CQRS projection requires es configuration")
        return self


@lru_cache
def get_settings() -> Settings:
    path = Path("config.yml")
    with path.open("r", encoding="utf-8") as f:
        raw = yaml.safe_load(f)
    return Settings.model_validate(raw)
