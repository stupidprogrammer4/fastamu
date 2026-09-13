# Runnable examples

These examples use the actual framework APIs. HTTP, SQLite, file/CSV and Excel examples need no external service and do not modify an application database.

## Prepare the environment

From the framework checkout:

```bash
python -m pip install -e '.[server,test,sqlite,files,csv,excel,docs]'
```

## HTTP application

```bash
python -m uvicorn plain_app:app --app-dir docs/examples --reload
```

Send `POST /greetings` with `{"name":"Sara"}`. See the [full walkthrough](../guide/start.md), [application source](plain_app.py) and [local settings](minimal.yml). `build_app()` creates an independent app for each test lifecycle.

## SQLite repository

```bash
python docs/examples/sqlite_repository.py
```

The script creates an in-memory database, inserts a product, reads a page in another UoW, performs a native upsert and verifies the committed result. Expected final line: `SQLite: create, page and upsert passed`.

```python
--8 < --"examples/sqlite_repository.py"
```

## File and CSV pipeline

```bash
python docs/examples/file_pipeline.py
```

The script roundtrips text, writes CSV records and streams a filtered copy into another file. Temporary files are removed when it exits. Expected final line: `Files and CSV: roundtrip and filtering passed`.

```python
--8 < --"examples/file_pipeline.py"
```

## Excel roundtrip

```bash
python docs/examples/excel_roundtrip.py
```

The script creates a workbook template, writes typed rows and reads them back through a process pool. Expected final line: `Excel: typed roundtrip passed`.

```python
--8 < --"examples/excel_roundtrip.py"
```

## Run examples and build the site

```bash
python docs/examples/sqlite_repository.py
python docs/examples/file_pipeline.py
python docs/examples/excel_roundtrip.py
python -m mkdocs build --strict
```

For HTTP assertions, follow the test in [Testing and migrations](../guide/testing.md). The strict site build validates navigation, links and snippet inclusion. PostgreSQL, other server databases, Redis and Elasticsearch still need their own environment-specific tests.
