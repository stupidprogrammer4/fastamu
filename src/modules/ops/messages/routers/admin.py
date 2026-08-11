"""The back-office messaging API (Scope.MESSAGES): the message log, the
provider in use, and the templates messages go out through."""

from typing import Annotated

from dishka.integrations.fastapi import DishkaRoute, FromDishka
from fastapi import APIRouter, Depends, Query

from src.common.bases.schemas import BaseMeta, PagerMeta
from src.modules.ops.messages.config.dependencies import MessageID
from src.modules.ops.messages.domain.dtos import (
    MessageSearch,
    SmsPatternUpsert,
    SmsProviderActivate,
    SmsProviderUpsert,
    SmsSend,
)
from src.modules.ops.messages.domain.schemas import (
    MessageOut,
    SmsPatternOut,
    SmsProviderOut,
)
from src.modules.ops.messages.interfaces import (
    IMessageService,
    ISMSPatternService,
    ISMSProviderService,
)
from src.web.dependencies import Scope, require_access
from src.web.response import APIResponse

router = APIRouter(
    prefix="/messages",
    tags=["Messages"],
    route_class=DishkaRoute,
    dependencies=[Depends(require_access(Scope.MESSAGES))],
)

MessageResponse = APIResponse[MessageOut, None]
PagedMessageResponse = APIResponse[MessageOut, BaseMeta]
SmsProviderResponse = APIResponse[SmsProviderOut, None]
SmsPatternResponse = APIResponse[SmsPatternOut, None]


@router.get(
    "",
    response_model=PagedMessageResponse,
    response_model_exclude_defaults=True,
)
async def search_messages(
    data: Annotated[MessageSearch, Query()],
    service: FromDishka[IMessageService],
) -> PagedMessageResponse:
    paged = await service.get_page(data)
    return APIResponse(
        success=True,
        data=MessageOut.from_objs(paged.items),
        meta=BaseMeta(
            pager=PagerMeta.from_total(
                data.page, data.per_page, paged.total_items
            )
        ),
    )


@router.post(
    "", response_model=MessageResponse, response_model_exclude_defaults=True
)
async def send_message(
    data: SmsSend,
    service: FromDishka[IMessageService],
) -> MessageResponse:
    message = await service.queue(data)
    return APIResponse.from_data(MessageOut.from_obj(message))


@router.get(
    "/providers",
    response_model=SmsProviderResponse,
    response_model_exclude_defaults=True,
)
async def get_providers(
    service: FromDishka[ISMSProviderService],
) -> SmsProviderResponse:
    providers = await service.get_all()
    return APIResponse.from_data(SmsProviderOut.from_objs(providers))


@router.put(
    "/providers",
    response_model=SmsProviderResponse,
    response_model_exclude_defaults=True,
)
async def upsert_provider(
    data: SmsProviderUpsert,
    service: FromDishka[ISMSProviderService],
) -> SmsProviderResponse:
    provider = await service.upsert(data)
    return APIResponse.from_data(SmsProviderOut.from_obj(provider))


@router.patch(
    "/providers/active",
    response_model=SmsProviderResponse,
    response_model_exclude_defaults=True,
)
async def activate_provider(
    data: SmsProviderActivate,
    service: FromDishka[ISMSProviderService],
) -> SmsProviderResponse:
    provider = await service.activate(data)
    return APIResponse.from_data(SmsProviderOut.from_obj(provider))


@router.get(
    "/patterns",
    response_model=SmsPatternResponse,
    response_model_exclude_defaults=True,
)
async def get_patterns(
    service: FromDishka[ISMSPatternService],
) -> SmsPatternResponse:
    patterns = await service.get_all()
    return APIResponse.from_data(SmsPatternOut.from_objs(patterns))


@router.put(
    "/patterns",
    response_model=SmsPatternResponse,
    response_model_exclude_defaults=True,
)
async def upsert_pattern(
    data: SmsPatternUpsert,
    service: FromDishka[ISMSPatternService],
) -> SmsPatternResponse:
    pattern = await service.upsert(data)
    return APIResponse.from_data(SmsPatternOut.from_obj(pattern))


# declared after /providers and /patterns: a literal path must be matched
# before the one that would swallow it as an id
@router.get(
    "/{id:int}",
    response_model=MessageResponse,
    response_model_exclude_defaults=True,
)
async def get_message(
    id: MessageID,
    service: FromDishka[IMessageService],
) -> MessageResponse:
    message = await service.get_by_id(id)
    return APIResponse.from_data(MessageOut.from_obj(message))


@router.post(
    "/{id:int}/retry",
    response_model=MessageResponse,
    response_model_exclude_defaults=True,
)
async def retry_message(
    id: MessageID,
    service: FromDishka[IMessageService],
) -> MessageResponse:
    message = await service.retry(id)
    return APIResponse.from_data(MessageOut.from_obj(message))
