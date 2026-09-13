import csv
from collections.abc import AsyncGenerator, AsyncIterator, Iterator
from contextlib import asynccontextmanager
from itertools import islice
from os import PathLike

from anyio import to_thread

from papilio.infra.files.reader import FileReader


def _batch(reader: Iterator[list[str]], size: int) -> list[list[str]]:
    return list(islice(reader, size))


class CSVReader:
    @asynccontextmanager
    async def rows(
        self,
        path: str | PathLike[str],
        *,
        encoding: str = "utf-8",
        delimiter: str = ",",
        quotechar: str | None = '"',
        escapechar: str | None = None,
        doublequote: bool = True,
        skipinitialspace: bool = False,
        strict: bool = True,
        batch_size: int = 1000,
    ) -> AsyncGenerator[AsyncIterator[list[str]]]:
        """Stream parsed records; leave the context to close the file."""
        if batch_size < 1:
            raise ValueError("batch_size must be positive")
        async with FileReader().open_text(
            path, encoding=encoding, newline=""
        ) as stream:
            reader = csv.reader(
                stream.wrapped,
                delimiter=delimiter,
                quotechar=quotechar,
                escapechar=escapechar,
                doublequote=doublequote,
                skipinitialspace=skipinitialspace,
                strict=strict,
            )

            async def iterate() -> AsyncGenerator[list[str]]:
                while batch := await to_thread.run_sync(
                    _batch, reader, batch_size
                ):
                    for row in batch:
                        yield row

            iterator = iterate()
            try:
                yield iterator
            finally:
                await iterator.aclose()
