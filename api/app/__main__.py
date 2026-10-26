"""Run the API on the host/port from .env:  python -m app [--reload]"""

import sys

import uvicorn

from .config import API_DIR, settings

if __name__ == "__main__":
    uvicorn.run(
        "app.main:app",
        host=settings.api_host,
        port=settings.api_port,
        reload="--reload" in sys.argv,
        reload_dirs=[str(API_DIR / "app")],
    )
