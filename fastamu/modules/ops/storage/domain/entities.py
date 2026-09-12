from fastamu.common.models.entities import BaseIDTimestampEntity
from fastamu.common.models.fields import BigIntField, CharField


class MediaEntity(BaseIDTimestampEntity):
    backend: str = CharField(20)
    path: str = CharField(255, unique=True)
    filename: str = CharField(255)
    extension: str = CharField(10)
    content_type: str = CharField(100)
    size: int = BigIntField()
    hash: str = CharField(64, unique=True)
