# Operations and troubleshooting

## Run the application you own

From a generated project root:

```bash
python -m uvicorn shop.main:app --host 0.0.0.0 --port 8000
```

Use `--reload` for local development. Configure process count and connection pool limits together: each worker owns its own pools, so worker count multiplies possible database and outbound connections.

The default settings loader reads `config.yml` from the working directory. For a different configuration source, build Settings explicitly in `main.py`. There is no framework-owned global ASGI app.

## Logs and API documentation

`logging.format` accepts `console` or `json`. `logging.service` identifies the application. Default middleware records request activity. The logger is configured during lifespan, so enter lifespan in integration tests too.

Swagger assets are served locally under `/static/swagger`. `docs_url` changes the UI path, and `root_path` supports a proxy mount prefix. Disable Swagger with `docs_url=None` or disable the schema as well with `openapi_url=None`.

## Resource and performance boundaries

| Operation | Cost or lifetime to account for |
| --- | --- |
| App/module discovery | Startup imports and dependency graph construction |
| Request UoW | One session per operation; not shared across concurrent tasks |
| `fetch_page` | A count query and a page query |
| MySQL `bulk_insert` | Native batch INSERT returning a count, without model reloads; replaces MySQL `bulk_create` |
| Streamed SQL | Cursor and UoW remain open until consumption completes |
| Whole-file reads / Excel row reads | Complete result held in memory |
| CSV batches | Worker transfer per batch, plus individual record memory |
| ES refresh requested by caller | Additional search-visibility work |

There is no universal best batch size. Measure query count, latency and memory using your schema, indexes, network and input sizes. Generated interfaces do not replace backend integration tests.

## Troubleshoot common failures

| Symptom | Check |
| --- | --- |
| `ModuleNotFoundError` for SQL/ES/Redis tools | Install the matching extra in the environment running the server |
| Missing `config.yml` | Run from the project root or pass Settings explicitly |
| Settings reject an unknown field | Define a Settings subclass and configure `app.settings` |
| Dishka cannot find a dependency | Register its provider under the exact requested type |
| New routes do not appear | Check `app.modules`, package imports and router placement |
| Changes disappear after a request | Open an explicit transaction; closing a UoW does not commit |
| `TransactionRollbackOnly` | An inner transactional operation failed, even if caught |
| A transaction belongs to another task | Stop sharing the UoW across concurrent operations |
| SQL write succeeds but search misses it | SQL-to-ES synchronization is not automatic; also consider ES refresh |
| Default rate limiting vanished | A custom middleware list replaces the default list |
| Excel subprocess startup fails | Use an importable script and a guarded main entry point |
| CSV header treated as data | Consume and validate the header explicitly |
| Second lifespan fails after a test | Build a fresh app; the previous container was closed |

## Current feature limits

Runtime SQL implementations cover six backends, while SQL scaffolding currently targets PostgreSQL. Oracle and SQL Server repositories do not expose upsert. `--context` leaves application-specific methods unimplemented, and `--excel` adds an exporter extension placeholder.

The CQRS template does not provide event delivery, projections, outbox, repair, retry or scheduling. Authentication helpers do not provide a complete identity system; consult the [token-type behavior](security.md) before combining access and refresh tokens.

A service responding to HTTP does not prove that migrations are current or ES indexes initialized successfully. Add health/readiness checks for the dependencies your application actually requires.
