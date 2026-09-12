from dataclasses import dataclass

from fastamu.modules.ops.messages.domain.entities import MessageEntity
from fastamu.modules.ops.messages.domain.enums import ProviderCode


@dataclass(frozen=True, slots=True)
class ProviderContext:
    id: int
    code: ProviderCode
    credentials: dict[str, str]


@dataclass(frozen=True, slots=True)
class MessageContext:
    """A message and the provider it would go out through, read together.

    The sender needs both and holds the connection for neither longer than the
    read, so they are joined in one query rather than fetched in two.
    """

    message: MessageEntity
    provider: ProviderContext | None
