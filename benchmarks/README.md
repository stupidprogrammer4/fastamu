# Database repository benchmarks

Run from the project root using the project's Python environment. Docker and
the optional drivers for the selected databases must be available. The runner
starts one disposable database at a time, uses loopback ports, and removes its
containers and database files after measurement. Existing services are untouched.

```bash
.venv/bin/python benchmarks/run_local.py \
  --backends sqlite postgresql mysql mariadb oracle mssql \
  --output benchmarks/results/new-run
```

SQL Server requires host unixODBC libraries. If they are extracted outside system
library paths, supply `--odbc-libs /path/to/usr/lib/x86_64-linux-gnu`. The runner
copies the Microsoft ODBC driver from the disposable SQL Server image. Its Docker
configuration uses the Developer edition and accepts the image's EULA.

For an existing **dedicated disposable** database, set
`FASTAMU_BENCH_POSTGRESQL` (or the corresponding uppercase backend name) to its
SQLAlchemy URL, then run:

```bash
PYTHONPATH=. .venv/bin/python benchmarks/db_repository.py \
  --backend postgresql --output benchmarks/results/new-run/postgresql.json
```

The direct script creates and drops `fastamu_bench_records`; it fails if that
table already exists. Use the default 100,000 rows for the recorded workload.
It expects at least 1,000 rows for the fixed concurrency and pagination cases;
custom bulk sizes must fit the first 8,000 selected IDs. `--concurrency-only`
reruns concurrency and retains serial sections from the specified existing JSON.
Use the same configuration when retaining previous measurements.

## What is measured

- Native repository bulk update against a reconstructed CASE reference with
  equivalent changed fields and return values: 10, 100, 500 and 1,000 rows,
  changing two integer columns. Each strategy uses one write statement.
- MySQL `bulk_insert` returning a count versus `bulk_create` returning populated
  ORM models. These have different output contracts; timings show the cost of
  obtaining the richer result, not interchangeable implementations.
- Pagination returning an exact count and up to 50 ORM models: separate COUNT
  and page queries versus `COUNT(*) OVER()`, with a separate count for empty
  window pages. Unfiltered and indexed-filter cases, four offsets each.
- Concurrent updates of 100 rows with 1, 4 and 8 workers, ten commits per worker,
  disjoint keys, and a pool of eight warmed connections. This is a short load
  sample, not a sustained saturation or lock-contention test.

Serial measurements use two warmups and nine recorded samples. Strategy order
is randomized per repetition. Construction, compilation, execute, fetch and ORM
conversion are timed; connection checkout, verification and rollback are outside
that timer. Inputs are prepared before timing. Serial writes roll back to the
same baseline. Concurrency latency includes checkout, commit and UoW cleanup;
throughput also includes worker input preparation. Each concurrency strategy and
its pool connections are warmed before timing, with randomized strategy order.

SQL hooks count cursor executions, excluding verification queries and transaction
control. `driver_ms` includes driver and transport time and is not server-only
time. `construction` is a single diagnostic sample; `unexpanded_bind_entries`
counts compiler dictionary entries, including an expanding IN list as one entry.
Actual SQL Server parameter counts are recorded separately in the recorded run.

Assertions verify returned counts/fields and persisted serial writes outside the
timed operation. Concurrency verifies affected counts, and pagination verifies
total, page length and first item. Errors are kept in operation results; a zero
process return code means the harness finished, **not that every operation
passed**. `runner_failures.json` covers only the most recent runner invocation.

Recorded results and limitations: [results/REPORT.md](results/REPORT.md).
Raw samples, versions, image IDs and source hashes are retained. The `pilot/`
directory contains exploratory measurements under different conditions and is
excluded from the final comparison. Server image tags can change; consult the
recorded image IDs when reproducing the environment.
