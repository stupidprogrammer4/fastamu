from dataclasses import dataclass

from src.modules.ops.messages.domain.enums import ProviderCode
from src.modules.ops.messages.domain.models import MessageModel


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

    message: MessageModel
    provider: ProviderContext | None
