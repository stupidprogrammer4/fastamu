from .base import DatabaseDialect


class MSSQLDialect(DatabaseDialect):
    name = "mssql"

    def unique_values(self, error):
        # pyodbc exposes driver text containing the native error number.
        detail = str(error.orig)
        return {} if "(2601)" in detail or "(2627)" in detail else None
