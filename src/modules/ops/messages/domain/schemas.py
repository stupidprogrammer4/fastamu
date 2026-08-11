from datetime import datetime

from src.common.bases.schemas import BaseIDOutput, BaseOutput
from src.modules.ops.messages.config.constants import (
    MESSAGE_ID_ENCRYPTION,
    SMS_PROVIDER_ID_ENCRYPTION,
)
from src.modules.ops.messages.domain.enums import (
    MessageChannel,
    MessageKind,
    MessageStatus,
    PatternKey,
    ProviderCode,
)


class SmsProviderOut(BaseIDOutput):
    __encryption__ = SMS_PROVIDER_ID_ENCRYPTION

    title: str
    code: ProviderCode
    is_active: bool
    created_at: datetime
    updated_at: datetime


class SmsPatternOut(BaseOutput):
    key: PatternKey
    pattern: str
    created_at: datetime
    updated_at: datetime


class MessageOut(BaseIDOutput):
    __encryption__ = MESSAGE_ID_ENCRYPTION

    channel: MessageChannel
    kind: MessageKind
    recipient: str
    body: str | None
    status: MessageStatus
    error: str | None
    tries: int
    sent_at: datetime | None
    created_at: datetime
