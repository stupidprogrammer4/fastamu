import pytest

from papilio.errors.exceptions import ValidationException
from papilio.infra.db.schema.entity import IdentifiedEntity
from papilio.tools.checks import IDChecks


class ThingModel(IdentifiedEntity):
    code: str


class ThingService(IDChecks[ThingModel]):
    entity = "Thing"


def thing(id: int, code: str) -> ThingModel:
    return ThingModel.model_construct(id=id, code=code)


def test_batch_results_keep_input_order_and_locate_the_original_value() -> (
    None
):
    result = ThingService()._check_batch_data(
        [3, 1, 2, 1],
        [thing(1, "one"), thing(3, "three")],
    )

    assert [row.id for row in result.items] == [3, 1]
    assert result.errors[0].input == 2
    assert result.errors[0].loc[-1] == 2


def test_an_entirely_missing_batch_carries_every_invalid_input() -> None:
    with pytest.raises(ValidationException) as caught:
        ThingService()._check_batch_data([7, 5], [])

    errors = caught.value.childs or []
    assert [(error.input, error.loc[-1]) for error in errors] == [
        (7, 0),
        (5, 1),
    ]


def test_non_id_batch_results_preserve_the_same_contract() -> None:
    result = ThingService()._func_check_batch_data(
        ["three", "missing", "one"],
        [thing(1, "one"), thing(3, "three")],
        key=lambda row: row.code,
        identifier="code",
    )

    assert [row.id for row in result.items] == [3, 1]
    assert result.errors[0].input == "missing"
    assert result.errors[0].loc[-1] == 1
