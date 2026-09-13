from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager
from os import PathLike

from anyio import AsyncFile, CancelScope, open_file


class FileReader:
    @asynccontextmanager
    async def open_text(
        self,
        path: str | PathLike[str],
        *,
        encoding: str = "utf-8",
        errors: str = "strict",
        newline: str | None = None,
    ) -> AsyncGenerator[AsyncFile[str]]:
        stream = await open_file(
            path, "r", encoding=encoding, errors=errors, newline=newline
        )
        try:
            yield stream
        finally:
            with CancelScope(shield=True):
                await stream.aclose()

    @asynccontextmanager
    async def open_bytes(
        self, path: str | PathLike[str]
    ) -> AsyncGenerator[AsyncFile[bytes]]:
        stream = await open_file(path, "rb")
        try:
            yield stream
        finally:
            with CancelScope(shield=True):
                await stream.aclose()

    async def read_text(
        self,
        path: str | PathLike[str],
        *,
        encoding: str = "utf-8",
        errors: str = "strict",
    ) -> str:
        async with self.open_text(path, encoding=encoding, errors=errors) as f:
            return await f.read()

    async def read_bytes(self, path: str | PathLike[str]) -> bytes:
        async with self.open_bytes(path) as stream:
            return await stream.read()
