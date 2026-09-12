from collections.abc import Awaitable, Callable, Coroutine, Sequence
from functools import wraps
from typing import Any

from pydantic import StrictInt, TypeAdapter

from fastamu.messaging.projections.contracts.base import (
    AbstractBatchProjection,
    AbstractFanoutProjection,
    AbstractProjection,
)
from fastamu.messaging.projections.contracts.delete import (
    AbstractBatchUnProjection,
    AbstractUnProjection,
)
from fastamu.messaging.projections.contracts.patch import (
    AbstractBatchPatchProjection,
    AbstractPatchProjection,
)
from fastamu.tasks.projection.delivery.fallback import fallback
from fastamu.tasks.projection.delivery.register import register

type SingleProjection = (
    AbstractProjection[Any, Any]
    | AbstractPatchProjection[Any, Any]
    | AbstractFanoutProjection[Any, Any]
    | AbstractUnProjection
)
type BatchProjection = (
    AbstractBatchProjection[Any, Any]
    | AbstractBatchPatchProjection[Any, Any]
    | AbstractBatchUnProjection
)

_id = TypeAdapter(StrictInt)
_ids = TypeAdapter(list[StrictInt])


def project[**P, R](
    projection: type[SingleProjection],
    mapper: Callable[[R], int],
) -> Callable[
    [Callable[P, Awaitable[R]]], Callable[P, Coroutine[Any, Any, R]]
]:
    def decorate(
        function: Callable[P, Awaitable[R]],
    ) -> Callable[P, Coroutine[Any, Any, R]]:
        @wraps(function)
        async def wrapped(*args: P.args, **kwargs: P.kwargs) -> R:
            result = await function(*args, **kwargs)
            id = _id.validate_python(mapper(result))
            task = register.get(projection)
            try:
                await task.kiq(id=id)
            except Exception as error:
                if not await fallback.queued(task.task_name, [id], error):
                    raise
            return result

        return wrapped

    return decorate


def batch_project[**P, R](
    projection: type[BatchProjection],
    mapper: Callable[[R], Sequence[int]],
) -> Callable[
    [Callable[P, Awaitable[R]]], Callable[P, Coroutine[Any, Any, R]]
]:
    def decorate(
        function: Callable[P, Awaitable[R]],
    ) -> Callable[P, Coroutine[Any, Any, R]]:
        @wraps(function)
        async def wrapped(*args: P.args, **kwargs: P.kwargs) -> R:
            result = await function(*args, **kwargs)
            ids = _ids.validate_python(mapper(result))
            task = register.get(projection)
            try:
                await task.kiq(ids=ids)
            except Exception as error:
                if not await fallback.queued(task.task_name, ids, error):
                    raise
            return result

        return wrapped

    return decorate


patch = project
unproject = project
fanout = project
batch_patch = batch_project
batch_unproject = batch_project
