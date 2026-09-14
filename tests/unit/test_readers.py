"""Table-independent readers preserve full join/aggregate results."""

import importlib
import inspect
from collections.abc import AsyncIterator
from dataclasses import dataclass
from unittest.mock import AsyncMock

import pytest
from dishka import Provider, Scope, make_async_container, provide
from sqlalchemy import (
    Column,
    Integer,
    MetaData,
    String,
    Table,
    func,
    insert,
    select,
)

from papilio.infra.db.connection import DBConnection
from papilio.infra.db.repositories.backends.sqlite import SQLiteReader
from papilio.infra.db.repositories.contracts.base import (
    ReaderContract,
)
from papilio.infra.db.tools.read import (
    fetch_page,
    stream,
)
from papilio.infra.db.uow import SQLiteUnitOfWork

metadata = MetaData()
groups = Table(
    "reader_groups",
    metadata,
    Column("id", Integer, primary_key=True),
    Column("name", String, nullable=False),
)
records = Table(
    "reader_records",
    metadata,
    Column("id", Integer, primary_key=True),
    Column("group_id", Integer, nullable=False),
    Column("amount", Integer, nullable=False),
)


@dataclass(frozen=True)
class GroupReport:
    name: str
    count: int
    total: int


class ReportReader(SQLiteReader):
    async def totals(self, *, minimum_count: int) -> list[GroupReport]:
        stmt = (
            select(
                groups.c.name,
                func.count(records.c.id).label("count"),
                func.sum(records.c.amount).label("total"),
            )
            .join(records, records.c.group_id == groups.c.id)
            .group_by(groups.c.id, groups.c.name)
            .having(func.count(records.c.id) >= minimum_count)
            .order_by(groups.c.id)
        )
        result = await self.uow.execute(stmt)
        return [
            GroupReport(row["name"], row["count"], row["total"])
            for row in result.mappings()
        ]

    async def details(self) -> list[tuple[int, str, int]]:
        stmt = (
            select(records.c.id, groups.c.name, records.c.amount)
            .join(groups, groups.c.id == records.c.group_id)
            .order_by(records.c.id)
        )
        result = await self.uow.execute(stmt)
        return [(row.id, row.name, row.amount) for row in result]


@pytest.mark.parametrize(
    "backend,prefix",
    [
        ("postgresql", "PG"),
        ("mysql", "MySQL"),
        ("mariadb", "MariaDB"),
        ("sqlite", "SQLite"),
        ("oracle", "Oracle"),
        ("mssql", "MSSQL"),
    ],
)
async def test_each_backend_has_its_own_reader(backend, prefix):
    contracts = importlib.import_module(
        f"papilio.infra.db.repositories.contracts.{backend}"
    )
    implementations = importlib.import_module(
        f"papilio.infra.db.repositories.backends.{backend}"
    )
    units = importlib.import_module("papilio.infra.db.uow")
    contract = getattr(contracts, f"{prefix}ReaderContract")
    implementation = getattr(implementations, f"{prefix}Reader")
    unit_type = getattr(units, f"{prefix}UnitOfWork")
    assert inspect.isabstract(contract)
    assert not inspect.isabstract(implementation)
    assert issubclass(implementation, contract)
    assert issubclass(contract, ReaderContract)
    assert (
        inspect.signature(implementation).parameters["uow"].annotation
        is unit_type
    )

    # Only exercise construction and DI here; no backend SQL is executed.
    database = DBConnection(
        "sqlite+aiosqlite:///:memory:",
        1,
        0,
        5,
        1800,
        uow_factory=unit_type,
    )
    provider = Provider()
    provider.from_context(provides=unit_type, scope=Scope.REQUEST)
    provider.provide(implementation, provides=contract, scope=Scope.REQUEST)
    container = make_async_container(provider)
    try:
        async with database.uow() as unit:
            async with container(
                scope=Scope.REQUEST, context={unit_type: unit}
            ) as scope:
                reader = await scope.get(contract)
                assert type(reader) is implementation
                assert reader.uow is unit
                assert reader.uow.session is unit.session
                assert not hasattr(reader, "table")
                assert not hasattr(reader, "create")
    finally:
        await container.close()
        await database.dispose()


