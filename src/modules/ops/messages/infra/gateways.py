"""The adapters that actually hand a message to a provider.

Everything above this file speaks `SmsDeliveryResult`, so a provider being
down, misconfigured or simply absent is a value the caller writes onto a row —
never an exception unwinding a send. That is the whole point of the boundary:
`app/` decides what to record, `infra/` decides how to talk.

Only the console gateway is built in. The three real ones go through
`sms-providers-sdk`, an optional dependency imported at call time, so a clone
with no SDK installed still boots, still queues, and still delivers to the log.
"""

from abc import ABC, abstractmethod
from typing import Any, Mapping, Sequence

from src.core.logger import logger
from src.modules.ops.messages.domain.enums import ProviderCode
from src.modules.ops.messages.domain.results import (
    SmsBulkDeliveryResult,
    SmsDeliveryResult,
)


class AbstractSmsGateway(ABC):
    """One provider's wire protocol, behind the two calls the sender makes."""

    __code__: ProviderCode

    def __init__(self, credentials: Mapping[str, str] | None = None) -> None:
        self.credentials = dict(credentials or {})

    @abstractmethod
    async def send(self, recipient: str, body: str) -> SmsDeliveryResult: ...

    @abstractmethod
    async def send_bulk(
        self,
        recipients: Sequence[str],
        body: str,
    ) -> SmsBulkDeliveryResult: ...

    def _failed(self, exc: Exception) -> str:
        logger.warning(
            "sms provider %s refused the message: %s",
            self.__code__,
            exc,
            exc_info=exc,
        )
        return f"{type(exc).__name__}: {exc}"

    def _delivered(self, result: Any) -> SmsDeliveryResult:
        if not result:
            return SmsDeliveryResult(
                delivered=False, error="provider accepted no recipient"
            )
        return SmsDeliveryResult(
            delivered=True, provider_message_id=result.message_id
        )

    def _delivered_bulk(self, result: Any) -> SmsBulkDeliveryResult:
        if not result:
            return SmsBulkDeliveryResult(
                delivered=False, error="provider accepted no recipient"
            )
        return SmsBulkDeliveryResult(
            delivered=True,
            accepted={row.receptor: row.message_id for row in result},
        )


class SdkSmsGateway(AbstractSmsGateway):
    """The real providers, all of which `sms-providers-sdk` already speaks.

    The SDK is imported inside the call, not at module scope: this file is
    imported by the module's providers on every boot, and an optional
    dependency must not decide whether the app starts.
    """

    def _sdk(self) -> Any:
        import sms_providers_sdk

        return sms_providers_sdk

    async def send(self, recipient: str, body: str) -> SmsDeliveryResult:
        try:
            # inside the try with the call itself: an SDK that was never
            # installed is a provider that cannot take the message, which is
            # an outcome to record, not an exception to unwind a send
            sdk = self._sdk()
            provider = sdk.get_async_provider(
                self.__code__.value, **self.credentials
            )
            result = await provider.send(
                sdk.SmsMessage(receptor=recipient, text=body)
            )
        except Exception as exc:
            return SmsDeliveryResult(delivered=False, error=self._failed(exc))
        return self._delivered(result)

    async def send_bulk(
        self,
        recipients: Sequence[str],
        body: str,
    ) -> SmsBulkDeliveryResult:
        try:
            sdk = self._sdk()
            provider = sdk.get_async_provider(
                self.__code__.value, **self.credentials
            )
            result = await provider.send_bulk(
                sdk.BulkSmsMessage(receptors=list(recipients), text=body)
            )
        except Exception as exc:
            return SmsBulkDeliveryResult(
                delivered=False, error=self._failed(exc)
            )
        return self._delivered_bulk(result)


class KavenegarGateway(SdkSmsGateway):
    __code__ = ProviderCode.KAVENEGAR


class MelipayamakGateway(SdkSmsGateway):
    __code__ = ProviderCode.MELIPAYAMAK


class SmsIrGateway(SdkSmsGateway):
    __code__ = ProviderCode.SMSIR


class ConsoleSmsGateway(AbstractSmsGateway):
    """Delivers to the log — the default in development, and the gateway the
    test suite can point at without a network."""

    __code__ = ProviderCode.CONSOLE

    async def send(self, recipient: str, body: str) -> SmsDeliveryResult:
        logger.info("sms to %s: %s", recipient, body)
        return SmsDeliveryResult(delivered=True)

    async def send_bulk(
        self,
        recipients: Sequence[str],
        body: str,
    ) -> SmsBulkDeliveryResult:
        logger.info("sms to %s recipients: %s", len(recipients), body)
        return SmsBulkDeliveryResult(
            delivered=True, accepted={row: "" for row in recipients}
        )


SMS_GATEWAYS: dict[ProviderCode, type[AbstractSmsGateway]] = {
    ProviderCode.CONSOLE: ConsoleSmsGateway,
    ProviderCode.KAVENEGAR: KavenegarGateway,
    ProviderCode.MELIPAYAMAK: MelipayamakGateway,
    ProviderCode.SMSIR: SmsIrGateway,
}
