"""Generate a web application project."""

from pathlib import Path

import typer

from papilio.scaffolding import project
from papilio.scaffolding.options import Infrastructure


def new(
    name: str = typer.Argument(..., help="Project name"),
    directory: str = typer.Option("", "--dir", help="Destination directory"),
    infra: list[Infrastructure] = typer.Option(
        [], "--infra", help="Optional infrastructure; repeat to select several"
    ),
    cqrs: bool = typer.Option(False, "--cqrs", help="Enable Elasticsearch"),
) -> None:
    package = name.strip().replace("-", "_").replace(" ", "_").lower()
    root = Path(directory) if directory else Path(package)
    try:
        project.write(root, package, name, cqrs=cqrs, infra=infra)
    except ValueError as error:
        raise typer.BadParameter(str(error)) from error
    except FileExistsError as error:
        typer.secho(str(error), fg=typer.colors.RED)
        raise typer.Exit(1) from error
    typer.secho(f"Created project at {root}", fg=typer.colors.GREEN)
    typer.echo(
        f'\n  cd {root}\n  pip install -e ".[dev]"\n'
        "  # Fill in config.yml, then:\n"
        f"  uvicorn {package}.main:app --reload"
    )
