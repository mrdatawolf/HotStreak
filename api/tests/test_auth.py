from datetime import timedelta

from app import auth, models
from app.config import settings

from .conftest import BREAKGLASS_PASSWORD, PASSWORD, make_user, sign_in


def login(client, username, password=PASSWORD):
    return client.post("/api/auth/login", json={"username": username, "password": password})


def test_login_me_logout(client, session):
    make_user(session, "pat@example.com", name="Pat")

    res = login(client, "  PAT@example.com ")
    assert res.status_code == 200
    token = res.json()["token"]
    headers = {"Authorization": f"Bearer {token}"}
    me = client.get("/api/auth/me", headers=headers).json()
    assert me == {"user_id": me["user_id"], "name": "Pat", "email": "pat@example.com", "role": "user",
                  "is_admin": False, "is_breakglass": False}

    assert client.post("/api/auth/logout", headers=headers).status_code == 204
    assert client.get("/api/auth/me", headers=headers).status_code == 401


def test_session_token_not_stored_in_plain_text(client, session):
    make_user(session, "pat@example.com")
    token = login(client, "pat@example.com").json()["token"]
    stored = session.query(models.AuthSession).one()
    assert stored.token_hash != token and token not in stored.token_hash


def test_wrong_password_and_unknown_user_look_the_same(client, session):
    make_user(session, "pat@example.com")
    a = login(client, "pat@example.com", "nope")
    b = login(client, "ghost@example.com", "nope")
    assert a.status_code == b.status_code == 401
    assert a.json() == b.json()


def test_lockout_after_repeated_failures_and_admin_unlock(admin_client, session):
    user = make_user(session, "pat@example.com")
    for _ in range(auth.MAX_FAILED_LOGINS):
        assert login(admin_client, "pat@example.com", "wrong").status_code == 401
    # Locked now, even with the right password.
    assert login(admin_client, "pat@example.com").status_code == 429

    res = admin_client.post(f"/api/users/{user.id}/unlock")
    assert res.status_code == 200 and res.json()["locked_until"] is None
    assert login(admin_client, "pat@example.com").status_code == 200


def test_lock_expires(client, session):
    user = make_user(session, "pat@example.com")
    user.locked_until = auth.utcnow() - timedelta(seconds=1)
    session.commit()
    assert login(client, "pat@example.com").status_code == 200


def test_inactive_user_cannot_sign_in(client, session):
    user = make_user(session, "pat@example.com")
    user.active = False
    session.commit()
    assert login(client, "pat@example.com").status_code == 401


def test_expired_session_rejected(client, session):
    make_user(session, "pat@example.com")
    sign_in(client, "pat@example.com")
    session.query(models.AuthSession).one().expires_at = auth.utcnow() - timedelta(seconds=1)
    session.commit()
    assert client.get("/api/auth/me").status_code == 401


def test_breakglass_is_full_admin_with_no_user_rows(client, session):
    sign_in(client, "BreakGlass", BREAKGLASS_PASSWORD)
    me = client.get("/api/auth/me").json()
    assert me["is_breakglass"] and me["is_admin"] and me["user_id"] is None

    # First-time setup: create the first admin.
    res = client.post("/api/users", json={"name": "Owner", "email": "owner@example.com", "role": "admin",
                                          "password": "a long password"})
    assert res.status_code == 201


def test_breakglass_never_locks_out(client):
    for _ in range(auth.MAX_FAILED_LOGINS + 3):
        assert login(client, "breakglass", "wrong").status_code == 401
    assert login(client, "breakglass", BREAKGLASS_PASSWORD).status_code == 200


def test_breakglass_disabled_when_password_empty(client, monkeypatch):
    sign_in(client, "breakglass", BREAKGLASS_PASSWORD)
    monkeypatch.setattr(settings, "breakglass_password", "")
    # Existing sessions stop working and new sign-ins fail.
    assert client.get("/api/auth/me").status_code == 401
    assert login(client, "breakglass", "").status_code == 422
    assert login(client, "breakglass", BREAKGLASS_PASSWORD).status_code == 401


def test_change_own_password_signs_out_other_devices(client, session):
    make_user(session, "pat@example.com")
    other = login(client, "pat@example.com").json()["token"]
    sign_in(client, "pat@example.com")

    bad = client.post("/api/auth/password", json={"current_password": "wrong", "new_password": "new password 1"})
    assert bad.status_code == 400
    ok = client.post("/api/auth/password", json={"current_password": PASSWORD, "new_password": "new password 1"})
    assert ok.status_code == 204

    assert client.get("/api/auth/me").status_code == 200
    assert client.get("/api/auth/me", headers={"Authorization": f"Bearer {other}"}).status_code == 401
    assert login(client, "pat@example.com", "new password 1").status_code == 200


def test_permissions(client, user_client, session):
    anon = client.__class__(client.app)
    assert anon.get("/api/periods").status_code == 401
    assert anon.get("/api/reps").status_code == 401

    assert user_client.get("/api/reps").status_code == 200
    assert user_client.post("/api/reps", json={"name": "X"}).status_code == 403
    assert user_client.get("/api/users").status_code == 403
    assert user_client.get("/api/settings").json()["board_key"] is None


def test_board_key_only_opens_the_board(admin_client, session):
    key = admin_client.post("/api/settings/board-key").json()["board_key"]
    session.add(models.Period(year=2026, month=9))
    session.commit()

    tv = admin_client.__class__(admin_client.app)
    assert tv.get("/api/periods/current").status_code == 401
    tv.headers["X-Board-Key"] = key
    period = tv.get("/api/periods/current").json()
    assert tv.get(f"/api/periods/{period['id']}/board").status_code == 200
    assert tv.get("/api/auth/me").json()["role"] == "board"
    # Reports (and the rep names it filters by) are read-only, so displays get them too.
    assert tv.get("/api/reports").status_code == 200
    assert tv.get("/api/reps").status_code == 200
    assert tv.post("/api/reps", json={"name": "X"}).status_code == 401
    assert tv.get("/api/deals").status_code == 401
    assert tv.get("/api/clients").status_code == 401
    assert tv.get("/api/users").status_code == 401
    assert tv.get("/api/settings").status_code == 401

    tv.headers["X-Board-Key"] = "wrong"
    assert tv.get("/api/periods/current").status_code == 401

    # Rotating the key cuts off the old one.
    tv.headers["X-Board-Key"] = key
    admin_client.post("/api/settings/board-key")
    assert tv.get("/api/periods/current").status_code == 401
