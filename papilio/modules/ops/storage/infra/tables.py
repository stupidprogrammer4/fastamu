from papilio.infra.db.table import BaseTable
from papilio.modules.ops.storage.domain.entities import MediaEntity


class MediaTable(MediaEntity, BaseTable, table=True):
    # "media" is already plural — skip the auto-pluralised name.
    __tablename__ = "tbl_media"  # pyright: ignore[reportAssignmentType]
