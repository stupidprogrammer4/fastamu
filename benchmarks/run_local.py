"""Start one disposable database at a time and run db_repository.py.

Requires Docker and this project's optional database drivers. For MSSQL,
install unixODBC on the host or supply its library directory via --odbc-libs;
the Microsoft driver itself is copied from the disposable SQL Server image.
"""

import argparse
import json
import os
import subprocess
import sys
import tempfile
import time
import uuid
from pathlib import Path

SERVERS = {
    "postgresql": {
        "image": "postgres:17-alpine",
        "port": 5432,
        "env": ["POSTGRES_PASSWORD=bench_test_only", "POSTGRES_DB=bench_test"],
        "health": ["pg_isready", "-U", "postgres"],
        "url": "postgresql+asyncpg://postgres:bench_test_only@127.0.0.1:{port}/bench_test",
    },
    "mysql": {
        "image": "mysql:8.4",
        "port": 3306,
        "env": [
            "MYSQL_ROOT_PASSWORD=bench_test_only",
            "MYSQL_DATABASE=bench_test",
            "MYSQL_ROOT_HOST=%",
        ],
        "health": [
            "mysqladmin",
            "ping",
            "--protocol=tcp",
            "-h127.0.0.1",
            "-uroot",
            "-pbench_test_only",
            "--silent",
        ],
        "url": "mysql+asyncmy://root:bench_test_only@127.0.0.1:{port}/bench_test",
    },
    "mariadb": {
        "image": "mariadb:11.4",
        "port": 3306,
        "env": [
            "MARIADB_ROOT_PASSWORD=bench_test_only",
            "MARIADB_DATABASE=bench_test",
            "MARIADB_ROOT_HOST=%",
        ],
        "health": ["healthcheck.sh", "--connect", "--innodb_initialized"],
        "url": "mysql+asyncmy://root:bench_test_only@127.0.0.1:{port}/bench_test",
    },
    "oracle": {
        "image": "gvenzl/oracle-xe:21-slim",
        "port": 1521,
        "env": [
            "ORACLE_PASSWORD=bench_test_only",
            "APP_USER=bench_user",
            "APP_USER_PASSWORD=bench_test_only",
        ],
        "health": ["healthcheck.sh"],
        "url": "oracle+oracledb://bench_user:bench_test_only@127.0.0.1:{port}/?service_name=XEPDB1",
    },
    "mssql": {
        "image": "mcr.microsoft.com/mssql/server:2022-latest",
        "port": 1433,
        "env": [
            "ACCEPT_EULA=Y",
            "MSSQL_PID=Developer",
            "MSSQL_SA_PASSWORD=Bench_Test_Only42",
            "MSSQL_MEMORY_LIMIT_MB=1536",
        ],
        "health": [
            "/opt/mssql-tools18/bin/sqlcmd",
            "-S",
            "localhost",
            "-U",
            "sa",
            "-P",
            "Bench_Test_Only42",
            "-C",
            "-Q",
            "SELECT 1",
            "-b",
        ],
        "url": "mssql+aioodbc://sa:Bench_Test_Only42@127.0.0.1:{port}/bench_test?TrustServerCertificate=yes",
    },
}


def run(*args, **kwargs):
    return subprocess.run(args, check=True, text=True, **kwargs)


