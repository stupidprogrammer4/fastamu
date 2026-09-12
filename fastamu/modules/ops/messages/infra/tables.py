from sqlalchemy.orm import declared_attr

from fastamu.infra.db.table import BaseTable
from fastamu.modules.ops.messages.domain.entities import (
    MessageEntity,
    SMSPatternEntity,
    SMSProviderEntity,
)


class MessageTable(MessageEntity, BaseTable, table=True):
    pass


class SMSProviderTable(SMSProviderEntity, BaseTable, table=True):
    # the derived name would be "tbl_smsproviders"
    @declared_attr.directive
    def __tablename__(cls) -> str:
        return "tbl_sms_providers"


class SMSPatternTable(SMSPatternEntity, BaseTable, table=True):
    @declared_attr.directive
    def __tablename__(cls) -> str:
        return "tbl_sms_patterns"
