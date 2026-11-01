"""Import the original Package Buddy app's backup XML or its SQLite database.

Quota safety: archived/history items are NEVER registered with 17TRACK. Active
items are only registered when the caller passes track_active=True. Numbers
that are already registered on the shared 17TRACK account are linked for free.
"""
from __future__ import annotations

import io
import json
import os
import sqlite3
import tarfile
import tempfile
import zlib
from dataclasses import dataclass, field
from datetime import datetime, timezone

from defusedxml import ElementTree as ET
from sqlalchemy import select
from sqlalchemy.orm import Session

from . import carriers, tracking
from .models import Package, Shipment, User, utcnow
from .status import STATE_CODE


@dataclass
class LegacyItem:
    number: str
    description: str = ""
    legacy_carrier: str | None = None  # e.g. "ups"
    legacy_index: int | None = None
    status: str = ""
    status_code: int = 0
    receiving: bool = True
    archived: bool = False
    details: str = ""
    last_update_ms: int | None = None


@dataclass
class ImportReport:
    total: int = 0
    imported: int = 0
    skipped_duplicates: int = 0
    history: int = 0
    active: int = 0
    linked_free: int = 0
    registered: int = 0
    queued_or_awaiting: int = 0
    not_tracked: int = 0
    unmapped_carriers: list[str] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)
    would_use_quota: int = 0
    package_ids: list[int] = field(default_factory=list)


def _text(el, tag: str) -> str:
    c = el.find(tag)
    return (c.text or "").strip() if c is not None and c.text else ""


def _int(s, default=0):
    try:
        return int(str(s).strip())
    except (TypeError, ValueError):
        return default


def parse_xml(data: bytes) -> list[LegacyItem]:
    root = ET.fromstring(data)
    items: list[LegacyItem] = []
    for p in root.iter("Package"):
        num = _text(p, "TrackingNumber")
        if not num:
            continue
        lu = _int(_text(p, "LastUpdate"), 0)
        items.append(LegacyItem(
            number=num,
            description=_text(p, "Description"),
            legacy_carrier=_text(p, "Carrier") or None,
            legacy_index=_int(_text(p, "CarrierCode"), -1),
            status=_text(p, "Status"),
            status_code=_int(_text(p, "StatusCode"), 0),
            receiving=_text(p, "SendReceive") != "0",
            archived=_text(p, "Archived") in ("1", "true"),
            details=_text(p, "TrackingDetails"),
            # The old app wrote the carrier index here by mistake, so only trust real epoch values.
            last_update_ms=lu if lu > 10**11 else None,
        ))
    return items


MAX_BACKUP_TAR = 256 * 1024 * 1024  # decompressed size limit
ADB_PACKAGE = "com.psyrus.packagebuddy"
ADB_DB_PATH = f"apps/{ADB_PACKAGE}/db/packagebuddy_db"


class BackupError(ValueError):
    pass


def extract_android_backup(data: bytes) -> tuple[bytes, dict[str, bytes]]:
    """Return (packagebuddy_db bytes, side files) from an `adb backup` (.ab) file.

    Format: text header lines 'ANDROID BACKUP', version, compressed (0/1), encryption ('none'),
    then a tar archive, zlib-compressed when the flag is 1."""
    if not data.startswith(b"ANDROID BACKUP\n"):
        raise BackupError("This is not an Android backup (.ab) file.")
    parts = data.split(b"\n", 4)
    if len(parts) < 5:
        raise BackupError("The Android backup file is truncated (incomplete header).")
    _, version, compressed, encryption, payload = parts
    enc = encryption.strip().decode("ascii", "replace")
    if enc.lower() != "none":
        raise BackupError(f"This backup is encrypted ({enc}). Make the backup again and leave the "
                          "backup password empty on the phone, then import that file.")
    if compressed.strip() == b"1":
        d = zlib.decompressobj()
        try:
            payload = d.decompress(payload, MAX_BACKUP_TAR)
            if d.unconsumed_tail:
                raise BackupError("The backup is too large once decompressed (over 256 MB).")
        except zlib.error as e:
            raise BackupError(f"The backup data could not be decompressed ({e}).") from e
    elif compressed.strip() != b"0":
        raise BackupError("Unknown compression flag in the backup header.")
    if not payload:
        raise BackupError("The backup is empty. On the phone, unlock it and tap 'Back up my data' "
                          f"when adb asks, and make sure the app ({ADB_PACKAGE}) allows backups.")
    found: dict[str, bytes] = {}
    try:
        with tarfile.open(fileobj=io.BytesIO(payload), mode="r|") as tf:
            for m in tf:
                name = m.name.lstrip("./")
                if m.isfile() and name.startswith(ADB_DB_PATH) and name[len(ADB_DB_PATH):] in ("", "-wal", "-journal"):
                    f = tf.extractfile(m)
                    if f is not None:
                        found[name[len(ADB_DB_PATH):]] = f.read()
    except (tarfile.TarError, EOFError) as e:
        if "" not in found:
            raise BackupError(f"The backup archive is damaged or incomplete ({e}).") from e
    if "" not in found:
        raise BackupError(f"No Package Buddy database in this backup (looked for {ADB_DB_PATH}). "
                          f"Was it made with: adb backup -f packagebuddy.ab {ADB_PACKAGE}")
    db = found.pop("")
    return db, found


