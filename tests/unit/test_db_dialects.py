import os

import pytest
from sqlalchemy.dialects import mssql, mysql, oracle, postgresql, sqlite
from sqlalchemy.schema import CreateTable
from sqlmodel import col

from fastamu.common.models.entities import (
    BaseIDTimestampEntity,
    BaseVersionEntity,
)
from fastamu.common.models.fields import CharField, IntField, JSONField
from fastamu.infra.db.connection import DBConnection
from fastamu.infra.db.dialects import DIALECTS, get_dialect
from fastamu.infra.db.repository import DBTimestampIDRepository
from fastamu.infra.db.table import BaseTable
from fastamu.infra.db.transaction import transaction


class DialectProbeEntity(BaseIDTimestampEntity, BaseVersionEntity):
    code: str = CharField(64, unique=True)
    quantity: int = IntField(default=0)
    attributes: dict | None = JSONField(nullable=True, default=dict)


class DialectProbeTable(DialectProbeEntity, BaseTable, table=True):
    pass


class ProbeRepository(DBTimestampIDRepository[DialectProbeEntity]):
    pass


@pytest.mark.parametrize("name", DIALECTS)
def test_builtin_dialect_registration(name):
    assert get_dialect(name).name == name


@pytest.mark.parametrize(
    "dialect",
    [
        postgresql.dialect(),
        mysql.dialect(),
        sqlite.dialect(),
        mssql.dialect(),
        oracle.dialect(),
    ],
)
def test_portable_identity_schema_and_bulk_update_compilation(dialect):
    ddl = str(
        CreateTable(DialectProbeTable.__table__).compile(dialect=dialect)
    )
    assert "CURRENT_TIMESTAMP" in ddl
    adapter = get_dialect(dialect.name)
    stmt = adapter.bulk_update(
        DialectProbeTable,
        [{"id": 1, "quantity": 5}, {"id": 2, "quantity": 8}],
        "id",
    )
    assert "UPDATE" in str(stmt.compile(dialect=dialect))


@pytest.mark.parametrize(
    "name,dialect,syntax",
    [
        ("postgresql", postgresql.dialect(), "ON CONFLICT"),
        ("sqlite", sqlite.dialect(), "ON CONFLICT"),
        ("mysql", mysql.dialect(), "ON DUPLICATE KEY UPDATE"),
        ("mariadb", mysql.dialect(), "ON DUPLICATE KEY UPDATE"),
    ],
)
def test_native_upsert_compiles(name, dialect, syntax):
    stmt = get_dialect(name).upsert(
        DialectProbeTable, [{"code": "a", "quantity": 4}], ["code"]
    )
    assert syntax in str(stmt.compile(dialect=dialect))


@pytest.mark.parametrize("backend", ["sqlite", "postgresql", "mysql"])
async def test_repository_crud_bulk_upsert_and_rollback(backend):
    url = (
        "sqlite+aiosqlite:///:memory:"
        if backend == "sqlite"
        else os.environ.get("FASTAMU_TEST_" + backend.upper())
    )
    if not url:
        pytest.skip(f"Set FASTAMU_TEST_{backend.upper()} for this backend")
    db = DBConnection(url, 2, 0, 30, 1800)
    table = DialectProbeTable.__table__
    try:
        async with db.engine.begin() as conn:
            await conn.run_sync(table.create)
        async with db.uow() as uow, transaction():
            repo = ProbeRepository(uow)
            first = await repo.create(
                DialectProbeEntity(
                    code="a", quantity=1, attributes={"value": 1}
                )
            )
            assert first.id is not None and first.created_at is not None
            assert first.attributes == {"value": 1}
            rows = await repo.bulk_create(
                [
                    DialectProbeEntity(attributes={}, code="b", quantity=2),
                    DialectProbeEntity(attributes={}, code="c", quantity=3),
                ]
            )
            assert len(rows) == 2
            all_rows = await repo.get_all()
            ids = {r.code: r.id for r in all_rows}
            updated = await repo.bulk_update_rows(
                [
                    DialectProbeEntity.patch(id=ids["a"], quantity=10),
                    DialectProbeEntity.patch(id=ids["b"], quantity=20),
                ],
                col(DialectProbeTable.id),
            )
            assert {r.quantity for r in updated} == {10, 20}
            # every write path raises the counter, and none of them is asked to
            assert {r.version_num for r in updated} == {2}
            json_rows = await repo.bulk_update_rows(
                [
                    DialectProbeEntity.patch(
                        id=ids["a"], attributes={"batch": True}
                    ),
                    DialectProbeEntity.patch(
                        id=ids["b"], attributes={"batch": False}
                    ),
                ],
                col(DialectProbeTable.id),
            )
            assert {r.attributes["batch"] for r in json_rows} == {True, False}
            upserted = await repo.upsert_rows(
                [DialectProbeEntity(attributes={}, code="a", quantity=30)],
                [col(DialectProbeTable.code)],
            )
            assert upserted[0].id == ids["a"] and upserted[0].quantity == 30
            # the SET clause of an upsert carries no onupdate of its own
            assert upserted[0].version_num == 4
            assert upserted[0].updated_at > first.created_at
            changed = await repo.update_by_id(ids["c"], {"quantity": 40})
            assert changed.quantity == 40
            assert changed.version_num == 2
            deleted = await repo.delete_by_ids([ids["b"], ids["c"]])
            assert len(deleted) == 2
            assert await repo.get_by_id(ids["b"]) is None
            assert await uow.now() is not None
        from fastamu.common.errors.exceptions import ConflictException

        with pytest.raises(ConflictException):
            async with db.uow() as uow, transaction():
                await ProbeRepository(uow).create(
                    DialectProbeEntity(attributes={}, code="a", quantity=99)
                )
        with pytest.raises(RuntimeError, match="rollback"):
            async with db.uow() as uow, transaction():
                await ProbeRepository(uow).create(
                    DialectProbeEntity(
                        attributes={}, code="rollback", quantity=0
                    )
                )
                raise RuntimeError("rollback")
        async with db.uow() as uow, transaction():
            assert [r.code for r in await ProbeRepository(uow).get_all()] == [
                "a"
            ]
    finally:
        async with db.engine.begin() as conn:
            await conn.run_sync(table.drop, checkfirst=True)
        await db.dispose()
