"""Carrier lookup: friendly names, the full 17TRACK list, the old Package Buddy
codes, simple number-pattern detection, and "open on carrier site" links."""
from __future__ import annotations

import json
import re
from functools import lru_cache
from pathlib import Path
from urllib.parse import quote

DATA = Path(__file__).parent / "data"

# Friendly names -> 17TRACK carrier keys (same map as the Open WebUI tool v1.1.0).
ALIASES: dict[str, int] = {
    "usps": 21051, "ups": 100002, "fedex": 100003,
    "dhl": 100001, "dhl express": 100001, "dhl ecommerce": 7047, "dhl ecommerce us": 7047,
    "royal mail": 11031, "royalmail": 11031,
    "amazon": 100308, "amazon shipping": 100308, "amazon mcf": 100308, "amazon logistics": 100308,
    "amazon shipping us": 101392,
    "canada post": 3041, "canadapost": 3041, "postes canada": 3041,
    "china post": 3011, "chinapost": 3011, "china ems": 3013, "ems china": 3013, "chinaems": 3013,
    "yunexpress": 190008, "yun express": 190008, "yun": 190008,
    "4px": 190094, "4px express": 190094,
    "yanwen": 190012, "yan wen": 190012,
    "sf express": 100012, "sf": 100012, "sfexpress": 100012, "sf international": 100012,
    "sf express cn": 190766, "sf express china": 190766,
    "japan post": 10021, "japanpost": 10021, "japan ems": 10021, "ems japan": 10021, "jp post": 10021,
    "korea post": 11051, "koreapost": 11051, "kpost": 11051, "k-post": 11051, "epost": 11051,
    "korea ems": 11051, "ems korea": 11051, "k-packet": 11051, "korea post domestic": 11054,
    "chunghwa post": 20011, "chunghwapost": 20011, "taiwan post": 20011, "taiwan": 20011,
    "chunghwa post domestic": 20012, "taiwan post domestic": 20012,
}

FEATURED: dict[int, str] = {
    21051: "USPS", 100002: "UPS", 100003: "FedEx", 100001: "DHL Express", 7047: "DHL eCommerce US",
    11031: "Royal Mail", 100308: "Amazon Shipping + Amazon MCF", 101392: "Amazon Shipping (US)",
    3041: "Canada Post", 3011: "China Post", 3013: "China EMS", 190008: "YunExpress", 190094: "4PX",
    190012: "Yanwen", 100012: "SF Express (international)", 190766: "SF Express (China domestic)",
    10021: "Japan Post (incl. EMS)", 11051: "Korea Post / ePOST (incl. EMS)",
    11054: "Korea Post / ePOST (domestic)", 20011: "Chunghwa Post (Taiwan)",
    20012: "Chunghwa Post (Taiwan, domestic)",
}

# Carriers that 17TRACK currently cannot serve on the free plan (USPS refuses
# registration) or that return no data (Amazon). They are still tracked through
# 17TRACK, in case that changes, but the UI should show a clear note + link.
LIMITED: dict[int, str] = {
    21051: "USPS tracking is not available via 17TRACK right now (free plan refused by 17TRACK because of USPS policy changes).",
    100308: "Amazon does not share tracking with 17TRACK, so Amazon numbers usually show nothing here.",
    101392: "Amazon does not share tracking with 17TRACK, so Amazon numbers usually show nothing here.",
}

# Carriers where "NotFound" from 17TRACK really means "no data is shared".
NOTFOUND_MEANS_UNSUPPORTED = {100308, 101392}

# Public tracking pages (templates written for this project).
SITE_URLS: dict[int, str] = {
    21051: "https://tools.usps.com/go/TrackConfirmAction?tLabels={n}",
    100002: "https://www.ups.com/track?tracknum={n}",
    100003: "https://www.fedex.com/fedextrack/?trknbr={n}",
    100001: "https://www.dhl.com/global-en/home/tracking/tracking-express.html?submit=1&tracking-id={n}",
    7047: "https://www.dhl.com/us-en/home/tracking/tracking-ecommerce.html?submit=1&tracking-id={n}",
    11031: "https://www.royalmail.com/track-your-item#/tracking-results/{n}",
    100308: "https://track.amazon.com/tracking/{n}",
    101392: "https://track.amazon.com/tracking/{n}",
    3041: "https://www.canadapost-postescanada.ca/track-reperage/en#/search?searchFor={n}",
    10021: "https://trackings.post.japanpost.jp/services/srv/search/direct?reqCodeNo1={n}&locale=en",
    100012: "https://www.sf-international.com/us/en/dynamic_function/waybill/#search/bill-number/{n}",
}
GENERIC_URL = "https://t.17track.net/en#nums={n}"


