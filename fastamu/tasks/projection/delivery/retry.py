from taskiq import TaskiqMessage, TaskiqMiddleware

from fastamu.tasks.projection.delivery.labels import RETRY_DELAY


class RetryLabelsMiddleware(TaskiqMiddleware):
    """Expose delay to SmartRetry only; Redis handles the transport delay."""

    def pre_execute(self, message: TaskiqMessage) -> TaskiqMessage:
        if RETRY_DELAY in message.labels:
            message.labels["delay"] = message.labels[RETRY_DELAY]
        return message

    def pre_send(self, message: TaskiqMessage) -> TaskiqMessage:
        if RETRY_DELAY in message.labels:
            message.labels.pop("delay", None)
            if message.labels_types is not None:
                message.labels_types.pop("delay", None)
        return message
