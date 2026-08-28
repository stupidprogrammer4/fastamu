from fastamu.infra.postgres.models.base import BaseTable
from fastamu.modules.ops.storage.domain.models import MediaModel


class MediaTable(MediaModel, BaseTable, table=True):
    # "media" is already plural — skip the auto-pluralised name.
    __tablename__ = "tbl_media"  # pyright: ignore[reportAssignmentType]
