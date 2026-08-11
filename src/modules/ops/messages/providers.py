from dishka import Provider, Scope, provide

from src.modules.ops.messages.app.senders import SmsSenderService
from src.modules.ops.messages.app.services import (
    MessageService,
    SMSPatternService,
    SMSProviderService,
)
from src.modules.ops.messages.infra.repository import (
    MessageRepository,
    SMSPatternRepository,
    SMSProviderRepository,
)
from src.modules.ops.messages.interfaces import (
    IMessageService,
    ISMSPatternService,
    ISMSProviderService,
    ISmsSenderService,
)
from src.modules.ops.messages.tasks.send import (
    MessageQueuedHandler,
    MessagesQueuedHandler,
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
    # APP scope: it is driven by the event bus and opens its own scopes
    sms_sender_service = provide(
        SmsSenderService, provides=ISmsSenderService, scope=Scope.APP
    )
    message_queued_handler = provide(MessageQueuedHandler)
    messages_queued_handler = provide(MessagesQueuedHandler)
