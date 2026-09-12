from typing import Mapping, Sequence

from fastamu.common.errors.exceptions import (
    NotFoundException,
    ValidationException,
)
from fastamu.common.schemas.results import PagedType
from fastamu.common.services import BaseIDService
from fastamu.common.utils import dates
from fastamu.core import resources
from fastamu.infra.db.transaction import transactional
from fastamu.modules.ops.messages.config.constants import (
    MESSAGE_ID_ENCRYPTION,
)
from fastamu.modules.ops.messages.domain.context import MessageContext
from fastamu.modules.ops.messages.domain.dtos import (
    MessageSearch,
    SmsPatternUpsert,
    SmsProviderActivate,
    SmsProviderUpsert,
    SmsSend,
)
from fastamu.modules.ops.messages.domain.entities import (
    MessageEntity,
    SMSPatternEntity,
    SMSProviderEntity,
)
from fastamu.modules.ops.messages.domain.enums import (
    MessageChannel,
    MessageKind,
    MessageStatus,
    PatternKey,
    ProviderCode,
)
from fastamu.modules.ops.messages.domain.results import SmsDeliveryResult
from fastamu.modules.ops.messages.infra.repository import (
    MessageRepository,
    SMSPatternRepository,
    SMSProviderRepository,
)


class SMSProviderService(BaseIDService[SMSProviderEntity]):
    def __init__(self, repo: SMSProviderRepository) -> None:
        self.repo = repo

    async def get_all(self) -> Sequence[SMSProviderEntity]:
        """
        Get every registered provider.

        Returns:
            (Sequence[SMSProviderEntity]): All providers.
        """
        providers = await self.repo.get_by_codes()
        return providers

    async def get_by_code(self, code: ProviderCode) -> SMSProviderEntity:
        """
        Get one provider by its code.

        Args:
            code (ProviderCode): The provider's code.
        Returns:
            (SMSProviderEntity): The found provider.
        """
        provider = await self.repo.get_by_code(code)
        provider = self._check_for_existence("code", code, provider)
        return provider

    async def get_active(self) -> SMSProviderEntity:
        """
        Get the provider messages are sent through.

        Returns:
            (SMSProviderEntity): The active provider.
        """
        providers = await self.repo.get_by_codes(is_active=True)
        active = providers[0] if providers else None
        active = self._check_for_existence("is_active", True, active)
        return active

    @transactional
    async def upsert(self, data: SmsProviderUpsert) -> SMSProviderEntity:
        """
        Register a provider, replacing the one already under its code so its
        credentials can be rotated without a second row.

        Args:
            data (SmsProviderUpsert): The provider and its credentials.
        Returns:
            (SMSProviderEntity): The stored provider.
        """
        provider = await self.repo.upsert(
            SMSProviderEntity(**data.to_row(exclude_unset=False))
        )
        return provider

    @transactional
    async def activate(self, data: SmsProviderActivate) -> SMSProviderEntity:
        """
        Send messages through one provider from now on, switching off whichever
        was carrying them, so two are never active at once.

        Args:
            data (SmsProviderActivate): The provider to switch to.
        Returns:
            (SMSProviderEntity): The provider now in use.
        """
        provider = await self.get_by_code(data.code)
        await self.repo.update_is_active(
            is_active=False, exclude_id=provider.id, current=True
        )
        updated = await self.repo.update_row_by_id(
            provider.id, SMSProviderEntity(id=provider.id, is_active=True)
        )
        updated = self._check_for_id_existence(provider.id, updated)
        return updated


class SMSPatternService(BaseIDService[SMSPatternEntity]):
    def __init__(self, repo: SMSPatternRepository) -> None:
        self.repo = repo

    async def get_all(self) -> Sequence[SMSPatternEntity]:
        """
        Get every registered template.

        Returns:
            (Sequence[SMSPatternEntity]): All patterns, by key.
        """
        patterns = await self.repo.get_by_keys()
        return patterns

    async def get_by_key(self, key: PatternKey) -> SMSPatternEntity:
        """
        Get the template one message key is sent through.

        Args:
            key (PatternKey): The message key, such as `otp`.
        Returns:
            (SMSPatternEntity): The found pattern.
        """
        pattern = await self.repo.get_by_key(key)
        pattern = self._check_for_existence("key", key, pattern)
        return pattern

    @transactional
    async def upsert(self, data: SmsPatternUpsert) -> SMSPatternEntity:
        """
        Register the template to send one message key through, replacing
        whatever that key pointed at before.

        Args:
            data (SmsPatternUpsert): The key and the provider's template name.
        Returns:
            (SMSPatternEntity): The registered pattern.
        """
        pattern = await self.repo.upsert(
            SMSPatternEntity(**data.to_row(exclude_unset=False))
        )
        return pattern


