from typing import Mapping, Sequence

from src.common.bases.results import PagedType
from src.common.bases.services import BaseIDService
from src.common.errors.exceptions import (
    NotFoundException,
    ValidationException,
)
from src.common.utils import date_utils
from src.core import resources
from src.modules.ops.messages.config.constants import (
    MESSAGE_ID_ENCRYPTION,
    MESSAGE_QUEUED,
    MESSAGES_QUEUED,
)
from src.modules.ops.messages.domain.context import MessageContext
from src.modules.ops.messages.domain.dtos import (
    MessageSearch,
    SmsPatternUpsert,
    SmsProviderActivate,
    SmsProviderUpsert,
    SmsSend,
)
from src.modules.ops.messages.domain.enums import (
    MessageChannel,
    MessageKind,
    MessageStatus,
    PatternKey,
    ProviderCode,
)
from src.modules.ops.messages.domain.events import (
    MessageQueuedInput,
    MessagesQueuedInput,
)
from src.modules.ops.messages.domain.models import (
    MessageModel,
    SMSPatternModel,
    SMSProviderModel,
)
from src.modules.ops.messages.domain.results import SmsDeliveryResult
from src.modules.ops.messages.infra.repository import (
    MessageRepository,
    SMSPatternRepository,
    SMSProviderRepository,
)
from src.tasks.events import emit


class SMSProviderService(BaseIDService[SMSProviderModel]):
    def __init__(self, repo: SMSProviderRepository) -> None:
        self.repo = repo

    async def get_all(self) -> Sequence[SMSProviderModel]:
        """
        Get every registered provider.

        Returns:
            (Sequence[SMSProviderModel]): All providers.
        """
        providers = await self.repo.get_by_codes()
        return providers

    async def get_by_code(self, code: ProviderCode) -> SMSProviderModel:
        """
        Get one provider by its code.

        Args:
            code (ProviderCode): The provider's code.
        Returns:
            (SMSProviderModel): The found provider.
        """
        provider = await self.repo.get_by_code(code)
        provider = self._check_for_existence("code", code, provider)
        return provider

    async def get_active(self) -> SMSProviderModel:
        """
        Get the provider messages are sent through.

        Returns:
            (SMSProviderModel): The active provider.
        """
        providers = await self.repo.get_by_codes(is_active=True)
        active = providers[0] if providers else None
        active = self._check_for_existence("is_active", True, active)
        return active

    async def upsert(self, data: SmsProviderUpsert) -> SMSProviderModel:
        """
        Register a provider, replacing the one already under its code so its
        credentials can be rotated without a second row.

        Args:
            data (SmsProviderUpsert): The provider and its credentials.
        Returns:
            (SMSProviderModel): The stored provider.
        """
        provider = await self.repo.upsert(
            SMSProviderModel(**data.to_row(exclude_unset=False))
        )
        return provider

    async def activate(self, data: SmsProviderActivate) -> SMSProviderModel:
        """
        Send messages through one provider from now on, switching off whichever
        was carrying them, so two are never active at once.

        Args:
            data (SmsProviderActivate): The provider to switch to.
        Returns:
            (SMSProviderModel): The provider now in use.
        """
        provider = await self.get_by_code(data.code)
        await self.repo.update_is_active(
            is_active=False, exclude_id=provider.id, current=True
        )
        updated = await self.repo.update_row_by_id(
            provider.id, SMSProviderModel(id=provider.id, is_active=True)
        )
        updated = self._check_for_id_existence(provider.id, updated)
        return updated


class SMSPatternService(BaseIDService[SMSPatternModel]):
    def __init__(self, repo: SMSPatternRepository) -> None:
        self.repo = repo

    async def get_all(self) -> Sequence[SMSPatternModel]:
        """
        Get every registered template.

        Returns:
            (Sequence[SMSPatternModel]): All patterns, by key.
        """
        patterns = await self.repo.get_by_keys()
        return patterns

    async def get_by_key(self, key: PatternKey) -> SMSPatternModel:
        """
        Get the template one message key is sent through.

        Args:
            key (PatternKey): The message key, such as `otp`.
        Returns:
            (SMSPatternModel): The found pattern.
        """
        pattern = await self.repo.get_by_key(key)
        pattern = self._check_for_existence("key", key, pattern)
        return pattern

    async def upsert(self, data: SmsPatternUpsert) -> SMSPatternModel:
        """
        Register the template to send one message key through, replacing
        whatever that key pointed at before.

        Args:
            data (SmsPatternUpsert): The key and the provider's template name.
        Returns:
            (SMSPatternModel): The registered pattern.
        """
        pattern = await self.repo.upsert(
            SMSPatternModel(**data.to_row(exclude_unset=False))
        )
        return pattern


