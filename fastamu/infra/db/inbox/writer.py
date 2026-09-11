"""Reserve an identity inside the transaction that owns the business write."""

from fastamu.core.config import get_settings
from fastamu.infra.db.inbox.repository import InboxRepository
from fastamu.infra.db.transaction import current_transaction


async def claim(consumer: str, message_id: str) -> bool:
    scope = current_transaction()
    if not get_settings().tasks.inbox:
        raise RuntimeError("Inbox is disabled; configure tasks.inbox")
    for name, value in (("consumer", consumer), ("message_id", message_id)):
        if not isinstance(value, str) or not value.strip() or len(value) > 255:
            raise ValueError(f"Inbox {name} must contain 1 to 255 characters")
    return await InboxRepository(scope.unit.session).claim(
        consumer, message_id
    )
