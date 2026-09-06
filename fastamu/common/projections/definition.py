from typing import ClassVar


class ProjectionDefinition:
    queue_name: ClassVar[str | None] = None

    def __init_subclass__(cls, **kwargs):
        super().__init_subclass__(**kwargs)
        if cls.queue_name is not None:
            from fastamu.tasks.projection.registry import registry

            registry.add(cls)