class MessageService(BaseIDService[MessageEntity]):
    def __init__(self, repo: MessageRepository) -> None:
        self.repo = repo

    @transactional
    async def queue(self, data: SmsSend) -> MessageEntity:
        """
        Record a pending message. Automatic dispatch is unavailable until
        the event subsystem is rewritten.

        Args:
            data (SmsSend): The recipient and the text.
        Returns:
            (MessageEntity): The queued message.
        """
        message = await self.repo.create(
            MessageEntity(
                channel=MessageChannel.SMS,
                kind=MessageKind.FREE_FORM,
                recipient=data.recipient,
                body=data.body,
                status=MessageStatus.PENDING,
                tries=0,
            )
        )
        return message

    @transactional
    async def queue_bulk(
        self,
        recipients: Sequence[str],
        body: str,
    ) -> Sequence[MessageEntity]:
        """
        Record pending messages in one database operation. This method does
        not dispatch them.

        Args:
            recipients (Sequence[str]): The destination numbers.
            body (str): The text, the same for every recipient.
        Returns:
            (Sequence[MessageEntity]): The queued messages.
        """
        queued: Sequence[MessageEntity] = []
        if recipients:
            queued = await self.repo.bulk_create(
                [
                    MessageEntity(
                        channel=MessageChannel.SMS,
                        kind=MessageKind.FREE_FORM,
                        recipient=recipient,
                        body=body,
                        status=MessageStatus.PENDING,
                        tries=0,
                    )
                    for recipient in recipients
                ]
            )
        return queued

    @transactional
    async def deliver(
        self,
        id: int,
        result: SmsDeliveryResult,
    ) -> MessageEntity:
        """
        Write down how a send went. The sending itself belongs to whoever holds
        the gateway; this only records the outcome, so a refusal is a row
        rather than an exception.

        Args:
            id (int): ID of the message that was sent.
            result (SmsDeliveryResult): What the gateway answered.
        Returns:
            (MessageEntity): The message with its outcome on it.
        """
        message = await self.get_by_id(id)
        updated = await self.repo.update_row_by_id(
            id, self._stamped(message, result)
        )
        updated = self._check_for_id_existence(id, updated)
        return updated

    @transactional
    async def deliver_bulk(
        self,
        results: Mapping[int, SmsDeliveryResult],
    ) -> Sequence[MessageEntity]:
        """
        Write down how a batch of sends went, in one statement rather than one
        round trip per message.

        Args:
            results (Mapping[int, SmsDeliveryResult]): What the gateway
                answered for each message id.
        Returns:
            (Sequence[MessageEntity]): The messages, each with its outcome.
        """
        delivered: Sequence[MessageEntity] = []
        if results:
            messages = await self.repo.get_by_ids(list(results))
            rows = [self._stamped(row, results[row.id]) for row in messages]
            if rows:
                delivered = await self.repo.bulk_update(rows)
        return delivered

    def _stamped(
        self,
        message: MessageEntity,
        result: SmsDeliveryResult,
    ) -> MessageEntity:
        return MessageEntity(
            id=message.id,
            tries=message.tries + 1,
            status=MessageStatus.SENT
            if result.delivered
            else MessageStatus.FAILED,
            error=result.error,
            provider_message_id=result.provider_message_id,
            sent_at=dates.utc_now() if result.delivered else None,
        )

    @transactional
    async def retry(self, id: int) -> MessageEntity:
        """
        Mark a failed message pending again. The try count is
        left standing, so how many attempts a message has cost survives the
        retry.

        Args:
            id (int): ID of the failed message.
        Returns:
            (MessageEntity): The message, queued again.
        """
        message = await self.get_by_id(id)
        if message.status == MessageStatus.SENT:
            raise ValidationException(
                message="this message has already been sent",
                message_code=resources.INVALID_INPUT,
                loc=["id"],
                input=MESSAGE_ID_ENCRYPTION.encode(id),
            )
        updated = await self.repo.update_row_by_id(
            id,
            MessageEntity(id=id, status=MessageStatus.PENDING, error=None),
        )
        updated = self._check_for_id_existence(id, updated)
        return updated

    async def get_page(self, data: MessageSearch) -> PagedType[MessageEntity]:
        """
        Get a filtered page of messages.

        Args:
            data (MessageSearch): Status, recipient and paging.
        Returns:
            (PagedType[MessageEntity]): The page and the total count.
        """
        paged = await self.repo.get_page(
            status=data.status,
            recipient=data.recipient,
            offset=(data.page - 1) * data.per_page,
            limit=data.per_page,
        )
        return paged

    async def get_by_id(self, id: int) -> MessageEntity:
        """
        Get one message by id.

        Args:
            id (int): ID of the message.
        Returns:
            (MessageEntity): The found message.
        """
        message = await self.repo.get_by_id(id)
        message = self._check_for_id_existence(id, message)
        return message

    async def get_context(self, id: int) -> MessageContext:
        """
        Read one message with the provider it goes out through.

        Args:
            id (int): ID of the message.
        Returns:
            (MessageContext): The message and its provider.
        """
        context = await self.repo.get_context_by_id(id, is_active=True)
        if context is None:
            # not _check_for_id_existence: the public id is what the caller
            # sent, so it is the one the error must name back
            raise NotFoundException(
                identifier="id",
                identifier_value=MESSAGE_ID_ENCRYPTION.encode(id),
                message=f"Cannot find Message by id with value {id}",
                message_code=resources.NOT_FOUND_ERROR,
                entity="Message",
            )
        return context

    async def get_contexts(
        self,
        ids: Sequence[int],
    ) -> Sequence[MessageContext]:
        """
        Read several messages with the provider they go out through.

        Args:
            ids (Sequence[int]): IDs of the messages.
        Returns:
            (Sequence[MessageContext]): One entry per message that exists.
        """
        contexts: Sequence[MessageContext] = []
        if ids:
            contexts = await self.repo.get_contexts_by_ids(ids, is_active=True)
        return contexts
