from src.common.bases.events import EventHandler
from src.core.logger import logger
from src.modules.ops.messages.config.constants import (
    MESSAGE_QUEUED,
    MESSAGES_QUEUED,
)
from src.modules.ops.messages.domain.events import (
    MessageQueuedInput,
    MessagesQueuedInput,
)
from src.modules.ops.messages.interfaces import ISmsSenderService
from src.tasks.events import on


@on(MESSAGE_QUEUED)
class MessageQueuedHandler(EventHandler[MessageQueuedInput]):
    def __init__(self, sender: ISmsSenderService) -> None:
        self.sender = sender

    async def handle(self, data: MessageQueuedInput) -> bool:
        took = await self.sender.send(data.id)
        logger.info("message %s taken by the provider: %s", data.id, took)
        return took


@on(MESSAGES_QUEUED)
class MessagesQueuedHandler(EventHandler[MessagesQueuedInput]):
    def __init__(self, sender: ISmsSenderService) -> None:
        self.sender = sender

    async def handle(self, data: MessagesQueuedInput) -> int:
        took = await self.sender.send_bulk(data.ids)
        logger.info(
            "%s of %s messages taken by the provider", took, len(data.ids)
        )
        return took
