import json
from datetime import datetime, timedelta, timezone
from pathlib import Path

from conftest import login
from fake17 import event, track_info

SAMPLES = Path(__file__).resolve().parents[1] / "samples"
API = "/api/v1"


def add(c, h, number, **kw):
    r = c.post(f"{API}/packages", json={"tracking_number": number, **kw}, headers=h)
    assert r.status_code == 201, r.text
    return r.json()


# ------------------------------------------------------------------ basics

def test_home_and_health(client):
    r = client.get("/")
    assert r.status_code == 200 and "/docs" in r.text
    h = client.get(f"{API}/health").json()
    assert h["status"] == "ok" and h["track17_key_configured"] is True
    assert client.get("/docs").status_code == 200
    spec = client.get(f"{API}/openapi.json").json()
    assert f"{API}/packages" in spec["paths"]


def test_auth_flow(client, admin_h):
    assert client.get(f"{API}/me").status_code == 401
    me = client.get(f"{API}/me", headers=admin_h).json()
    assert me["username"] == "admin" and me["is_admin"]
    assert client.post(f"{API}/auth/login", json={"username": "admin", "password": "nope"}).status_code == 401
    # long-lived API token (e.g. for Mira)
    t = client.post(f"{API}/tokens", json={"name": "Mira"}, headers=admin_h).json()
    assert t["kind"] == "api" and t["expires_at"] is None
    th = {"Authorization": f"Bearer {t['token']}"}
    assert client.get(f"{API}/me", headers=th).status_code == 200
    assert client.get(f"{API}/me", headers={"X-API-Key": t["token"]}).status_code == 200
    toks = client.get(f"{API}/tokens", headers=admin_h).json()
    assert {x["kind"] for x in toks} == {"session", "api"}
    assert all("token" not in x for x in toks)
    assert client.delete(f"{API}/tokens/{t['id']}", headers=admin_h).status_code == 204
    assert client.get(f"{API}/me", headers=th).status_code == 401
    assert client.post(f"{API}/auth/logout", headers=admin_h).status_code == 204
    assert client.get(f"{API}/me", headers=admin_h).status_code == 401


def test_password_is_hashed(client, admin_h, env):
    import sqlite3
    con = sqlite3.connect(env / "packagebuddy.sqlite3")
    (h,) = con.execute("select password_hash from users").fetchone()
    assert h.startswith("$argon2") and "admin-pass-123" not in h


def test_admin_users_and_signup(client, admin_h, make_user):
    alice = make_user("alice")
    assert client.get(f"{API}/admin/users", headers=alice).status_code == 403
    assert client.post(f"{API}/auth/signup", json={"username": "bob", "password": "bob-pass-123"}).status_code == 403
    client.patch(f"{API}/admin/settings", json={"allow_signup": True}, headers=admin_h)
    assert client.post(f"{API}/auth/signup", json={"username": "bob", "password": "bob-pass-123"}).status_code == 201
    users = client.get(f"{API}/admin/users", headers=admin_h).json()
    assert [u["username"] for u in users] == ["admin", "alice", "bob"]
    bob = users[2]["id"]
    assert client.delete(f"{API}/admin/users/{bob}", headers=admin_h).status_code == 204
    assert client.post(f"{API}/auth/login", json={"username": "bob", "password": "bob-pass-123"}).status_code == 401


# --------------------------------------------------------------- packages

def test_add_package_registers_and_reads(client, admin_h, fake):
    fake.infos["1234567890"] = track_info("1234567890", 100001, "Delivered", "Delivered_Other",
                                          events=[event("2026-10-19T19:05:00Z", "Delivered", "Springfield", "TX", "Delivered"),
                                                  event("2026-10-14T05:28:00Z", "Picked up", "Tokyo", "JP", "PickedUp")],
                                          delivered="2026-10-19T19:05:00Z")
    out = add(client, admin_h, "1234 5678 90", carrier="dhl", description="Gift")
    assert out["outcome"] == "registered"
    p = out["package"]
    assert p["tracking_number"] == "1234567890"
    assert p["state"] == "delivered" and p["status_code"] == 2
    assert p["delivered_at"].startswith("2026-10-19") and p["event_count"] == 2
    assert p["last_location"] == "Springfield, TX"
    assert p["carrier_site_url"].startswith("https://www.dhl.com/")
    ev = client.get(f"{API}/packages/{p['id']}/events", headers=admin_h).json()
    assert ev[0]["description"] == "Delivered"
    assert fake.quota_used == 4


