from collections.abc import Callable, Coroutine
from functools import wraps
from typing import Any, get_args

from dishka.integrations.taskiq import FromDishka, inject
from pydantic import BaseModel

from src.common.bases.projection import (
    TBatchPayloadProjection,
    TBatchProjection,
    TESProjection,
    TPayloadProjection,
)
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


def _payload_model(projection_cls: type[Any]) -> type[BaseModel]:
    """Read the payload model a payload projection is bound to.

    Taking it off the projection's own generic parameter keeps the two ends
    from drifting apart — the job rebuilds exactly what the projection expects.

    Args:
        projection_cls (type[Any]): The projection to inspect.
    Returns:
        (type[BaseModel]): The model its payload is made of.
    """
    model: type[BaseModel] | None = None
    for base in getattr(projection_cls, "__orig_bases__", []):
        for arg in get_args(base):
            if isinstance(arg, type) and issubclass(arg, BaseModel):
                model = arg
                break
    if model is None:
        raise TypeError(f"{projection_cls.__name__} names no payload model to project")
    return model


def _dispatch_payload_after(
    projection_cls: type[Any],
    method: str,
    task_prefix: str,
    batch: bool = False,
) -> Callable[..., Callable[..., Any]]:
    """Register a background job that is *handed* its data, and return a
    decorator that dispatches it with whatever the wrapped method returned.

    Shared by ``payload_project`` / ``batch_payload_project``. The model is
    dumped to JSON to cross the queue and rebuilt inside the job.

    Args:
        projection_cls (type[Any]): The projection to run in background.
        method (str): The projection method to call.
        task_prefix (str): Task-name prefix (keeps the tasks distinct).
        batch (bool): The method returns a sequence, not a single model.
    Returns:
        (Callable): A decorator for the service method.
    """
    name = projection_cls.__name__.lower()
    task_name = f"{task_prefix}_{name}"
    queue_name = f"{name}_queue"
    model = _payload_model(projection_cls)

    async def _task(payload: Any, projection: Any) -> bool:
        rebuilt = (
            [model.model_validate(row) for row in payload]
            if batch
            else model.model_validate(payload)
        )
        result = await getattr(projection, method)(rebuilt)
        return result

    _task.__name__ = task_name
    _task.__qualname__ = task_name
    # dishka resolves the concrete projection off this annotation
    _task.__annotations__ = {
        "payload": list[dict[str, Any]] if batch else dict[str, Any],
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
            dumped = (
                [item.model_dump(mode="json") for item in result]
                if batch
                else result.model_dump(mode="json")
            )
            if dumped:
                await registered.kiq(dumped)
            return result

        return wrapper

    return decorator


def payload_project(
    projection_cls: type[TPayloadProjection],
) -> Callable[..., Callable[..., Any]]:
    """Decorate a write service method so that what it *returned* is projected
    into Elasticsearch by a background job — no read-back.

    Use this over `@project` when the caller already holds every value the
    document needs; `@project` stays right whenever the document needs more
    than the caller happens to hold::

        @payload_project(ListingPriceProjection)
        async def reprice(self, id: int) -> ListingPricePayload: ...
    """
    return _dispatch_payload_after(projection_cls, "project", "payload")


def batch_payload_project(
    projection_cls: type[TBatchPayloadProjection],
) -> Callable[..., Callable[..., Any]]:
    """Decorate a write service method returning a sequence of models so that
    all of them are projected from their own data by ONE background job::

        @batch_payload_project(ListingPriceBatchProjection)
        async def reprice_all(self, ids: Sequence[int]) -> Sequence[ListingPricePayload]: ...
    """
    return _dispatch_payload_after(
        projection_cls, "batch_project", "batch_payload", batch=True
    )
