"""Consumer receipts within the caller's SQL transaction."""

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncConnection, AsyncSession

from fastamu.infra.db.dialects import DIALECTS, DatabaseDialect
from fastamu.infra.db.inbox.table import inbox


class InboxRepository:
    def __init__(self, session: AsyncSession):
        self.session = session

    async def claim(self, consumer: str, message_id: str) -> bool:
        """Reserve an identity without committing or flushing ORM changes."""
        if not self.session.in_transaction():
            raise RuntimeError("Inbox claim requires an active transaction")
        connection = await self.session.connection()
        adapter = DIALECTS.get(connection.dialect.name, DatabaseDialect)()
        values = {"consumer": consumer, "message_id": message_id}
        statement = adapter.insert_if_absent(
            inbox, values, ("consumer", "message_id")
        )
        if statement is not None:
            result = await connection.execute(statement)
            if result.first() is not None:
                return True
            if not await self._exists(connection, consumer, message_id):
                raise ValueError(
                    "Conflicting row does not match the exact key"
                )
            return False

        try:
            async with connection.begin_nested():
                await connection.execute(inbox.insert().values(values))
            return True
        except IntegrityError as error:
            if (
                adapter.name != "generic"
                and adapter.unique_values(error) is None
            ):
                raise
            if not await self._exists(connection, consumer, message_id):
                raise
            return False

    async def _exists(
        self, connection: AsyncConnection, consumer: str, message_id: str
    ) -> bool:
        # A locking read also sees the winner under MySQL's REPEATABLE READ.
        result = await connection.execute(
            select(inbox.c.consumer, inbox.c.message_id)
            .where(
                inbox.c.consumer == consumer, inbox.c.message_id == message_id
            )
            .with_for_update(read=True)
        )
        existing = result.one_or_none()
        return existing is not None and tuple(existing) == (
            consumer,
            message_id,
        )
