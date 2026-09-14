"""Repeatable repository microbenchmark; use a dedicated disposable database.

Run from the repository root with PYTHONPATH=. and FASTAMU_BENCH_<BACKEND> set.
Only papilio_bench_records is created/dropped. No framework code is patched.
"""

import argparse
import asyncio
import importlib.metadata
import json
import math
import os
import platform
import random
import statistics
import time
from pathlib import Path

from sqlalchemy import case, event, func, insert, literal, select, text, update

from papilio.infra.db.schema.entity import IdentifiedEntity
from papilio.infra.db.schema.fields import CharField, IntField
from papilio.infra.db.connection import DBConnection
from papilio.infra.db.repositories.backends.mariadb import (
    MariaDBIdentifiedRepository,
)
from papilio.infra.db.repositories.backends.mssql import (
    MSSQLIdentifiedRepository,
)
from papilio.infra.db.repositories.backends.mysql import (
    MySQLIdentifiedRepository,
)
from papilio.infra.db.repositories.backends.oracle import (
    OracleIdentifiedRepository,
)
from papilio.infra.db.repositories.backends.postgresql import (
    PGIdentifiedRepository,
)
from papilio.infra.db.repositories.backends.sqlite import (
    SQLiteIdentifiedRepository,
)
from papilio.infra.db.table import BaseTable
from papilio.infra.db.tools.read import fetch_page
from papilio.infra.db.uow import (
    MariaDBUnitOfWork,
    MSSQLUnitOfWork,
    MySQLUnitOfWork,
    OracleUnitOfWork,
    PGUnitOfWork,
    SQLiteUnitOfWork,
)


class RecordEntity(IdentifiedEntity):
    code: str = CharField(64, unique=True)
    quantity: int = IntField(default=0)
    amount: int = IntField(default=0)
    category: int = IntField(default=0, index=True)


class Record(RecordEntity, BaseTable, table=True):
    __tablename__ = "papilio_bench_records"


BACKENDS = {
    "postgresql": (PGIdentifiedRepository, PGUnitOfWork),
    "mysql": (MySQLIdentifiedRepository, MySQLUnitOfWork),
    "mariadb": (MariaDBIdentifiedRepository, MariaDBUnitOfWork),
    "sqlite": (SQLiteIdentifiedRepository, SQLiteUnitOfWork),
    "oracle": (OracleIdentifiedRepository, OracleUnitOfWork),
    "mssql": (MSSQLIdentifiedRepository, MSSQLUnitOfWork),
}
COUNTS = {"mysql", "mariadb"}
C = Record.__table__.c


def summary(samples):
    ordered = sorted(samples)
    return {
        "median_ms": round(statistics.median(ordered), 3),
        "min_ms": round(ordered[0], 3),
        "max_ms": round(ordered[-1], 3),
        "p95_ms": round(ordered[math.ceil(len(ordered) * 0.95) - 1], 3),
    }


def update_stmt(repo, backend, data, method):
    if method == "grid":
        if backend == "postgresql":
            stmt = repo._bulk_update_stmt(
                [item.to_row() for item in data],
                key_columns=[C.id],
                update_columns=[C.quantity, C.amount],
            )
        else:
            stmt = repo._bulk_update_stmt(
                data,
                update_columns={"quantity": C.quantity, "amount": C.amount},
            )
    else:
        # CASE reference with identical predicates, results and options.
        rows = [item.to_changes() for item in data]
        ids = [item.id for item in data]
        stmt = (
            update(Record)
            .where(C.id.in_(ids))
            .values(
                {
                    field: case(
                        *(
                            (C.id == key, literal(row[field.key], field.type))
                            for key, row in zip(ids, rows)
                        ),
                        else_=field,
                    )
                    for field in (C.quantity, C.amount)
                }
            )
        )
    if backend in COUNTS:
        return stmt.execution_options(synchronize_session=False)
    return stmt.returning(Record).execution_options(
        synchronize_session=False, populate_existing=True
    )


async def run_update(repo, backend, data, method):
    if method == "grid":
        if backend == "postgresql":
            return await repo.bulk_update(
                [item.to_row() for item in data],
                key_columns=[C.id],
                update_columns=[C.quantity, C.amount],
            )
        return await repo.bulk_update(
            data, update_columns={"quantity": C.quantity, "amount": C.amount}
        )
    stmt = update_stmt(repo, backend, data, method)
    result = await repo.uow.execute(stmt)
    return result.rowcount if backend in COUNTS else result.scalars().all()


