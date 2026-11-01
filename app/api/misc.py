from __future__ import annotations

import json
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, File, HTTPException, Query, UploadFile
from fastapi.responses import JSONResponse
from sqlalchemy import select, text
from sqlalchemy.orm import Session

from .. import __version__, carriers, config, importer, tracking
from ..db import get_db
from ..models import Package, User
from .deps import current_user
from .schemas import PackageOut

router = APIRouter()
MAX_UPLOAD = 50 * 1024 * 1024


@router.get("/health", tags=["meta"], summary="Is the server OK")
def health(db: Session = Depends(get_db)):
    db.execute(text("SELECT 1"))
    return {"status": "ok", "version": __version__, "track17_key_configured": tracking.get_client().configured,
            "poll_interval_minutes": config.settings.poll_interval_minutes,
            "last_poll_finished_at": tracking.last_poll.get("finished_at")}


@router.get("/carriers", tags=["carriers"], summary="Carrier list (featured first; search the full 17TRACK list with q)")
def list_carriers(q: str = "", all: bool = Query(False, description="Include all ~3,500 17TRACK carriers"),
                  limit: int = Query(50, ge=0, le=5000)):
    return carriers.search(q, include_all=all, limit=limit)


@router.get("/carriers/detect", tags=["carriers"], summary="Guess the carrier from a tracking number")
def detect(number: str):
    n = tracking.normalize_number(number)
    strong = carriers.detect(n)
    guess = strong or carriers.detect(n, strong_only=False)
    return {"number": n, "carrier_code": guess, "carrier_name": carriers.carrier_name(guess),
            "confident": strong is not None, "limited": (guess or 0) in carriers.LIMITED,
            "note": carriers.LIMITED.get(guess or 0), "carrier_site_url": carriers.site_url(guess, n)}


async def _read(f: UploadFile) -> bytes:
    data = await f.read(MAX_UPLOAD + 1)
    if len(data) > MAX_UPLOAD:
        raise HTTPException(413, "File too large (max 50 MB)")
    return data


def _report(rep: importer.ImportReport) -> dict:
    d = rep.__dict__.copy()
    d["note"] = ("History items were imported without contacting 17TRACK. "
                 + ("Active items were registered where allowed." if rep.registered or rep.queued_or_awaiting else
                    f"{rep.would_use_quota} active item(s) are saved but not tracked yet; re-run with "
                    "track_active=true or use POST /packages/{id}/track for the ones you still need."))
    return d


@router.post("/import/xml", tags=["import/export"],
             summary="Import the old app's backup file (tracking_list_bkp.xml)")
async def import_xml(file: UploadFile = File(...),
                     track_active: bool = Query(False, description="Also register ACTIVE items with 17TRACK (uses quota). History items are never registered."),
                     dry_run: bool = Query(False, description="Only report what would happen"),
                     user: User = Depends(current_user), db: Session = Depends(get_db)):
    try:
        items = importer.parse_xml(await _read(file))
    except Exception as e:  # noqa: BLE001
        raise HTTPException(400, f"Could not read that XML file: {e}") from e
    return _report(importer.import_items(db, user, items, "import_xml", track_active, dry_run))


@router.post("/import/sqlite", tags=["import/export"],
             summary="Import the old app's database file (packagebuddy_db)")
async def import_sqlite(file: UploadFile = File(...), track_active: bool = False, dry_run: bool = False,
                        user: User = Depends(current_user), db: Session = Depends(get_db)):
    try:
        items = importer.parse_sqlite(await _read(file))
    except Exception as e:  # noqa: BLE001
        raise HTTPException(400, f"Could not read that database file: {e}") from e
    return _report(importer.import_items(db, user, items, "import_db", track_active, dry_run))


@router.post("/import/adb", tags=["import/export"],
             summary="Import an Android 'adb backup' (.ab) of the old app (unencrypted)")
async def import_adb(file: UploadFile = File(...), track_active: bool = False, dry_run: bool = False,
                     user: User = Depends(current_user), db: Session = Depends(get_db)):
    """Make the file on a computer with: `adb backup -f packagebuddy.ab com.psyrus.packagebuddy`
    (leave the backup password empty on the phone). The database inside is imported like
    `/import/sqlite`."""
    try:
        items = importer.parse_android_backup(await _read(file))
    except importer.BackupError as e:
        raise HTTPException(400, str(e)) from e
    except Exception as e:  # noqa: BLE001
        raise HTTPException(400, f"Could not read the database inside the backup: {e}") from e
    return _report(importer.import_items(db, user, items, "import_adb", track_active, dry_run))


@router.post("/import", tags=["import/export"],
             summary="Import any old-app file: backup XML, packagebuddy_db, or adb backup (.ab); detected automatically")
async def import_any(file: UploadFile = File(...), track_active: bool = False, dry_run: bool = False,
                     user: User = Depends(current_user), db: Session = Depends(get_db)):
    try:
        kind, items = importer.parse_any(await _read(file))
    except importer.BackupError as e:
        raise HTTPException(400, str(e)) from e
    except Exception as e:  # noqa: BLE001
        raise HTTPException(400, f"Could not read that file: {e}") from e
    source = {"ab": "import_adb", "sqlite": "import_db", "xml": "import_xml"}[kind]
    rep = _report(importer.import_items(db, user, items, source, track_active, dry_run))
    rep["file_type"] = {"ab": "Android backup (.ab)", "sqlite": "Package Buddy database", "xml": "Backup XML"}[kind]
    return rep


@router.get("/export", tags=["import/export"], summary="Download all my packages as JSON")
def export(user: User = Depends(current_user), db: Session = Depends(get_db)):
    rows = db.scalars(select(Package).where(Package.user_id == user.id).order_by(Package.id)).all()
    body = {"format": "packagebuddy-server-export", "version": 1,
            "exported_at": datetime.now(timezone.utc).isoformat(), "user": user.username,
            "packages": [json.loads(PackageOut.of(p, with_events=True).model_dump_json()) for p in rows]}
    fname = f"packagebuddy-export-{user.username}-{datetime.now(timezone.utc):%Y%m%d}.json"
    return JSONResponse(body, headers={"Content-Disposition": f'attachment; filename="{fname}"'})
