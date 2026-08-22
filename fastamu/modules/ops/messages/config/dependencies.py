from typing import Annotated

from fastapi import Depends

from fastamu.modules.ops.messages.config.constants import MESSAGE_ID_ENCRYPTION
from fastamu.web.dependencies import decode_path_id

MessageID = Annotated[
    int, Depends(decode_path_id(MESSAGE_ID_ENCRYPTION, "Message"))
]
