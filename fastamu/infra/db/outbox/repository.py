"""Short SQL transactions for claiming and completing publications."""

from collections.abc import Sequence
from dataclasses import dataclass
from datetime import timedelta
from uuid import UUID, uuid4

from sqlalchemy import and_, delete, func, or_, select, update

from fastamu.infra.db.connection import DBConnection
from fastamu.infra.db.outbox.table import (
    outbox,
    outbox_batches,
    outbox_control,
)
from fastamu.messaging.outbox.message import OutboxMessage


@dataclass(frozen=True, slots=True)
class Claimed:
    message: OutboxMessage
    token: UUID
    attempts: int


@dataclass(frozen=True, slots=True)
class Batch:
    id: UUID
    size: int


@dataclass(frozen=True, slots=True)
class BatchOwner:
    id: UUID
    token: UUID


def affected(result) -> int:
    count = result.rowcount
    if count < 0:
        raise RuntimeError("The database driver must report affected rows")
    return count


class OutboxRepository:
    def __init__(self, db: DBConnection):
        self.db = db

    async def claim(
        self,
        *,
        limit: int,
        lease_seconds: float,
        ids: Sequence[UUID] | None = None,
        batch: BatchOwner | None = None,
        batch_lease_seconds: float = 60,
    ) -> list[Claimed]:
        if ids is not None and not ids:
            return []
        token = uuid4()
        async with self.db.session_factory.begin() as session:
            await self._lock(session)
            now = (
                await session.execute(select(func.current_timestamp()))
            ).scalar_one()
            if batch is not None:
                renewed = await session.execute(
                    update(outbox_batches)
                    .where(
                        outbox_batches.c.id == batch.id,
                        outbox_batches.c.worker_token == batch.token,
                        outbox_batches.c.expires_at > now,
                    )
                    .values(
                        expires_at=now + timedelta(seconds=batch_lease_seconds)
                    )
                )
                if not affected(renewed):
                    return []
            ready = and_(
                outbox.c.available_at <= now,
                outbox.c.batch_id == batch.id
                if batch
                else outbox.c.batch_id.is_(None),
            )
            query = select(outbox.c.id).where(ready)
            if ids is not None:
                query = query.where(outbox.c.id.in_(ids))
            candidates = (
                await session.scalars(
                    query.order_by(outbox.c.available_at, outbox.c.id).limit(
                        limit
                    )
                )
            ).all()
            if not candidates:
                return []
            # Recheck readiness so an existing live lease is preserved.
            await session.execute(
                update(outbox)
                .where(outbox.c.id.in_(candidates), ready)
                .values(
                    claim_token=token,
                    available_at=now + timedelta(seconds=lease_seconds),
                    attempts=outbox.c.attempts + 1,
                )
            )
            rows = (
                (
                    await session.execute(
                        select(outbox).where(
                            outbox.c.id.in_(candidates),
                            outbox.c.claim_token == token,
                        )
                    )
                )
                .mappings()
                .all()
            )
        return [
            Claimed(
                OutboxMessage(
                    id=row["id"],
                    kind=row["kind"],
                    target=row["target"],
                    payload=row["payload"],
                ),
                token,
                row["attempts"],
            )
            for row in rows
        ]

    async def published(self, claimed: Sequence[Claimed]) -> int:
        """Delete confirmed messages together, checking each claim owner."""
        if not claimed:
            return 0
        async with self.db.session_factory.begin() as session:
            return affected(
                await session.execute(
                    delete(outbox).where(
                        or_(
                            *[
                                and_(
                                    outbox.c.id == item.message.id,
                                    outbox.c.claim_token == item.token,
                                )
                                for item in claimed
                            ]
                        )
                    )
                )
            )

    async def reschedule(
        self, claimed: Claimed, error: Exception, delay: float
    ) -> bool:
        async with self.db.session_factory.begin() as session:
            now = (
                await session.execute(select(func.current_timestamp()))
            ).scalar_one()
            return bool(
                affected(
                    await session.execute(
                        update(outbox)
                        .where(
                            outbox.c.id == claimed.message.id,
                            outbox.c.claim_token == claimed.token,
                        )
                        .values(
                            available_at=now + timedelta(seconds=delay),
                            claim_token=None,
                            batch_id=None,
                            last_error=f"{type(error).__name__}: {error}"[
                                :2000
                            ],
                        )
                    )
                )
            )

    async def plan_batches(
        self, *, batch_size: int, max_batches: int, lease_seconds: float
    ) -> list[Batch]:
        """A singleton SQL row serializes reservations, never network sends."""
        async with self.db.session_factory.begin() as session:
            await self._lock(session)
            now = (
                await session.execute(select(func.current_timestamp()))
            ).scalar_one()
            expired = (
                await session.scalars(
                    select(outbox_batches.c.id).where(
                        outbox_batches.c.expires_at <= now
                    )
                )
            ).all()
            if expired:
                await session.execute(
                    delete(outbox_batches).where(
                        outbox_batches.c.id.in_(expired),
                        outbox_batches.c.expires_at <= now,
                    )
                )
                retained = set(
                    (
                        await session.scalars(
                            select(outbox_batches.c.id).where(
                                outbox_batches.c.id.in_(expired)
                            )
                        )
                    ).all()
                )
                await session.execute(
                    update(outbox)
                    .where(
                        outbox.c.batch_id.in_(
                            [id for id in expired if id not in retained]
                        )
                    )
                    .values(batch_id=None)
                )
            active = await session.scalar(
                select(func.count()).select_from(outbox_batches)
            )
            capacity = max(0, max_batches - (active or 0))
            if not capacity:
                return []
            ready = and_(
                outbox.c.available_at <= now, outbox.c.batch_id.is_(None)
            )
            ids = (
                await session.scalars(
                    select(outbox.c.id)
                    .where(ready)
                    .order_by(outbox.c.available_at, outbox.c.id)
                    .limit(capacity * batch_size)
                )
            ).all()
            batches = []
            for start in range(0, len(ids), batch_size):
                selected = ids[start : start + batch_size]
                id = uuid4()
                assigned = affected(
                    await session.execute(
                        update(outbox)
                        .where(outbox.c.id.in_(selected), ready)
                        .values(batch_id=id)
                    )
                )
                if not assigned:
                    continue
                await session.execute(
                    outbox_batches.insert().values(
                        id=id,
                        expires_at=now + timedelta(seconds=lease_seconds),
                    )
                )
                batches.append(Batch(id, assigned))
            return batches

    async def _lock(self, session) -> None:
        locked = await session.execute(
            update(outbox_control).where(outbox_control.c.id == 1).values(id=1)
        )
        if not affected(locked):
            raise RuntimeError(
                "Outbox control row is missing; apply migrations"
            )

    async def start_batch(
        self, id: UUID, *, lease_seconds: float
    ) -> BatchOwner | None:
        token = uuid4()
        async with self.db.session_factory.begin() as session:
            now = (
                await session.execute(select(func.current_timestamp()))
            ).scalar_one()
            started = affected(
                await session.execute(
                    update(outbox_batches)
                    .where(
                        outbox_batches.c.id == id,
                        outbox_batches.c.worker_token.is_(None),
                        outbox_batches.c.expires_at > now,
                    )
                    .values(
                        worker_token=token,
                        expires_at=now + timedelta(seconds=lease_seconds),
                    )
                )
            )
        return BatchOwner(id, token) if started else None

    async def finish_batch(self, batch: BatchOwner) -> None:
        async with self.db.session_factory.begin() as session:
            removed = affected(
                await session.execute(
                    delete(outbox_batches).where(
                        outbox_batches.c.id == batch.id,
                        outbox_batches.c.worker_token == batch.token,
                    )
                )
            )
            if removed:
                await session.execute(
                    update(outbox)
                    .where(outbox.c.batch_id == batch.id)
                    .values(batch_id=None)
                )
