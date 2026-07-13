from typing import TypeVar
from .base import (
    BaseModel,
    BaseIDModel,
    BaseIDTimestampModel,
    BaseTimestampModel
)

TModel = TypeVar("TModel", bound=BaseModel)
TIDModel = TypeVar("TIDModel", bound=BaseIDModel)
TTimestampModel = TypeVar("TTimestampModel", bound=BaseTimestampModel)
TIDTimestampModel = TypeVar("TIDTimestampModel", bound=BaseIDTimestampModel)