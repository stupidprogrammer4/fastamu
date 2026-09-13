from typing import Annotated, Any

from dishka.integrations.fastapi import DishkaRoute, FromDishka
from fastapi import APIRouter, Query

from <<PKG>>.<<M>>.app.queries import <<P>>SearchQuery

router = APIRouter(prefix="/<<PL>>", tags=["<<PL>>"], route_class=DishkaRoute)


@router.get("/search", response_model=list[dict[str, Any]])
async def search(
    query: FromDishka[<<P>>SearchQuery],
    limit: Annotated[int, Query(ge=1, le=100)] = 20,
    offset: Annotated[int, Query(ge=0)] = 0,
):
    return await query.execute(limit=limit, offset=offset)
