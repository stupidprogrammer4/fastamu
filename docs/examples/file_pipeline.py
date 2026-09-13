import asyncio
from pathlib import Path
from tempfile import TemporaryDirectory

from papilio.infra.csv.reader import CSVReader
from papilio.infra.csv.writer import CSVWriter
from papilio.infra.files.reader import FileReader
from papilio.infra.files.writer import FileWriter


async def main():
    with TemporaryDirectory() as folder:
        root = Path(folder)
        note = root / "note.txt"
        await FileWriter().write_text(note, "Hello Papilio")
        assert await FileReader().read_text(note) == "Hello Papilio"

        source, output = root / "source.csv", root / "output.csv"
        async with CSVWriter().open(source) as writer:
            count = await writer.write_rows(
                [("sku", "quantity"), ("BOOK", 2), ("PEN", 0)]
            )
            assert count == 3

        async with CSVReader().rows(source, batch_size=100) as rows:
            async with CSVWriter().open(output) as writer:
                await writer.write_row(await anext(rows))
                async for sku, quantity in rows:
                    if int(quantity) > 0:
                        await writer.write_row([sku, quantity])

        async with CSVReader().rows(output) as rows:
            result = [row async for row in rows]
        assert result == [["sku", "quantity"], ["BOOK", "2"]]
        print("Files and CSV: roundtrip and filtering passed")


if __name__ == "__main__":
    asyncio.run(main())
