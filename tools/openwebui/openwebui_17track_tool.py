"""
title: Package Tracker (17TRACK)
author: Gavinvox
description: Lets the model track parcels (USPS, UPS, FedEx, DHL, Royal Mail, Amazon, Canada Post, China Post/EMS, YunExpress, 4PX, Yanwen, SF Express, Japan Post, Korea Post, Chunghwa Post, and more) through the 17TRACK API, check your 17TRACK quota, and troubleshoot 17TRACK errors.
required_open_webui_version: 0.6.0
version: 1.1.0
licence: MIT
"""

# Uses only the Python standard library (urllib), so nothing extra has to be
# installed inside the Open WebUI container.

import asyncio
import json
import re
import urllib.error
import urllib.request
from typing import Any, Callable, Optional

from pydantic import BaseModel, Field

# Friendly names -> 17TRACK carrier codes (checked against 17TRACK's carrier list).
CARRIERS = {
    "usps": 21051,
    "ups": 100002,
    "fedex": 100003,
    "dhl": 100001,
    "dhl express": 100001,
    "dhl ecommerce": 7047,
    "dhl ecommerce us": 7047,
    "royal mail": 11031,
    "royalmail": 11031,
    "amazon": 100308,
    "amazon shipping": 100308,
    "amazon mcf": 100308,
    "amazon logistics": 100308,
    "amazon shipping us": 101392,
    # Canada
    "canada post": 3041, "canadapost": 3041, "postes canada": 3041,
    # China (17TRACK keeps China Post and China EMS separate)
    "china post": 3011, "chinapost": 3011, "china ems": 3013, "ems china": 3013, "chinaems": 3013,
    "yunexpress": 190008, "yun express": 190008, "yun": 190008,
    "4px": 190094, "4px express": 190094,
    "yanwen": 190012, "yan wen": 190012,
    "sf express": 100012, "sf": 100012, "sfexpress": 100012, "sf international": 100012,
    "sf express cn": 190766, "sf express china": 190766,
    # Japan (one code covers Japan Post parcels, registered mail and EMS)
    "japan post": 10021, "japanpost": 10021, "japan ems": 10021, "ems japan": 10021, "jp post": 10021,
    # Korea (one ePOST code covers international mail, K-Packet and EMS)
    "korea post": 11051, "koreapost": 11051, "kpost": 11051, "k-post": 11051, "epost": 11051,
    "korea ems": 11051, "ems korea": 11051, "k-packet": 11051,
    "korea post domestic": 11054,
    # Taiwan
    "chunghwa post": 20011, "chunghwapost": 20011, "taiwan post": 20011, "taiwan": 20011,
    "chunghwa post domestic": 20012, "taiwan post domestic": 20012,
}
CARRIER_NAMES = {
    21051: "USPS",
    100002: "UPS",
    100003: "FedEx",
    100001: "DHL Express",
    7047: "DHL eCommerce US",
    11031: "Royal Mail",
    100308: "Amazon Shipping + Amazon MCF",
    101392: "Amazon Shipping (US)",
    3041: "Canada Post",
    3011: "China Post",
    3013: "China EMS",
    190008: "YunExpress",
    190094: "4PX",
    190012: "Yanwen",
    100012: "SF Express (international)",
    190766: "SF Express (China domestic)",
    10021: "Japan Post (incl. EMS)",
    11051: "Korea Post / ePOST (incl. EMS)",
    11054: "Korea Post / ePOST (domestic)",
    20011: "Chunghwa Post (Taiwan)",
    20012: "Chunghwa Post (Taiwan, domestic)",
}

MAIN_NAMES = (
    "usps, ups, fedex, dhl (express), dhl ecommerce, royal mail, amazon, amazon shipping us, "
    "canada post, china post, china ems, yunexpress, 4px, yanwen, sf express, sf express cn, "
    "japan post (incl. EMS), korea post (incl. EMS), chunghwa post (Taiwan)"
)

NOT_REGISTERED = -18019902
ALREADY_REGISTERED = -18019901