class MessageService(BaseIDService[MessageModel]):
    def __init__(self, repo: MessageRepository) -> None:
        self.repo = repo

    async def queue(self, data: SmsSend) -> MessageModel:
        """
        Write a message down as owed and ask for it to be sent. It is not
        delivered here: the row is the record that it should be, and the event
        is what carries it to whoever sends it.

        Args:
            data (SmsSend): The recipient and the text.
        Returns:
            (MessageModel): The queued message.
        """
        message = await self.repo.create(
            MessageModel(
                channel=MessageChannel.SMS,
                kind=MessageKind.FREE_FORM,
                recipient=data.recipient,
                body=data.body,
                status=MessageStatus.PENDING,
                tries=0,
            )
        )
        await emit(MESSAGE_QUEUED, MessageQueuedInput(id=message.id))
        return message

    async def queue_bulk(
        self,
        recipients: Sequence[str],
        body: str,
    ) -> Sequence[MessageModel]:
        """
        Owe the same text to several recipients and ask for the batch to be
        sent. One event carries the whole batch, so a hundred recipients cost
        one message on the bus rather than a hundred.

        Args:
            recipients (Sequence[str]): The destination numbers.
            body (str): The text, the same for every recipient.
        Returns:
            (Sequence[MessageModel]): The queued messages.
        """
        if not recipients:
            return []
        queued = await self.repo.bulk_create(
            [
                MessageModel(
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
        await emit(
            MESSAGES_QUEUED,
            MessagesQueuedInput(ids=[row.id for row in queued]),
        )
        return queued

    async def deliver(
        self,
        id: int,
        result: SmsDeliveryResult,
    ) -> MessageModel:
        """
        Write down how a send went. The sending itself belongs to whoever holds
        the gateway; this only records the outcome, so a refusal is a row
        rather than an exception.

        Args:
            id (int): ID of the message that was sent.
            result (SmsDeliveryResult): What the gateway answered.
        Returns:
            (MessageModel): The message with its outcome on it.
        """
        message = await self.get_by_id(id)
        updated = await self.repo.update_row_by_id(
            id, self._stamped(message, result)
        )
        updated = self._check_for_id_existence(id, updated)
        return updated

    async def deliver_bulk(
        self,
        results: Mapping[int, SmsDeliveryResult],
    ) -> Sequence[MessageModel]:
        """
        Write down how a batch of sends went, in one statement rather than one
        round trip per message.

        Args:
            results (Mapping[int, SmsDeliveryResult]): What the gateway
                answered for each message id.
        Returns:
            (Sequence[MessageModel]): The messages, each with its outcome.
        """
        if not results:
            return []
        messages = await self.repo.get_by_ids(list(results))
        rows = [self._stamped(row, results[row.id]) for row in messages]
        if not rows:
            return []
        return await self.repo.bulk_update(rows)

    def _stamped(
        self,
        message: MessageModel,
        result: SmsDeliveryResult,
    ) -> MessageModel:
        return MessageModel(
            id=message.id,
            tries=message.tries + 1,
            status=MessageStatus.SENT
            if result.delivered
            else MessageStatus.FAILED,
            error=result.error,
            provider_message_id=result.provider_message_id,
            sent_at=date_utils.utc_now() if result.delivered else None,
        )

    async def retry(self, id: int) -> MessageModel:
        """
        Owe a failed message again and ask for it to be sent. The try count is
        left standing, so how many attempts a message has cost survives the
        retry.

        Args:
            id (int): ID of the failed message.
        Returns:
            (MessageModel): The message, queued again.
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
            MessageModel(id=id, status=MessageStatus.PENDING, error=None),
        )
        updated = self._check_for_id_existence(id, updated)
        await emit(MESSAGE_QUEUED, MessageQueuedInput(id=updated.id))
        return updated

    async def get_page(self, data: MessageSearch) -> PagedType[MessageModel]:
        """
        Get a filtered page of messages.

        Args:
            data (MessageSearch): Status, recipient and paging.
        Returns:
            (PagedType[MessageModel]): The page and the total count.
        """
        paged = await self.repo.get_page(
            status=data.status,
            recipient=data.recipient,
            offset=(data.page - 1) * data.per_page,
            limit=data.per_page,
        )
        return paged

    async def get_by_id(self, id: int) -> MessageModel:
        """
        Get one message by id.

        Args:
            id (int): ID of the message.
        Returns:
            (MessageModel): The found message.
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
        if not ids:
            return []
        return await self.repo.get_contexts_by_ids(ids, is_active=True)