def main(args):
    output = Path(args.output).resolve()
    output.mkdir(parents=True, exist_ok=True)
    failures = []
    for backend in args.backends:
        name = None
        with tempfile.TemporaryDirectory(
            prefix=".papilio-bench-", dir=Path.cwd()
        ) as temporary:
            scratch = Path(temporary)
            env = dict(os.environ, PYTHONPATH=str(Path.cwd()))
            if args.odbc_libs:
                env["LD_LIBRARY_PATH"] = str(Path(args.odbc_libs).resolve())
            try:
                config = SERVERS.get(backend)
                if config:
                    name = (
                        f"papilio-benchmark-{backend}-{uuid.uuid4().hex[:8]}"
                    )
                    command = [
                        "docker",
                        "run",
                        "--rm",
                        "-d",
                        "--name",
                        name,
                        "--label",
                        "papilio.review=benchmark",
                        "-p",
                        f"127.0.0.1::{config['port']}",
                    ]
                    for value in config["env"]:
                        command += ["-e", value]
                    command.append(config["image"])
                    run(*command, capture_output=True)
                    deadline = time.monotonic() + 240
                    while subprocess.run(
                        ["docker", "exec", name, *config["health"]],
                        capture_output=True,
                    ).returncode:
                        if time.monotonic() > deadline:
                            raise TimeoutError(
                                f"{backend} did not become ready"
                            )
                        time.sleep(2)
                    port = (
                        run(
                            "docker",
                            "port",
                            name,
                            f"{config['port']}/tcp",
                            capture_output=True,
                        )
                        .stdout.strip()
                        .rsplit(":", 1)[1]
                    )
                    url = config["url"].format(port=port)
                    if backend == "mssql":
                        run(
                            "docker",
                            "exec",
                            name,
                            *config["health"][:-3],
                            "-Q",
                            "CREATE DATABASE bench_test",
                            "-b",
                            capture_output=True,
                        )
                        run(
                            "docker",
                            "cp",
                            name + ":/opt/microsoft/msodbcsql18",
                            str(scratch / "msodbcsql18"),
                            capture_output=True,
                        )
                        driver = next(
                            (scratch / "msodbcsql18" / "lib64").glob(
                                "libmsodbcsql-*.so.*"
                            )
                        )
                        from urllib.parse import quote_plus

                        url += "&driver=" + quote_plus(str(driver))
                    env[f"FASTAMU_BENCH_{backend.upper()}"] = url
                    image_id = run(
                        "docker",
                        "inspect",
                        "--format",
                        "{{.Image}}",
                        name,
                        capture_output=True,
                    ).stdout.strip()
                else:
                    env["FASTAMU_BENCH_SQLITE"] = (
                        f"sqlite+aiosqlite:///{scratch}/data.db"
                    )
                    image_id = None
                print(f"Measuring {backend} in isolation", flush=True)
                result = subprocess.run(
                    [
                        sys.executable,
                        "benchmarks/db_repository.py",
                        "--backend",
                        backend,
                        "--output",
                        str(output / f"{backend}.json"),
                        "--rows",
                        str(args.rows),
                        "--repeats",
                        str(args.repeats),
                        *(
                            ["--concurrency-only"]
                            if args.concurrency_only
                            else []
                        ),
                    ],
                    env=env,
                    timeout=600,
                )
                path = output / f"{backend}.json"
                if path.exists():
                    report = json.loads(path.read_text())
                    report["container_image_id"] = image_id
                    report["isolated_database"] = True
                    report["statistics_refreshed_after_seed"] = True
                    report["process_returncode"] = result.returncode
                    path.write_text(
                        json.dumps(report, indent=2, ensure_ascii=False)
                    )
                if result.returncode:
                    failures.append(
                        {"backend": backend, "returncode": result.returncode}
                    )
            except Exception as exc:
                failures.append(
                    {
                        "backend": backend,
                        "error": type(exc).__name__ + ": " + str(exc)[:300],
                    }
                )
                print(
                    f"{backend}: {type(exc).__name__}: {str(exc)[:300]}",
                    flush=True,
                )
            finally:
                if name:
                    subprocess.run(
                        ["docker", "rm", "-f", name], capture_output=True
                    )
    (output / "runner_failures.json").write_text(
        json.dumps(failures, indent=2)
    )
    return bool(failures)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--backends",
        nargs="+",
        choices=["sqlite", *SERVERS],
        default=["sqlite", *SERVERS],
    )
    parser.add_argument("--output", default="benchmarks/results")
    parser.add_argument("--odbc-libs")
    parser.add_argument("--rows", type=int, default=100_000)
    parser.add_argument("--repeats", type=int, default=9)
    parser.add_argument("--concurrency-only", action="store_true")
    raise SystemExit(main(parser.parse_args()))
