from datetime import datetime

from pydantic import computed_field

from src.common.bases.schemas import BaseOutput


class MediaOut(BaseOutput):
    id: int
    filename: str
    extension: str
    content_type: str
    size: int
    hash: str
    backend: str
    path: str
    created_at: datetime

    @computed_field
    @property
    def url(self) -> str:
        # The download route for this file; path is what callers store/reference.
        return f"/storage/file/{self.path}"
