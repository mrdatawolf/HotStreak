import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app import auth, models
from app.config import settings
from app.db import Base, get_session, make_engine
from app.main import app

BREAKGLASS_PASSWORD = "test-breakglass-password"
PASSWORD = "correct horse battery"


@pytest.fixture(autouse=True)
def test_settings(monkeypatch):
    # Never depend on the developer's real .env.
    monkeypatch.setattr(settings, "breakglass_user", "breakglass")
    monkeypatch.setattr(settings, "breakglass_password", BREAKGLASS_PASSWORD)
    monkeypatch.setattr(auth.time, "sleep", lambda _s: None)
    monkeypatch.setattr(settings, "google_sheet", "")
    monkeypatch.setattr(settings, "google_credentials", "")


@pytest.fixture
def session():
    engine = make_engine("sqlite://", poolclass=StaticPool)
    Base.metadata.create_all(engine)
    with sessionmaker(bind=engine, expire_on_commit=False)() as session:
        yield session


@pytest.fixture
def client(session):
    """Signed-out client."""
    app.dependency_overrides[get_session] = lambda: session
    yield TestClient(app)
    app.dependency_overrides.clear()


def make_user(session, email, role="user", name=None):
    user = models.User(name=name or email.split("@")[0], email=email, role=role, password_hash=auth.hash_password(PASSWORD))
    session.add(user)
    session.commit()
    return user


def sign_in(client, username, password=PASSWORD):
    res = client.post("/api/auth/login", json={"username": username, "password": password})
    assert res.status_code == 200, res.text
    client.headers["Authorization"] = f"Bearer {res.json()['token']}"
    return client


@pytest.fixture
def admin_client(client, session):
    make_user(session, "admin@example.com", role="admin")
    return sign_in(client, "admin@example.com")


@pytest.fixture
def user_client(client, session):
    make_user(session, "user@example.com")
    return sign_in(client, "user@example.com")
