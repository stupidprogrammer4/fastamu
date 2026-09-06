from fastamu.common.bases.fields import BigIntField, CharField
from fastamu.common.bases.models import BaseIDTimestampModel


class MediaModel(BaseIDTimestampModel):
    backend: str = CharField(20)
    path: str = CharField(255, unique=True)
    filename: str = CharField(255)
    extension: str = CharField(10)
    content_type: str = CharField(100)
    size: int = BigIntField()
    hash: str = CharField(64, unique=True)
