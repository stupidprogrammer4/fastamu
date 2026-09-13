from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class <<P>>Context:
    """Everything the <<S>> logic needs to produce a result.

    Read once at the edge, then never touched again — the logic below it is a
    pure function of this context and the input.
    """
