from pathlib import Path

import yaml
from dishka import Provider, Scope, provide
from dishka.integrations.fastapi import DishkaRoute, FromDishka
from fastapi import APIRouter
from pydantic import Field

from papilio.api.application import create_app
from papilio.api.responses.envelope import APIResponse
from papilio.core.config import Settings
from papilio.schemas.inputs import BaseDTO
from papilio.schemas.outputs import BaseOutput


class GreetingInput(BaseDTO):
    name: str = Field(min_length=1, max_length=80)


class GreetingOutput(BaseOutput):
    text: str


class GreetingService:
    async def greet(self, data: GreetingInput) -> GreetingOutput:
        return GreetingOutput(text=f"Hello, {data.name}!")


class GreetingProvider(Provider):
    service = provide(GreetingService, scope=Scope.REQUEST)


router = APIRouter(route_class=DishkaRoute)


@router.post("/greetings", response_model=APIResponse[GreetingOutput, None])
async def greet(
    data: GreetingInput,
    service: FromDishka[GreetingService],
):
    return APIResponse.from_data(await service.greet(data))


def build_app():
    path = Path(__file__).with_name("minimal.yml")
    settings = Settings.model_validate(yaml.safe_load(path.read_text()))
    return create_app(
        settings,
        providers=[GreetingProvider()],
        routers=[router],
    )


app = build_app()
