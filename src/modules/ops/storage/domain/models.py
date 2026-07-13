from src.infra.postgres.models.base import BaseIDTimestampModel
from src.infra.postgres.types import BigIntField, CharField


class MediaModel(BaseIDTimestampModel, table=True):
    # "media" is already plural — skip the auto-pluralised name.
    __tablename__ = "tbl_media"  # pyright: ignore[reportAssignmentType]

    backend: str = CharField(20)
    path: str = CharField(255, unique=True)
    filename: str = CharField(255)
    extension: str = CharField(10)
    content_type: str = CharField(100)
    size: int = BigIntField()
    hash: str = CharField(64, unique=True)
