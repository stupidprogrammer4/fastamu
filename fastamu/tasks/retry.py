"""RabbitMQ retry destinations shared by the native task transports."""

import hashlib
import math
import time

from fastamu.core.config import RetryTransportConfig
from fastamu.messaging.retry import RetryDecision


def failed_queue(queue: str, config: RetryTransportConfig) -> str:
    return (
        config.namespace
        + ".failed."
        + hashlib.sha256(queue.encode()).hexdigest()
    )


def retry_queue(
    queue: str, decision: RetryDecision, config: RetryTransportConfig
):
    if decision.delay is None:
        raise ValueError("Retry destination requires a delay")
    maximum = decision.max_delay or decision.delay
    if maximum < decision.delay:
        raise ValueError("Retry max_delay must cover the requested delay")
    ttl = math.ceil(maximum * 1000)
    digest = hashlib.sha256(queue.encode()).hexdigest()
    name = f"{config.namespace}.retry.{digest}.{ttl}"
    return name, {
        "x-queue-type": "quorum",
        "x-message-ttl": ttl,
        "x-dead-letter-exchange": "",
        "x-dead-letter-routing-key": queue,
        "x-dead-letter-strategy": "at-least-once",
        "x-overflow": "reject-publish",
    }


def failure_headers(
    headers: dict, error: Exception, attempt: int, config: RetryTransportConfig
) -> dict:
    return {
        **headers,
        "fastamu_attempt": attempt,
        "fastamu_first_failure": headers.get(
            "fastamu_first_failure", time.time()
        ),
        "fastamu_error_type": type(error).__name__,
        "fastamu_error": str(error)[: config.error_max_length],
    }
