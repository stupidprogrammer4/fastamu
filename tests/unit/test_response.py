from fastapi.exceptions import RequestValidationError
from pydantic import BaseModel, ValidationError, field_validator

from fastamu.web.response import APIResponse


class Payload(BaseModel):
    value: int


class Input(BaseModel):
    value: str

    @field_validator("value")
    @classmethod
    def reject(cls, value: str) -> str:
        raise ValueError("refused")


def test_response_accepts_any_pydantic_payload_and_omits_empty_envelope() -> (
    None
):
    response = APIResponse[Payload, None].from_data(Payload(value=3))

    assert response.model_dump(mode="json") == {
        "success": True,
        "data": {"value": 3},
    }


def test_validation_context_is_json_readable() -> None:
    try:
        Input(value="bad")
    except ValidationError as error:
        refused = RequestValidationError(
            [{**row, "loc": ("body", *row["loc"])} for row in error.errors()]
        )
    response = APIResponse.from_pydantic_error(refused)

    dumped = response.model_dump(mode="json")
    assert dumped["errors"][0]["loc"] == ["value"]
    assert all(
        isinstance(value, (str, int, float, bool, type(None)))
        for value in dumped["errors"][0].get("ctx", {}).values()
    )
