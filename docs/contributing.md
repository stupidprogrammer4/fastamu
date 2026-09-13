# Maintaining the documentation

The site is English-only and left-to-right. Keep navigation, prose, comments and sample data in English. Put learning material under `docs/guide`, executable examples under `docs/examples`, and API signatures under `docs/reference`. Internal planning notes under `docs/plans` are excluded from the site.

## Preview locally

From the framework checkout:

```bash
python -m pip install -e '.[docs]'
python -m mkdocs serve
```

Open `http://127.0.0.1:8000`. MkDocs reloads the preview after edits. Stop an application already using that port, or use `python -m mkdocs serve -a 127.0.0.1:8001`.

## Build the static site

```bash
python -m mkdocs build --strict
```

Output goes to `site/`, which is ignored by Git. The static files can be served by a normal web server. Building does not publish or deploy them.

## Keep signatures synchronized

Reference pages show class declarations, public functions and protected extension methods; implementation bodies appear as `...`. Inherited methods remain in their base-class reference. Localized source string values are rendered using Unicode escapes.

After changing a public API:

1. Update the affected signatures in `docs/reference` to match the source.
2. Update the corresponding guide and executable examples.
3. Run the affected executable examples and application tests.
4. Run `python -m mkdocs build --strict` to validate navigation, links and snippets.

Add a reference section and navigation entry when introducing a new feature area. Check inherited contracts as well as the concrete implementation when documenting a method.

## Example conventions

Complete programs belong in source files and are included into pages with the snippets extension. Smaller fragments must state their prerequisites and identify application-defined names such as `repo` or `consume`. Use exact backend method names, return types and argument names. Do not present planned task/projection functionality as an existing API.

Execute self-contained examples directly. A passing site build does not validate the behavior of a server-dependent SQL or Elasticsearch fragment. Test those against the intended service before changing their guarantees.

## Site tooling

The theme is [Material for MkDocs](https://squidfunk.github.io/mkdocs-material/). Its official guides describe [language and direction settings](https://squidfunk.github.io/mkdocs-material/setup/changing-the-language/) and [navigation configuration](https://squidfunk.github.io/mkdocs-material/setup/setting-up-navigation/). Dependencies are isolated in the `docs` extra and are not required to run a Papilio API.
