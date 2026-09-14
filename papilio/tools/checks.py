from typing import Any, Callable, Protocol, Sequence

from papilio.core import resources
from papilio.errors.exceptions import (
    NotFoundException,
    ValidationException,
)
from papilio.schemas.results import BatchResultType


class HasID(Protocol):
    @property
    def id(self) -> int: ...


class Checks[TModel]:
    entity: str

    def _check_not_empty_dict(self, d: dict):
        if not d:
            raise ValidationException(
                message="Your input must be not empty",
                message_code=resources.EMPTY_INPUT,
                loc=[],
                input={},
            )
        return d

    def _check_not_empty_list(self, ls: list):
        if not ls:
            raise ValidationException(
                message="Your input must be not empty",
                message_code=resources.EMPTY_INPUT,
                loc=[],
                input=[],
            )
        return ls

    def _check_for_existence(
        self, identifier: str, identifier_value: Any, obj: TModel | None
    ) -> TModel:
        if obj is None:
            raise NotFoundException(
                identifier=identifier,
                identifier_value=identifier_value,
                message=(
                    f"Cannot find {self.entity} by {identifier} "
                    f"with value {identifier_value}"
                ),
                message_code=resources.NOT_FOUND_ERROR,
                entity=self.entity,
            )
        return obj

    def _check_batch_data(
        self,
        found_ids: Sequence[int],
        input_ids: Sequence[int],
        prefix_loc: list[str],
    ) -> Sequence[ValidationException]:
        found_ids_set = set(found_ids)
        errors = []
        for idx, id in enumerate(input_ids):
            if id not in found_ids_set:
                errors.append(
                    ValidationException(
                        message=(f"Cannot find {self.entity} with id {id}"),
                        message_code=resources.NOT_FOUND_ERROR,
                        loc=prefix_loc + [idx],
                    )
                )
        return errors

    def _func_check_batch_data(
        self,
        input_values: Sequence[Any],
        found_objs: Sequence[TModel],
        key: Callable[[TModel], Any],
        identifier: str,
        loc: list[str] | None = None,
    ) -> BatchResultType[TModel, ValidationException]:
        """Match rows by `key`, preserving first-requested order.

        Missing values produce errors at their first input position. Raise
        ValidationException if no rows match. No row ID is required or
        collected; item_ids stays empty.
        """
        found_values = {key(o): o for o in found_objs}

        items, errors = [], []
        base_loc = loc or [f"{self.entity.lower()}_{identifier}s"]
        positions = {}
        for index, value in enumerate(input_values):
            positions.setdefault(value, index)
        for value in dict.fromkeys(input_values):
            if value in found_values:
                items.append(found_values[value])
            else:
                errors.append(
                    ValidationException(
                        message=(
                            f"Cannot find {self.entity} with "
                            f"{identifier} {value}"
                        ),
                        message_code=resources.NOT_FOUND_ERROR,
                        loc=base_loc + [positions[value]],
                        input=value,
                    )
                )

        if not items:
            raise ValidationException.get_invalid_input(errors)

        return BatchResultType(items=items, errors=errors)


class IDChecks[TIDModel: HasID](Checks[TIDModel]):
    def _check_for_id_existence(self, id: int, obj: TIDModel | None):
        return super()._check_for_existence(
            identifier="id", identifier_value=id, obj=obj
        )

    def _check_batch_data(
        self,
        input_ids: Sequence[int],
        found_objs: Sequence[TIDModel],
        loc: list[str] | None = None,
    ) -> BatchResultType[TIDModel, ValidationException]:
        """Split a batch of ids into the rows that exist and one error per id
        that does not, so a partial batch reports what it dropped instead of
        failing whole.

        Args:
            input_ids (Sequence[int]): The ids that were asked for.
            found_objs (Sequence[TIDModel]): The rows that came back.
            loc (list[str] | None): Where the ids sat in the request body.
        Returns:
            (BatchResultType): The found rows, their ids, and the misses.
        Raises:
            ValidationException: Nothing was found — there is no partial
                success to report, so the whole input is rejected.
        """
        found_ids = {o.id: o for o in found_objs}

        items, errors, ids = [], [], []
        base_loc = loc or [f"{self.entity.lower()}_ids"]
        positions = {}
        for index, value in enumerate(input_ids):
            positions.setdefault(value, index)
        for id in dict.fromkeys(input_ids):
            if id in found_ids:
                items.append(found_ids[id])
                ids.append(id)
            else:
                errors.append(
                    ValidationException(
                        message=(f"Cannot find {self.entity} with id {id}"),
                        message_code=resources.NOT_FOUND_ERROR,
                        loc=base_loc + [positions[id]],
                        input=id,
                    )
                )

        if not items:
            raise ValidationException.get_invalid_input(errors)

        return BatchResultType(items=items, errors=errors, item_ids=set(ids))

    def _func_check_batch_data(
        self,
        input_values: Sequence[Any],
        found_objs: Sequence[TIDModel],
        key: Callable[[TIDModel], Any],
        identifier: str,
        loc: list[str] | None = None,
    ) -> BatchResultType[TIDModel, ValidationException]:
        """Match rows through Checks and include their row IDs."""
        result = super()._func_check_batch_data(
            input_values, found_objs, key, identifier, loc
        )
        return BatchResultType(
            items=result.items,
            errors=result.errors,
            item_ids={row.id for row in result.items},
        )
