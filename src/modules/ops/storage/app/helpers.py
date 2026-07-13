import hashlib
from collections.abc import AsyncIterator

from src.common.errors.exceptions import ValidationException
from src.modules.ops.storage import resources


class StreamMeter:
    """Passes a byte stream through while hashing and enforcing a size cap."""

    def __init__(self, stream: AsyncIterator[bytes], max_size: int) -> None:
        self.stream = stream
        self.max_size = max_size
        self.size = 0
        self._hasher = hashlib.sha256()

    @property
    def hexdigest(self) -> str:
        return self._hasher.hexdigest()

    async def chunks(self) -> AsyncIterator[bytes]:
        """Re-yield the wrapped stream, updating the hash and byte count.

        Returns:
            (AsyncIterator[bytes]): The unchanged chunks of the wrapped stream.
        """
        async for chunk in self.stream:
            self.size += len(chunk)
            if self.size > self.max_size:
                raise ValidationException(
                    message=f"File exceeds the {self.max_size} byte limit",
                    message_code=resources.STORAGE_FILE_TOO_LARGE,
                    loc=["file"],
                )
            self._hasher.update(chunk)
            yield chunk
