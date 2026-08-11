from src.common.bases.events import EventInput


class MessageQueuedInput(EventInput):
    id: int


class MessagesQueuedInput(EventInput):
    ids: list[int]
