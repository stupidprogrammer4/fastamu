from typing import Any, Optional, Sequence

from sqlalchemy import ColumnElement, and_, true
from sqlmodel import col, select, update

from papilio.infra.db.repositories.backends.postgresql import (
    PostgreSQLIdentifiedRepository,
)
from papilio.infra.db.tools.read import fetch_page
from papilio.modules.ops.messages.domain.context import (
    MessageContext,
    ProviderContext,
)
from papilio.modules.ops.messages.domain.entities import (
    MessageEntity,
    SMSPatternEntity,
    SMSProviderEntity,
)
from papilio.modules.ops.messages.domain.enums import (
    MessageStatus,
    PatternKey,
    ProviderCode,
)
from papilio.modules.ops.messages.infra.tables import (
    MessageTable,
    SMSPatternTable,
    SMSProviderTable,
)
from papilio.schemas.results import PagedType


class SMSProviderRepository(PostgreSQLIdentifiedRepository[SMSProviderEntity]):
    table = SMSProviderTable

    async def get_by_id(
        self,
        id: int,
        is_active: Optional[bool] = None,
    ) -> Optional[SMSProviderEntity]:
        """
        Get one provider by id.

        Args:
            id (int): ID of the provider.
            is_active (Optional[bool]): Keep only providers switched this way
                when given.
        Returns:
            (Optional[SMSProviderEntity]): The provider, or None.
        """
        stmt = select(self.table).where(col(self.table.id) == id)
        if is_active is not None:
            stmt = stmt.where(col(self.table.is_active).is_(is_active))
        result = await self.uow.execute(stmt)
        return result.scalar_one_or_none()

    async def get_by_code(
        self,
        code: ProviderCode,
        is_active: Optional[bool] = None,
    ) -> Optional[SMSProviderEntity]:
        """
        Get one provider by its code.

        Args:
            code (ProviderCode): The provider's code.
            is_active (Optional[bool]): Keep only providers switched this way
                when given.
        Returns:
            (Optional[SMSProviderEntity]): The provider, or None.
        """
        stmt = select(self.table).where(col(self.table.code) == code)
        if is_active is not None:
            stmt = stmt.where(col(self.table.is_active).is_(is_active))
        result = await self.uow.execute(stmt)
        return result.scalar_one_or_none()

    async def get_by_codes(
        self,
        codes: Optional[Sequence[ProviderCode]] = None,
        is_active: Optional[bool] = None,
    ) -> Sequence[SMSProviderEntity]:
        """
        Get the providers matching the given filters.

        Args:
            codes (Optional[Sequence[ProviderCode]]): Keep only these codes
                when given.
            is_active (Optional[bool]): Keep only providers switched this way
                when given.
        Returns:
            (Sequence[SMSProviderEntity]): The providers that match.
        """
        stmt = select(self.table)
        if codes is not None:
            stmt = stmt.where(col(self.table.code).in_(list(codes)))
        if is_active is not None:
            stmt = stmt.where(col(self.table.is_active).is_(is_active))
        result = await self.uow.execute(stmt)
        return result.scalars().all()

    async def save(self, row: SMSProviderEntity) -> SMSProviderEntity:
        """
        Write a provider down, rewriting the one already registered under its
        code.

        Args:
            row (SMSProviderEntity): The provider to write.
        Returns:
            (SMSProviderEntity): The written provider.
        """
        columns = SMSProviderTable.__table__.c
        return await self.upsert(
            row,
            conflict_columns=[columns.code],
            update_columns=[columns.title, columns.credentials],
        )

    async def update_is_active(
        self,
        is_active: bool,
        exclude_id: Optional[int] = None,
        current: Optional[bool] = None,
    ) -> None:
        """
        Switch providers in one statement.

        Args:
            is_active (bool): What to switch the matched providers to.
            exclude_id (Optional[int]): Leave this provider untouched when
                given.
            current (Optional[bool]): Match only providers switched this way
                when given.
        """
        conditions: list[ColumnElement[bool]] = [true()]
        if exclude_id is not None:
            conditions.append(col(self.table.id) != exclude_id)
        if current is not None:
            conditions.append(col(self.table.is_active).is_(current))
        where = and_(*conditions)
        stmt = update(self.table).where(where).values(is_active=is_active)
        stmt = stmt.execution_options(synchronize_session=False)
        await self.uow.execute(stmt)


