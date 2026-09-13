from typing import Any, ClassVar

from pydantic import BaseModel, Field


def Row(*, title: str | None = None, **kwargs: Any) -> Any:
    """Declare an Excel column on an `ExcelRow` — the field-level counterpart
    to pydantic's `Field`. ``title`` is the column header; any other ``Field``
    keyword (default, validators, ...) is passed through::

        class ProductRow(ExcelRow):
            title: str = Row(title="عنوان")
    """
    return Field(title=title, **kwargs)


class ExcelRow(BaseModel):
    """A single spreadsheet row — the Excel counterpart to an ORM model / ES
    document. Declare columns as fields via `Row(...)`; column order follows
    field-definition order."""

    column_names: ClassVar[tuple[str, ...]] = ()
    _titles: ClassVar[tuple[str, ...]] = ()

    @classmethod
    def __pydantic_init_subclass__(cls, **kwargs: Any) -> None:
        super().__pydantic_init_subclass__(**kwargs)
        cls.column_names = tuple(cls.model_fields)
        cls._titles = tuple(
            field.title or name for name, field in cls.model_fields.items()
        )

    @classmethod
    def titles(cls) -> list[str]:
        return list(cls._titles)

    def cells(self) -> list[Any]:
        return [self.__dict__[name] for name in self.column_names]
