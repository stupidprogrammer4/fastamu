from __future__ import annotations

from abc import ABC, abstractmethod
from .schemas import BaseErrorOut


class APPException[T: BaseErrorOut](Exception, ABC):
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
