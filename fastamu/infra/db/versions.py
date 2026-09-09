import hashlib
import time
from uuid import uuid4

from pydantic import BaseModel, Field
from sqlalchemy import and_, insert, or_, select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from fastamu.infra.db.tables import ProjectionVersionTable


class ProjectionPending(RuntimeError):
    pass


class ProjectionObsolete(RuntimeError):
    pass


class ProjectionExpired(RuntimeError):
    pass


class VersionStamp(BaseModel):
    target_id: int
    last_version: int = Field(ge=1)
    version_id: str = Field(pattern=r"^[0-9a-f]{32}$")


class ProjectionTicket(BaseModel):
    projection: str = Field(min_length=1, max_length=512)
    expires_at: float = Field(gt=0, allow_inf_nan=False)
    entries: list[VersionStamp] = Field(min_length=1)


class ProjectionVersions:
    def __init__(self, session: AsyncSession):
        self.session = session
        self.table = ProjectionVersionTable.metadata.tables[
            "fastamu_projection_versions"
        ]

    @staticmethod
    def key(projection: str, target_id: int) -> str:
        return hashlib.sha256(f"{projection}:{target_id}".encode()).hexdigest()

    async def stage(
        self, projection: str, ids: list[int], expires_at: float
    ) -> ProjectionTicket:
        version_id = uuid4().hex
        keys = {self.key(projection, id): id for id in dict.fromkeys(ids)}
        values = dict(
            version_id=version_id,
            expires_at=expires_at,
            updated_at=time.time(),
        )
        for attempt in range(3):
            # UPDATE starts the outer SQLite transaction before SAVEPOINT.
            # Existing rows serialize publishers, including concurrent inserts.
            await self.session.execute(
                update(self.table)
                .where(self.table.c.key.in_(sorted(keys)))
                .values(last_version=self.table.c.last_version + 1, **values)
            )
            result = await self.session.execute(
                select(self.table).where(self.table.c.key.in_(sorted(keys)))
            )
            rows = {row.key: row for row in result}
            missing = [key for key in keys if key not in rows]
            if any(row.version_id != version_id for row in rows.values()):
                continue
            try:
                if missing:
                    async with self.session.begin_nested():
                        await self.session.execute(
                            insert(self.table),
                            [
                                dict(
                                    key=key,
                                    projection=projection,
                                    target_id=keys[key],
                                    last_version=1,
                                    **values,
                                )
                                for key in missing
                            ],
                        )
            except IntegrityError:
                if attempt == 2:
                    raise
                continue
            return ProjectionTicket(
                projection=projection,
                expires_at=expires_at,
                entries=[
                    VersionStamp(
                        target_id=id,
                        last_version=rows[key].last_version
                        if key in rows
                        else 1,
                        version_id=version_id,
                    )
                    for key, id in keys.items()
                ],
            )
        raise RuntimeError("Concurrent projection version allocation failed")

    async def pending(self, ticket: ProjectionTicket) -> ProjectionTicket:
        keys = [
            self.key(ticket.projection, row.target_id)
            for row in ticket.entries
        ]
        result = await self.session.execute(
            select(self.table).where(self.table.c.key.in_(keys))
        )
        rows = {row.key: row for row in result}
        pending = []
        for entry, key in zip(ticket.entries, keys):
            row = rows.get(key)
            if row is None or row.last_version < entry.last_version:
                raise ProjectionPending(
                    "Projection version is not committed yet"
                )
            if (
                row.last_version == entry.last_version
                and row.version_id == entry.version_id
                and (
                    row.completed_version != entry.last_version
                    or row.completed_id != entry.version_id
                )
            ):
                pending.append(entry)
        if not pending:
            raise ProjectionObsolete("Projection was superseded or completed")
        if ticket.expires_at <= time.time():
            raise ProjectionExpired("Projection retry deadline has passed")
        return ticket.model_copy(update={"entries": pending})

    async def complete(self, ticket: ProjectionTicket) -> None:
        await self.session.execute(
            update(self.table)
            .where(
                or_(
                    *[
                        and_(
                            self.table.c.key
                            == self.key(ticket.projection, row.target_id),
                            self.table.c.last_version == row.last_version,
                            self.table.c.version_id == row.version_id,
                        )
                        for row in ticket.entries
                    ]
                )
            )
            .values(
                completed_version=self.table.c.last_version,
                completed_id=self.table.c.version_id,
            )
        )
