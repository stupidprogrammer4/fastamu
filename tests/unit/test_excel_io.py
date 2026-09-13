from openpyxl import Workbook

from papilio.infra.excel.reader import ExcelReader
from papilio.infra.excel.row import ExcelRow, Row
from papilio.infra.excel.writer import ExcelWriter


class ProductRow(ExcelRow):
    name: str = Row(title="Name")
    count: int = Row(title="Count")


async def test_excel_process_jobs_accept_plain_payloads(tmp_path):
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