def parse_android_backup(data: bytes) -> list[LegacyItem]:
    db, extra = extract_android_backup(data)
    return parse_sqlite(db, extra)


def sniff(data: bytes) -> str:
    """'ab', 'sqlite', 'xml' or 'unknown' from the first bytes of an upload."""
    if data.startswith(b"ANDROID BACKUP\n"):
        return "ab"
    if data.startswith(b"SQLite format 3\x00"):
        return "sqlite"
    head = data[:512].lstrip(b"\xef\xbb\xbf \t\r\n")
    if head.startswith(b"<"):
        return "xml"
    return "unknown"


def parse_any(data: bytes) -> tuple[str, list[LegacyItem]]:
    kind = sniff(data)
    if kind == "ab":
        return kind, parse_android_backup(data)
    if kind == "sqlite":
        return kind, parse_sqlite(data)
    if kind == "xml":
        return kind, parse_xml(data)
    raise BackupError("Unrecognised file. Use the old app's backup XML (tracking_list_bkp.xml), its "
                      "packagebuddy_db database, or an adb backup (.ab) file.")


def parse_sqlite(data: bytes, extra: dict[str, bytes] | None = None) -> list[LegacyItem]:
    """Read the old app's packagebuddy_db. `extra` may hold '-wal'/'-journal' side files from a backup."""
    if not data.startswith(b"SQLite format 3\x00"):
        raise ValueError("This is not an SQLite database file.")
    with tempfile.TemporaryDirectory() as tmp:
        path = os.path.join(tmp, "packagebuddy_db")
        with open(path, "wb") as f:
            f.write(data)
        for suffix, blob in (extra or {}).items():
            with open(path + suffix, "wb") as f:
                f.write(blob)
        con = sqlite3.connect(path)  # a private temp copy, so a pending WAL can be applied
        con.row_factory = sqlite3.Row
        try:
            cols = {r[1] for r in con.execute("PRAGMA table_info(tracking_numbers)")}
            if not cols:
                raise ValueError("No 'tracking_numbers' table found; is this the packagebuddy_db file?")
            rows = con.execute("SELECT * FROM tracking_numbers").fetchall()
        finally:
            con.close()
    items = []
    for r in rows:
        r = dict(r)
        if "tracknum" in cols:  # current schema
            num = r.get("tracknum")
            carrier, idx = r.get("carrier"), r.get("carrier_code")
            recv, arch, det, dttm = r.get("receive"), r.get("archived"), r.get("details"), r.get("dttm")
        else:  # very old schema
            num = r.get("packageid")
            carrier, idx = None, r.get("carrier")
            recv, arch, det, dttm = r.get("notice"), r.get("autoupdate"), r.get("lastinfo"), r.get("lasttime")
        if not num:
            continue
        items.append(LegacyItem(
            number=str(num), description=str(r.get("description") or ""),
            legacy_carrier=str(carrier) if carrier else None, legacy_index=_int(idx, -1),
            status=str(r.get("status") or ""), status_code=_int(r.get("status_code"), 0),
            receiving=bool(_int(recv, 1)), archived=bool(_int(arch, 0)), details=str(det or ""),
            last_update_ms=_int(dttm, 0) if _int(dttm, 0) > 10**11 else None))
    return items


