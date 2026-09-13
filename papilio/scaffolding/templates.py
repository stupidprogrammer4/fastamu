"""Load packaged source templates."""

from collections.abc import Mapping
from importlib.resources import files


def render(template: str, values: Mapping[str, str]) -> str:
    source = files("papilio.scaffolding").joinpath("templates", template)
    text = source.read_text(encoding="utf-8")
    for name, value in values.items():
        text = text.replace(f"<<{name}>>", value)
    return text