class Tools:
    class Valves(BaseModel):
        API_KEY: str = Field(
            default="",
            description="Your 17TRACK API key (the '17token' from api.17track.net > Settings / Security).",
        )
        API_BASE_URL: str = Field(
            default="https://api.17track.net/track/v2.2/",
            description="17TRACK API address. Leave as is unless 17TRACK tells you to change the version.",
        )
        AUTO_REGISTER: bool = Field(
            default=True,
            description="If on, track_package registers numbers it has never seen (uses 1 quota each). Turn off to protect your free quota.",
        )
        MAX_EVENTS: int = Field(
            default=15,
            description="How many tracking events to show in a timeline.",
        )
        TIMEOUT_SECONDS: int = Field(
            default=30, description="How long to wait for 17TRACK before giving up."
        )

    def __init__(self):
        self.valves = self.Valves()

    # ------------------------------------------------------------------ helpers
    # (names start with "_" so Open WebUI does not show them to the model)

    def _post_sync(self, endpoint: str, body: Any) -> dict:
        key = (self.valves.API_KEY or "").strip()
        if not key:
            return {"_local_error": "No 17TRACK API key is set. Open Workspace > Tools, click the gear icon next to 'Package Tracker (17TRACK)', and paste your key into API_KEY."}
        url = self.valves.API_BASE_URL.rstrip("/") + "/" + endpoint
        req = urllib.request.Request(
            url,
            data=json.dumps(body).encode("utf-8"),
            headers={"17token": key, "Content-Type": "application/json", "User-Agent": "OpenWebUI-17TRACK-Tool/1.0"},
            method="POST",
        )
        try:
            with urllib.request.urlopen(req, timeout=self.valves.TIMEOUT_SECONDS) as resp:
                return json.loads(resp.read().decode("utf-8"))
        except urllib.error.HTTPError as e:
            detail = e.read().decode("utf-8", "replace")[:500]
            return {"_local_error": f"17TRACK answered HTTP {e.code} {e.reason}. Body: {detail}"}
        except urllib.error.URLError as e:
            return {"_local_error": f"Could not reach api.17track.net ({e.reason}). The Open WebUI container may have no internet access, or DNS is failing."}
        except Exception as e:  # noqa: BLE001
            return {"_local_error": f"Unexpected error talking to 17TRACK: {type(e).__name__}: {e}"}

    async def _post(self, endpoint: str, body: Any) -> dict:
        return await asyncio.to_thread(self._post_sync, endpoint, body)

    async def _status(self, emitter: Optional[Callable], text: str, done: bool = False):
        if emitter:
            try:
                await emitter({"type": "status", "data": {"description": text, "done": done}})
            except Exception:  # noqa: BLE001
                pass

    @staticmethod
    def _carrier_code(carrier: str) -> tuple[Optional[int], Optional[str]]:
        """Returns (code, error). Empty carrier -> (None, None) = auto-detect."""
        c = (carrier or "").strip().lower()
        if not c or c in ("auto", "none", "unknown"):
            return None, None
        if c.lstrip("-").isdigit():
            return int(c), None
        c = " ".join(re.sub(r"\(.*?\)", " ", c).replace("_", " ").split())
        for cand in (c, c.replace("-", " "), c.replace(" ", ""), c.replace("-", "").replace(" ", "")):
            if cand in CARRIERS:
                return CARRIERS[cand], None
        return None, f"Unknown carrier '{carrier}'. Use one of: {MAIN_NAMES}; or a numeric 17TRACK carrier code; or leave carrier empty to auto-detect."

    @staticmethod
    def _carrier_label(code: Any) -> str:
        try:
            code = int(code)
        except (TypeError, ValueError):
            return str(code)
        return f"{CARRIER_NAMES.get(code, 'carrier')} (code {code})" if code else "not detected yet (code 0)"

    @staticmethod
    def _api_problem(resp: dict) -> Optional[str]:
        """Whole-request failure (bad key, network, etc.), quoted verbatim."""
        if "_local_error" in resp:
            return "ERROR: " + resp["_local_error"]
        if resp.get("code", 0) != 0:
            data = resp.get("data")
            errs = data.get("errors") if isinstance(data, dict) else None
            msg = "; ".join(f"code {e.get('code')}: {e.get('message')}" for e in (errs or [])) or json.dumps(resp)[:500]
            return f"17TRACK rejected the request (top-level code {resp.get('code')}): {msg}"
        return None

    @staticmethod
    def _rejections(resp: dict) -> list[str]:
        out = []
        for r in (resp.get("data") or {}).get("rejected") or []:
            err = r.get("error") or {}
            out.append(f"{r.get('number')}: 17TRACK error {err.get('code')}: {err.get('message')}")
        return out

    @staticmethod
    def _fmt_event(ev: dict) -> str:
        when = (ev.get("time_iso") or ev.get("time_utc") or "time unknown")
        when = when.replace("T", " ")[:16] if isinstance(when, str) else when
        where = ev.get("location") or ""
        if not where:
            a = ev.get("address") or {}
            where = ", ".join(x for x in (a.get("city"), a.get("state"), a.get("country")) if x)
        desc = ev.get("description") or ev.get("stage") or "(no description)"
        return f"{when} - {desc}" + (f" [{where}]" if where else "")

    def _fmt_trackinfo(self, item: dict) -> str:
        number = item.get("number")
        ti = item.get("track_info") or {}
        ls = ti.get("latest_status") or {}
        lines = [f"Tracking number: {number}"]
        providers = (ti.get("tracking") or {}).get("providers") or []
        pname = providers[0].get("provider", {}).get("name") if providers else None
        lines.append(f"Carrier: {pname or self._carrier_label(item.get('carrier'))} (17TRACK code {item.get('carrier')})")
        status = ls.get("status") or "Unknown"
        sub = ls.get("sub_status") or ""
        descr = ls.get("sub_status_descr")
        lines.append(f"Status: {status}" + (f" / {sub}" if sub else "") + (f" ({descr})" if descr else ""))
        tm = ti.get("time_metrics") or {}
        edd = tm.get("estimated_delivery_date") or {}
        if edd.get("from") or edd.get("to"):
            rng = " to ".join(x for x in (edd.get("from"), edd.get("to")) if x)
            lines.append(f"Estimated delivery: {rng}" + (f" (source: {edd.get('source')})" if edd.get("source") else ""))
        else:
            lines.append("Estimated delivery: not provided")
        if tm.get("days_of_transit"):
            lines.append(f"Days in transit: {tm.get('days_of_transit')}")
        le = ti.get("latest_event")
        lines.append("Latest event: " + (self._fmt_event(le) if le else "none yet"))
        events = []
        for p in providers:
            events.extend(p.get("events") or [])
        if events:
            cap = max(1, int(self.valves.MAX_EVENTS))
            lines.append(f"Timeline (newest first, {min(cap, len(events))} of {len(events)} events):")
            lines += ["  - " + self._fmt_event(e) for e in events[:cap]]
        else:
            lines.append("Timeline: no events returned by the carrier.")
            sync = [f"{p.get('provider', {}).get('name')}: last sync {p.get('latest_sync_status')} at {p.get('latest_sync_time')}" for p in providers]
            if sync:
                lines.append("Carrier sync info: " + "; ".join(sync))
            if status == "NotFound":
                lines.append("Hint: NotFound means 17TRACK asked the carrier and got nothing back. The number may be too new, the carrier may be wrong (see change_carrier), or the carrier does not share data with 17TRACK (common for Amazon TBA numbers).")
        return "\n".join(lines)

    # -------------------------------------------------------------- tools

    async def track_package(self, tracking_number: str, carrier: str = "", __event_emitter__: Optional[Callable] = None) -> str:
        """
        Find out where a package is. Use this first for any "where is my package / track this number" request.
        Free if the number is already tracked. If it is new, it registers it, which uses 1 of the limited 17TRACK quota.
        :param tracking_number: The tracking number exactly as the user gave it.
        :param carrier: Optional. One of: usps, ups, fedex, dhl, dhl ecommerce, royal mail, amazon, canada post, china post, china ems, yunexpress, 4px, yanwen, sf express, japan post, korea post, chunghwa post. Leave empty to auto-detect.
        """
        number = tracking_number.strip().replace(" ", "")
        code, err = self._carrier_code(carrier)
        if err:
            return err
        await self._status(__event_emitter__, f"Checking {number} with 17TRACK...")
        q = {"number": number}
        if code:
            q["carrier"] = code
        resp = await self._post("gettrackinfo", [q])
        problem = self._api_problem(resp)
        if problem:
            await self._status(__event_emitter__, "17TRACK error", True)
            return problem
        accepted = (resp.get("data") or {}).get("accepted") or []
        if accepted:
            await self._status(__event_emitter__, "Done", True)
            return "\n\n".join(self._fmt_trackinfo(a) for a in accepted)

        rej = (resp.get("data") or {}).get("rejected") or []
        not_registered = any((r.get("error") or {}).get("code") == NOT_REGISTERED for r in rej)
        if not not_registered:
            await self._status(__event_emitter__, "17TRACK error", True)
            return "17TRACK could not return tracking info:\n" + "\n".join(self._rejections(resp))
        if not self.valves.AUTO_REGISTER:
            await self._status(__event_emitter__, "Not registered", True)
            return (f"{number} is not registered with 17TRACK yet, and automatic registration is turned off "
                    "(AUTO_REGISTER valve). Ask the user whether to call register_package, which uses 1 quota.")

        await self._status(__event_emitter__, f"Registering {number} (uses 1 quota)...")
        reg_text, ok = await self._register(number, code)
        if not ok:
            await self._status(__event_emitter__, "Registration rejected", True)
            return reg_text
        for attempt in range(4):
            await self._status(__event_emitter__, f"Waiting for the carrier's data (try {attempt + 1}/4)...")
            await asyncio.sleep(4)
            resp = await self._post("gettrackinfo", [q])
            accepted = (resp.get("data") or {}).get("accepted") or []
            if accepted:
                ti = accepted[0].get("track_info") or {}
                if (ti.get("latest_status") or {}).get("status") not in (None, "NotFound") or attempt == 3:
                    await self._status(__event_emitter__, "Done", True)
                    return reg_text + "\n\n" + "\n\n".join(self._fmt_trackinfo(a) for a in accepted)
        await self._status(__event_emitter__, "Registered, results pending", True)
        return reg_text + "\n17TRACK has not returned results yet. This can take up to a few minutes; ask again shortly with get_tracking_info."

    async def get_tracking_info(self, tracking_number: str, carrier: str = "", __event_emitter__: Optional[Callable] = None) -> str:
        """
        Re-check a package that is already being tracked. Free, never uses quota, never registers.
        :param tracking_number: The tracking number.
        :param carrier: Optional carrier name (e.g. usps, ups, canada post, japan post). Usually leave empty.
        """
        number = tracking_number.strip().replace(" ", "")
        code, err = self._carrier_code(carrier)
        if err:
            return err
        await self._status(__event_emitter__, f"Fetching tracking info for {number}...")
        q = {"number": number}
        if code:
            q["carrier"] = code
        resp = await self._post("gettrackinfo", [q])
        await self._status(__event_emitter__, "Done", True)
        problem = self._api_problem(resp)
        if problem:
            return problem
        parts = [self._fmt_trackinfo(a) for a in (resp.get("data") or {}).get("accepted") or []]
        rej = self._rejections(resp)
        if rej:
            parts.append("Rejected by 17TRACK:\n" + "\n".join(rej))
        return "\n\n".join(parts) or "17TRACK returned no data for that number."

    async def _register(self, number: str, code: Optional[int]) -> tuple[str, bool]:
        q = {"number": number}
        if code:
            q["carrier"] = code
        resp = await self._post("register", [q])
        problem = self._api_problem(resp)
        if problem:
            return problem, False
        acc = (resp.get("data") or {}).get("accepted") or []
        if acc:
            a = acc[0]
            return f"Registered {a.get('number')} with 17TRACK under {self._carrier_label(a.get('carrier'))}. This used 1 quota.", True
        rej = (resp.get("data") or {}).get("rejected") or []
        if any((r.get("error") or {}).get("code") == ALREADY_REGISTERED for r in rej):
            return f"{number} was already registered (no quota used).", True
        return "17TRACK refused to register the number (no quota used):\n" + "\n".join(self._rejections(resp)), False

    async def register_package(self, tracking_number: str, carrier: str = "", __event_emitter__: Optional[Callable] = None) -> str:
        """
        Add a new tracking number to 17TRACK. Uses 1 of the limited quota. Only call when the user asks to add or register a number.
        :param tracking_number: The tracking number to add.
        :param carrier: Optional. One of: usps, ups, fedex, dhl, dhl ecommerce, royal mail, amazon, canada post, china post, china ems, yunexpress, 4px, yanwen, sf express, japan post, korea post, chunghwa post. Leave empty to auto-detect.
        """
        code, err = self._carrier_code(carrier)
        if err:
            return err
        await self._status(__event_emitter__, "Registering with 17TRACK...")
        text, _ = await self._register(tracking_number.strip().replace(" ", ""), code)
        await self._status(__event_emitter__, "Done", True)
        return text

    async def list_tracked_packages(self, page: int = 1, __event_emitter__: Optional[Callable] = None) -> str:
        """
        List all packages being tracked, with their status. Free. Use for "what packages do I have / what is arriving".
        :param page: Page number, start with 1.
        """
        await self._status(__event_emitter__, "Loading tracked packages...")
        resp = await self._post("gettracklist", {"page_no": max(1, int(page))})
        await self._status(__event_emitter__, "Done", True)
        problem = self._api_problem(resp)
        if problem:
            return problem
        items = (resp.get("data") or {}).get("accepted") or []
        pg = resp.get("page") or {}
        if not items:
            return "No packages are registered on this 17TRACK account."
        lines = [f"{pg.get('data_total', len(items))} package(s) on the account (page {pg.get('page_no', page)} of {pg.get('page_total', 1)}):"]
        for it in items:
            line = (f"- {it.get('number')}: {it.get('package_status')} | carrier {self._carrier_label(it.get('carrier'))}"
                    f" | tracking {it.get('tracking_status')} | registered {str(it.get('register_time') or '')[:10]}")
            if it.get("latest_event_info"):
                line += f" | latest: {it.get('latest_event_info')} ({str(it.get('latest_event_time') or '')[:16]})"
            if it.get("stop_track_reason"):
                line += f" | stopped: {it.get('stop_track_reason')}"
            lines.append(line)
        return "\n".join(lines)

    async def get_quota(self, __event_emitter__: Optional[Callable] = None) -> str:
        """
        Show how many 17TRACK tracking credits are left. Free.
        """
        resp = await self._post("getquota", {})
        problem = self._api_problem(resp)
        if problem:
            return problem
        d = resp.get("data") or {}
        return (f"17TRACK quota: {d.get('quota_remain')} left of {d.get('quota_total')} "
                f"({d.get('quota_used')} used, {d.get('today_used')} used today).")

    async def change_carrier(self, tracking_number: str, new_carrier: str, old_carrier: str = "", __event_emitter__: Optional[Callable] = None) -> str:
        """
        Fix a package filed under the wrong carrier. No quota used; max 5 changes per number.
        :param tracking_number: The tracking number.
        :param new_carrier: The correct carrier: usps, ups, fedex, dhl, dhl ecommerce, royal mail, amazon, canada post, china post, china ems, yunexpress, 4px, yanwen, sf express, japan post, korea post, chunghwa post, or a 17TRACK code.
        :param old_carrier: Optional. The current wrong carrier. Usually leave empty.
        """
        new_code, err = self._carrier_code(new_carrier)
        if err or not new_code:
            return err or "Please give the new carrier."
        old_code, err = self._carrier_code(old_carrier)
        if err:
            return err
        q = {"number": tracking_number.strip().replace(" ", ""), "carrier_new": new_code}
        if old_code:
            q["carrier_old"] = old_code
        resp = await self._post("changecarrier", [q])
        problem = self._api_problem(resp)
        if problem:
            return problem
        acc = (resp.get("data") or {}).get("accepted") or []
        out = [f"Changed {a.get('number')} to {self._carrier_label(a.get('carrier'))}. Check again in a minute with get_tracking_info." for a in acc]
        out += self._rejections(resp)
        return "\n".join(out) or "17TRACK returned no result."

    async def _simple(self, endpoint: str, tracking_number: str, carrier: str, verb: str) -> str:
        code, err = self._carrier_code(carrier)
        if err:
            return err
        q = {"number": tracking_number.strip().replace(" ", "")}
        if code:
            q["carrier"] = code
        resp = await self._post(endpoint, [q])
        problem = self._api_problem(resp)
        if problem:
            return problem
        acc = (resp.get("data") or {}).get("accepted") or []
        out = [f"{verb} {a.get('number')} ({self._carrier_label(a.get('carrier'))})." for a in acc]
        out += self._rejections(resp)
        return "\n".join(out) or "17TRACK returned no result."

    async def stop_tracking(self, tracking_number: str, carrier: str = "") -> str:
        """
        Pause updates for a package (it can be restarted with retrack_package).
        :param tracking_number: The tracking number.
        :param carrier: Optional carrier name. Usually leave empty.
        """
        return await self._simple("stoptrack", tracking_number, carrier, "Stopped tracking")

    async def retrack_package(self, tracking_number: str, carrier: str = "") -> str:
        """
        Restart updates for a stopped package. 17TRACK allows this once per number.
        :param tracking_number: The tracking number.
        :param carrier: Optional carrier name. Usually leave empty.
        """
        return await self._simple("retrack", tracking_number, carrier, "Restarted tracking for")

    async def delete_package(self, tracking_number: str, carrier: str = "") -> str:
        """
        Permanently remove a package from 17TRACK. Cannot be undone, quota is not refunded. Only call if the user explicitly asks to delete.
        :param tracking_number: The tracking number to delete.
        :param carrier: Optional carrier name. Usually leave empty.
        """
        return await self._simple("deletetrack", tracking_number, carrier, "Deleted")
