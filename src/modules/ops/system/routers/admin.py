"""The back-office system API (Scope.SYSTEM): health check and system info."""

from dishka.integrations.fastapi import DishkaRoute, FromDishka
from fastapi import APIRouter, Depends

from src.modules.ops.system.domain.schemas import HealthOut, SystemInfoOut
from src.modules.ops.system.interfaces import ISystemService
from src.web.dependencies import Scope, require_access
from src.web.response import APIResponse

router = APIRouter(
    prefix="/system",
    tags=["System"],
    route_class=DishkaRoute,
    dependencies=[Depends(require_access(Scope.SYSTEM))],
)


@router.get("/health", response_model=APIResponse[HealthOut, None])
async def system_health(service: FromDishka[ISystemService]) -> APIResponse[HealthOut, None]:
    health = await service.health()
    return APIResponse.from_data(health)


@router.get("/info", response_model=APIResponse[SystemInfoOut, None])
async def system_info(service: FromDishka[ISystemService]) -> APIResponse[SystemInfoOut, None]:
    info = await service.info()
    return APIResponse.from_data(info)
