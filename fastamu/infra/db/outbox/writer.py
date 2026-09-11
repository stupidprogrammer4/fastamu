"""Append using the business transaction, without committing or publishing."""

from uuid import UUID

from fastamu.core.config import get_settings
from fastamu.infra.db.outbox.table import outbox
from fastamu.infra.db.transaction import current_transaction, transaction
from fastamu.messaging.outbox import receipts
from fastamu.messaging.outbox.message import OutboxMessage


def require_transaction():
    scope = current_transaction()
    if get_settings().tasks.outbox is None:
        raise RuntimeError("Outbox is disabled; configure tasks.outbox")
    collected = receipts.current.get()
    if collected is not None:
        collected.check()
    return scope


async def append(message: OutboxMessage) -> UUID:
    scope = require_transaction()
    # Joining marks the owner rollback-only even if the caller catches failure.
    async with transaction():
        await scope.unit.session.execute(
            outbox.insert().values(
                id=message.id,
                kind=message.kind,
                target=message.target,
                payload=message.payload,
            )
        )
        collected = receipts.current.get()
        if collected is not None:
            collected.ids.append(message.id)
    return message.id
