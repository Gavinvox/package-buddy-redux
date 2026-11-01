"""In-memory stand-in for the 17TRACK API, shaped like real v2.2 responses."""
from __future__ import annotations

import copy

from app.track17 import ALREADY_REGISTERED, CARRIER_POLICY_BLOCKED, NOT_REGISTERED


def track_info(number, carrier, status="InTransit", sub="InTransit_Other", events=None, delivered=None, eta=None):
    events = events or []
    return {
        "number": number, "carrier": carrier, "param": None, "tag": None,
        "track_info": {
            "latest_status": {"status": status, "sub_status": sub, "sub_status_descr": None},
            "latest_event": events[0] if events else None,
            "time_metrics": {"days_of_transit": 3 if events else 0,
                             "estimated_delivery_date": {"source": None, "from": eta, "to": eta}},
            "milestone": ([{"key_stage": "Delivered", "time_iso": delivered, "time_utc": delivered}] if delivered else []),
            "tracking": {"providers_hash": 1, "providers": [{
                "provider": {"key": carrier, "name": {100001: "DHL Express", 100308: "Amazon Shipping + Amazon MCF"}.get(carrier, f"Carrier {carrier}")},
                "latest_sync_status": "Success", "events": events}]},
        },
    }


def event(t, desc, city="Memphis", state="TN", stage="InTransit", sub=None):
    return {"time_iso": t, "time_utc": t, "description": desc, "location": f"{city}, {state}", "stage": stage,
            "sub_status": sub, "address": {"city": city, "state": state, "country": "US"}}


class Fake17:
    def __init__(self):
        self.configured = True
        self.registered: dict[str, int] = {}
        self.stopped: set[str] = set()
        self.infos: dict[str, dict] = {}
        self.calls: list[tuple[str, list]] = []
        self.quota_used = 3
        self.policy_blocked = {21051}
        self.auto_carrier = 100002

    def _wrap(self, acc, rej):
        return {"code": 0, "data": {"accepted": acc, "rejected": rej}}

    def register(self, nums):
        assert len(nums) <= 40
        self.calls.append(("register", nums))
        acc, rej = [], []
        for n, c in nums:
            if n in self.registered:
                rej.append({"number": n, "error": {"code": ALREADY_REGISTERED, "message": "already registered"}})
            elif (c or 0) in self.policy_blocked:
                rej.append({"number": n, "error": {"code": CARRIER_POLICY_BLOCKED, "message":
                            "Due to policy restrictions of the carrier 'USPS', registration is temporarily not supported."}})
            else:
                self.registered[n] = c or self.auto_carrier
                self.quota_used += 1
                acc.append({"number": n, "carrier": self.registered[n], "origin": 1})
        return self._wrap(acc, rej)

    def gettrackinfo(self, nums):
        assert len(nums) <= 40
        self.calls.append(("gettrackinfo", nums))
        acc, rej = [], []
        for n, c in nums:
            if n not in self.registered:
                rej.append({"number": n, "error": {"code": NOT_REGISTERED, "message": "does not register"}})
            else:
                acc.append(copy.deepcopy(self.infos.get(n) or track_info(n, self.registered[n], "NotFound", "NotFound_Other")))
        return self._wrap(acc, rej)

    def stoptrack(self, nums):
        self.calls.append(("stoptrack", nums))
        for n, _ in nums:
            self.stopped.add(n)
        return self._wrap([{"number": n} for n, _ in nums], [])

    def retrack(self, nums):
        self.calls.append(("retrack", nums))
        for n, _ in nums:
            self.stopped.discard(n)
        return self._wrap([{"number": n} for n, _ in nums], [])

    def getquota(self):
        self.calls.append(("getquota", []))
        return {"code": 0, "data": {"quota_total": 200, "quota_used": self.quota_used,
                                    "quota_remain": 200 - self.quota_used, "today_used": 0, "max_track_daily": 0}}

    def gettracklist(self, page_no=1, number=None):
        self.calls.append(("gettracklist", [page_no]))
        items = [{"number": n, "carrier": c, "tracking_status": "Stopped" if n in self.stopped else "Tracking"}
                 for n, c in self.registered.items()]
        chunk = items[(page_no - 1) * 40: page_no * 40]
        return {"code": 0, "data": {"accepted": chunk}, "page": {"page_no": page_no, "has_next": len(items) > page_no * 40}}

    def count(self, name):
        return sum(1 for c in self.calls if c[0] == name)
