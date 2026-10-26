"""Write the API's OpenAPI spec to web/openapi.json for the frontend's type generator.

Usage (from api/):  python -m scripts.export_openapi
"""

import json
from pathlib import Path

from app.main import app

OUT = Path(__file__).resolve().parents[2] / "web" / "openapi.json"

if __name__ == "__main__":
    OUT.write_text(json.dumps(app.openapi(), indent=2) + "\n")
    print(f"Wrote {OUT}")
