import importlib
import inspect
import pkgutil
from functools import cached_property, lru_cache

from dishka import Provider
from elasticsearch import AsyncElasticsearch
from elasticsearch.dsl import AsyncDocument
from fastapi import APIRouter

from src.core.logger import logger


class Bootstrapper:
    def __init__(self, base_pkg: str = "src.modules") -> None:
        self.base_pkg = base_pkg
        self.providers_path = "providers"
        self.models_path = "domain.models"
        self.routers_path = "routers"
        self.doc_path = "domain.documents"
        self.tasks_path = "tasks"

    @cached_property
    def submodules(self) -> list:
        """
        Scan and import submodules ONLY ONCE.
        Returns a list of imported modules instead of yielding them repeatedly.

        Children of ``base_pkg`` are domain groups (catalog, market, …); a
        package counts as a module when it has a ``domain``/``app`` layer,
        so a group placed directly under ``base_pkg`` is scanned one level in.
        """
        modules = []
        base = importlib.import_module(self.base_pkg)
        for _, name, is_pkg in pkgutil.iter_modules(base.__path__, prefix=self.base_pkg + "."):
            if is_pkg:
                if self._is_module(name):
                    modules.append(name)
                else:
                    group = importlib.import_module(name)
                    for _, sub_name, sub_is_pkg in pkgutil.iter_modules(group.__path__, prefix=name + "."):
                        if sub_is_pkg and self._is_module(sub_name):
                            modules.append(sub_name)
        return modules

    def _is_module(self, name: str) -> bool:
        """Tell a feature module apart from a group folder.

        Args:
            name (str): Dotted package path under ``base_pkg``.
        Returns:
            (bool): True when the package has a ``domain`` or ``app`` layer.
        """
        pkg = importlib.import_module(name)
        layers = {sub for _, sub, is_pkg in pkgutil.iter_modules(pkg.__path__) if is_pkg}
        return bool(layers & {"domain", "app"})

    def import_module(self, path: str, *, raise_nested: bool = False):
        module = None
        try:
            module = importlib.import_module(path)
        except ModuleNotFoundError as e:
            if raise_nested and e.name != path:
                raise
        return module

    def import_package_modules(self, path: str, *, raise_nested: bool = False) -> list:
        """Import a package and every file inside it — packages keep an empty
        ``__init__.py``, so the members live in the files.

        Args:
            path (str): Dotted path of the package (e.g. ``...listings.routers``).
            raise_nested (bool): Re-raise import errors coming from inside a file.
        Returns:
            (list): The imported file modules; empty when the package is absent.
        """
        modules = []
        package = self.import_module(path, raise_nested=raise_nested)
        if package is not None and hasattr(package, "__path__"):
            for _, name, is_pkg in pkgutil.iter_modules(package.__path__, prefix=path + "."):
                if not is_pkg:
                    module = self.import_module(name, raise_nested=raise_nested)
                    if module is not None:
                        modules.append(module)
        return modules

    def boot_routers(self) -> list[APIRouter]:
        """Find all instances of fastapi.APIRouter in each module's routers files."""
        routers = []
        for module_name in self.submodules:
            files = self.import_package_modules(
                f"{module_name}.{self.routers_path}", raise_nested=True
            )
            for module in files:
                for _, obj in inspect.getmembers(module):
                    if isinstance(obj, APIRouter) and not any(obj is seen for seen in routers):
                        routers.append(obj)
        return routers

    def boot_sqlmodels(self) -> None:
        """
        Models are implicitly registered when submodules are imported
        via the cached_property. We just need to access self.submodules.
        """
        for module_name in self.submodules:
            self.import_module(f"{module_name}.{self.models_path}")

    def boot_providers(self) -> list[Provider]:
        """Find and instantiate all subclasses of dishka.Provider."""
        providers = []
        for module_name in self.submodules:
            module = self.import_module(f"{module_name}.{self.providers_path}")
            if module:
                for _, obj in inspect.getmembers(module):
                    if (
                        inspect.isclass(obj)
                        and issubclass(obj, Provider)
                        and obj is not Provider
                        and obj.__module__.startswith(self.base_pkg)
                    ):
                        providers.append(obj())
        return providers

    def boot_documents(self) -> list[type[AsyncDocument]]:
        """Find all AsyncDocument subclasses."""
        es_documents = []
        for module_name in self.submodules:
            module = self.import_module(f"{module_name}.{self.doc_path}")
            if module:
                for _, obj in inspect.getmembers(module):
                    if inspect.isclass(obj) and issubclass(obj, AsyncDocument) and obj is not AsyncDocument:
                        es_documents.append(obj)
        return es_documents

    def boot_tasks(self) -> None:
        """Import each module's tasks files so their taskiq tasks register on the broker."""
        for module_name in self.submodules:
            self.import_package_modules(f"{module_name}.{self.tasks_path}")

    async def boot_es_indices(self, es: AsyncElasticsearch) -> None:
        """Create each ES read-model index (with its mapping) if it's missing.

        Safe to run on startup: a missing or unreachable Elasticsearch is logged
        and skipped so the app still boots.

        Args:
            es (AsyncElasticsearch): The client to create the indices with.
        Returns:
            (None)
        """
        for document in self.boot_documents():
            index_name = document._index._name
            try:
                if not await es.indices.exists(index=index_name):
                    await document.init(using=es)
            except Exception as exc:  # noqa: BLE001 — boot must survive a down ES
                logger.warning(f"skipping ES index init for {index_name}: {exc}")


@lru_cache
def get_bootstrapper():
    return Bootstrapper()
