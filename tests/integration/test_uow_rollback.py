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

from papilio.api.responses.csrf import csrf_error_handler
from papilio.api.responses.handlers import (
    setup_exception_handlers,
)
from papilio.core.config import get_settings
from papilio.errors.exceptions import ValidationException
from papilio.infra.db.connection import DBConnection
from papilio.infra.db.provider import PGProvider
from papilio.infra.db.tools.decorators import transactional
from papilio.infra.db.uow import PGUnitOfWork


@pytest.fixture
async def database(tmp_path):
    db = DBConnection(
        f"sqlite+aiosqlite:///{tmp_path}/requests.db",
        3,
        0,
        5,
        1800,
        uow_factory=PGUnitOfWork,
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
        def database(self) -> DBConnection[PGUnitOfWork]:
            return database

    container = make_async_container(
        PGProvider(get_settings().db), DatabaseProvider()
    )
    app = FastAPI()
    setup_dishka(container, app)
    setup_exception_handlers(app)
    app.add_exception_handler(CsrfProtectError, csrf_error_handler)

    @app.post("/{outcome}")
    @inject
    @transactional
    async def write(outcome: str, uow: FromDishka[PGUnitOfWork]):
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
