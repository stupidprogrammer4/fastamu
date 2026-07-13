from collections.abc import AsyncIterator
from pathlib import Path

import aiofiles
import aiofiles.os


class InvalidStoragePath(ValueError):
    """Raised when a requested path escapes the storage root."""


class LocalStorage:
    """A local-filesystem media store rooted at a base directory.

    All paths are resolved under ``base`` and checked so a caller can never read
    or write outside it (no ``..`` traversal).
    """

    backend = "local"

    def __init__(self, base_path: str) -> None:
        self.base = Path(base_path or "media").resolve()

    def _resolve(self, path: str) -> Path:
        """Resolve a relative path under the base, rejecting traversal.

        Args:
            path (str): Relative path inside the store.
        Returns:
            (Path): Absolute path guaranteed to live under ``base``.
        """
        target = (self.base / path).resolve()
        if target != self.base and not target.is_relative_to(self.base):
            raise InvalidStoragePath(path)
        return target

    async def save_stream(self, path: str, chunks: AsyncIterator[bytes]) -> str:
        """Write a byte stream to ``path`` under the store, chunk by chunk.

        Args:
            path (str): Relative path to write (parent dirs created if missing).
            chunks (AsyncIterator[bytes]): The file contents as a chunk stream.
        Returns:
            (str): The stored path relative to the base.
        """
        target = self._resolve(path)
        target.parent.mkdir(parents=True, exist_ok=True)
        async with aiofiles.open(target, "wb") as handle:
            async for chunk in chunks:
                await handle.write(chunk)
        return path

    async def move(self, src: str, dst: str) -> str:
        """Move a stored file to a new relative path.

        Args:
            src (str): Existing relative path inside the store.
            dst (str): Destination relative path (parent dirs created if missing).
        Returns:
            (str): The destination path relative to the base.
        """
        source = self._resolve(src)
        target = self._resolve(dst)
        target.parent.mkdir(parents=True, exist_ok=True)
        await aiofiles.os.replace(source, target)
        return dst

    def exists(self, path: str) -> bool:
        """Whether a stored file exists.

        Args:
            path (str): Relative path inside the store.
        Returns:
            (bool): True if it points to a regular file.
        """
        return self._resolve(path).is_file()

    async def stream(self, path: str, chunk_size: int = 64 * 1024) -> AsyncIterator[bytes]:
        """Yield a file's contents in chunks.

        Args:
            path (str): Relative path inside the store.
            chunk_size (int): Bytes per chunk.
        Returns:
            (AsyncIterator[bytes]): The file's contents.
        """
        target = self._resolve(path)
        async with aiofiles.open(target, "rb") as handle:
            while chunk := await handle.read(chunk_size):
                yield chunk

    async def delete(self, path: str) -> None:
        """Delete a stored file if it exists.

        Args:
            path (str): Relative path inside the store.
        Returns:
            (None)
        """
        target = self._resolve(path)
        if target.is_file():
            await aiofiles.os.remove(target)
