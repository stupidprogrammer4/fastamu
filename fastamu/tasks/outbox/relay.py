"""Immediate delivery and optional polling share exactly one claim protocol."""

import asyncio
import logging
import random
from collections.abc import Awaitable, Callable, Sequence
from uuid import UUID

from fastamu.core.config import OutboxConfig
from fastamu.infra.db.outbox.repository import (
    BatchOwner,
    Claimed,
    OutboxRepository,
)
from fastamu.messaging.outbox.message import OutboxMessage
from fastamu.tasks.outbox.publishers import publish

logger = logging.getLogger(__name__)


class OutboxRelay:
    def __init__(
        self,
        repository: OutboxRepository,
        config: OutboxConfig,
        publisher: Callable[[OutboxMessage], Awaitable[None]] = publish,
    ):
        self.repository = repository
        self.config = config
        self.publisher = publisher

    async def _send(self, claimed: Claimed) -> bool:
        try:
            async with asyncio.timeout(self.config.publish_timeout):
                await self.publisher(claimed.message)
        except Exception as error:
            logger.warning(
                "Outbox publication failed: %s",
                claimed.message.id,
                exc_info=True,
            )
            ceiling = min(
                self.config.max_retry_delay,
                self.config.retry_delay * 2 ** min(claimed.attempts - 1, 20),
            )
            await self.repository.reschedule(
                claimed, error, random.uniform(ceiling / 2, ceiling)
            )
            return False
        return True

    async def run_once(
        self,
        ids: Sequence[UUID] | None = None,
        *,
        batch: BatchOwner | None = None,
    ) -> int:
        """A bounded pass; only claim as many messages as can start now."""
        sent = 0
        remaining = self.config.batch_size if ids is None else len(ids)
        while remaining > 0:
            limit = min(remaining, self.config.concurrency)
            selected = None
            if ids is not None:
                offset = len(ids) - remaining
                selected = ids[offset : offset + limit]
            claimed = await self.repository.claim(
                ids=selected,
                limit=limit,
                lease_seconds=self.config.lease_seconds,
                batch=batch,
                batch_lease_seconds=self.config.batch_lease_seconds,
            )
            if not claimed and ids is None:
                break
            remaining -= limit if ids is not None else len(claimed)
            results = await asyncio.gather(
                *(self._send(item) for item in claimed),
                return_exceptions=True,
            )
            confirmed = []
            for item, result in zip(claimed, results, strict=True):
                if isinstance(result, BaseException):
                    if isinstance(result, asyncio.CancelledError):
                        raise result
                    logger.error(
                        "Outbox result could not be stored: %s",
                        item.message.id,
                        exc_info=(type(result), result, result.__traceback__),
                    )
                elif result:
                    confirmed.append(item)
            if confirmed:
                try:
                    sent += await self.repository.published(confirmed)
                except Exception:
                    logger.exception(
                        "Outbox confirmations could not be stored: %s",
                        [item.message.id for item in confirmed],
                    )
        return sent

    async def run_batch(self, id: UUID) -> int:
        owner = await self.repository.start_batch(
            id, lease_seconds=self.config.batch_lease_seconds
        )
        if owner is None:
            return 0
        try:
            return await self.run_once(batch=owner)
        finally:
            await self.repository.finish_batch(owner)
