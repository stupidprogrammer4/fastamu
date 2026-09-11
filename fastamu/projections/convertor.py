from abc import ABC, abstractmethod


class Convertor[TModel, TDocument](ABC):
    """Convert a source model into a destination document, without I/O."""

    @abstractmethod
    def convert(self, model: TModel) -> TDocument:
        """Build a document from an already-loaded model."""
        ...