class SMSPatternRepository(PostgreSQLIdentifiedRepository[SMSPatternEntity]):
    table = SMSPatternTable

    async def get_by_key(self, key: PatternKey) -> Optional[SMSPatternEntity]:
        """
        Get the template registered for one message key.

        Args:
            key (PatternKey): The message key, such as `otp`.
        Returns:
            (Optional[SMSPatternEntity]): The pattern, or None.
        """
        stmt = select(self.table).where(col(self.table.key) == key)
        result = await self.uow.execute(stmt)
        return result.scalar_one_or_none()

    async def get_by_keys(
        self,
        keys: Optional[Sequence[PatternKey]] = None,
    ) -> Sequence[SMSPatternEntity]:
        """
        Get the templates matching the given filters.

        Args:
            keys (Optional[Sequence[PatternKey]]): Keep only these keys when
                given.
        Returns:
            (Sequence[SMSPatternEntity]): The patterns that match.
        """
        stmt = select(self.table).order_by(col(self.table.key))
        if keys is not None:
            stmt = stmt.where(col(self.table.key).in_(list(keys)))
        result = await self.uow.execute(stmt)
        return result.scalars().all()

    async def save(self, row: SMSPatternEntity) -> SMSPatternEntity:
        """
        Write a pattern down, rewriting the one already registered under its
        key.

        Args:
            row (SMSPatternEntity): The pattern to write.
        Returns:
            (SMSPatternEntity): The written pattern.
        """
        columns = SMSPatternTable.__table__.c
        return await self.upsert(
            row,
            conflict_columns=[columns.key],
            update_columns=[columns.pattern],
        )


class MessageRepository(PostgreSQLIdentifiedRepository[MessageEntity]):
    table = MessageTable

    async def get_page(
        self,
        status: Optional[MessageStatus] = None,
        recipient: Optional[str] = None,
        offset: int = 0,
        limit: int = 20,
    ) -> PagedType[MessageEntity]:
        """
        Get a page of messages, newest first.

        Args:
            status (Optional[MessageStatus]): Keep only messages in this
                status when given.
            recipient (Optional[str]): Keep only messages to this number when
                given.
            offset (int): How many rows to skip.
            limit (int): How many rows to take.
        Returns:
            (PagedType[MessageEntity]): The page and the total count.
        """
        stmt = select(self.table).order_by(col(self.table.id).desc())
        if status is not None:
            stmt = stmt.where(col(self.table.status) == status)
        if recipient is not None:
            stmt = stmt.where(col(self.table.recipient) == recipient)
        return await fetch_page(self.uow, stmt, offset=offset, limit=limit)

    async def get_context_by_id(
        self,
        id: int,
        is_active: Optional[bool] = None,
    ) -> Optional[MessageContext]:
        """
        Read a message together with the provider it would go out through, so
        a delivery costs one query rather than two.

        Args:
            id (int): ID of the message.
            is_active (Optional[bool]): Join only providers switched this way
                when given.
        Returns:
            (Optional[MessageContext]): The message and the provider joined to
                it, or None when the message does not exist.
        """
        stmt = self._context_stmt(is_active).where(col(self.table.id) == id)
        result = await self.uow.execute(stmt)
        row = result.first()
        return None if row is None else self._context(row)

    async def get_contexts_by_ids(
        self,
        ids: Sequence[int],
        is_active: Optional[bool] = None,
    ) -> Sequence[MessageContext]:
        """
        Read several messages together with the provider they would go out
        through, so delivering a batch costs one query.

        Args:
            ids (Sequence[int]): IDs of the messages.
            is_active (Optional[bool]): Join only providers switched this way
                when given.
        Returns:
            (Sequence[MessageContext]): One entry per message that exists,
                each with the provider joined to it.
        """
        stmt = self._context_stmt(is_active).where(
            col(self.table.id).in_(list(ids))
        )
        result = await self.uow.execute(stmt)
        return [self._context(row) for row in result.all()]

    async def save_delivery_results(
        self,
        data: Sequence[MessageEntity],
    ) -> Sequence[MessageEntity]:
        columns = MessageTable.__table__.c
        return await self.bulk_update(
            [item.to_row() for item in data],
            key_columns=[columns.id],
            update_columns=[
                columns.tries,
                columns.status,
                columns.error,
                columns.provider_message_id,
                columns.sent_at,
            ],
        )

    def _context_stmt(self, is_active: Optional[bool]) -> Any:
        # an outer join on a constant: there is no key between a message and
        # the provider it has not been sent through yet, so the active one is
        # attached by the join condition itself and a message with no provider
        # still comes back
        provider_table = SMSProviderTable
        onclause = (
            col(provider_table.is_active).is_(is_active)
            if is_active is not None
            else true()
        )
        return select(
            self.table,
            col(provider_table.id).label("provider_id"),
            col(provider_table.code).label("provider_code"),
            col(provider_table.credentials).label("credentials"),
        ).join(provider_table, onclause, isouter=True)

    def _context(self, row: Any) -> MessageContext:
        provider = None
        if row.provider_id is not None:
            provider = ProviderContext(
                id=row.provider_id,
                code=row.provider_code,
                credentials=row.credentials,
            )
        return MessageContext(message=row[0], provider=provider)
