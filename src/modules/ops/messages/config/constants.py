from typing import Annotated

from pydantic import AfterValidator, PlainSerializer

from src.common.bases.encryption import IDEncryption

MESSAGE_ID_ENCRYPTION = IDEncryption(
    mod=99_999_989,
    coff=27_182_818,
    offset=700_000_000,
)

MessageIDField = Annotated[
    int, PlainSerializer(MESSAGE_ID_ENCRYPTION.encode, return_type=int)
]

MessageIDInput = Annotated[int, AfterValidator(MESSAGE_ID_ENCRYPTION.decode)]

SMS_PROVIDER_ID_ENCRYPTION = IDEncryption(
    mod=99_999_989,
    coff=31_415_926,
    offset=750_000_000,
)

SmsProviderIDField = Annotated[
    int, PlainSerializer(SMS_PROVIDER_ID_ENCRYPTION.encode, return_type=int)
]

# the event vocabulary — emitters and handlers meet on these names
MESSAGE_QUEUED = "message_queued"
MESSAGES_QUEUED = "messages_queued"
