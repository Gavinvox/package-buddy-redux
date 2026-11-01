"""Turn 17TRACK track_info into Package Buddy-style states."""
from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone

from . import carriers

# Normalized states used by the API and the apps.
STATES = {
    "pending": "Waiting for first update",
    "info_received": "Info received",
    "in_transit": "In transit",
    "out_for_delivery": "Out for delivery",
    "delivered": "Delivered",
    "exception": "Exception",
    "not_found": "Not found",
    "expired": "Expired",
    "carrier_unsupported": "Carrier not available via 17TRACK",
}

# Numeric codes in the spirit of the original app (0 none, 1 moving, 2 delivered, 3 returned/problem).
STATE_CODE = {"pending": 0, "not_found": 0, "carrier_unsupported": 0, "expired": 0,
              "info_received": 1, "in_transit": 1, "out_for_delivery": 1, "delivered": 2, "exception": 3}

T17_MAP = {
    "NotFound": "not_found", "InfoReceived": "info_received", "InTransit": "in_transit",
    "AvailableForPickup": "out_for_delivery", "OutForDelivery": "out_for_delivery",
    "DeliveryFailure": "exception", "Exception": "exception", "Delivered": "delivered", "Expired": "expired",
}

SUB_LABELS = {
    "AvailableForPickup_Other": "Ready for pickup",
    "Exception_Returning": "Returning to sender",
    "Exception_Returned": "Returned to sender",
    "Exception_Delayed": "Delayed",
    "Exception_NoBody": "Recipient not available",
    "Exception_Security": "Held for security/customs",
    "Exception_Damage": "Damaged",
    "Exception_Rejected": "Refused",
    "Exception_Cancel": "Cancelled",
    "DeliveryFailure_Other": "Delivery attempt failed",
    "DeliveryFailure_NoBody": "Delivery attempt failed (no one home)",
    "DeliveryFailure_Security": "Delivery failed (security)",
    "DeliveryFailure_Rejected": "Delivery refused",
    "DeliveryFailure_InvalidAddress": "Delivery failed (bad address)",
    "InTransit_PickedUp": "Picked up",
    "InTransit_Departure": "Departed",
    "InTransit_Arrival": "Arrived",
    "InTransit_CustomsProcessing": "In customs",
    "InTransit_CustomsReleased": "Released by customs",
    "InTransit_CustomsRequiringInformation": "Customs needs information",
}


def _fmt_location(ev: dict) -> str | None:
    if ev.get("location"):
        return ev["location"]
    a = ev.get("address") or {}
    parts = [a.get("city"), a.get("state"), a.get("country")]
    s = ", ".join(p for p in parts if p)
    return s or None


def parse_track_info(item: dict) -> dict:
    """item = one entry of data.accepted from gettrackinfo. Returns normalized fields."""
    ti = item.get("track_info") or {}
    ls = ti.get("latest_status") or {}
    raw_status = ls.get("status") or "NotFound"
    sub = ls.get("sub_status")
    state = T17_MAP.get(raw_status, "in_transit")
    carrier_code = item.get("carrier") or None

    providers = (ti.get("tracking") or {}).get("providers") or []
    events: list[dict] = []
    pname = None
    for p in providers:
        pname = pname or (p.get("provider") or {}).get("name")
        for ev in p.get("events") or []:
            events.append({
                "time": ev.get("time_iso") or ev.get("time_utc"),
                "time_utc": ev.get("time_utc"),
                "description": ev.get("description") or ev.get("stage") or "",
                "location": _fmt_location(ev),
                "stage": ev.get("stage"),
                "sub_status": ev.get("sub_status"),
                "carrier": (p.get("provider") or {}).get("name"),
            })
    events.sort(key=lambda e: e.get("time_utc") or e.get("time") or "", reverse=True)

    le = ti.get("latest_event") or (events[0] if events else None) or {}
    tm = ti.get("time_metrics") or {}
    edd = tm.get("estimated_delivery_date") or {}
    eta = edd.get("to") or edd.get("from")

    delivered_at = None
    for m in ti.get("milestone") or []:
        if m.get("key_stage") == "Delivered" and (m.get("time_iso") or m.get("time_utc")):
            delivered_at = m.get("time_iso") or m.get("time_utc")
    if state == "delivered" and not delivered_at:
        delivered_at = le.get("time_iso") or le.get("time_utc") or le.get("time")

    note = None
    if carrier_code in carriers.NOTFOUND_MEANS_UNSUPPORTED and state == "not_found":
        state = "carrier_unsupported"
        note = carriers.LIMITED[carrier_code]

    label = SUB_LABELS.get(sub or "") or STATES[state]
    if state == "exception" and sub in ("Exception_Returned", "Exception_Returning"):
        label = SUB_LABELS[sub]
    latest_desc = le.get("description") if le else None
    days = tm.get("days_of_transit") or None

    payload_hash = hashlib.sha256(json.dumps([raw_status, sub, [e["time_utc"] or e["time"] for e in events]],
                                             sort_keys=True).encode()).hexdigest()
    return {
        "state": state,
        "status_label": label,
        "status_text": latest_desc or label,
        "sub_status": sub,
        "carrier_code": carrier_code,
        "carrier_name": pname or carriers.carrier_name(carrier_code),
        "eta": eta,
        "last_location": _fmt_location(le) if le else None,
        "last_event_time": (le.get("time_iso") or le.get("time_utc") or le.get("time")) if le else None,
        "delivered_at": delivered_at,
        "days_in_transit": days,
        "events": events,
        "events_hash": payload_hash,
        "note": note,
    }


def parse_iso(s: str | None) -> datetime | None:
    if not s:
        return None
    try:
        d = datetime.fromisoformat(s.replace("Z", "+00:00"))
        return d if d.tzinfo else d.replace(tzinfo=timezone.utc)
    except ValueError:
        return None
