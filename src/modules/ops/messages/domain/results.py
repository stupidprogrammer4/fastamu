from dataclasses import dataclass, field


@dataclass(frozen=True, slots=True)
class SmsDeliveryResult:
    """What a gateway answered for one message.

    A refusal is a value, not an exception: the caller has a row to write it
    onto, and a provider being down is an outcome the system records rather
    than an error that unwinds the send.
    """

    delivered: bool
    provider_message_id: str | None = None
    error: str | None = None


@dataclass(frozen=True, slots=True)
class SmsBulkDeliveryResult:
    """The same, for a batch — `accepted` maps recipient to provider id."""

    delivered: bool
    accepted: dict[str, str] = field(default_factory=dict)
    error: str | None = None
