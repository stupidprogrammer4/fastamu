"""Result selectors run inside an existing SQL transaction."""

from functools import wraps

from fastamu.infra.db.outbox.writer import require_transaction
from fastamu.infra.db.transaction import transaction
from fastamu.messaging.calls import after_result


def after_write(record):
    def decorate(function):
        wrapped = after_result(record)(function)

        @wraps(function)
        async def guarded(*args, **kwargs):
            require_transaction()
            async with transaction():
                return await wrapped(*args, **kwargs)

        return guarded

    return decorate
