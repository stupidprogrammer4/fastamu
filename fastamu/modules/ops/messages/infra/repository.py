from typing import Any, Optional, Sequence

from sqlalchemy import ColumnElement, and_, true
from sqlmodel import col, select, update

from fastamu.common.schemas.results import PagedType
from fastamu.infra.db.repository import DBIDRepository
from fastamu.infra.db.uow import DBUnitOfWork
from fastamu.modules.ops.messages.domain.context import (
    MessageContext,
    ProviderContext,
)
from fastamu.modules.ops.messages.domain.enums import (
    MessageStatus,
    PatternKey,
    ProviderCode,
)
from fastamu.modules.ops.messages.domain.models import (
    MessageModel,
    SMSPatternModel,
    SMSProviderModel,
)


class SMSProviderRepository(DBIDRepository[SMSProviderModel]):
    def __init__(self, uow: DBUnitOfWork):
        super().__init__(uow)

    async def get_by_id(
        self,
        id: int,
        is_active: Optional[bool] = None,
    ) -> Optional[SMSProviderModel]:
        """
        Get one provider by id.

        Args:
            id (int): ID of the provider.
            is_active (Optional[bool]): Keep only providers switched this way
                when given.
        Returns:
            (Optional[SMSProviderModel]): The provider, or None.
        """
        stmt = select(self.__table__).where(col(self.__table__.id) == id)
        if is_active is not None:
            stmt = stmt.where(col(self.__table__.is_active).is_(is_active))
        result = await self.session.execute(stmt)
        return result.scalar_one_or_none()

    async def get_by_code(
        self,
        code: ProviderCode,
        is_active: Optional[bool] = None,
    ) -> Optional[SMSProviderModel]:
        """
        Get one provider by its code.

        Args:
            code (ProviderCode): The provider's code.
            is_active (Optional[bool]): Keep only providers switched this way
                when given.
        Returns:
            (Optional[SMSProviderModel]): The provider, or None.
        """
        stmt = select(self.__table__).where(col(self.__table__.code) == code)
        if is_active is not None:
            stmt = stmt.where(col(self.__table__.is_active).is_(is_active))
        result = await self.session.execute(stmt)
        return result.scalar_one_or_none()

    async def get_by_codes(
        self,
        codes: Optional[Sequence[ProviderCode]] = None,
        is_active: Optional[bool] = None,
    ) -> Sequence[SMSProviderModel]:
        """
        Get the providers matching the given filters.

        Args:
            codes (Optional[Sequence[ProviderCode]]): Keep only these codes
                when given.
            is_active (Optional[bool]): Keep only providers switched this way
                when given.
        Returns:
            (Sequence[SMSProviderModel]): The providers that match.
        """
        stmt = select(self.__table__)
        if codes is not None:
            stmt = stmt.where(col(self.__table__.code).in_(list(codes)))
        if is_active is not None:
            stmt = stmt.where(col(self.__table__.is_active).is_(is_active))
        result = await self.session.execute(stmt)
        return result.scalars().all()

    async def upsert(self, row: SMSProviderModel) -> SMSProviderModel:
        """
        Write a provider down, rewriting the one already registered under its
        code.

        Args:
            row (SMSProviderModel): The provider to write.
        Returns:
            (SMSProviderModel): The written provider.
        """
        rows = await self.upsert_rows([row], [col(self.__table__.code)])
        return rows[0]

    async def update_is_active(
        self,
        is_active: bool,
        exclude_id: Optional[int] = None,
        current: Optional[bool] = None,
    ) -> Sequence[SMSProviderModel]:
        """
        Switch providers in one statement.

        Args:
            is_active (bool): What to switch the matched providers to.
            exclude_id (Optional[int]): Leave this provider untouched when
                given.
            current (Optional[bool]): Match only providers switched this way
                when given.
        Returns:
            (Sequence[SMSProviderModel]): The providers written.
        """
        conditions: list[ColumnElement[bool]] = [true()]
        if exclude_id is not None:
            conditions.append(col(self.__table__.id) != exclude_id)
        if current is not None:
            conditions.append(col(self.__table__.is_active).is_(current))
        where = and_(*conditions)
        stmt = update(self.__table__).where(where).values(is_active=is_active)
        return await self._mutate(stmt, where)


class SMSPatternRepository(DBIDRepository[SMSPatternModel]):
    def __init__(self, uow: DBUnitOfWork):
        super().__init__(uow)

    async def get_by_key(self, key: PatternKey) -> Optional[SMSPatternModel]:
        """
        Get the template registered for one message key.

        Args:
            key (PatternKey): The message key, such as `otp`.
        Returns:
            (Optional[SMSPatternModel]): The pattern, or None.
        """
        stmt = select(self.__table__).where(col(self.__table__.key) == key)
        result = await self.session.execute(stmt)
        return result.scalar_one_or_none()

    async def get_by_keys(
        self,
        keys: Optional[Sequence[PatternKey]] = None,
    ) -> Sequence[SMSPatternModel]:
        """
        Get the templates matching the given filters.

        Args:
            keys (Optional[Sequence[PatternKey]]): Keep only these keys when
                given.
        Returns:
            (Sequence[SMSPatternModel]): The patterns that match.
        """
        stmt = select(self.__table__).order_by(col(self.__table__.key))
        if keys is not None:
            stmt = stmt.where(col(self.__table__.key).in_(list(keys)))
        result = await self.session.execute(stmt)
        return result.scalars().all()

    async def upsert(self, row: SMSPatternModel) -> SMSPatternModel:
        """
        Write a pattern down, rewriting the one already registered under its
        key.

        Args:
            row (SMSPatternModel): The pattern to write.
        Returns:
            (SMSPatternModel): The written pattern.
        """
        rows = await self.upsert_rows([row], [col(self.__table__.key)])
        return rows[0]


class MessageRepository(DBIDRepository[MessageModel]):
    def __init__(self, uow: DBUnitOfWork):
        super().__init__(uow)

    async def bulk_update(
        self,
        items: Sequence[MessageModel],
    ) -> Sequence[MessageModel]:
        """
        Write each given message's own columns in one statement.

        Args:
            items (Sequence[MessageModel]): The messages to write.
        Returns:
            (Sequence[MessageModel]): The written messages.
        """
        return await self.bulk_update_rows(items, col(self.__table__.id))

    async def get_page(
        self,
        status: Optional[MessageStatus] = None,
        recipient: Optional[str] = None,
        offset: int = 0,
        limit: int = 20,
    ) -> PagedType[MessageModel]:
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
            (PagedType[MessageModel]): The page and the total count.
        """
        stmt = select(self.__table__).order_by(col(self.__table__.id).desc())
        if status is not None:
            stmt = stmt.where(col(self.__table__.status) == status)
        if recipient is not None:
            stmt = stmt.where(col(self.__table__.recipient) == recipient)
        return await self._paginate(stmt, offset, limit)

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
        stmt = self._context_stmt(is_active).where(
            col(self.__table__.id) == id
        )
        result = await self.session.execute(stmt)
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
            col(self.__table__.id).in_(list(ids))
        )
        result = await self.session.execute(stmt)
        return [self._context(row) for row in result.all()]

    def _context_stmt(self, is_active: Optional[bool]) -> Any:
        # an outer join on a constant: there is no key between a message and
        # the provider it has not been sent through yet, so the active one is
        # attached by the join condition itself and a message with no provider
        # still comes back
        provider_table = self._tabled(SMSProviderModel)
        onclause = (
            col(provider_table.is_active).is_(is_active)
            if is_active is not None
            else true()
        )
        return select(
            self.__table__,
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
