"""Papilio command-line entry point."""

import typer

from .modules import module
from .project import new

app = typer.Typer(help="Papilio project CLI", no_args_is_help=True)
app.command()(new)
app.command()(module)