def test_dedupe_registers_once(client, admin_h, make_user, fake):
    alice = make_user("alice")
    add(client, admin_h, "1Z999AA10123456784")
    out = add(client, alice, "1Z999AA10123456784", description="Alice copy")
    assert out["outcome"] == "shared"
    assert fake.count("register") == 1 and fake.quota_used == 4
    # each user sees only their own list
    assert len(client.get(f"{API}/packages", headers=alice).json()) == 1
    assert client.get(f"{API}/packages", headers=alice).json()[0]["description"] == "Alice copy"
    # number already on the 17TRACK account (e.g. added by Mira): no quota
    fake.registered["TBA000000000001"] = 100308
    out = add(client, admin_h, "TBA000000000001")
    assert out["outcome"] == "already_registered" and fake.quota_used == 4


def test_amazon_and_usps_show_unsupported(client, admin_h, fake):
    out = add(client, admin_h, "TBA000000000002")
    p = out["package"]
    assert p["carrier_code"] == 100308
    assert p["state"] == "carrier_unsupported" and p["carrier_limited"]
    assert p["carrier_site_url"] == "https://track.amazon.com/tracking/TBA000000000002"
    out = add(client, admin_h, "9300100000000000000001")
    p = out["package"]
    assert out["outcome"] == "unsupported" and p["state"] == "carrier_unsupported"
    assert "tools.usps.com" in p["carrier_site_url"]
    assert "USPS" in p["note"]
    assert fake.quota_used == 4  # amazon used 1, usps refused for free


def test_save_without_tracking_and_track_later(client, admin_h, fake):
    p = add(client, admin_h, "LX123456789CN", track=False)["package"]
    assert p["tracking_mode"] == "not_tracked" and fake.count("register") == 0
    assert client.post(f"{API}/packages/{p['id']}/refresh", headers=admin_h).status_code == 409
    r = client.post(f"{API}/packages/{p['id']}/track", headers=admin_h).json()
    assert r["outcome"] == "registered" and r["package"]["carrier_code"] == 3011


def test_list_filters_patch_delete(client, admin_h):
    a = add(client, admin_h, "AAA111", track=False, description="Lamp")["package"]
    b = add(client, admin_h, "BBB222", track=False, direction="sending", description="Return")["package"]
    assert client.get(f"{API}/packages?direction=sending", headers=admin_h).json()[0]["id"] == b["id"]
    client.patch(f"{API}/packages/{a['id']}", json={"archived": True}, headers=admin_h)
    assert [p["id"] for p in client.get(f"{API}/packages?view=history", headers=admin_h).json()] == [a["id"]]
    assert [p["id"] for p in client.get(f"{API}/packages", headers=admin_h).json()] == [b["id"]]
    assert len(client.get(f"{API}/packages?view=all&q=lamp", headers=admin_h).json()) == 1
    assert client.post(f"{API}/packages", json={"tracking_number": "aaa111"}, headers=admin_h).status_code == 409
    assert client.delete(f"{API}/packages/{a['id']}", headers=admin_h).status_code == 204
    assert client.get(f"{API}/packages/{a['id']}", headers=admin_h).status_code == 404


def test_refresh_and_change_log(client, admin_h, fake):
    p = add(client, admin_h, "1Z999AA10123456784")["package"]
    assert p["state"] == "not_found"
    fake.infos["1Z999AA10123456784"] = track_info("1Z999AA10123456784", 100002, "OutForDelivery", "OutForDelivery_Other",
                                                  events=[event("2026-10-25T08:00:00Z", "Out for delivery", stage="OutForDelivery")],
                                                  eta="2026-10-25")
    r = client.post(f"{API}/packages/{p['id']}/refresh", headers=admin_h).json()
    assert r["state"] == "out_for_delivery" and r["eta"] == "2026-10-25"
    ch = client.get(f"{API}/changes", headers=admin_h).json()
    assert ch[-1]["kind"] == "status" and ch[-1]["new_state"] == "out_for_delivery"
    assert client.get(f"{API}/changes?since_id={ch[-1]['id']}", headers=admin_h).json() == []
    latest = client.get(f"{API}/changes/latest", headers=admin_h).json()
    assert latest["latest_id"] == ch[-1]["id"] and latest["poll_interval_minutes"] >= 5