@pytest.fixture
async def query_store(tmp_path):
    db = DBConnection(
        f"sqlite+aiosqlite:///{tmp_path}/queries.db",
        2,
        0,
        5,
        1800,
        uow_factory=SQLiteUnitOfWork,
    )
    try:
        async with db.engine.begin() as connection:
            await connection.run_sync(metadata.create_all)
            await connection.execute(
                insert(groups),
                [
                    {"id": 1, "name": "retail"},
                    {"id": 2, "name": "wholesale"},
                    {"id": 3, "name": "archive"},
                    {"id": 4, "name": "empty"},
                ],
            )
            await connection.execute(
                insert(records),
                [
                    {"group_id": 1, "amount": 10},
                    {"group_id": 1, "amount": 20},
                    {"group_id": 2, "amount": 40},
                    {"group_id": 3, "amount": 80},
                ],
            )
        async with db.uow() as unit:
            yield ReportReader(unit)
    finally:
        await db.dispose()


async def test_reader_joins_tables_and_returns_complete_rows(query_store):
    assert isinstance(query_store, ReaderContract)
    assert not hasattr(query_store, "table")
    assert await query_store.details() == [
        (1, "retail", 10),
        (2, "retail", 20),
        (3, "wholesale", 40),
        (4, "archive", 80),
    ]


async def test_reader_maps_joined_aggregates_to_its_own_report(query_store):
    assert await query_store.totals(minimum_count=1) == [
        GroupReport("retail", 2, 30),
        GroupReport("wholesale", 1, 40),
        GroupReport("archive", 1, 80),
    ]
    assert await query_store.totals(minimum_count=2) == [
        GroupReport("retail", 2, 30),
    ]
    assert await query_store.totals(minimum_count=3) == []


async def test_reader_receives_its_typed_uow_through_dishka(query_store):
    database = query_store.uow.connection

    class ReaderProvider(Provider):
        reader = provide(ReportReader, scope=Scope.REQUEST)

        @provide(scope=Scope.REQUEST)
        async def uow(self) -> AsyncIterator[SQLiteUnitOfWork]:
            async with database.uow() as unit:
                yield unit

    container = make_async_container(ReaderProvider())
    try:
        async with container(scope=Scope.REQUEST) as scope:
            reader = await scope.get(ReportReader)
            unit = await scope.get(SQLiteUnitOfWork)
            assert reader.uow is unit
            assert reader.uow.session is unit.session
            assert await reader.totals(minimum_count=2) == [
                GroupReport("retail", 2, 30),
            ]
        assert not unit.is_open
    finally:
        await container.close()


async def test_page_counts_groups_and_keeps_total_beyond_last_page(
    query_store,
):
    query = (
        select(records.c.group_id)
        .where(records.c.group_id > 1)
        .group_by(records.c.group_id)
        .order_by(records.c.group_id)
    )
    page = await fetch_page(query_store.uow, query, limit=1, offset=1)
    assert list(page.items) == [3]
    assert page.total_items == 2
    empty = await fetch_page(query_store.uow, query, limit=1, offset=20)
    assert list(empty.items) == []
    assert empty.total_items == 2


async def test_closing_scalar_stream_releases_result(query_store, monkeypatch):
    result = await query_store.uow.stream(
        select(records.c.id).order_by(records.c.id)
    )
    monkeypatch.setattr(
        query_store.uow, "stream", AsyncMock(return_value=result)
    )
    rows = stream(query_store.uow, select(records.c.id), batch_size=1)
    assert await anext(rows) == 1
    await rows.aclose()
    assert result.closed
