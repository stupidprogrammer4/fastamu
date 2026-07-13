from collections.abc import Callable, Coroutine
from functools import wraps
from typing import Any

from dishka.integrations.taskiq import FromDishka, inject

from src.common.bases.projection import TBatchProjection, TESProjection
from src.tasks.broker import broker


def _dispatch_after(
    projection_cls: type[Any],
    method: str,
    task_prefix: str,
    id_attr: str | None,
    batch: bool = False,
) -> Callable[..., Callable[..., Any]]:
    """Register a background taskiq job that calls ``projection.<method>(id)`` and
    return a decorator that dispatches it after the wrapped service method returns.

    Shared by ``project`` / ``unproject`` / ``batch_project`` — the differences
    are which projection method runs, the task-name prefix, and (``batch``)
    whether the ids come off one returned entity or a returned sequence.

    Args:
        projection_cls (type[TESProjection]): The projection to run in background.
        method (str): The projection method to call (``"project"`` / ``"unproject"``
            / ``"batch_project"``).
        task_prefix (str): Task-name prefix (keeps the tasks distinct).
        id_attr (str): Attribute on the returned object(s) holding the entity id.
        batch (bool): When True the wrapped method returns a sequence and the
            job gets the list of their ids.
    Returns:
        (Callable): A decorator for the service method.
    """
    name = projection_cls.__name__.lower()
    task_name = f"{task_prefix}_{name}"
    queue_name = f"{name}_queue"

    async def _task(id: Any, projection: Any) -> bool:
        result = await getattr(projection, method)(id)
        return result

    _task.__name__ = task_name
    _task.__qualname__ = task_name
    # Resolve the concrete projection from dishka by its type (modern FromDishka[T]).
    _task.__annotations__ = {
        "id": list[int] if batch else int,
        "projection": FromDishka[projection_cls],
        "return": bool,
    }

    registered: Any = broker.task(task_name=task_name, queue_name=queue_name)(
        inject(_task, patch_module=True)
    )

    def decorator(func: Callable[..., Coroutine[Any, Any, Any]]) -> Callable[..., Any]:
        @wraps(func)
        async def wrapper(*args: Any, **kwargs: Any) -> Any:
            result = await func(*args, **kwargs)
            if batch:
                ids = list(result) if id_attr is None else [getattr(item, id_attr) for item in result]
                await registered.kiq(ids)
            else:
                await registered.kiq(getattr(result, id_attr or "id"))
            return result

        return wrapper

    return decorator


def project(
    projection_cls: type[TESProjection],
    id_attr: str = "id",
) -> Callable[..., Callable[..., Any]]:
    """Decorate a write service method so that, after it returns, the changed
    entity is (re)projected into Elasticsearch by a background taskiq job.

    The id handed to ``projection_cls.project(id)`` is read off the returned
    object's ``id_attr`` — ``"id"`` by default, or e.g. ``"product_id"`` when the
    method returns a child row whose owning entity is what gets reprojected::

        @project(ProductProjection)
        async def create(self, data: ProductCreate) -> ProductModel: ...
    """
    return _dispatch_after(projection_cls, "project", "run", id_attr)


def batch_project(
    projection_cls: type[TBatchProjection],
    id_attr: str | None = "id",
) -> Callable[..., Callable[..., Any]]:
    """Decorate a write service method returning a sequence of entities so that,
    after it returns, they are all (re)projected by ONE background job carrying
    the list of their ids (``projection.batch_project(ids)``); pass
    ``id_attr=None`` when the method already returns the ids themselves::

        @batch_project(ListingBatchProjection)
        async def deactive_all(self, platform_id: int) -> Sequence[ListingModel]: ...
    """
    return _dispatch_after(projection_cls, "batch_project", "run_batch", id_attr, batch=True)


def unproject(
    projection_cls: type[TESProjection],
    id_attr: str = "id",
) -> Callable[..., Callable[..., Any]]:
    """Decorate a delete service method so that, after it returns, the removed
    entity's Elasticsearch document is dropped by a background taskiq job::

        @unproject(ProductProjection)
        async def remove(self, id: int) -> ProductModel: ...
    """
    return _dispatch_after(projection_cls, "unproject", "unproject", id_attr)
