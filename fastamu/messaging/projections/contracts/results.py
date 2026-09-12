from collections.abc import Mapping
from dataclasses import dataclass

from pydantic import JsonValue


@dataclass(frozen=True, slots=True)
class BulkItemResult:
    id: str
    status: int
    error: Mapping[str, JsonValue] | None = None
    # The writer's decision that repeating this operation cannot help.
    final: bool = False

    @property
    def succeeded(self) -> bool:
        return 200 <= self.status < 300 and self.error is None

    @property
    def settled(self) -> bool:
        """Done with, written or not. No status is interpreted here."""
        return self.succeeded or self.final


class ProjectionBatchError(Exception):
    def __init__(self, results: list[BulkItemResult]) -> None:
        self.results = results
        failed = sum(not result.settled for result in results)
        super().__init__(f"{failed} projection operations failed")
