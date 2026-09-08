"""Raised when a projection cannot see the rows it was asked about."""


class ProjectionSourceMissing(Exception):
    def __init__(self, *ids: int) -> None:
        self.ids = ids
        named = ", ".join(str(id) for id in ids)
        super().__init__(
            f"No source row is visible for {named}; it has not committed "
            "yet, or the transaction that queued this rolled back"
        )