async def main(args):
    backend = args.backend
    dsn = os.environ[f"FASTAMU_BENCH_{backend.upper()}"]
    base, factory = BACKENDS[backend]

    class Repository(base[RecordEntity]):
        table = Record

    db = DBConnection(dsn, 8, 0, 30, 1800, uow_factory=factory)
    if backend == "oracle":

        @event.listens_for(db.engine.sync_engine, "do_connect")
        def oracle_transport(dialect, record, cargs, cparams):
            cparams["disable_oob"] = True

        @event.listens_for(db.engine.sync_engine, "connect")
        def oracle_timeout(connection, record):
            connection.driver_connection.call_timeout = 30000

    measured = {"active": False, "queries": [], "driver_ms": []}

    @event.listens_for(db.engine.sync_engine, "before_cursor_execute")
    def before(conn, cursor, statement, parameters, context, many):
        if measured["active"]:
            measured["queries"].append(statement)
            context.bench_started = time.perf_counter()

    @event.listens_for(db.engine.sync_engine, "after_cursor_execute")
    def after(conn, cursor, statement, parameters, context, many):
        if measured["active"]:
            measured["driver_ms"].append(
                (time.perf_counter() - context.bench_started) * 1000
            )

    report = {
        "backend": backend,
        "python": platform.python_version(),
        "platform": platform.platform(),
        "versions": {
            p: importlib.metadata.version(p)
            for p in ("SQLAlchemy", "sqlmodel", "pydantic")
        },
        "rows": args.rows,
        "warmups": args.warmups,
        "repeats": args.repeats,
        "batch_sizes": args.batches,
        "methodology": {
            "serial": (
                "Operation latency includes statement construction, SQL "
                "compilation, execute, fetch and ORM conversion. Pool "
                "checkout and rollback excluded; each sample starts with the "
                "same committed data and is rolled back."
            ),
            "concurrent": (
                "Latency includes UoW open, pool checkout, bulk_update and "
                "commit. Distinct keys per worker; no intentional row-lock "
                "contention. Ten commits per worker; schema/data preparation "
                "excluded. Pool connections and each method are warmed before "
                "timing; method order is randomized for each worker count."
            ),
            "pagination": (
                "Exact count plus up to 50 ORM models; window path adds COUNT "
                "when page is empty. No concurrent data changes; "
                "first/middle/last/beyond-end offsets. Warm local caches, not "
                "a production SLA."
            ),
            "order": (
                "Seeded randomized order within each serial repetition; all "
                "backends measured sequentially."
            ),
        },
        "updates": [],
        "inserts": [],
        "pages": [],
        "concurrency": [],
    }
    output = Path(args.output)
    output.parent.mkdir(parents=True, exist_ok=True)
    if args.concurrency_only and output.exists():
        previous = json.loads(output.read_text())
        assert previous["rows"] == args.rows
        for section in ("updates", "inserts", "pages"):
            report[section] = previous[section]

    def save():
        output.write_text(json.dumps(report, indent=2, ensure_ascii=False))

    rng = random.Random(41)

    async def measure_pair(operations, verify):
        results = {
            name: {"samples_ms": [], "sql_counts": [], "driver_ms": []}
            for name in operations
        }
        for repetition in range(args.warmups + args.repeats):
            order = list(operations)
            rng.shuffle(order)
            for name in order:
                if "error" in results[name]:
                    continue
                async with db.uow() as unit:
                    await unit.execute(
                        select(1)
                    )  # Acquire the pooled connection.
                    measured.update(active=True, queries=[], driver_ms=[])
                    start = time.perf_counter()
                    try:
                        result = await operations[name](Repository(unit))
                        elapsed = (time.perf_counter() - start) * 1000
                        measured["active"] = False
                        await verify(unit, result)
                        if repetition >= args.warmups:
                            results[name]["samples_ms"].append(
                                round(elapsed, 4)
                            )
                            results[name]["sql_counts"].append(
                                len(measured["queries"])
                            )
                            results[name]["driver_ms"].append(
                                round(sum(measured["driver_ms"]), 4)
                            )
                    except Exception as exc:
                        # Do not record bound parameters or connection details.
                        message = str(getattr(exc, "orig", exc))
                        results[name]["error"] = (
                            f"{type(exc).__name__}: {message[:500]}"
                        )
                    finally:
                        measured["active"] = False
                        await unit.rollback()
        for result in results.values():
            if result["samples_ms"]:
                result.update(summary(result["samples_ms"]))
                result["median_driver_ms"] = round(
                    statistics.median(result["driver_ms"]), 3
                )
        return results

    created = False
    try:
        async with db.engine.begin() as connection:
            await connection.run_sync(Record.__table__.create)
            created = True
        async with db.uow() as unit:
            for start in range(0, args.rows, 1000):
                await unit.execute(
                    insert(Record.__table__),
                    [
                        {
                            "code": f"seed-{i}",
                            "quantity": 1,
                            "amount": 1,
                            "category": i % 20,
                        }
                        for i in range(start, min(args.rows, start + 1000))
                    ],
                )
            await unit.commit()
            statistics_sql = {
                "postgresql": "ANALYZE papilio_bench_records",
                "sqlite": "ANALYZE papilio_bench_records",
                "mysql": "ANALYZE TABLE papilio_bench_records",
                "mariadb": "ANALYZE TABLE papilio_bench_records",
                "oracle": (
                    "BEGIN DBMS_STATS.GATHER_TABLE_STATS("
                    "USER, 'FASTAMU_BENCH_RECORDS'); END;"
                ),
                "mssql": (
                    "UPDATE STATISTICS papilio_bench_records WITH FULLSCAN"
                ),
            }
            await unit.execute(text(statistics_sql[backend]))
            await unit.commit()
            ids = list(
                (
                    await unit.execute(select(C.id).order_by(C.id).limit(8000))
                ).scalars()
            )
        report["server_version"] = str(db.engine.dialect.server_version_info)
        print(f"{backend}: seeded {args.rows} rows", flush=True)
        for size in () if args.concurrency_only else args.batches:
            data = [
                RecordEntity.patch(id=key, quantity=17, amount=29)
                for key in ids[:size]
            ]
            build = {}
            for method in ("grid", "case"):
                started = time.perf_counter()
                stmt = update_stmt(Repository(None), backend, data, method)
                compiled = stmt.compile(dialect=db.engine.dialect)
                build[method] = {
                    "build_compile_ms": round(
                        (time.perf_counter() - started) * 1000, 3
                    ),
                    "sql_bytes": len(str(compiled).encode()),
                    "unexpanded_bind_entries": len(compiled.params),
                }

            async def verify_update(unit, result):
                if backend in COUNTS:
                    assert result == size, (result, size)
                else:
                    assert len(result) == size
                    assert all(
                        row.quantity == 17 and row.amount == 29
                        for row in result
                    )
                rows = (
                    await unit.execute(
                        select(C.quantity, C.amount).where(
                            C.id.in_(ids[:size])
                        )
                    )
                ).all()
                assert len(rows) == size and all(
                    row == (17, 29) for row in rows
                )

            pair = await measure_pair(
                {
                    name: (
                        lambda repo, name=name: run_update(
                            repo, backend, data, name
                        )
                    )
                    for name in ("grid", "case")
                },
                verify_update,
            )
            report["updates"].append(
                {"batch": size, "results": pair, "construction": build}
            )
            save()
            print(
                f"{backend}: update {size}:",
                [
                    (k, v.get("median_ms", v.get("error")))
                    for k, v in pair.items()
                ],
                flush=True,
            )

        if backend == "mysql" and not args.concurrency_only:
            for size in args.batches:
                data = [
                    RecordEntity(
                        code=f"insert-{i}", quantity=17, amount=29, category=2
                    )
                    for i in range(size)
                ]

                async def verify_insert(unit, result):
                    if isinstance(result, int):
                        assert result == size
                    else:
                        assert len(result) == size
                        assert all(
                            row.id is not None and row.quantity == 17
                            for row in result
                        )
                    count = (
                        await unit.execute(
                            select(func.count())
                            .select_from(Record)
                            .where(C.code.like("insert-%"))
                        )
                    ).scalar_one()
                    assert count == size

                pair = await measure_pair(
                    {
                        "bulk_insert": lambda repo: repo.bulk_insert(
                            data,
                            insert_columns={
                                "code": C.code,
                                "quantity": C.quantity,
                                "amount": C.amount,
                                "category": C.category,
                            },
                        ),
                        "bulk_create": lambda repo: repo.bulk_create(data),
                    },
                    verify_insert,
                )
                report["inserts"].append({"batch": size, "results": pair})
                save()
                print(
                    f"{backend}: insert {size}:",
                    [
                        (k, v.get("median_ms", v.get("error")))
                        for k, v in pair.items()
                    ],
                    flush=True,
                )

        for filtered in () if args.concurrency_only else (False, True):
            query = select(Record).order_by(C.id)
            window = select(
                Record, func.count().over().label("total")
            ).order_by(C.id)
            expected_total = args.rows
            if filtered:
                query = query.where(C.category == 7)
                window = window.where(C.category == 7)
                expected_total = len(range(7, args.rows, 20))
            for offset in (
                0,
                expected_total // 2,
                expected_total - 50,
                expected_total,
            ):

                async def two_queries(repo):
                    page = await fetch_page(
                        repo.uow, query, limit=50, offset=offset
                    )
                    return list(page.items), page.total_items

                async def count_over(repo):
                    stmt = window.limit(50).offset(offset)
                    rows = (await repo.uow.execute(stmt)).all()
                    if rows:
                        return [row[0] for row in rows], rows[0].total
                    stmt = select(func.count()).select_from(
                        query.order_by(None).subquery()
                    )
                    return [], (await repo.uow.execute(stmt)).scalar_one()

                async def verify_page(unit, result):
                    items, total = result
                    assert total == expected_total
                    assert len(items) == max(
                        0, min(50, expected_total - offset)
                    )
                    if items:
                        expected_index = (
                            offset * 20 + 7 if filtered else offset
                        )
                        assert items[0].code == f"seed-{expected_index}"

                pair = await measure_pair(
                    {"two_queries": two_queries, "count_over": count_over},
                    verify_page,
                )
                report["pages"].append(
                    {
                        "filtered": filtered,
                        "offset": offset,
                        "total": expected_total,
                        "results": pair,
                    }
                )
                save()
            print(
                f"{backend}: pagination filtered={filtered} done", flush=True
            )

        for workers in (1, 4, 8):
            methods = ["grid", "case"]
            rng.shuffle(methods)
            for method in methods:
                barrier = asyncio.Barrier(workers)

                async def warm(index):
                    async with db.uow() as unit:
                        await unit.execute(select(1))
                        await barrier.wait()
                        data = [
                            RecordEntity.patch(id=key, quantity=50, amount=50)
                            for key in ids[index * 100 : (index + 1) * 100]
                        ]
                        await run_update(
                            Repository(unit), backend, data, method
                        )
                        await unit.commit()

                await asyncio.gather(*(warm(i) for i in range(workers)))
                latencies = []
                failures = []
                gate = asyncio.Event()

                async def worker(index):
                    await gate.wait()
                    for turn in range(10):
                        data = [
                            RecordEntity.patch(
                                id=key, quantity=turn + 2, amount=turn + 3
                            )
                            for key in ids[index * 100 : (index + 1) * 100]
                        ]
                        started = time.perf_counter()
                        try:
                            async with db.uow() as unit:
                                result = await run_update(
                                    Repository(unit), backend, data, method
                                )
                                assert (
                                    result == 100
                                    if backend in COUNTS
                                    else len(result) == 100
                                )
                                await unit.commit()
                            latencies.append(
                                (time.perf_counter() - started) * 1000
                            )
                        except Exception as exc:
                            failures.append(
                                type(exc).__name__
                                + ": "
                                + str(getattr(exc, "orig", exc))[:200]
                            )
                            break

                tasks = [
                    asyncio.create_task(worker(i)) for i in range(workers)
                ]
                started = time.perf_counter()
                gate.set()
                await asyncio.gather(*tasks)
                duration = time.perf_counter() - started
                result = {
                    "workers": workers,
                    "method": method,
                    "batch": 100,
                    "commits": len(latencies),
                    "errors": failures,
                    "elapsed_s": round(duration, 3),
                    "rows_per_second": round(len(latencies) * 100 / duration),
                }
                if latencies:
                    result.update(summary(latencies))
                    result["samples_ms"] = [round(v, 4) for v in latencies]
                report["concurrency"].append(result)
                save()
            print(f"{backend}: concurrent writers={workers} done", flush=True)
    finally:
        measured["active"] = False
        if created:
            async with db.engine.begin() as connection:
                await connection.run_sync(Record.__table__.drop)
        await db.dispose()
        save()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--backend", required=True, choices=BACKENDS)
    parser.add_argument("--output", required=True)
    parser.add_argument("--rows", type=int, default=100_000)
    parser.add_argument("--repeats", type=int, default=9)
    parser.add_argument("--warmups", type=int, default=2)
    parser.add_argument("--concurrency-only", action="store_true")
    parser.add_argument(
        "--batches", type=int, nargs="+", default=[10, 100, 500, 1000]
    )
    asyncio.run(main(parser.parse_args()))
