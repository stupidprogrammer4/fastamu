"""The storage/media API: upload, list, fetch and delete media (each managing
route guarded by Scope.STORAGE) plus the unauthenticated file-download route."""

from collections.abc import AsyncIterator

from dishka.integrations.fastapi import DishkaRoute, FromDishka
from fastapi import APIRouter, Depends, File, UploadFile
from fastapi.responses import StreamingResponse

from src.common.bases.schemas import BaseMeta, PagerMeta
from src.common.types import PageType, PerPageType
from src.modules.ops.storage.domain.schemas import MediaOut
from src.modules.ops.storage.interfaces import IMediaService
from src.web.dependencies import Scope, require_access
from src.web.response import APIResponse

router = APIRouter(prefix="/storage", tags=["Storage"], route_class=DishkaRoute)
_guarded = [Depends(require_access(Scope.STORAGE))]

MediaResponse = APIResponse[MediaOut, None]
PagedMediaResponse = APIResponse[MediaOut, BaseMeta]

_CHUNK_SIZE = 64 * 1024


async def _chunks(file: UploadFile) -> AsyncIterator[bytes]:
    while chunk := await file.read(_CHUNK_SIZE):
        yield chunk


@router.post("", response_model=MediaResponse, dependencies=_guarded)
async def upload_media(
    service: FromDishka[IMediaService],
    data: UploadFile = File(...),
) -> MediaResponse:
    media = await service.upload(_chunks(data), data.filename)
    return APIResponse.from_data(MediaOut.from_obj(media))


@router.get("", response_model=PagedMediaResponse, dependencies=_guarded)
async def get_media_list(
    service: FromDishka[IMediaService],
    page: PageType = 1,
    per_page: PerPageType = 20,
) -> PagedMediaResponse:
    paged = await service.get_paged(page, per_page)
    return APIResponse(
        success=True,
        data=MediaOut.from_objs(paged.items),
        meta=BaseMeta(pager=PagerMeta.from_total(page, per_page, paged.total_items)),
    )


@router.get("/file/{path:path}")
async def download_media(
    path: str,
    service: FromDishka[IMediaService],
) -> StreamingResponse:
    stream, content_type = await service.open(path)
    return StreamingResponse(stream, media_type=content_type)


@router.get("/{id}", response_model=MediaResponse, dependencies=_guarded)
async def get_media(
    id: int,
    service: FromDishka[IMediaService],
) -> MediaResponse:
    media = await service.get_by_id(id)
    return APIResponse.from_data(MediaOut.from_obj(media))


@router.delete("/{id}", response_model=MediaResponse, dependencies=_guarded)
async def remove_media(
    id: int,
    service: FromDishka[IMediaService],
) -> MediaResponse:
    media = await service.remove(id)
    return APIResponse.from_data(MediaOut.from_obj(media))
