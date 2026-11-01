import json
from pathlib import Path

from app import carriers, importer
from app.status import parse_track_info
from fake17 import event, track_info

SAMPLES = Path(__file__).resolve().parents[1] / "samples"


def test_resolve_aliases():
    assert carriers.resolve("Royal Mail") == 11031
    assert carriers.resolve("ups") == 100002
    assert carriers.resolve("Japan Post (EMS)") == 10021
    assert carriers.resolve("190008") == 190008
    assert carriers.resolve("") is None
    assert carriers.resolve("Correos Spain") == 19181


def test_legacy_mapping():
    assert carriers.legacy_to_17track("usps") == 21051
    assert carriers.legacy_to_17track(None, 0) == 100003  # FedEx was index 0
    assert carriers.legacy_to_17track("japanems") == 10021
    assert carriers.legacy_to_17track("korea") == 11051
    assert carriers.legacy_to_17track("streamlite") is None


def test_status_mapping():
    p = parse_track_info(track_info("X", 100002, "AvailableForPickup", "AvailableForPickup_Other",
                                    events=[event("2026-10-20T10:00:00Z", "At pickup point")]))
    assert p["state"] == "out_for_delivery" and p["status_label"] == "Ready for pickup"
    p = parse_track_info(track_info("X", 100002, "Exception", "Exception_Returned"))
    assert p["state"] == "exception" and p["status_label"] == "Returned to sender"
    p = parse_track_info(track_info("X", 100002, "Expired", None))
    assert p["state"] == "expired"
    p = parse_track_info(track_info("TBA1", 100308, "NotFound", "NotFound_Other"))
    assert p["state"] == "carrier_unsupported" and "Amazon" in p["note"]
    p = parse_track_info(track_info("X", 100003, "NotFound", "NotFound_Other"))
    assert p["state"] == "not_found"


def test_parse_real_shape():
    """Shape copied from a real 17TRACK v2.2 response (values made up)."""
    item = {"number": "1234567890", "carrier": 100001, "track_info": {
        "latest_status": {"status": "Delivered", "sub_status": "Delivered_Other", "sub_status_descr": None},
        "latest_event": {"time_iso": "2026-10-19T14:05:00-05:00", "time_utc": "2026-10-19T19:05:00Z",
                         "description": "Delivered", "location": "SOMEWHERE - TX - USA", "stage": "Delivered"},
        "time_metrics": {"days_of_transit": 6, "estimated_delivery_date": {"source": None, "from": None, "to": None}},
        "milestone": [{"key_stage": "Delivered", "time_iso": "2026-10-19T14:05:00-05:00"}],
        "tracking": {"providers": [{"provider": {"key": 100001, "name": "DHL Express"}, "events": [
            {"time_iso": "2026-10-19T14:05:00-05:00", "time_utc": "2026-10-19T19:05:00Z", "description": "Delivered",
             "location": "SOMEWHERE - TX - USA", "stage": "Delivered"}]}]}}}
    p = parse_track_info(item)
    assert p["state"] == "delivered" and p["days_in_transit"] == 6
    assert p["carrier_name"] == "DHL Express" and p["delivered_at"] == "2026-10-19T14:05:00-05:00"


def test_parse_sample_xml():
    items = importer.parse_xml((SAMPLES / "sample_backup.xml").read_bytes())
    assert len(items) == 6
    ups = items[0]
    assert ups.legacy_carrier == "ups" and ups.legacy_index == 1 and not ups.archived and ups.receiving
    assert len(importer._legacy_events(ups.details)) == 2
    assert items[2].archived and not items[2].receiving and items[2].status_code == 2


def test_xml_entity_bomb_rejected():
    bomb = b'<?xml version="1.0"?><!DOCTYPE x [<!ENTITY a "aaaa"><!ENTITY b "&a;&a;&a;">]><PackageBuddy>&b;</PackageBuddy>'
    try:
        importer.parse_xml(bomb)
    except Exception:
        return
    raise AssertionError("entity expansion should be refused")
