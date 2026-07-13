import mimetypes
from collections.abc import AsyncIterator
from uuid import uuid4

from src.common.bases.results import PagedType
from src.common.bases.services import BaseIDService
from src.common.errors.exceptions import NotFoundException, ValidationException
from src.core.config import StorageConfig
from src.modules.ops.storage import resources
from src.modules.ops.storage.app.helpers import StreamMeter
from src.modules.ops.storage.domain.models import MediaModel
from src.modules.ops.storage.infra.repository import MediaRepository
from src.modules.ops.storage.infra.storage import InvalidStoragePath, LocalStorage


class MediaService(BaseIDService[MediaModel]):
    """Manages uploaded media: streamed storage, dedupe by hash, and the catalog."""

    def __init__(self, repo: MediaRepository, storage: LocalStorage, config: StorageConfig) -> None:
        self.repo = repo
        self.storage = storage
        self.config = config

    def _validate_extension(self, filename: str | None) -> str:
        """Extract and validate a file's extension against the configured whitelist.

        Args:
            filename (str | None): The original file name.
        Returns:
            (str): The lowercased extension without the dot.
        """
        name = filename or ""
        extension = name.rsplit(".", 1)[-1].lower() if "." in name else ""
        if extension not in self.config.allowed_extensions:
            raise ValidationException(
                message=f"Unsupported file extension: {extension or '(none)'}",
                message_code=resources.STORAGE_INVALID_EXTENSION,
                loc=["file"],
            )
        return extension

    async def upload(self, stream: AsyncIterator[bytes], filename: str | None) -> MediaModel:
        """Stream an upload into the store and register it, deduplicating by hash.

        Args:
            stream (AsyncIterator[bytes]): The file contents as a chunk stream.
            filename (str | None): The original file name (extension is validated).
        Returns:
            (MediaModel): The stored media record (an existing one on duplicate content).
        """
        extension = self._validate_extension(filename)
        temp_path = f"{self.config.temp_dir}/{uuid4().hex}"
        meter = StreamMeter(stream, self.config.max_file_size)
        try:
            await self.storage.save_stream(temp_path, meter.chunks())
        except Exception:
            await self.storage.delete(temp_path)
            raise
        if meter.size == 0:
            await self.storage.delete(temp_path)
            raise ValidationException(
                message="Uploaded file is empty",
                message_code=resources.STORAGE_EMPTY_FILE,
                loc=["file"],
            )

        digest = meter.hexdigest
        result = await self.repo.get_by_hash(digest)
        if result is not None:
            await self.storage.delete(temp_path)
        else:
            path = f"{digest[:2]}/{digest}.{extension}"
            await self.storage.move(temp_path, path)
            content_type = mimetypes.guess_type(f"f.{extension}")[0] or "application/octet-stream"
            result = await self.repo.create(
                MediaModel(
                    backend=self.storage.backend,
                    path=path,
                    filename=filename or f"file.{extension}",
                    extension=extension,
                    content_type=content_type,
                    size=meter.size,
                    hash=digest,
                )
            )
        return result

    async def get_by_id(self, id: int) -> MediaModel:
        """Get a media record by ID.

        Args:
            id (int): ID of the media record.
        Returns:
            (MediaModel): The found record.
        """
        media = await self.repo.get_by_id(id)
        media = self._check_for_id_existence(id, media)
        return media

    async def get_paged(self, page: int, per_page: int) -> PagedType[MediaModel]:
        """Get a page of media records, newest first.

        Args:
            page (int): 1-based page number.
            per_page (int): Rows per page.
        Returns:
            (PagedType[MediaModel]): The page rows and the total count.
        """
        paged = await self.repo.get_paged(limit=per_page, offset=(page - 1) * per_page)
        return paged

    async def open(self, path: str) -> tuple[AsyncIterator[bytes], str]:
        """Open a managed file for streaming by its stored path.

        Args:
            path (str): The stored path (as returned by ``upload``).
        Returns:
            (tuple[AsyncIterator[bytes], str]): A chunk iterator and the content type.
        """
        media = await self.repo.get_by_path(path)
        media = self._check_for_existence("path", path, media)
        try:
            found = self.storage.exists(path)
        except InvalidStoragePath:
            raise ValidationException(
                message="Invalid media path",
                message_code=resources.STORAGE_INVALID_PATH,
                loc=["path"],
            )
        if not found:
            raise NotFoundException(
                identifier="path",
                identifier_value=path,
                message=f"Media file missing from storage: {path}",
                message_code=resources.STORAGE_NOT_FOUND,
                entity="Media",
            )
        return self.storage.stream(path), media.content_type

    async def remove(self, id: int) -> MediaModel:
        """Delete a media record and its stored file.

        Args:
            id (int): ID of the media record.
        Returns:
            (MediaModel): The deleted record.
        """
        media = await self.repo.delete_by_id(id)
        media = self._check_for_id_existence(id, media)
        await self.storage.delete(media.path)
        return media
