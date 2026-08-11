from typing import Annotated

from pydantic import Field

from src.common.bases.dtos import BaseDTO
from src.common.types import (
    LStrType,
    MobileType,
    MStrType,
    PageType,
    PerPageType,
)
from src.modules.ops.messages.domain.enums import (
    MessageStatus,
    PatternKey,
    ProviderCode,
)

BodyType = Annotated[str, Field(min_length=1, max_length=1000)]
TokensType = Annotated[dict[str, str], Field(max_length=10)]


class SmsProviderUpsert(BaseDTO):
    title: MStrType
    code: ProviderCode
    credentials: dict[str, str]


class SmsProviderActivate(BaseDTO):
    code: ProviderCode


class SmsPatternUpsert(BaseDTO):
    key: PatternKey
    pattern: LStrType


class SmsSend(BaseDTO):
    recipient: MobileType
    body: BodyType


class SmsPatternSend(BaseDTO):
    recipient: MobileType
    key: PatternKey
    tokens: TokensType


class MessageSearch(BaseDTO):
    status: MessageStatus | None = None
    recipient: MobileType | None = None
    page: PageType = 1
    per_page: PerPageType = 20
