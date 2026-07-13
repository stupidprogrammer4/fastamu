from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Generic, TypeVar

from .schemas import BaseErrorOut

T = TypeVar("T", bound=BaseErrorOut)


class APPException(Exception, ABC, Generic[T]):
    def __init__(
        self,
        message: str,
        message_code: str,
        status_code: int,
        childs: list[APPException] | None = None,
    ) -> None:
        super().__init__(message)
        self.message = message
        self.message_code = message_code
        self.status_code = status_code
        self.childs = childs

    @abstractmethod
    def as_schema(self) -> T: ...
