import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.web import AllowedHosts, mount_web


@pytest.fixture
def dist(tmp_path):
    (tmp_path / "assets").mkdir()
    (tmp_path / "index.html").write_text("<html>app</html>", encoding="utf-8")
    (tmp_path / "assets" / "main-abc123.js").write_text("console.log(1)", encoding="utf-8")
    (tmp_path / "favicon.svg").write_text("<svg/>", encoding="utf-8")
    (tmp_path.parent / "secret.txt").write_text("nope", encoding="utf-8")
    return tmp_path


@pytest.fixture
def web(dist):
    app = FastAPI()

    @app.get("/api/health")
    def health():
        return {"status": "ok"}

    mount_web(app, dist, allowed_hosts=["office-pc.local"])
    return TestClient(app, base_url="http://127.0.0.1:5190")


def test_serves_files_and_index_for_client_routes(web):
    assert web.get("/").text == "<html>app</html>"
    assert web.get("/board").text == "<html>app</html>"
    assert web.get("/reports/reps?month=2026-01").text == "<html>app</html>"
    assert web.get("/favicon.svg").text == "<svg/>"
    res = web.get("/assets/main-abc123.js")
    assert res.text == "console.log(1)"
    assert "immutable" in res.headers["cache-control"]
    assert web.get("/").headers["cache-control"] == "no-cache"
    assert web.head("/assets/main-abc123.js").status_code == 200


def test_api_routes_win_and_unknown_api_paths_404(web):
    assert web.get("/api/health").json() == {"status": "ok"}
    assert web.get("/api/nope").status_code == 404
    assert web.get("/api").status_code == 404


def test_no_files_outside_dist(web):
    assert "nope" not in web.get("/../secret.txt").text
    assert "nope" not in web.get("/%2e%2e/secret.txt").text


def test_missing_build_is_an_error(tmp_path):
    with pytest.raises(RuntimeError, match="build the web app"):
        mount_web(FastAPI(), tmp_path)


@pytest.mark.parametrize("host", [
    "127.0.0.1:5190", "192.168.1.20", "localhost:5190", "tv.localhost", "[::1]:5190", "OFFICE-PC.local:5190",
])
def test_allowed_hosts(host):
    assert AllowedHosts(None, ["office-pc.local"]).allowed(host)


@pytest.mark.parametrize("host", ["", "evil.example.com", "office-pc", "evil.example.com:5190"])
def test_blocked_hosts(host):
    assert not AllowedHosts(None, ["office-pc.local"]).allowed(host)


def test_blocked_host_gets_403(web):
    res = web.get("/", headers={"host": "evil.example.com"})
    assert res.status_code == 403
    assert "TRACKER_WEB_ALLOWED_HOSTS" in res.text
