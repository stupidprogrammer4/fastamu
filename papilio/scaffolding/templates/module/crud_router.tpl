from dishka.integrations.fastapi import DishkaRoute, FromDishka
from fastapi import APIRouter

from papilio.api.responses.envelope import APIResponse
from <<PKG>>.<<M>>.domain.dtos import <<P>>Create, <<P>>Update
from <<PKG>>.<<M>>.interfaces import I<<P>>Service
from <<PKG>>.<<M>>.routers.schemas import <<P>>Out

router = APIRouter(prefix="/<<PL>>", tags=["<<PL>>"], route_class=DishkaRoute)


@router.post("", response_model=APIResponse[<<P>>Out, None], status_code=201)
async def create(data: <<P>>Create, service: FromDishka[I<<P>>Service]):
    return APIResponse.from_data(await service.create(data))


@router.get("/{id:int}", response_model=APIResponse[<<P>>Out, None])
async def get(id: int, service: FromDishka[I<<P>>Service]):
    return APIResponse.from_data(await service.get_by_id(id))


@router.patch("/{id:int}", response_model=APIResponse[<<P>>Out, None])
async def update(id: int, data: <<P>>Update, service: FromDishka[I<<P>>Service]):
    return APIResponse.from_data(await service.update(id, data))


@router.delete("/{id:int}", response_model=int)
async def remove(id: int, service: FromDishka[I<<P>>Service]):
    return await service.remove(id)
