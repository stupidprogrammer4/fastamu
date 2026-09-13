from enum import StrEnum


class AccessScope(StrEnum):
    """Guardable sections of the API — one per feature module.

    The demo modules reference these; extend the enum as you add modules
    (the module scaffolder does not touch it — scopes are an app concern).
    """

    STORAGE = "storage"
    SYSTEM = "system"
    MESSAGES = "messages"