def test_changes_latest_empty_and_sliding_session(client, admin_h):
    assert client.get(f"{API}/changes/latest", headers=admin_h).json()["latest_id"] == 0
    from app import db as dbm
    from app.models import ApiToken
    from app.security import aware
    with dbm.SessionLocal() as s:
        tok = s.query(ApiToken).filter_by(kind="session").first()
        tok.expires_at = datetime.now(timezone.utc) + timedelta(days=2)
        s.commit()
    assert client.get(f"{API}/me", headers=admin_h).status_code == 200
    with dbm.SessionLocal() as s:
        tok = s.query(ApiToken).filter_by(kind="session").first()
        assert aware(tok.expires_at) > datetime.now(timezone.utc) + timedelta(days=20)


# ----------------------------------------------------------- quota controls

def test_approval_mode(client, admin_h, make_user, fake):
    client.patch(f"{API}/admin/settings", json={"require_approval": True}, headers=admin_h)
    alice = make_user("alice")
    out = add(client, alice, "1Z999AA10123456784")
    assert out["outcome"] == "awaiting_approval" and fake.count("register") == 0
    pend = client.get(f"{API}/admin/approvals", headers=admin_h).json()
    assert [x["id"] for x in pend] == [out["package"]["id"]]
    r = client.post(f"{API}/admin/approvals/{pend[0]['id']}/approve", headers=admin_h).json()
    assert r["outcome"] == "registered" and r["package"]["tracking_mode"] == "tracked"
    q = client.get(f"{API}/admin/quota", headers=admin_h).json()
    assert q["server"]["quota_used_by_user"] == {"alice": 1}
    # already-registered numbers are shared without approval
    bob = make_user("bob")
    assert add(client, bob, "1Z999AA10123456784")["outcome"] == "shared"


def test_monthly_limit(client, admin_h, make_user, fake):
    alice = make_user("alice", monthly_new_limit=1)
    assert add(client, alice, "1ZAAAAAAAAAAAAAAA1")["outcome"] == "registered"
    out = add(client, alice, "1ZAAAAAAAAAAAAAAA2")
    assert out["outcome"] == "limit_reached" and out["package"]["tracking_mode"] == "awaiting_approval"
    assert fake.count("register") == 1


def test_admin_quota(client, admin_h, fake):
    q = client.get(f"{API}/admin/quota", headers=admin_h).json()
    assert q["seventeen_track"]["quota_remain"] == 197
    assert "test-key" not in json.dumps(q)


# ------------------------------------------------------------------ poller

def test_poller_batches_archive_and_stop(client, admin_h, fake):
    from app import db, tracking
    from app.models import Package
    nums = [f"1ZBATCH{i:011d}" for i in range(45)]
    for n in nums:
        assert add(client, admin_h, n)["outcome"] == "registered"  # registered by this server
    fake.calls.clear()
    old = (datetime.now(timezone.utc) - timedelta(days=10)).isoformat()
    fake.infos[nums[0]] = track_info(nums[0], 100002, "Delivered", "Delivered_Other",
                                     events=[event(old, "Delivered", stage="Delivered")], delivered=old)
    r = client.post(f"{API}/admin/poll-now", headers=admin_h).json()
    sizes = [len(a) for name, a in fake.calls if name == "gettrackinfo"]
    assert sizes == [40, 5]
    assert r["auto_archived"] == 1 and r["stopped"] == 1
    assert fake.stopped == {nums[0]}
    hist = client.get(f"{API}/packages?view=history", headers=admin_h).json()
    assert [p["tracking_number"] for p in hist] == [nums[0]]
    # stopped numbers are no longer polled
    fake.calls.clear()
    client.post(f"{API}/admin/poll-now", headers=admin_h)
    polled = {n for name, a in fake.calls if name == "gettrackinfo" for n, _ in a}
    assert nums[0] not in polled and len(polled) == 44
    # restoring from history restarts tracking once
    client.patch(f"{API}/packages/{hist[0]['id']}", json={"archived": False}, headers=admin_h)
    assert fake.count("retrack") == 1


