"""
Offline API docs.

FastAPI's default `/docs` pulls Swagger UI JS/CSS from a public CDN — broken in
air-gapped/intranet deploys and a third-party dependency on every page load.
Here the assets ship inside the `swagger-ui-bundle` Python package; we mount
them as static files and render Swagger UI / the OAuth2 redirect against the
local copy. No network egress, version pinned with the dependency set.
"""

from __future__ import annotations

from fastapi import FastAPI
from fastapi.openapi.docs import get_swagger_ui_html, get_swagger_ui_oauth2_redirect_html
from fastapi.responses import HTMLResponse
from fastapi.staticfiles import StaticFiles
from swagger_ui_bundle import swagger_ui_path

DOCS_URL = "/docs"
STATIC_MOUNT = "/static/swagger"
OAUTH2_REDIRECT_URL = "/docs/oauth2-redirect"


def setup_docs(app: FastAPI) -> None:
    """Disable FastAPI's CDN docs and serve Swagger UI from local assets.

    Call before `setup_dishka`; the app must be created with
    ``docs_url=None, redoc_url=None``.
    """
    app.mount(STATIC_MOUNT, StaticFiles(directory=swagger_ui_path), name="swagger")

    @app.get(DOCS_URL, include_in_schema=False)
    async def swagger_ui() -> HTMLResponse:
        return get_swagger_ui_html(
            openapi_url=app.openapi_url or "/openapi.json",
            title=f"{app.title} — API docs",
            oauth2_redirect_url=OAUTH2_REDIRECT_URL,
            swagger_js_url=f"{STATIC_MOUNT}/swagger-ui-bundle.js",
            swagger_css_url=f"{STATIC_MOUNT}/swagger-ui.css",
            swagger_favicon_url=f"{STATIC_MOUNT}/favicon-32x32.png",
        )

    @app.get(OAUTH2_REDIRECT_URL, include_in_schema=False)
    async def swagger_ui_redirect() -> HTMLResponse:
        return get_swagger_ui_oauth2_redirect_html()
    
    app.openapi_version = "3.0.2"