@lru_cache
def all_carriers() -> list[dict]:
    return json.loads((DATA / "17track_carriers.json").read_text())


@lru_cache
def _by_key() -> dict[int, dict]:
    return {c["key"]: c for c in all_carriers()}


@lru_cache
def legacy_table() -> list[dict]:
    return json.loads((DATA / "legacy_carriers.json").read_text())


def carrier_name(code: int | None) -> str | None:
    if not code:
        return None
    if code in FEATURED:
        return FEATURED[code]
    c = _by_key().get(code)
    return c["name"] if c else f"Carrier {code}"


def is_known(code: int) -> bool:
    return code in FEATURED or code in _by_key()


def resolve(carrier: str | int | None) -> int | None:
    """Turn a friendly name, a 17TRACK key or an exact carrier name into a key.
    Returns None for empty/auto. Raises ValueError for unknown names."""
    if carrier is None:
        return None
    if isinstance(carrier, int):
        return carrier or None
    c = carrier.strip().lower()
    if c in ("", "auto", "none", "unknown", "0"):
        return None
    if c.isdigit():
        return int(c)
    c = " ".join(re.sub(r"\(.*?\)", " ", c).replace("_", " ").split())
    for cand in (c, c.replace("-", " "), c.replace(" ", ""), c.replace("-", "").replace(" ", "")):
        if cand in ALIASES:
            return ALIASES[cand]
    for item in all_carriers():
        if item["name"].lower() == carrier.strip().lower():
            return item["key"]
    raise ValueError(f"Unknown carrier '{carrier}'. Use GET /api/v1/carriers?q=... to find its code, or leave it empty to auto-detect.")


def search(q: str = "", include_all: bool = False, limit: int = 50) -> list[dict]:
    out: list[dict] = []
    ql = (q or "").strip().lower()
    for key, name in FEATURED.items():
        if not ql or ql in name.lower() or any(ql in a and v == key for a, v in ALIASES.items()):
            out.append({"code": key, "name": name, "featured": True, "limited": key in LIMITED})
    if include_all or ql:
        seen = {c["code"] for c in out}
        for c in all_carriers():
            if c["key"] in seen:
                continue
            if not ql or ql in c["name"].lower() or ql == str(c["key"]):
                out.append({"code": c["key"], "name": c["name"], "country": c.get("country"),
                            "featured": False, "limited": c["key"] in LIMITED})
    return out[: max(1, limit)] if limit else out


def detect(number: str, strong_only: bool = True) -> int | None:
    """Best-effort local guess from well-known number formats. None = let 17TRACK decide.
    Weak guesses (plain digit runs) are only used for links/labels, never sent to 17TRACK,
    because registering under the wrong carrier would waste quota."""
    n = number.strip().upper().replace(" ", "")
    if re.fullmatch(r"TBA\d{9,15}", n):
        return 100308
    if re.fullmatch(r"1Z[0-9A-Z]{16}", n):
        return 100002
    if re.fullmatch(r"(9[1-5]\d{20}|9[1-5]\d{24}|420\d{5}9[1-5]\d{20,24})", n):
        return 21051
    if re.fullmatch(r"[A-Z]{2}\d{9}GB", n):
        return 11031
    if re.fullmatch(r"[A-Z]{2}\d{9}CA", n):
        return 3041
    if re.fullmatch(r"[A-Z]{2}\d{9}JP", n):
        return 10021
    if re.fullmatch(r"[A-Z]{2}\d{9}KR", n):
        return 11051
    if re.fullmatch(r"[A-Z]{2}\d{9}TW", n):
        return 20011
    if re.fullmatch(r"E[A-Z]\d{9}CN", n):
        return 3013
    if re.fullmatch(r"[A-Z]{2}\d{9}CN", n):
        return 3011
    if re.fullmatch(r"YT\d{16}", n):
        return 190008
    if re.fullmatch(r"SF\d{12,13}", n):
        return 100012
    if strong_only:
        return None
    if re.fullmatch(r"\d{10}", n):
        return 100001  # DHL Express waybill
    if re.fullmatch(r"(\d{12}|\d{15}|\d{20}|\d{22})", n):
        return 100003
    return None


def site_url(code: int | None, number: str) -> str:
    tmpl = SITE_URLS.get(code or 0, GENERIC_URL)
    return tmpl.format(n=quote(number.strip(), safe=""))


def legacy_to_17track(legacy_code: str | None = None, legacy_index: int | None = None, name: str | None = None) -> int | None:
    for row in legacy_table():
        if legacy_code and row["legacy_code"] == legacy_code.strip().lower():
            return row["track17"]
    for row in legacy_table():
        if legacy_index is not None and row["legacy_index"] == legacy_index:
            return row["track17"]
    if name:
        try:
            return resolve(name)
        except ValueError:
            return None
    return None
