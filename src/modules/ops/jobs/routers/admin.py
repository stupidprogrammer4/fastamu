"""The back-office jobs API (Scope.JOBS): task overview, running jobs and
per-task status lookup."""

from dishka.integrations.fastapi import DishkaRoute, FromDishka
from fastapi import APIRouter, Depends

from src.modules.ops.jobs.domain.schemas import JobStatusOut, JobsOverviewOut, RunningJobOut
from src.modules.ops.jobs.interfaces import IJobService
from src.web.dependencies import Scope, require_access
from src.web.response import APIResponse

router = APIRouter(
    prefix="/jobs",
    tags=["Jobs"],
    route_class=DishkaRoute,
    dependencies=[Depends(require_access(Scope.JOBS))],
)


@router.get("", response_model=APIResponse[JobsOverviewOut, None], response_model_exclude_defaults=True)
async def jobs_overview(service: FromDishka[IJobService]) -> APIResponse[JobsOverviewOut, None]:
    overview = await service.overview()
    return APIResponse.from_data(overview)


@router.get("/running", response_model=APIResponse[RunningJobOut, None], response_model_exclude_defaults=True)
async def running_jobs(service: FromDishka[IJobService]) -> APIResponse[RunningJobOut, None]:
    running = await service.running()
    return APIResponse.from_data(running)


@router.get("/{task_id}", response_model=APIResponse[JobStatusOut, None], response_model_exclude_defaults=True)
async def job_status(task_id: str, service: FromDishka[IJobService]) -> APIResponse[JobStatusOut, None]:
    status = await service.get_status(task_id)
    return APIResponse.from_data(status)