def _legacy_events(details: str) -> list[dict]:
    """Best-effort read of the old tracker response stored in TrackingDetails."""
    if not details or "<" not in details:
        return []
    try:
        root = ET.fromstring(details)
    except Exception:  # noqa: BLE001
        try:
            root = ET.fromstring(f"<Wrap>{details}</Wrap>")
        except Exception:  # noqa: BLE001
            return []
    evs = []
    for a in root.iter("Activity"):
        loc = ", ".join(x for x in (_text(a, "City"), _text(a, "State"), _text(a, "Country")) if x)
        when = " ".join(x for x in (_text(a, "Date"), _text(a, "Time")) if x)
        evs.append({"time": when or None, "time_utc": None, "description": _text(a, "Event"),
                    "location": loc or None, "stage": None, "sub_status": None, "carrier": None})
    return evs


def _legacy_state(item: LegacyItem) -> tuple[str, str | None, str | None, str | None]:
    parts = [p.strip() for p in item.status.split(" - ")]
    text = parts[0] if parts and parts[0] else None
    loc = parts[1] if len(parts) > 1 and parts[1] else None
    when = parts[2] if len(parts) > 2 and parts[2] else None
    if when and when.isdigit():  # epoch seconds or milliseconds
        v = int(when)
        when = datetime.fromtimestamp(v / 1000 if v > 10**11 else v, tz=timezone.utc).isoformat()
    if item.status_code == 2:
        state = "delivered"
    elif item.status_code == 3:
        state, text = "exception", text or "Returned"
    elif text:
        state = "in_transit"
    else:
        state = "not_found"
    return state, text, loc, when


def import_items(db: Session, user: User, items: list[LegacyItem], source: str,
                 track_active: bool = False, dry_run: bool = False) -> ImportReport:
    rep = ImportReport(total=len(items))
    existing = set(db.scalars(select(Package.tracking_number).where(Package.user_id == user.id)).all())
    to_register: list[Package] = []
    for it in items:
        number = tracking.normalize_number(it.number)
        if number in existing:
            rep.skipped_duplicates += 1
            continue
        existing.add(number)
        code = carriers.legacy_to_17track(
            it.legacy_carrier, it.legacy_index if it.legacy_index is not None and it.legacy_index >= 0 else None)
        if code is None:
            code = carriers.detect(number)
            if code is None and it.legacy_carrier:
                rep.unmapped_carriers.append(f"{number}: {it.legacy_carrier}")
        state, text, loc, when = _legacy_state(it)
        pkg = Package(user_id=user.id, tracking_number=number, carrier_code=code,
                      carrier_name=carriers.carrier_name(code), description=it.description[:500],
                      direction="receiving" if it.receiving else "sending", archived=it.archived,
                      archived_at=utcnow() if it.archived else None, tracking_mode="not_tracked",
                      source=source, state=state, status_text=text, status_code=STATE_CODE.get(state, 0),
                      last_location=loc, last_event_time=when,
                      delivered_at=when if state == "delivered" else None,
                      events_json=json.dumps(_legacy_events(it.details)),
                      note="Imported from the old Package Buddy app.")
        if it.last_update_ms:
            pkg.updated_at = datetime.fromtimestamp(it.last_update_ms / 1000, tz=timezone.utc)
        rep.imported += 1
        if it.archived:
            rep.history += 1
            rep.not_tracked += 1
            if not dry_run:
                db.add(pkg)
            continue
        rep.active += 1
        sh = db.scalar(select(Shipment).where(Shipment.number == number))
        if sh is not None and sh.registered:
            rep.linked_free += 1
            if not dry_run:
                db.add(pkg)
                db.flush()
                tracking.start_tracking(db, user, pkg)
            continue
        if state == "delivered" or not track_active:
            rep.not_tracked += 1
            if state != "delivered":
                rep.would_use_quota += 1
            if not dry_run:
                db.add(pkg)
            continue
        rep.would_use_quota += 1
        if not dry_run:
            db.add(pkg)
            to_register.append(pkg)
    if dry_run:
        return rep
    db.flush()
    for pkg in to_register:
        try:
            outcome = tracking.start_tracking(db, user, pkg)
        except Exception as e:  # noqa: BLE001
            rep.errors.append(f"{pkg.tracking_number}: {e}")
            continue
        if outcome in ("registered", "already_registered", "shared"):
            rep.registered += 1
        elif outcome in ("awaiting_approval", "limit_reached", "queued"):
            rep.queued_or_awaiting += 1
        else:
            rep.errors.append(f"{pkg.tracking_number}: {outcome} ({pkg.note or ''})")
    db.flush()
    rep.package_ids = [p.id for p in db.scalars(select(Package).where(Package.user_id == user.id,
                                                                      Package.source == source)).all()]
    return rep
