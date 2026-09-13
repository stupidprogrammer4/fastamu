from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager
from os import PathLike
from typing import Literal

from anyio import AsyncFile, CancelScope, open_file


class FileWriter:
    @asynccontextmanager
    async def open_text(
        self,
        path: str | PathLike[str],
        *,
        mode: Literal["w", "a", "x"] = "w",
        encoding: str = "utf-8",
        errors: str = "strict",
        newline: str | None = None,
    ) -> AsyncGenerator[AsyncFile[str]]:
        stream = await open_file(
            path, mode, encoding=encoding, errors=errors, newline=newline
        )
        try:
            yield stream
        finally:
            with CancelScope(shield=True):
                await stream.aclose()

    @asynccontextmanager
    async def open_bytes(
        self,
        path: str | PathLike[str],
        *,
        mode: Literal["wb", "ab", "xb"] = "wb",
    ) -> AsyncGenerator[AsyncFile[bytes]]:
        stream = await open_file(path, mode)
        try:
            yield stream
        finally:
            with CancelScope(shield=True):
                await stream.aclose()

    async def write_text(
        self,
        path: str | PathLike[str],
        data: str,
        *,
        mode: Literal["w", "a", "x"] = "w",
        encoding: str = "utf-8",
    ) -> int:
        async with self.open_text(
            path, mode=mode, encoding=encoding
        ) as stream:
            return await stream.write(data)

    async def write_bytes(
        self,
        path: str | PathLike[str],
        data: bytes,
        *,
        mode: Literal["wb", "ab", "xb"] = "wb",
    ) -> int:
        async with self.open_bytes(path, mode=mode) as stream:
            return await stream.write(data)
