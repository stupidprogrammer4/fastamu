"""Shared Elasticsearch analyzers.

Assign these to `Text` fields (``Text(analyzer=persian_analyzer)``);
`elasticsearch.dsl` collects their definitions into the index settings on
``Document.init()`` — no manual registration needed.
"""

from elasticsearch.dsl import analyzer, char_filter, token_filter

_persian_zwnj = char_filter(
    "persian_zwnj",
    type="mapping",
    mappings=["\\u200C=>\\u0020"],
)

_persian_stop = token_filter(
    "persian_stop",
    type="stop",
    stopwords="_persian_",
)

persian_analyzer = analyzer(
    "persian",
    char_filter=[_persian_zwnj],
    tokenizer="standard",
    filter=[
        "lowercase",
        "decimal_digit",
        "arabic_normalization",
        "persian_normalization",
        _persian_stop,
    ],
)
