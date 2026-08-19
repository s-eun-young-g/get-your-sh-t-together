"""App factory and entry point."""

from __future__ import annotations

from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.responses import RedirectResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

from . import auth, db
from .config import Settings
from .deps import age_days

PKG_DIR = Path(__file__).parent


def _seeds_dir() -> Path:
    # Repo checkout: seeds sit next to the package. Installed (e.g. in the
    # deploy container): the package lives in site-packages, so fall back to
    # the working directory.
    for candidate in (PKG_DIR.parent / "seeds", Path.cwd() / "seeds"):
        if candidate.is_dir():
            return candidate
    return PKG_DIR.parent / "seeds"


SEEDS_DIR = _seeds_dir()


def create_app(settings: Settings | None = None) -> FastAPI:
    settings = settings or Settings()

    from .services import prefs as prefs_svc

    conn = db.connect(settings.db_path)
    try:
        db.migrate(conn)
        prefs = prefs_svc.load(conn)
        from .services.workspaces import bootstrap

        bootstrap(conn, prefs)
    finally:
        conn.close()

    app = FastAPI(title="strata")
    app.state.settings = settings
    app.state.prefs = prefs

    templates = Jinja2Templates(directory=PKG_DIR / "templates")
    templates.env.filters["age_days"] = age_days
    templates.env.globals["auth_enabled"] = settings.auth_enabled
    templates.env.globals["ai_enabled"] = settings.ai_enabled
    # Same dict object as app.state.prefs; settings saves mutate it in place.
    templates.env.globals["prefs"] = prefs
    app.state.templates = templates

    app.mount("/static", StaticFiles(directory=PKG_DIR / "static"), name="static")

    @app.middleware("http")
    async def auth_gate(request: Request, call_next):
        s: Settings = request.app.state.settings
        # /api/* carries its own bearer-token auth; the cookie gate skips it.
        open_path = (
            request.url.path.startswith("/static")
            or request.url.path.startswith("/api/")
            or request.url.path == "/login"
        )
        if s.auth_enabled and not open_path:
            token = request.cookies.get(auth.COOKIE_NAME)
            if not auth.check_token(s.secret, token):
                return RedirectResponse("/login", status_code=303)
        return await call_next(request)

    from .routes import (
        api, home, learn, life, model, notion, now, pack, pause, rescue,
        settings_page, work,
    )

    app.include_router(home.router)
    app.include_router(settings_page.router)
    app.include_router(pause.router)
    app.include_router(rescue.router)
    app.include_router(now.router)
    app.include_router(work.router)
    app.include_router(life.router)
    app.include_router(pack.router)
    app.include_router(model.router)
    app.include_router(learn.router)
    app.include_router(notion.router)
    app.include_router(api.router)
    return app


def main() -> None:
    import uvicorn

    settings = Settings()
    uvicorn.run(create_app(settings), host="0.0.0.0", port=settings.port)


if __name__ == "__main__":
    main()
