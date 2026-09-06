from collections.abc import Sequence


def pairs_read(value: Sequence[str]) -> list[str]:
    """Validate `<integer>:<integer>` query pairs."""
    for pair in value:
        key, separator, picked = pair.partition(":")
        if separator != ":" or not key.isdigit() or not picked.isdigit():
            raise ValueError("each pick reads as <key>:<value>")
    return list(value)


def pairs_folded(value: Sequence[str]) -> dict[int, list[int]]:
    """Group validated query pairs by their integer key."""
    folded: dict[int, list[int]] = {}
    for pair in value:
        key, _, picked = pair.partition(":")
        folded.setdefault(int(key), []).append(int(picked))
    return folded
