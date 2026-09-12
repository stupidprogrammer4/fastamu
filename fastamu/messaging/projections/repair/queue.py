import logging
import time
from collections.abc import Sequence

from fastamu.infra.redis.client import RedisClient, resolve
from fastamu.messaging.projections.repair.records import FailureRecord

logger = logging.getLogger(__name__)


class RedisFailureQueue:
    """One Redis list per projection: taking pops, handing back appends.

    Spending every attempt moves a record to the dead list, not to nowhere.
    """

    def __init__(
        self,
        redis: RedisClient,
        prefix: str,
        max_attempts: int = 5,
        max_pending: int = 100_000,
    ) -> None:
        self.redis = redis
        self.prefix = prefix
        self.max_attempts = max_attempts
        self.max_pending = max_pending

    def key(self, projection_name: str) -> str:
        return f"{self.prefix}:{projection_name}"

    def dead_key(self, projection_name: str) -> str:
        return f"{self.key(projection_name)}:dead"

    async def record(
        self,
        projection_name: str,
        ids: Sequence[int],
        error: str,
    ) -> None:
        if not ids:
            return
        now = time.time()
        records = [
            FailureRecord(input_id=id, error=error, failed_at=now)
            for id in dict.fromkeys(ids)
        ]
        await self._push(self.key(projection_name), records)
        await self._bound(projection_name)

    async def take(
        self,
        projection_name: str,
        limit: int,
    ) -> list[FailureRecord]:
        records: list[FailureRecord] = []
        if limit >= 1:
            raw = await resolve(
                self.redis.client.lpop(self.key(projection_name), limit)
            )
            records = [
                FailureRecord.model_validate_json(item) for item in raw or []
            ]
        return records

    async def requeue(
        self,
        projection_name: str,
        records: Sequence[FailureRecord],
    ) -> None:
        if not records:
            return
        pending: list[FailureRecord] = []
        dead: list[FailureRecord] = []
        for record in records:
            attempted = record.attempted()
            target = (
                dead if attempted.attempts >= self.max_attempts else pending
            )
            target.append(attempted)
        await self._push(self.key(projection_name), pending)
        await self._push(self.dead_key(projection_name), dead)
        if dead:
            logger.warning(
                "Gave up on %d %s inputs after %d attempts: %s",
                len(dead),
                projection_name,
                self.max_attempts,
                ", ".join(str(record.input_id) for record in dead),
            )
        await self._bound(projection_name)

    async def _push(
        self,
        key: str,
        records: Sequence[FailureRecord],
    ) -> None:
        if records:
            await resolve(
                self.redis.client.rpush(
                    key, *[record.model_dump_json() for record in records]
                )
            )

    async def _bound(self, projection_name: str) -> None:
        """Drop the oldest once the queue passes its ceiling."""
        key = self.key(projection_name)
        pending = await resolve(self.redis.client.llen(key))
        if pending > self.max_pending:
            await resolve(self.redis.client.ltrim(key, -self.max_pending, -1))
            logger.warning(
                "Dropped %d oldest %s failures over the %d ceiling",
                pending - self.max_pending,
                projection_name,
                self.max_pending,
            )
