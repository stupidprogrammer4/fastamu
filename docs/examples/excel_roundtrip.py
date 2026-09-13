import asyncio
from pathlib import Path
from tempfile import TemporaryDirectory

from openpyxl import Workbook

from papilio.infra.excel.reader import ExcelReader
from papilio.infra.excel.row import ExcelRow, Row
from papilio.infra.excel.writer import ExcelWriter


class ProductRow(ExcelRow):
    sku: str = Row(title="SKU")
    quantity: int = Row(title="Quantity", ge=0)


def make_template(path: str):
    workbook = Workbook()
    try:
        workbook.save(path)
    finally:
        workbook.close()


async def main():
    reader, writer = ExcelReader(), ExcelWriter()
    try:
        with TemporaryDirectory() as folder:
            template = str(Path(folder) / "template.xlsx")
            output = str(Path(folder) / "products.xlsx")
            await asyncio.to_thread(make_template, template)
            expected = [ProductRow(sku="BOOK", quantity=2)]
            await writer.write_rows(
                template, output, expected, start_row=1, with_titles=True
            )
            actual = await reader.read_rows(output, ProductRow, start_row=2)
            assert actual == expected
            print("Excel: typed roundtrip passed")
    finally:
        await reader.close()
        await writer.close()


if __name__ == "__main__":
    asyncio.run(main())
