from typing import Any, Callable, Sequence, TypeVar, get_args, get_origin

from src.common.bases.results import BatchResultType
from src.common.errors.exceptions import NotFoundException, ValidationException
from src.core import resources
from src.infra.postgres.models.base import BaseIDModel, BaseModel


class BaseService[TModel: BaseModel]:
    __model__: type[TModel]
    __model_name__: str

    def __init_subclass__(cls, **kwargs):
        super().__init_subclass__(**kwargs)

        for base in getattr(cls, "__orig_bases__", []):
            origin = get_origin(base)
            args = get_args(base)

            if not origin or not args:
                continue

            if isinstance(args[0], TypeVar):
                continue

            if isinstance(origin, type) and issubclass(origin, BaseService):
                model_cls = args[0]
                cls.__model__ = model_cls
                cls.__model_name__ = model_cls.__name__.removesuffix("Model")
                break

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
        if not obj:
            raise NotFoundException(
                identifier=identifier,
                identifier_value=identifier_value,
                message=(
                    f"Cannot find {self.__model_name__} by {identifier} "
                    f"with value {identifier_value}"
                ),
                message_code=resources.NOT_FOUND_ERROR,
                entity=self.__model_name__,
            )
        return obj

    def _check_batch_data(
        self,
        founed_ids: Sequence[int],
        input_ids: Sequence[int],
        prefix_loc: list[str],
    ) -> Sequence[ValidationException]:
        set_founded_ids = set(founed_ids)
        errors = []
        for idx, id in enumerate(input_ids):
            if id not in set_founded_ids:
                errors.append(
                    ValidationException(
                        message=(
                            f"Cannot find {self.__model_name__} with id {id}"
                        ),
                        message_code=resources.NOT_FOUND_ERROR,
                        loc=prefix_loc + [idx],
                    )
                )
        return errors


class BaseIDService[TIDModel: BaseIDModel](BaseService[TIDModel]):
    def _check_for_id_existence(self, id: int, obj: TIDModel | None):
        return super()._check_for_existence(
            identifier="id", identifier_value=id, obj=obj
        )

    def _check_batch_data(
        self,
        input_ids: Sequence[int],
        founded_objs: Sequence[TIDModel],
        loc: list[str] | None = None,
    ) -> BatchResultType[TIDModel, ValidationException]:
        """Split a batch of ids into the rows that exist and one error per id
        that does not, so a partial batch reports what it dropped instead of
        failing whole.

        Args:
            input_ids (Sequence[int]): The ids that were asked for.
            founded_objs (Sequence[TIDModel]): The rows that came back.
            loc (list[str] | None): Where the ids sat in the request body.
        Returns:
            (BatchResultType): The found rows, their ids, and the misses.
        Raises:
            ValidationException: Nothing was found — there is no partial
                success to report, so the whole input is rejected.
        """
        founded_ids = {o.id: o for o in founded_objs}

        items, errors, ids = [], [], []
        base_loc = loc or [f"{self.__model_name__.lower()}_ids"]
        for idx, id in enumerate(set(input_ids)):
            if id in founded_ids:
                items.append(founded_ids[id])
                ids.append(id)
            else:
                errors.append(
                    ValidationException(
                        message=(
                            f"Cannot find {self.__model_name__} with id {id}"
                        ),
                        message_code=resources.NOT_FOUND_ERROR,
                        loc=base_loc + [idx],
                    )
                )

        if not items:
            raise ValidationException.get_invalid_input(errors)

        return BatchResultType(items=items, errors=errors, item_ids=set(ids))

    def _func_check_batch_data(
        self,
        input_values: Sequence[Any],
        founded_objs: Sequence[TIDModel],
        key: Callable[[TIDModel], Any],
        identifier: str,
        loc: list[str] | None = None,
    ) -> BatchResultType[TIDModel, ValidationException]:
        """`_check_batch_data`, for a batch keyed on something other than the
        id — a slug, a code, an external reference.

        `key` reads that field off a found row so the two sides can be matched;
        `identifier` names it in the error message and in the default `loc`.
        The ids on the result are still the row ids, because that is what the
        caller writes with.

        Args:
            input_values (Sequence[Any]): The values that were asked for.
            founded_objs (Sequence[TIDModel]): The rows that came back.
            key (Callable[[TIDModel], Any]): Reads the matched field off a row.
            identifier (str): The field's name, for the message and the `loc`.
            loc (list[str] | None): Where the values sat in the request body.
        Returns:
            (BatchResultType): The found rows, their ids, and the misses.
        Raises:
            ValidationException: Nothing was found.
        """
        founded_values = {key(o): o for o in founded_objs}

        items, errors, ids = [], [], []
        base_loc = loc or [f"{self.__model_name__.lower()}_{identifier}s"]
        for idx, value in enumerate(set(input_values)):
            if value in founded_values:
                items.append(founded_values[value])
                ids.append(founded_values[value].id)
            else:
                errors.append(
                    ValidationException(
                        message=(
                            f"Cannot find {self.__model_name__} with "
                            f"{identifier} {value}"
                        ),
                        message_code=resources.NOT_FOUND_ERROR,
                        loc=base_loc + [idx],
                    )
                )

        if not items:
            raise ValidationException.get_invalid_input(errors)

        return BatchResultType(items=items, errors=errors, item_ids=set(ids))
