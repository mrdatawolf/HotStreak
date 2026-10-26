"""Settings from the repo-root .env (shared with the web app) or TRACKER_* environment variables."""

from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict

API_DIR = Path(__file__).resolve().parents[1]
ROOT_DIR = API_DIR.parent


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=ROOT_DIR / ".env", env_prefix="TRACKER_", extra="ignore")

    api_host: str = "127.0.0.1"
    api_port: int = 8000
    web_port: int = 5190
    database_url: str = f"sqlite:///{API_DIR / 'tracker.db'}"
    # Comma-separated; defaults to the web dev server.
    cors_origins: str = ""

    # Break-glass super admin: not stored in the database, can't be disabled or locked out.
    # Leave the password empty to turn it off.
    breakglass_user: str = "breakglass"
    breakglass_password: str = ""

    session_days: int = 14

    # The client's Google Sheet (its URL or ID) and a service-account key file that can read it.
    # Relative paths are from the repo root. Sync is off until both are set.
    google_sheet: str = ""
    google_credentials: str = ""
    # How often the API pulls the sheet; 0 = only when an admin clicks "Sync now".
    google_sync_minutes: int = 5

    @property
    def google_credentials_path(self) -> Path | None:
        if not self.google_credentials:
            return None
        path = Path(self.google_credentials)
        return path if path.is_absolute() else ROOT_DIR / path

    @property
    def cors_origin_list(self) -> list[str]:
        if self.cors_origins:
            return [o.strip() for o in self.cors_origins.split(",") if o.strip()]
        return [f"http://localhost:{self.web_port}", f"http://127.0.0.1:{self.web_port}"]


settings = Settings()
