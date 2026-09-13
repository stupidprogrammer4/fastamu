import csv
from _csv import Writer
from collections.abc import AsyncGenerator, Iterable
from contextlib import asynccontextmanager
from os import PathLike
from typing import Literal

from anyio import to_thread

from papilio.infra.files.writer import FileWriter


class CSVStreamWriter:
    def __init__(self, writer: Writer) -> None:
        self._writer = writer

    async def write_row(self, row: Iterable[object]) -> int:
        """Write one record and return the number of characters written."""
        return await to_thread.run_sync(self._writer.writerow, row)

    async def write_rows(self, rows: Iterable[Iterable[object]]) -> int:
        """Write a batch and return its record count."""
        return await to_thread.run_sync(self._write_rows, rows)

    def _write_rows(self, rows: Iterable[Iterable[object]]) -> int:
        count = 0
        for row in rows:
            self._writer.writerow(row)
            count += 1
        return count


class CSVWriter:
    @asynccontextmanager
    async def open(
        self,
        path: str | PathLike[str],
        *,
        mode: Literal["w", "a", "x"] = "w",
        encoding: str = "utf-8",
        delimiter: str = ",",
        quotechar: str | None = '"',
        escapechar: str | None = None,
        doublequote: bool = True,
        quoting: int = csv.QUOTE_MINIMAL,
        lineterminator: str = "\r\n",
    ) -> AsyncGenerator[CSVStreamWriter]:
        async with FileWriter().open_text(
            path, mode=mode, encoding=encoding, newline=""
        ) as stream:
            writer = csv.writer(
                stream.wrapped,
                delimiter=delimiter,
                quotechar=quotechar,
                escapechar=escapechar,
                doublequote=doublequote,
                quoting=quoting,
                lineterminator=lineterminator,
            )
            yield CSVStreamWriter(writer)
