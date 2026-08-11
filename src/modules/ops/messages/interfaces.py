from typing import Mapping, Protocol, Sequence

from src.common.bases.results import PagedType
from src.modules.ops.messages.domain.context import MessageContext
from src.modules.ops.messages.domain.dtos import (
    MessageSearch,
    SmsPatternUpsert,
    SmsProviderActivate,
    SmsProviderUpsert,
    SmsSend,
)
from src.modules.ops.messages.domain.enums import PatternKey, ProviderCode
from src.modules.ops.messages.domain.models import (
    MessageModel,
    SMSPatternModel,
    SMSProviderModel,
)
from src.modules.ops.messages.domain.results import SmsDeliveryResult


class ISMSProviderService(Protocol):
    async def get_all(self) -> Sequence[SMSProviderModel]: ...

    async def get_by_code(self, code: ProviderCode) -> SMSProviderModel: ...

    async def get_active(self) -> SMSProviderModel: ...

    async def upsert(self, data: SmsProviderUpsert) -> SMSProviderModel: ...

    async def activate(
        self, data: SmsProviderActivate
    ) -> SMSProviderModel: ...


class ISMSPatternService(Protocol):
    async def get_all(self) -> Sequence[SMSPatternModel]: ...

    async def get_by_key(self, key: PatternKey) -> SMSPatternModel: ...

    async def upsert(self, data: SmsPatternUpsert) -> SMSPatternModel: ...


class IMessageService(Protocol):
    async def get_page(
        self, data: MessageSearch
    ) -> PagedType[MessageModel]: ...

    async def get_by_id(self, id: int) -> MessageModel: ...

    async def get_context(self, id: int) -> MessageContext: ...

    async def get_contexts(
        self, ids: Sequence[int]
    ) -> Sequence[MessageContext]: ...

    async def queue(self, data: SmsSend) -> MessageModel: ...

    async def queue_bulk(
        self,
        recipients: Sequence[str],
        body: str,
    ) -> Sequence[MessageModel]: ...

    async def deliver(
        self,
        id: int,
        result: SmsDeliveryResult,
    ) -> MessageModel: ...

    async def deliver_bulk(
        self,
        results: Mapping[int, SmsDeliveryResult],
    ) -> Sequence[MessageModel]: ...

    async def retry(self, id: int) -> MessageModel: ...


class ISmsSenderService(Protocol):
    async def send(self, id: int) -> bool: ...

    async def send_bulk(self, ids: Sequence[int]) -> int: ...
