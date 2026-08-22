from enum import StrEnum


class MessageChannel(StrEnum):
    SMS = "sms"


class MessageStatus(StrEnum):
    PENDING = "pending"
    SENT = "sent"
    FAILED = "failed"


class ProviderCode(StrEnum):
    CONSOLE = "console"
    KAVENEGAR = "kavenegar"
    MELIPAYAMAK = "melipayamak"
    SMSIR = "smsir"


class MessageKind(StrEnum):
    FREE_FORM = "free_form"
    PATTERN = "pattern"


class PatternKey(StrEnum):
    OTP = "otp"
