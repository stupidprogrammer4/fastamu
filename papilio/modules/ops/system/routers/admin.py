"""System health and information endpoints."""

from dishka.integrations.fastapi import DishkaRoute, FromDishka
from fastapi import APIRouter, Depends

from papilio.api.authentication import require_access
from papilio.api.responses.envelope import APIResponse
from papilio.modules.ops.scopes import AccessScope
from papilio.modules.ops.system.app.results import (
    HealthOut,
    SystemInfoOut,
)
from papilio.modules.ops.system.interfaces import ISystemService

router = APIRouter(
    prefix="/system",
    tags=["System"],
    route_class=DishkaRoute,
    dependencies=[Depends(require_access(AccessScope.SYSTEM))],
)


@router.get("/health", response_model=APIResponse[HealthOut, None])
async def system_health(
    service: FromDishka[ISystemService],
) -> APIResponse[HealthOut, None]:
    health = await service.health()
    return APIResponse.from_data(health)


@router.get("/info", response_model=APIResponse[SystemInfoOut, None])
async def system_info(
    service: FromDishka[ISystemService],
) -> APIResponse[SystemInfoOut, None]:
    info = await service.info()
    return APIResponse.from_data(info)
