from typing import Annotated

from fastapi import Depends

from papilio.api.requests.parameters import decode_path_id
from papilio.modules.ops.messages.config.constants import (
    MESSAGE_ID_ENCRYPTION,
)

MessageID = Annotated[
    int, Depends(decode_path_id(MESSAGE_ID_ENCRYPTION, "Message"))
]
