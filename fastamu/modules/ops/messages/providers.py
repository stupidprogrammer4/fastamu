from dishka import Provider, Scope, provide

from fastamu.modules.ops.messages.app.senders import SmsSenderService
from fastamu.modules.ops.messages.app.services import (
    MessageService,
    SMSPatternService,
    SMSProviderService,
)
from fastamu.modules.ops.messages.infra.repository import (
    MessageRepository,
    SMSPatternRepository,
    SMSProviderRepository,
)
from fastamu.modules.ops.messages.interfaces import (
    IMessageService,
    ISMSPatternService,
    ISMSProviderService,
    ISmsSenderService,
)


class MessageProvider(Provider):
    scope = Scope.REQUEST

    message_repo = provide(MessageRepository)
    sms_provider_repo = provide(SMSProviderRepository)
    sms_pattern_repo = provide(SMSPatternRepository)
    message_service = provide(MessageService, provides=IMessageService)
    sms_provider_service = provide(
        SMSProviderService, provides=ISMSProviderService
    )
    sms_pattern_service = provide(
        SMSPatternService, provides=ISMSPatternService
    )
    # APP scope: the sender opens its own database scopes
    sms_sender_service = provide(
        SmsSenderService, provides=ISmsSenderService, scope=Scope.APP
    )
