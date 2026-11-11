"""Run the API.

    python -m app [--reload]   the API alone, on TRACKER_API_HOST:TRACKER_API_PORT (development, with the Vite
                               dev server in front; start.py runs both)
    python -m app --serve      the API plus the built web app (web/dist), on TRACKER_WEB_IP:TRACKER_WEB_PORT;
                               what the Windows service runs
"""

import sys

import uvicorn

from .config import API_DIR, settings

if __name__ == "__main__":
    if "--serve" in sys.argv:
        from .main import app
        from .web import mount_web

        mount_web(app)
        # Don't wait forever for open connections (TVs keep one open) when the service is stopped.
        uvicorn.run(app, host=settings.web_ip, port=settings.web_port, proxy_headers=False,
                    timeout_graceful_shutdown=5)
    else:
        uvicorn.run(
            "app.main:app",
            host=settings.api_host,
            port=settings.api_port,
            reload="--reload" in sys.argv,
            reload_dirs=[str(API_DIR / "app")],
        )
