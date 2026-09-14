"""Provider suggestions without importing optional infrastructure."""

from dataclasses import dataclass
from importlib.metadata import PackageNotFoundError, version


@dataclass(frozen=True)
class ProviderSpec:
    name: str
    module: str
    cls: str
    extra: str
    dependencies: tuple[str, ...]
    config: str

    def missing(self) -> tuple[str, ...]:
        """Check installed distributions without importing their modules."""
        missing = []
        for name in self.dependencies:
            try:
                version(name)
            except PackageNotFoundError:
                missing.append(name)
        return tuple(missing)


PROVIDERS = (
    ProviderSpec(
        "pg",
        "db",
        "PGProvider",
        "postgresql",
        ("sqlalchemy", "sqlmodel", "asyncpg"),
        "db",
    ),
    ProviderSpec(
        "mysql",
        "db",
        "MySQLProvider",
        "mysql",
        ("sqlalchemy", "sqlmodel", "asyncmy"),
        "db",
    ),
    ProviderSpec(
        "mariadb",
        "db",
        "MariaDBProvider",
        "mariadb",
        ("sqlalchemy", "sqlmodel", "asyncmy"),
        "db",
    ),
    ProviderSpec(
        "sqlite",
        "db",
        "SQLiteProvider",
        "sqlite",
        ("sqlalchemy", "sqlmodel", "aiosqlite"),
        "db",
    ),
    ProviderSpec(
        "oracle",
        "db",
        "OracleProvider",
        "oracle",
        ("sqlalchemy", "sqlmodel", "oracledb"),
        "db",
    ),
    ProviderSpec(
        "mssql",
        "db",
        "MSSQLProvider",
        "mssql",
        ("sqlalchemy", "sqlmodel", "aioodbc", "pyodbc"),
        "db",
    ),
    ProviderSpec(
        "es", "es", "ESProvider", "es", ("elasticsearch", "aiohttp"), "es"
    ),
    ProviderSpec(
        "redis", "redis", "RedisProvider", "redis", ("redis",), "redis"
    ),
    ProviderSpec("http", "http", "HTTPProvider", "http", ("httpx",), "http"),
    ProviderSpec(
        "rate-memory",
        "rate_limit.memory",
        "MemoryRateProvider",
        "rate-limit",
        ("throttled-py",),
        "",
    ),
    ProviderSpec(
        "rate-redis",
        "rate_limit.redis",
        "RedisRateProvider",
        "rate-limit-redis",
        ("throttled-py", "redis"),
        "",
    ),
    ProviderSpec(
        "passwords",
        "passwords",
        "PasswordProvider",
        "passwords",
        ("bcrypt",),
        "crypto.password_salt",
    ),
)
