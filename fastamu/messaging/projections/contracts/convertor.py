from abc import ABC, abstractmethod


class AbstractConvertor[TModel, TDocument](ABC):
    """Convert a source model into a destination value without I/O."""

    @abstractmethod
    def convert(self, model: TModel) -> TDocument: ...
