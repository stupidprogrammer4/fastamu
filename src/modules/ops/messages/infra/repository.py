from typing import Any, Optional, Sequence

from sqlalchemy import true
from sqlmodel import col, select, update

from src.common.bases.results import PagedType
from src.infra.postgres.repository.base import PGIDRepository
from src.infra.postgres.uow import PGUnitOfWork
from src.modules.ops.messages.domain.context import (
    MessageContext,
    ProviderContext,
)
from src.modules.ops.messages.domain.enums import (
    MessageStatus,
    PatternKey,
    ProviderCode,
)
from src.modules.ops.messages.domain.models import (
    MessageModel,
    SMSPatternModel,
    SMSProviderModel,
)


class SMSProviderRepository(PGIDRepository[SMSProviderModel]):
    def __init__(self, uow: PGUnitOfWork):
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
        stmt = select(SMSProviderModel).where(col(SMSProviderModel.id) == id)
        if is_active is not None:
            stmt = stmt.where(col(SMSProviderModel.is_active).is_(is_active))
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
        stmt = select(SMSProviderModel).where(
            col(SMSProviderModel.code) == code
        )
        if is_active is not None:
            stmt = stmt.where(col(SMSProviderModel.is_active).is_(is_active))
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
        stmt = select(SMSProviderModel)
        if codes is not None:
            stmt = stmt.where(col(SMSProviderModel.code).in_(list(codes)))
        if is_active is not None:
            stmt = stmt.where(col(SMSProviderModel.is_active).is_(is_active))
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
        stmt = self._upsert_stmt(row, [col(SMSProviderModel.code)])
        result = await self.session.execute(
            stmt, execution_options={"populate_existing": True}
        )
        return result.scalars().one()

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
        stmt = update(SMSProviderModel).values(is_active=is_active)
        if exclude_id is not None:
            stmt = stmt.where(col(SMSProviderModel.id) != exclude_id)
        if current is not None:
            stmt = stmt.where(col(SMSProviderModel.is_active).is_(current))
        result = await self.session.execute(stmt.returning(SMSProviderModel))
        return result.scalars().all()


class SMSPatternRepository(PGIDRepository[SMSPatternModel]):
    def __init__(self, uow: PGUnitOfWork):
        super().__init__(uow)

    async def get_by_key(self, key: PatternKey) -> Optional[SMSPatternModel]:
        """
        Get the template registered for one message key.

        Args:
            key (PatternKey): The message key, such as `otp`.
        Returns:
            (Optional[SMSPatternModel]): The pattern, or None.
        """
        stmt = select(SMSPatternModel).where(col(SMSPatternModel.key) == key)
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
        stmt = select(SMSPatternModel).order_by(col(SMSPatternModel.key))
        if keys is not None:
            stmt = stmt.where(col(SMSPatternModel.key).in_(list(keys)))
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
        stmt = self._upsert_stmt(row, [col(SMSPatternModel.key)])
        result = await self.session.execute(
            stmt, execution_options={"populate_existing": True}
        )
        return result.scalars().one()


class MessageRepository(PGIDRepository[MessageModel]):
    def __init__(self, uow: PGUnitOfWork):
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
        stmt = self._bulk_update_stmt(items, col(MessageModel.id))
        result = await self.session.execute(stmt)
        return result.scalars().all()

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
        stmt = select(MessageModel).order_by(col(MessageModel.id).desc())
        if status is not None:
            stmt = stmt.where(col(MessageModel.status) == status)
        if recipient is not None:
            stmt = stmt.where(col(MessageModel.recipient) == recipient)
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
        stmt = self._context_stmt(is_active).where(col(MessageModel.id) == id)
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
            col(MessageModel.id).in_(list(ids))
        )
        result = await self.session.execute(stmt)
        return [self._context(row) for row in result.all()]

    def _context_stmt(self, is_active: Optional[bool]) -> Any:
        # an outer join on a constant: there is no key between a message and
        # the provider it has not been sent through yet, so the active one is
        # attached by the join condition itself and a message with no provider
        # still comes back
        onclause = (
            col(SMSProviderModel.is_active).is_(is_active)
            if is_active is not None
            else true()
        )
        return select(
            MessageModel,
            col(SMSProviderModel.id).label("provider_id"),
            col(SMSProviderModel.code).label("provider_code"),
            col(SMSProviderModel.credentials).label("credentials"),
        ).join(SMSProviderModel, onclause, isouter=True)

    def _context(self, row: Any) -> MessageContext:
        provider = None
        if row.provider_id is not None:
            provider = ProviderContext(
                id=row.provider_id,
                code=row.provider_code,
                credentials=row.credentials,
            )
        return MessageContext(message=row[0], provider=provider)
