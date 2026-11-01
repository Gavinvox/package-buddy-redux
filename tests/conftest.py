import os
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "tests"))


@pytest.fixture()
def env(tmp_path, monkeypatch):
    monkeypatch.setenv("DATA_DIR", str(tmp_path))
    monkeypatch.setenv("ADMIN_USERNAME", "admin")
    monkeypatch.setenv("ADMIN_PASSWORD", "admin-pass-123")
    monkeypatch.setenv("TRACK17_API_KEY", "test-key-not-real")
    monkeypatch.setenv("ENABLE_POLLER", "false")
    monkeypatch.setenv("REFRESH_COOLDOWN_SECONDS", "0")
    monkeypatch.setenv("WEB_DIR", str(tmp_path / "no-web-build"))  # placeholder page unless a test adds one
    from app import config
    config.reload_settings()
    return tmp_path


@pytest.fixture()
def fake():
    from fake17 import Fake17
    return Fake17()


@pytest.fixture()
def client(env, fake):
    from fastapi.testclient import TestClient
    from app import tracking
    from app.main import create_app
    tracking.set_client(fake)
    app = create_app(start_poller=False)
    with TestClient(app) as c:
        yield c
    tracking.set_client(None)


def login(c, user="admin", pw="admin-pass-123"):
    r = c.post("/api/v1/auth/login", json={"username": user, "password": pw})
    assert r.status_code == 200, r.text
    return {"Authorization": f"Bearer {r.json()['token']}"}


@pytest.fixture()
def admin_h(client):
    return login(client)


@pytest.fixture()
def make_user(client, admin_h):
    def _make(name="alice", pw="alice-pass-123", **kw):
        r = client.post("/api/v1/admin/users", json={"username": name, "password": pw, **kw}, headers=admin_h)
        assert r.status_code == 201, r.text
        return login(client, name, pw)
    return _make


def pytest_sessionstart(session):
    """The binary sample files (.sqlite, .ab) are not in git; build them from make_samples.py."""
    samples = ROOT / "samples"
    if not (samples / "sample_packagebuddy.ab").exists() or not (samples / "sample_packagebuddy_db.sqlite").exists():
        import subprocess
        subprocess.run([sys.executable, str(samples / "make_samples.py")], check=True, cwd=samples)
