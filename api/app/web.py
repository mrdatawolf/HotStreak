"""Serve the built web app (web/dist) from the API, so one process does everything: `python -m app --serve`.

Development uses the Vite dev server instead (`start.py`), which proxies /api here. This is what the Windows
service runs, and what `start.py --serve` runs to try it out.
"""

import ipaddress
from pathlib import Path

from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse, PlainTextResponse
from starlette.types import ASGIApp, Receive, Scope, Send

from .config import ROOT_DIR, settings

DIST_DIR = ROOT_DIR / "web" / "dist"


def mount_web(app: FastAPI, dist: Path = DIST_DIR, allowed_hosts: list[str] | None = None) -> None:
    """Serve `dist` for every path the API doesn't handle; unknown paths get index.html (client-side routes)."""
    dist = dist.resolve()
    index = dist / "index.html"
    if not index.is_file():
        raise RuntimeError(f"{index} not found; build the web app first (python start.py --setup)")

    @app.api_route("/{path:path}", methods=["GET", "HEAD"], include_in_schema=False)
    def web(path: str):
        if path == "api" or path.startswith("api/"):
            raise HTTPException(404)  # an unknown API path stays a JSON 404, not the web app
        file = (dist / path).resolve()
        if path and file.is_file() and file.is_relative_to(dist):
            # Vite fingerprints everything under assets/, so those never change; everything else is re-checked.
            cache = "public, max-age=31536000, immutable" if path.startswith("assets/") else "no-cache"
            return FileResponse(file, headers={"Cache-Control": cache})
        return FileResponse(index, headers={"Cache-Control": "no-cache"})

    app.add_middleware(
        AllowedHosts,
        hosts=settings.web_allowed_host_list if allowed_hosts is None else allowed_hosts,
    )


class AllowedHosts:
    """The same rule the Vite dev server applies: IP addresses and localhost always work; other hostnames must be
    listed in TRACKER_WEB_ALLOWED_HOSTS. Stops DNS-rebinding pages from talking to the app."""

    def __init__(self, app: ASGIApp, hosts: list[str]):
        self.app = app
        self.hosts = {h.lower() for h in hosts}

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] in ("http", "websocket"):
            host = dict(scope["headers"]).get(b"host", b"").decode("latin-1")
            if not self.allowed(host):
                response = PlainTextResponse(
                    f"Blocked request. This host ({host!r}) is not allowed; add it to TRACKER_WEB_ALLOWED_HOSTS.",
                    status_code=403,
                )
                await response(scope, receive, send)
                return
        await self.app(scope, receive, send)

    def allowed(self, host: str) -> bool:
        name = host.lower()
        if name.startswith("["):  # [::1]:5190
            name = name[1:].split("]", 1)[0]
        elif name.count(":") == 1:
            name = name.split(":", 1)[0]
        if not name:
            return False
        if name == "localhost" or name.endswith(".localhost") or name in self.hosts:
            return True
        try:
            ipaddress.ip_address(name)
        except ValueError:
            return False
        return True