def test_poller_registers_queued_and_retries_unsupported(client, admin_h, fake, monkeypatch):
    from app import config
    out = add(client, admin_h, "9300100000000000000001")
    assert out["outcome"] == "unsupported"
    client.post(f"{API}/admin/poll-now", headers=admin_h)
    assert fake.count("register") == 1  # not retried before RETRY_UNSUPPORTED_HOURS
    monkeypatch.setattr(config.settings, "retry_unsupported_hours", 0)
    fake.policy_blocked = set()  # 17TRACK "fixed" USPS
    client.post(f"{API}/admin/poll-now", headers=admin_h)
    assert fake.count("register") == 2
    p = client.get(f"{API}/packages/{out['package']['id']}", headers=admin_h).json()
    assert p["state"] == "not_found" and p["tracking_mode"] == "tracked"


def test_delete_last_owner_stops_tracking(client, admin_h, fake):
    p = add(client, admin_h, "1Z999AA10123456784")["package"]
    client.delete(f"{API}/packages/{p['id']}", headers=admin_h)
    client.post(f"{API}/admin/poll-now", headers=admin_h)
    assert fake.stopped == {"1Z999AA10123456784"}
    assert fake.count("deletetrack") == 0


# ----------------------------------------------------------- import/export

def _upload(c, h, path, url):
    with open(path, "rb") as f:
        return c.post(url, files={"file": (path.name, f, "application/octet-stream")}, headers=h)


def test_import_xml_history_never_registers(client, admin_h, fake):
    r = _upload(client, admin_h, SAMPLES / "sample_backup.xml", f"{API}/import/xml")
    assert r.status_code == 200, r.text
    rep = r.json()
    assert rep["total"] == 6 and rep["imported"] == 6
    assert rep["history"] == 4 and rep["active"] == 2
    assert rep["registered"] == 0 and rep["would_use_quota"] == 2
    assert fake.count("register") == 0
    allp = {p["tracking_number"]: p for p in client.get(f"{API}/packages?view=all", headers=admin_h).json()}
    ups = allp["1ZTEST0000000000A1"]
    assert ups["carrier_code"] == 100002 and ups["state"] == "in_transit" and ups["event_count"] == 2
    assert ups["last_location"] == "Springfield, IL" and ups["tracking_mode"] == "not_tracked"
    assert allp["SAMPLEDHL01"]["archived"] and allp["SAMPLEDHL01"]["direction"] == "sending"
    assert allp["SAMPLEDHL01"]["state"] == "delivered" and allp["SAMPLEDHL01"]["carrier_code"] == 100001
    assert allp["RR000000000GB"]["carrier_code"] == 11031
    assert allp["SAMPLEFEDEX1"]["state"] == "exception" and allp["SAMPLEFEDEX1"]["carrier_code"] == 100003
    assert allp["TBA000000000001"]["carrier_code"] == 100308
    # re-import skips duplicates
    rep2 = _upload(client, admin_h, SAMPLES / "sample_backup.xml", f"{API}/import/xml").json()
    assert rep2["skipped_duplicates"] == 6 and rep2["imported"] == 0


def test_import_xml_track_active_only(client, admin_h, fake):
    r = _upload(client, admin_h, SAMPLES / "sample_backup.xml", f"{API}/import/xml?track_active=true").json()
    regs = [n for name, a in fake.calls if name == "register" for n, _ in a]
    assert sorted(regs) == ["1ZTEST0000000000A1", "TBA000000000001"]
    assert r["registered"] == 2


def test_import_dry_run_and_sqlite(client, admin_h, fake):
    rep = _upload(client, admin_h, SAMPLES / "sample_backup.xml", f"{API}/import/xml?dry_run=true").json()
    assert rep["imported"] == 6 and client.get(f"{API}/packages?view=all", headers=admin_h).json() == []
    rep = _upload(client, admin_h, SAMPLES / "sample_packagebuddy_db.sqlite", f"{API}/import/sqlite").json()
    assert rep["imported"] == 6 and rep["history"] == 4 and fake.count("register") == 0
    allp = {p["tracking_number"]: p for p in client.get(f"{API}/packages?view=all", headers=admin_h).json()}
    assert allp["1ZTEST0000000000A1"]["event_count"] == 2


def test_import_links_already_registered_for_free(client, admin_h, fake):
    fake.registered["1ZTEST0000000000A1"] = 100002
    add(client, admin_h, "1ZTEST0000000000A1")  # someone already tracks it on the server
    from conftest import login as _l  # noqa
    client.post(f"{API}/admin/users", json={"username": "carl", "password": "carl-pass-123"}, headers=admin_h)
    carl = login(client, "carl", "carl-pass-123")
    rep = _upload(client, carl, SAMPLES / "sample_backup.xml", f"{API}/import/xml").json()
    assert rep["linked_free"] == 1 and fake.quota_used == 3


