from typing import TypeVar
from .base import PGRepository, PGIDRepository, PGTimestampIDRepository

TPGRepository = TypeVar(
    "TPGRepository",
    bound=PGRepository
)
TPGIDRepository = TypeVar(
    "TPGIDRepository",
    bound=PGIDRepository
)
TPGTimestampIDRepository = TypeVar(
    "TPGTimestampIDRepository",
    bound=PGTimestampIDRepository
)