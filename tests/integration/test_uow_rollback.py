from uuid import uuid4

import pytest
from dishka import Provider, Scope, make_async_container, provide
from dishka.integrations.fastapi import FromDishka, inject, setup_dishka
from fastapi import FastAPI
from fastapi.exceptions import RequestValidationError
from fastapi_csrf_protect.exceptions import CsrfProtectError
from httpx import ASGITransport, AsyncClient
from sqlalchemy import Column, Integer, MetaData, Table, insert, select
from starlette.exceptions import HTTPException

from fastamu.common.errors.exceptions import ValidationException
from fastamu.core.provider import CoreProvider
from fastamu.infra.db.connection import DBConnection
from fastamu.infra.db.transaction import transactional
from fastamu.infra.db.uow import DBUnitOfWork
from fastamu.web.error_handlers import setup_exception_handlers


@pytest.fixture
async def database(tmp_path):
    db = DBConnection(
        f"sqlite+aiosqlite:///{tmp_path}/requests.db", 3, 0, 5, 1800
    )
    try:
        yield db
    finally:
        await db.dispose()


@pytest.fixture
async def records(database):
    metadata = MetaData()
    table = Table(
        "test_uow_" + uuid4().hex,
        metadata,
        Column("id", Integer, primary_key=True),
    )
    async with database.session_factory() as session:
        connection = await session.connection()
        await connection.run_sync(metadata.create_all)
        await session.commit()
    try:
        yield table
    finally:
        async with database.session_factory() as session:
            connection = await session.connection()
            await connection.run_sync(metadata.drop_all)
            await session.commit()


@pytest.fixture
async def client(database, records):
    class DatabaseProvider(Provider):
        @provide(scope=Scope.APP, override=True)
        def database(self) -> DBConnection:
            return database

    container = make_async_container(CoreProvider(), DatabaseProvider())
    app = FastAPI()
    setup_dishka(container, app)
    setup_exception_handlers(app)

    @app.post("/{outcome}")
    @inject
    @transactional
    async def write(outcome: str, uow: FromDishka[DBUnitOfWork]):
        await uow.session.execute(insert(records).values(id=1))
        if outcome == "validation":
            raise ValidationException(
                message="Invalid batch",
                message_code="test.invalid",
                loc=["items", 1],
            )
        if outcome == "pydantic":
            raise RequestValidationError(
                [
                    {
                        "type": "missing",
                        "loc": ["body", "value"],
                        "msg": "Required",
                    }
                ]
            )
        if outcome == "http":
            raise HTTPException(status_code=409, detail="Conflict")
        if outcome == "csrf":
            raise CsrfProtectError(status_code=403, message="Invalid CSRF")
        if outcome == "unexpected":
            raise RuntimeError("Unexpected failure")
        return {"ok": True}

    try:
        async with AsyncClient(
            transport=ASGITransport(app=app, raise_app_exceptions=False),
            base_url="http://test",
        ) as http:
            yield http
    finally:
        await container.close()


@pytest.mark.parametrize(
    ("outcome", "status"),
    [
        ("validation", 400),
        ("pydantic", 422),
        ("http", 409),
        ("csrf", 403),
        ("unexpected", 500),
    ],
)
async def test_error_response_rolls_back_the_write(
    client, database, records, outcome, status
):
    response = await client.post("/" + outcome)
    assert response.status_code == status, response.text
    async with database.session_factory() as session:
        result = await session.execute(select(records.c.id))
        assert result.scalars().all() == []


async def test_success_response_commits_the_write(client, database, records):
    response = await client.post("/success")
    assert response.status_code == 200, response.text
    async with database.session_factory() as session:
        result = await session.execute(select(records.c.id))
        assert result.scalars().all() == [1]
