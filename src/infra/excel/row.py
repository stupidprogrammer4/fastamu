from typing import Any

from pydantic import BaseModel, Field


def Row(*, title: str | None = None, **kwargs: Any) -> Any:
    """Declare an Excel column on an `ExcelRow` — the field-level counterpart to
    pydantic's `Field`. ``title`` is the column header; any other ``Field``
    keyword (default, validators, ...) is passed through::

        class ProductRow(ExcelRow):
            title: str = Row(title="عنوان")
    """
    return Field(title=title, **kwargs)


class ExcelRow(BaseModel):
    """A single spreadsheet row — the Excel counterpart to an ORM model / ES
    document. Declare columns as fields via `Row(...)`; column order follows
    field-definition order."""

    @classmethod
    def titles(cls) -> list[str]:
        """Column headers, in column order (falls back to the field name)."""
        return [field.title or name for name, field in cls.model_fields.items()]

    def cells(self) -> list[Any]:
        """Cell values, in column order."""
        return [getattr(self, name) for name in type(self).model_fields]
