from __future__ import annotations

from enum import StrEnum
from functools import lru_cache
from importlib import import_module
from pathlib import Path
from typing import Literal, TypeVar, overload

import yaml
from pydantic import BaseModel, ConfigDict, Field, model_validator


class Feature(StrEnum):
    CQRS = "cqrs"


class AppConfig(BaseModel):
    """What this application *is* — the packages its modules live in.

    The bootstrapper walks these and finds everything else. List your own
    package first; add `papilio.modules` to adopt the framework's `ops`
    reference modules (messages, storage, system) as they are.
    """

    modules: list[str] = Field(default_factory=list)
    features: set[Feature] = Field(default_factory=set)
    settings: str | None = None


class FastAPIConfig(BaseModel):
    title: str
    description: str
    version: str


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

    enabled: bool = False
    trusted_proxies: list[str] = Field(default_factory=list)
    general: RateLimitRule = RateLimitRule(limit=120, window_seconds=60)
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
    index: str = Field(default="logs", min_length=1)


class Settings(BaseModel):
    model_config = ConfigDict(extra="forbid")

    app: AppConfig = AppConfig()
    fastapi: FastAPIConfig
    db: DatabaseConfig | None = None
    crypto: CryptoConfig
    redis: RedisConfig | None = None
    rate_limit: RateLimitConfig = RateLimitConfig()
    jwt: JWTConfig
    storage: StorageConfig
    csrf: CSRFConfig
    es: ESConfig | None = None
    http: HTTPConfig | None = None
    logging: LoggingConfig

    @model_validator(mode="after")
    def validate_features(self):
        if Feature.CQRS in self.app.features and self.es is None:
            raise ValueError("CQRS requires es configuration")
        return self


class FullSettings(Settings):
    """Every optional subsystem present, for a project installed with all
    the extras. Narrows the shapes the base leaves optional so a caller
    reads them without a None check."""

    db: DatabaseConfig = Field(...)  # pyright: ignore[reportGeneralTypeIssues]
    redis: RedisConfig = Field(...)  # pyright: ignore[reportGeneralTypeIssues]
    http: HTTPConfig = Field(...)  # pyright: ignore[reportGeneralTypeIssues]
    es: ESConfig = Field(...)  # pyright: ignore[reportGeneralTypeIssues]


SettingsT = TypeVar("SettingsT", bound=Settings)


def _settings_model(raw: object) -> type[Settings]:
    model: type[Settings] = Settings
    app = raw.get("app") if isinstance(raw, dict) else None
    dotted = app.get("settings") if isinstance(app, dict) else None
    if dotted:
        if not isinstance(dotted, str) or "." not in dotted:
            raise ValueError("app.settings must be a dotted model path")
        module_name, class_name = dotted.rsplit(".", 1)
        selected = getattr(import_module(module_name), class_name)
        if not isinstance(selected, type) or not issubclass(
            selected, Settings
        ):
            raise TypeError("app.settings must reference a Settings subclass")
        model = selected
    return model


@overload
def get_settings() -> Settings: ...


@overload
def get_settings(model: type[SettingsT]) -> SettingsT: ...


@lru_cache
def get_settings(model: type[SettingsT] | None = None) -> SettingsT | Settings:
    path = Path("config.yml")
    with path.open("r", encoding="utf-8") as f:
        raw = yaml.safe_load(f)
    selected = model or _settings_model(raw)
    if model is None and selected is not Settings:
        settings: SettingsT | Settings = get_settings(selected)
    else:
        settings = selected.model_validate(raw)
    return settings