def test_bad_import_file(client, admin_h):
    r = client.post(f"{API}/import/xml", files={"file": ("x.xml", b"not xml", "text/xml")}, headers=admin_h)
    assert r.status_code == 400


def test_export(client, admin_h):
    add(client, admin_h, "AAA111", track=False, description="Lamp")
    r = client.get(f"{API}/export", headers=admin_h)
    assert r.status_code == 200 and "attachment" in r.headers["content-disposition"]
    body = r.json()
    assert body["format"] == "packagebuddy-server-export" and body["packages"][0]["description"] == "Lamp"


# ---------------------------------------------------------------- carriers

def test_carriers(client):
    feat = client.get(f"{API}/carriers").json()
    assert {c["code"] for c in feat} >= {21051, 100002, 100003, 100001, 11031, 100308, 3041, 10021, 11051, 20011}
    assert any(c["name"] == "Correos Spain" for c in client.get(f"{API}/carriers?q=correos").json())
    assert len(client.get(f"{API}/carriers?all=true&limit=0").json()) > 3000
    d = client.get(f"{API}/carriers/detect?number=TBA000000000001").json()
    assert d["carrier_code"] == 100308 and d["limited"] and d["confident"]
    d = client.get(f"{API}/carriers/detect?number=1234567890").json()
    assert d["carrier_code"] == 100001 and not d["confident"]
    assert client.post(f"{API}/packages", json={"tracking_number": "X1234", "carrier": "nonsense carrier"},
                       headers=login(client)).status_code == 422


def test_sync_account_avoids_register_calls(client, admin_h, fake):
    for i in range(45):
        fake.registered[f"NUM{i:05d}"] = 100001
    fake.registered["TBA000000000001"] = 100308
    r = client.post(f"{API}/admin/sync-account", headers=admin_h).json()
    assert r == {"numbers_on_account": 46, "new_to_server": 46}
    out = add(client, admin_h, "TBA000000000001")
    assert out["outcome"] == "shared" and fake.count("register") == 0
    assert out["package"]["state"] == "carrier_unsupported"


def test_disable_registration_switch(client, admin_h, fake, monkeypatch):
    from app import config
    monkeypatch.setattr(config.settings, "disable_registration", True)
    out = add(client, admin_h, "1Z999AA10123456784")
    assert out["outcome"] == "registration_disabled" and fake.count("register") == 0
    client.post(f"{API}/admin/poll-now", headers=admin_h)
    assert fake.count("register") == 0


# ----------------------------------------------------------- adb backup (.ab) import

def _ab(**kw):
    import sys
    sys.path.insert(0, str(SAMPLES))
    from make_samples import android_backup
    return android_backup((SAMPLES / "sample_packagebuddy_db.sqlite").read_bytes(), **kw)


def test_import_adb_compressed_and_plain(client, admin_h, fake):
    rep = _upload(client, admin_h, SAMPLES / "sample_packagebuddy.ab", f"{API}/import/adb?dry_run=true").json()
    assert rep["total"] == 6 and rep["history"] == 4 and rep["would_use_quota"] == 2
    assert client.get(f"{API}/packages?view=all", headers=admin_h).json() == []
    r = client.post(f"{API}/import/adb", files={"file": ("b.ab", _ab(compressed=False), "application/octet-stream")},
                    headers=admin_h).json()
    assert r["imported"] == 6 and r["registered"] == 0 and fake.count("register") == 0
    pk = client.get(f"{API}/packages?view=all", headers=admin_h).json()
    assert {p["source"] for p in pk} == {"import_adb"}
    assert all(p["tracking_mode"] == "not_tracked" for p in pk)


