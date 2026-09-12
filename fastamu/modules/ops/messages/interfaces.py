from typing import Mapping, Protocol, Sequence

from fastamu.common.schemas.results import PagedType
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
from fastamu.modules.ops.messages.domain.enums import PatternKey, ProviderCode
from fastamu.modules.ops.messages.domain.results import SmsDeliveryResult


class ISMSProviderService(Protocol):
    async def get_all(self) -> Sequence[SMSProviderEntity]: ...

    async def get_by_code(self, code: ProviderCode) -> SMSProviderEntity: ...

    async def get_active(self) -> SMSProviderEntity: ...

    async def upsert(self, data: SmsProviderUpsert) -> SMSProviderEntity: ...

    async def activate(
        self, data: SmsProviderActivate
    ) -> SMSProviderEntity: ...


class ISMSPatternService(Protocol):
    async def get_all(self) -> Sequence[SMSPatternEntity]: ...

    async def get_by_key(self, key: PatternKey) -> SMSPatternEntity: ...

    async def upsert(self, data: SmsPatternUpsert) -> SMSPatternEntity: ...


class IMessageService(Protocol):
    async def get_page(
        self, data: MessageSearch
    ) -> PagedType[MessageEntity]: ...

    async def get_by_id(self, id: int) -> MessageEntity: ...

    async def get_context(self, id: int) -> MessageContext: ...

    async def get_contexts(
        self, ids: Sequence[int]
    ) -> Sequence[MessageContext]: ...

    async def queue(self, data: SmsSend) -> MessageEntity: ...

    async def queue_bulk(
        self,
        recipients: Sequence[str],
        body: str,
    ) -> Sequence[MessageEntity]: ...

    async def deliver(
        self,
        id: int,
        result: SmsDeliveryResult,
    ) -> MessageEntity: ...

    async def deliver_bulk(
        self,
        results: Mapping[int, SmsDeliveryResult],
    ) -> Sequence[MessageEntity]: ...

    async def retry(self, id: int) -> MessageEntity: ...


class ISmsSenderService(Protocol):
    async def send(self, id: int) -> bool: ...

    async def send_bulk(self, ids: Sequence[int]) -> int: ...
