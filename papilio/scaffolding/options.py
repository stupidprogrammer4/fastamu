from enum import StrEnum


class Infrastructure(StrEnum):
    POSTGRESQL = "postgresql"
    ES = "es"
    REDIS = "redis"
    RATE_LIMIT = "rate-limit"
    HTTP = "http"
    EXCEL = "excel"
    FILES = "files"
    CSV = "csv"
