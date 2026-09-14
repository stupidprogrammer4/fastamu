import asyncio

from papilio.infra.db.connection import DBConnection
from papilio.infra.db.schema.fields import CharField, IntField
from papilio.infra.db.schema.entity import IdentifiedEntity
from papilio.infra.db.repositories.backends.sqlite import (
    SQLiteIdentifiedRepository,
)
from papilio.infra.db.table import BaseTable
from papilio.infra.db.transaction import transaction
from papilio.infra.db.uow import SQLiteUnitOfWork


class Product(IdentifiedEntity):
    sku: str = CharField(40, unique=True)
    quantity: int = IntField(default=0)


class ProductTable(Product, BaseTable, table=True):
    __tablename__ = "docs_products"


class ProductRepository(SQLiteIdentifiedRepository[Product]):
    table = ProductTable


async def main():
    connection = DBConnection(
        "sqlite+aiosqlite:///:memory:",
        pool_size=1,
        max_overflow=0,
        pool_timeout=30,
        pool_recycle=1800,
        uow_factory=SQLiteUnitOfWork,
    )
    try:
        async with connection.engine.begin() as engine:
            await engine.run_sync(ProductTable.__table__.create)

        async with connection.uow() as uow:
            repo = ProductRepository(uow)
            async with transaction(uow):
                product = await repo.create(Product(sku="BOOK", quantity=2))
                product_id = product.id

        async with connection.uow() as uow:
            page = await ProductRepository(uow).get_paged(limit=10)
            assert page.total_items == 1
            assert page.items[0].quantity == 2

        columns = ProductTable.__table__.c
        async with connection.uow() as uow:
            async with transaction(uow):
                product = await ProductRepository(uow).upsert(
                    Product(sku="BOOK", quantity=5),
                    conflict_columns=[columns.sku],
                    update_columns=[columns.quantity],
                )
                assert product.id == product_id

        async with connection.uow() as uow:
            product = await ProductRepository(uow).get_by_id(product_id)
            assert product is not None and product.quantity == 5
        print("SQLite: create, page and upsert passed")
    finally:
        await connection.dispose()


if __name__ == "__main__":
    asyncio.run(main())
