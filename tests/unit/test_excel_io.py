import os
from multiprocessing import current_process

import pytest
from openpyxl import Workbook
from pydantic import PrivateAttr, ValidationError

from papilio.infra.excel.reader import ExcelReader
from papilio.infra.excel.row import ExcelRow, Row
from papilio.infra.excel.writer import ExcelWriter


class ProductRow(ExcelRow):
    name: str = Row(title="Name")
    count: int = Row(title="Count")


class WorkerRow(ProductRow):
    _pid: int = PrivateAttr(default_factory=os.getpid)

    @classmethod
    def titles(cls) -> list[str]:
        assert current_process().name != "MainProcess"
        return super().titles()

    def cells(self) -> list:
        assert os.getpid() != self._pid
        return super().cells()


async def test_excel_roundtrip(tmp_path):
    template, output = tmp_path / "template.xlsx", tmp_path / "output.xlsx"
    workbook = Workbook()
    workbook.save(template)
    workbook.close()
    writer, reader = ExcelWriter(), ExcelReader()
    try:
        await writer.write_rows(
            str(template),
            str(output),
            [ProductRow(name="پروانه", count=2)],
            start_row=1,
            with_titles=True,
        )
        rows = await reader.read_rows(str(output), ProductRow, start_row=2)
        assert rows == [ProductRow(name="پروانه", count=2)]
        assert await reader.read_cell(str(output), "A1") == "Name"
        await writer.write_cell(str(output), str(output), "B2", 3)
        assert await reader.read_cell(str(output), "B2") == 3
    finally:
        await writer.close()
        await reader.close()


async def test_excel_rows_are_converted_in_worker_processes(tmp_path):
    template, output = tmp_path / "template.xlsx", tmp_path / "output.xlsx"
    workbook = Workbook()
    workbook.save(template)
    workbook.close()
    writer, reader = ExcelWriter(), ExcelReader()
    try:
        await writer.write_rows(
            str(template),
            str(output),
            [WorkerRow(name="item", count=2)],
            start_row=1,
            with_titles=True,
        )
        rows = await reader.read_rows(str(output), WorkerRow, start_row=2)
        assert len(rows) == 1
        assert rows[0].model_dump() == {"name": "item", "count": 2}
        assert rows[0]._pid != os.getpid()
        assert await reader.read_cell(str(output), "A1") == "Name"
    finally:
        await writer.close()
        await reader.close()


async def test_excel_worker_preserves_selection_and_validation(tmp_path):
    path = tmp_path / "rows.xlsx"
    workbook = Workbook()
    sheet = workbook.create_sheet("items")
    sheet.append(["Name", "Count"])
    sheet.append(["first", "2"])
    sheet.append(["second", 3])
    sheet.append([None, None])
    sheet.append(["invalid", "not a number"])
    workbook.save(path)
    workbook.close()
    reader = ExcelReader()
    try:
        rows = await reader.read_rows(
            str(path),
            ProductRow,
            sheet="items",
            start_row=2,
            limit=1,
        )
        assert rows == [ProductRow(name="first", count=2)]
        rows = await reader.read_rows(
            str(path),
            ProductRow,
            sheet="items",
            start_row=2,
        )
        assert rows == [
            ProductRow(name="first", count=2),
            ProductRow(name="second", count=3),
        ]
        with pytest.raises(ValidationError) as error:
            await reader.read_rows(
                str(path),
                ProductRow,
                sheet="items",
                start_row=5,
            )
        assert error.value.errors()[0]["loc"] == ("count",)
        assert error.value.errors()[0]["type"] == "int_parsing"
        # A failed job must leave the pool usable.
        assert (
            await reader.read_rows(
                str(path),
                ProductRow,
                sheet="items",
                start_row=2,
                limit=0,
            )
            == []
        )
    finally:
        await reader.close()
