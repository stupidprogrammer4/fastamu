from datetime import datetime

from sqlalchemy.orm import declared_attr

from src.infra.postgres.models.base import BaseIDTimestampModel
from src.infra.postgres.types import (
    BoolField,
    CharField,
    JSONBField,
    TextField,
    TimestampField,
)
from src.modules.ops.messages.domain.enums import (
    MessageChannel,
    MessageKind,
    MessageStatus,
    PatternKey,
    ProviderCode,
)


class SMSProviderModel(BaseIDTimestampModel, table=True):
    """A provider you can send through, and the credentials to do it.

    One row per code, so rotating a key is an upsert rather than a second row,
    and `is_active` marks the one messages actually leave through.
    """

    @declared_attr.directive
    def __tablename__(cls) -> str:
        return "tbl_sms_providers"

    title: str = CharField(55)
    code: ProviderCode = CharField(35, unique=True)
    credentials: dict[str, str] = JSONBField(default=dict)
    is_active: bool = BoolField(default=False)


class SMSPatternModel(BaseIDTimestampModel, table=True):
    """The provider-side template one message key is sent through.

    Providers register approved templates and address them by name; this maps
    a key your code knows (`otp`) to whatever the current provider calls it.
    """

    @declared_attr.directive
    def __tablename__(cls) -> str:
        return "tbl_sms_patterns"

    key: PatternKey = CharField(35, unique=True)
    pattern: str = CharField(100)


class MessageModel(BaseIDTimestampModel, table=True):
    """One message owed to one recipient, and what became of it.

    The row is written before anything is sent, so a message that never leaves
    is still a record rather than a lost call — `status`, `tries` and `error`
    are how a send that failed explains itself afterwards.
    """

    channel: MessageChannel = CharField(35)
    kind: MessageKind = CharField(35)
    recipient: str = CharField(55)
    body: str | None = TextField(nullable=True)
    status: MessageStatus = CharField(35)
    provider_message_id: str | None = CharField(100, nullable=True)
    error: str | None = TextField(nullable=True)
    tries: int = 0
    sent_at: datetime | None = TimestampField(nullable=True)
