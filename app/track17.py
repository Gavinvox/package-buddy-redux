"""Small 17TRACK API v2.2 client. The API key is never logged or returned."""
from __future__ import annotations

import time
from typing import Any

import httpx

NOT_REGISTERED = -18019902
ALREADY_REGISTERED = -18019901
CARRIER_POLICY_BLOCKED = -18019823  # e.g. USPS on the free plan
BATCH = 40


class Track17Error(Exception):
    pass


class Track17Client:
    def __init__(self, api_key: str, base_url: str = "https://api.17track.net/track/v2.2/", timeout: float = 30.0):
        self._key = api_key
        self.base_url = base_url.rstrip("/") + "/"
        self.timeout = timeout

    @property
    def configured(self) -> bool:
        return bool(self._key)

    def _post(self, endpoint: str, body: Any) -> dict:
        if not self._key:
            raise Track17Error("TRACK17_API_KEY is not set on the server.")
        last: Exception | None = None
        for attempt in range(3):
            try:
                r = httpx.post(self.base_url + endpoint, json=body, timeout=self.timeout,
                               headers={"17token": self._key, "Content-Type": "application/json",
                                        "User-Agent": "PackageBuddyServer/0.1"})
                if r.status_code == 429:
                    time.sleep(1.5 * (attempt + 1))
                    continue
                if r.status_code >= 400:
                    raise Track17Error(f"17TRACK answered HTTP {r.status_code}: {r.text[:300]}")
                data = r.json()
                if data.get("code", 0) != 0:
                    errs = (data.get("data") or {}).get("errors") if isinstance(data.get("data"), dict) else None
                    msg = "; ".join(f"{e.get('code')}: {e.get('message')}" for e in (errs or [])) or str(data)[:300]
                    raise Track17Error(f"17TRACK rejected the request: {msg}")
                return data
            except httpx.HTTPError as e:
                last = e
                time.sleep(1.0 * (attempt + 1))
        raise Track17Error(f"Could not reach 17TRACK: {last}")

    @staticmethod
    def _items(numbers: list[tuple[str, int | None]]) -> list[dict]:
        out = []
        for n, c in numbers:
            d: dict[str, Any] = {"number": n}
            if c:
                d["carrier"] = c
            out.append(d)
        return out

    # Each call takes at most 40 numbers (17TRACK limit); callers batch.
    def register(self, numbers: list[tuple[str, int | None]]) -> dict:
        return self._post("register", self._items(numbers)[:BATCH])

    def gettrackinfo(self, numbers: list[tuple[str, int | None]]) -> dict:
        return self._post("gettrackinfo", self._items(numbers)[:BATCH])

    def stoptrack(self, numbers: list[tuple[str, int | None]]) -> dict:
        return self._post("stoptrack", self._items(numbers)[:BATCH])

    def retrack(self, numbers: list[tuple[str, int | None]]) -> dict:
        return self._post("retrack", self._items(numbers)[:BATCH])

    def gettracklist(self, page_no: int = 1, number: str | None = None) -> dict:
        body: dict[str, Any] = {"page_no": page_no}
        if number:
            body["number"] = number
        return self._post("gettracklist", body)

    def getquota(self) -> dict:
        return self._post("getquota", {})


def chunks(seq: list, n: int = BATCH):
    for i in range(0, len(seq), n):
        yield seq[i:i + n]
