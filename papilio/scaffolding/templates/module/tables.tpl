from papilio.infra.db.table import BaseTable
from <<PKG>>.<<M>>.domain.entities import <<P>>Model


class <<P>>Table(<<P>>Model, BaseTable, table=True):
    # the table name derives from the class: "tbl_<<PL>>"
    pass
