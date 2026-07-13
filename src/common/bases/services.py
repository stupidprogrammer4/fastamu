from typing import Generic, Any, Sequence, TypeVar, get_args, get_origin

from src.common.errors.exceptions import NotFoundException, ValidationException
from src.common.bases.results import BatchResultType
from src.core import resources
from src.infra.postgres.models.typing import TIDModel, TModel


class BaseService(Generic[TModel]):

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
                input={}
            )
        return d
    
    def _check_not_empty_list(self, ls: list):
        if not ls:
            raise ValidationException(
                message="Your input must be not empty",
                message_code=resources.EMPTY_INPUT,
                loc=[],
                input=[]
            )
        return ls

    def _check_for_existence(
        self,
        identifier: str,
        identifier_value: Any,
        obj: TModel | None
    ) -> TModel:
        if not obj:
            raise NotFoundException(
                identifier=identifier,
                identifier_value=identifier_value,
                message=f"Cannot find {self.__model_name__} by {identifier} with value {identifier_value}",
                message_code=resources.NOT_FOUND_ERROR,
                entity=self.__model_name__
            )
        return obj
    

    def _check_batch_data(
        self,
        founed_ids: Sequence[int],
        input_ids: Sequence[int],
        prefix_loc: list[str]
    ) -> Sequence[ValidationException]:
        set_founded_ids = set(founed_ids)
        errors = []
        for idx, id in enumerate(input_ids):
            if id not in set_founded_ids:
                errors.append(
                    ValidationException(
                        message=f"Cannot find {self.__model_name__} with id {id}",
                        message_code=resources.NOT_FOUND_ERROR,
                        loc=prefix_loc + [idx]
                    )
                )
        return errors

    

class BaseIDService(BaseService[TIDModel]):

    def _check_for_id_existence(
        self,
        id: int,
        obj: TIDModel | None
    ):
        return super()._check_for_existence(
            identifier="id",
            identifier_value=id,
            obj=obj
        )
    
    def _check_batch_data(
        self,
        input_ids: Sequence[int],
        founded_objs: Sequence[TIDModel],
        loc: list[str] | None = None
    ) -> BatchResultType[TIDModel, ValidationException]:
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
                        message=f"Cannot find {self.__model_name__} with id {id}",
                        message_code=resources.NOT_FOUND_ERROR,
                        loc=base_loc + [idx]
                    )
                )

        if not items:
            raise ValidationException.get_invalid_input(errors)

        return BatchResultType(
            items=items,
            errors=errors,
            item_ids=set(ids)
        )