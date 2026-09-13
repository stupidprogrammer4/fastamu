from dishka.integrations.fastapi import DishkaRoute, FromDishka
from fastapi import APIRouter

from papilio.api.responses.envelope import APIResponse
from <<PKG>>.<<M>>.app.results import <<P>>Out
from <<PKG>>.<<M>>.domain.dtos import <<P>>Input
from <<PKG>>.<<M>>.interfaces import I<<P>>Service

router = APIRouter(prefix="/<<PL>>", tags=["<<PL>>"], route_class=DishkaRoute)


@router.post("", response_model=APIResponse[<<P>>Out, None])
async def run(data: <<P>>Input, service: FromDishka[I<<P>>Service]):
    return APIResponse.from_data(await service.run(data))
