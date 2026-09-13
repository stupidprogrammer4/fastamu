from <<PKG>>.<<M>>.domain.context import <<P>>Context
from <<PKG>>.<<M>>.domain.dtos import <<P>>Input
from <<PKG>>.<<M>>.app.results import <<P>>Out
from <<PKG>>.<<M>>.infra.readers import <<P>>Reader


class <<P>>Service:
    """The <<S>> engine.

    ``run`` is the only place that touches I/O: it reads the context,
    then hands it to ``calculate``, which stays pure and testable.
    """

    def __init__(self, reader: <<P>>Reader) -> None:
        self.reader = reader

    async def run(self, data: <<P>>Input) -> <<P>>Out:
        context = await self.reader.read()
        return self.calculate(context, data)

    def calculate(
        self, context: <<P>>Context, data: <<P>>Input
    ) -> <<P>>Out:
        raise NotImplementedError
