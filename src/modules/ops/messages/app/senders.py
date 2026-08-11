from typing import Sequence

from dishka import AsyncContainer

from src.modules.ops.messages.domain.context import MessageContext
from src.modules.ops.messages.domain.results import SmsDeliveryResult
from src.modules.ops.messages.infra.gateways import SMS_GATEWAYS
from src.modules.ops.messages.interfaces import IMessageService


class SmsSenderService:
    """Sends what has been queued, holding a connection only to read and write.

    This is the one service in the module that opens its own scopes instead of
    taking a repository. It has to: a provider call is a network round trip of
    unknown length, and a request-scoped session would sit idle across it,
    holding a pool connection hostage while nothing happens on it. So the read
    closes, the gateway is called with no transaction open, and a fresh scope
    records the outcome.

    That is also why it lives in APP scope — it is driven by the event bus, not
    by a request.
    """

    def __init__(self, container: AsyncContainer) -> None:
        self.container = container

    async def send(self, id: int) -> bool:
        """
        Send one queued message and write down how it went.

        Args:
            id (int): ID of the message to send.
        Returns:
            (bool): Whether the provider took it.
        """
        async with self.container() as scope:
            messages = await scope.get(IMessageService)
            context = await messages.get_context(id)

        result = await self._sent(context)

        async with self.container() as scope:
            messages = await scope.get(IMessageService)
            await messages.deliver(id, result)
        return result.delivered

    async def send_bulk(self, ids: Sequence[int]) -> int:
        """
        Send a batch of queued messages the same way — one connection for the
        read, one for the write, and the provider in between.

        Args:
            ids (Sequence[int]): IDs of the messages to send.
        Returns:
            (int): How many the provider took.
        """
        if not ids:
            return 0
        async with self.container() as scope:
            messages = await scope.get(IMessageService)
            contexts = await messages.get_contexts(ids)
        if not contexts:
            return 0

        results = {
            context.message.id: await self._sent(context)
            for context in contexts
        }

        async with self.container() as scope:
            messages = await scope.get(IMessageService)
            await messages.deliver_bulk(results)
        return sum(1 for row in results.values() if row.delivered)

    async def _sent(self, context: MessageContext) -> SmsDeliveryResult:
        provider = context.provider
        if provider is None:
            return SmsDeliveryResult(
                delivered=False, error="no sms provider is in use"
            )
        gateway_cls = SMS_GATEWAYS.get(provider.code)
        if gateway_cls is None:
            return SmsDeliveryResult(
                delivered=False,
                error=f"no gateway for provider {provider.code}",
            )
        gateway = gateway_cls(provider.credentials)
        return await gateway.send(
            context.message.recipient, context.message.body or ""
        )
