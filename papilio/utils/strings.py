"""Lightweight English string helpers (no external deps)."""

import re

_VOWELS = ("a", "e", "i", "o", "u")


def snake_case(name: str) -> str:
    """Separate CamelCase words while keeping acronyms together."""
    name = re.sub(r"([A-Z]+)([A-Z][a-z])", r"\1_\2", name)
    return re.sub(r"([a-z0-9])([A-Z])", r"\1_\2", name).lower()


def pluralize(word: str) -> str:
    """Pluralise a single lowercase English word with simple heuristics.

    Covers the regular cases this codebase needs (category -> categories,
    box -> boxes, product -> products); it is intentionally not a full
    inflection engine. Override ``__tablename__`` for irregular nouns.
    """
    result = word + "s"
    if not word:
        result = word
    elif word.endswith(("s", "x", "z", "ch", "sh")):
        result = word + "es"
    elif word.endswith("y") and word[-2:-1] not in _VOWELS:
        result = word[:-1] + "ies"
    return result