def test_import_adb_rejects_encrypted_and_foreign(client, admin_h):
    r = client.post(f"{API}/import/adb", files={"file": ("e.ab", _ab(encrypted=True), "application/octet-stream")},
                    headers=admin_h)
    assert r.status_code == 400 and "encrypted" in r.json()["detail"]
    import io, tarfile, zlib
    buf = io.BytesIO()
    with tarfile.open(fileobj=buf, mode="w") as tf:
        ti = tarfile.TarInfo("apps/com.other.app/db/x.db")
        ti.size = 3
        tf.addfile(ti, io.BytesIO(b"abc"))
    other = b"ANDROID BACKUP\n5\n1\nnone\n" + zlib.compress(buf.getvalue())
    r = client.post(f"{API}/import/adb", files={"file": ("o.ab", other, "application/octet-stream")}, headers=admin_h)
    assert r.status_code == 400 and "No Package Buddy database" in r.json()["detail"]
    r = client.post(f"{API}/import/adb", files={"file": ("x.ab", b"hello", "application/octet-stream")}, headers=admin_h)
    assert r.status_code == 400 and "not an Android backup" in r.json()["detail"]
    empty = b"ANDROID BACKUP\n5\n1\nnone\n" + zlib.compress(b"")
    r = client.post(f"{API}/import/adb", files={"file": ("z.ab", empty, "application/octet-stream")}, headers=admin_h)
    assert r.status_code == 400 and "empty" in r.json()["detail"]


def test_import_auto_detects_type(client, admin_h, fake):
    for name, kind in (("sample_packagebuddy.ab", "Android backup (.ab)"), ("sample_backup.xml", "Backup XML"),
                       ("sample_packagebuddy_db.sqlite", "Package Buddy database")):
        rep = _upload(client, admin_h, SAMPLES / name, f"{API}/import?dry_run=true").json()
        assert rep["file_type"] == kind and rep["total"] == 6
    r = client.post(f"{API}/import", files={"file": ("x.bin", b"\x00\x01junk", "application/octet-stream")}, headers=admin_h)
    assert r.status_code == 400 and "Unrecognised" in r.json()["detail"]


def test_refresh_all_is_batched_and_free(client, admin_h, fake):
    add(client, admin_h, "1Z999AA10123456784")
    add(client, admin_h, "1Z999AA10123456785", track=False)
    before = fake.count("register")
    r = client.post(f"{API}/packages/refresh", headers=admin_h).json()
    assert r["checked"] + r["skipped_recent"] == 1
    assert fake.count("register") == before


def test_web_app_served_at_root(env, fake, tmp_path, monkeypatch):
    from fastapi.testclient import TestClient
    from app import config, tracking
    from app.main import create_app
    web = tmp_path / "web"
    (web / "assets").mkdir(parents=True)
    (web / "index.html").write_text("<html><body>flutter app</body></html>")
    (web / "main.dart.js").write_text("console.log(1)")
    monkeypatch.setenv("WEB_DIR", str(web))
    config.reload_settings()
    tracking.set_client(fake)
    with TestClient(create_app(start_poller=False)) as c:
        r = c.get("/")
        assert r.status_code == 200 and "flutter app" in r.text and r.headers["cache-control"] == "no-cache"
        assert c.get("/main.dart.js").text == "console.log(1)"
        assert c.get("/api/v1/health").json()["status"] == "ok"
        assert c.get("/docs").status_code == 200
        assert c.get("/api/v1/openapi.json").status_code == 200
        assert c.get("/api/v1/nope").status_code == 404
    tracking.set_client(None)


def test_poller_never_stops_numbers_it_did_not_register(client, admin_h, fake):
    """Numbers already on the shared account (e.g. added by Mira) must never get stoptrack/retrack."""
    from app import db, tracking
    fake.registered["9876543210"] = 100001
    fake.registered["TBA000000000001"] = 100308
    fake.infos["9876543210"] = track_info("9876543210", 100001, "Delivered", "Delivered_Other",
                                          events=[event("2026-10-10T10:00:00Z", "Delivered", stage="Delivered")],
                                          delivered="2026-10-10T10:00:00Z")
    client.post(f"{API}/admin/sync-account", headers=admin_h)
    with db.session_scope() as d:
        r = tracking.poll_once(d)  # no packages yet: an old version stopped all synced numbers here
    assert r["stopped"] == 0 and fake.count("stoptrack") == 0
    p = add(client, admin_h, "9876543210")["package"]
    client.patch(f"{API}/packages/{p['id']}", json={"archived": True}, headers=admin_h)
    client.delete(f"{API}/packages/{p['id']}", headers=admin_h)
    with db.session_scope() as d:
        r = tracking.poll_once(d)
    assert r["stopped"] == 0 and fake.count("stoptrack") == 0 and fake.count("retrack") == 0
