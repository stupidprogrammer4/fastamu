from .mysql import MySQLDialect


class MariaDBDialect(MySQLDialect):
    name = "mariadb"
