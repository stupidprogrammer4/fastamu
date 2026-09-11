"""Only explicit outbox delivery scopes collect persisted message IDs."""

import asyncio
from contextvars import ContextVar
from dataclasses import dataclass, field
from uuid import UUID

from fastamu.infra.db.uow import DBUnitOfWork


@dataclass
class Receipts:
    unit: DBUnitOfWork
    owner: asyncio.Task | None
    ids: list[UUID] = field(default_factory=list)
    active: bool = True

    def check(self):
        if not self.active or self.owner is not asyncio.current_task():
            raise RuntimeError("Outbox delivery scope belongs to another task")
        if self.unit is not DBUnitOfWork.current():
            raise RuntimeError("Cannot switch UoW in an outbox delivery scope")


current: ContextVar[Receipts | None] = ContextVar(
    "outbox_receipts", default=None
)
