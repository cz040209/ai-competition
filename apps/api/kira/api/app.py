"""Application factory."""

from __future__ import annotations

from pathlib import Path

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles
from starlette.exceptions import HTTPException as StarletteHTTPException
from starlette.types import Scope

from kira.api.routers import auth, dashboard, transactions
from kira.config import get_settings


class SpaStaticFiles(StaticFiles):
    """Serve the built bundle, falling back to index.html for client routes.

    Mounted last, so registered /v1 routes resolve first. An unknown /v1 path
    still returns the API's JSON 404; other missing client routes return the
    app shell so a deep link does not break.
    """

    async def get_response(self, path: str, scope: Scope):
        if path == "v1" or path.startswith("v1/"):
            return JSONResponse({"detail": "Not Found"}, status_code=404)
        try:
            return await super().get_response(path, scope)
        except StarletteHTTPException as exc:
            if exc.status_code == 404:
                return await super().get_response("index.html", scope)
            raise


def create_app(*, static_dir: Path | None = None) -> FastAPI:
    settings = get_settings()
    app = FastAPI(
        title="Kira API",
        version="0.1.0",
        docs_url="/v1/docs",
        openapi_url="/v1/openapi.json",
    )
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origins,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    @app.get("/v1/health", tags=["meta"])
    async def health() -> dict[str, str]:
        return {"status": "ok"}

    app.include_router(auth.router)
    app.include_router(dashboard.router)
    app.include_router(transactions.router)

    # In the shipped image the built bundle sits beside the package. In
    # development it is absent and Vite serves the UI instead, so this is
    # conditional rather than required.
    static_dir = static_dir or Path(__file__).resolve().parents[1] / "static"
    if static_dir.is_dir():
        app.mount("/", SpaStaticFiles(directory=static_dir, html=True), name="spa")
    return app


app = create_app()
