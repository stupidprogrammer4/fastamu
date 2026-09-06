from sqlalchemy.orm import declared_attr

from fastamu.infra.db.table import BaseTable
from fastamu.modules.ops.messages.domain.models import (
    MessageModel,
    SMSPatternModel,
    SMSProviderModel,
)


class MessageTable(MessageModel, BaseTable, table=True):
    pass


class SMSProviderTable(SMSProviderModel, BaseTable, table=True):
    # the derived name would be "tbl_smsproviders"
    @declared_attr.directive
    def __tablename__(cls) -> str:
        return "tbl_sms_providers"


class SMSPatternTable(SMSPatternModel, BaseTable, table=True):
    @declared_attr.directive
    def __tablename__(cls) -> str:
        return "tbl_sms_patterns"
