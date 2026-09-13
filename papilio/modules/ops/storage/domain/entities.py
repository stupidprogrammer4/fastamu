from papilio.infra.db.fields import BigIntField, CharField
from papilio.infra.db.models import PersistenceEntity


class MediaEntity(PersistenceEntity):
    backend: str = CharField(20)
    path: str = CharField(255, unique=True)
    filename: str = CharField(255)
    extension: str = CharField(10)
    content_type: str = CharField(100)
    size: int = BigIntField()
    hash: str = CharField(64, unique=True)
