"""Minimal client for NSE India's public website endpoints.

NSE's JSON API sits behind Akamai and expects browser-like headers plus the
cookies it hands out when a regular page is visited, so we "warm up" a session
first and retry with a fresh one if a call is rejected.
"""

from __future__ import annotations

import logging
import time

import requests

log = logging.getLogger(__name__)

BASE_URL = "https://www.nseindia.com"
ARCHIVE_URL = "https://nsearchives.nseindia.com"

_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/124.0 Safari/537.36"
    ),
    "Accept-Language": "en-US,en;q=0.9",
    "Accept-Encoding": "gzip, deflate",
}

PREOPEN_PAGE = "/market-data/pre-open-market-cm-and-emerge-market"


class NSEError(RuntimeError):
    pass


def _describe(r: requests.Response) -> str:
    return f"{r.status_code} ({r.elapsed.total_seconds():.2f}s, {len(r.content) / 1024:.0f} KB)"


class NSEClient:
    def __init__(self, timeout: float = 15.0, retries: int = 3):
        self.timeout = timeout
        self.retries = retries
        self._new_session()

    def _new_session(self) -> None:
        self.session = requests.Session()
        self.session.headers.update(_HEADERS)
        self._warmed = False

    def _warm_up(self) -> None:
        # The page may itself answer 403; the cookies it sets are what matter.
        try:
            r = self.session.get(BASE_URL + PREOPEN_PAGE, timeout=self.timeout)
            log.info("GET %s -> %s [cookie warm-up]", r.url, _describe(r))
        except requests.RequestException as e:
            log.warning("GET %s failed [cookie warm-up]: %s", BASE_URL + PREOPEN_PAGE, e)
        self._warmed = True

    def get_json(self, path: str, params: dict | None = None, referer: str = PREOPEN_PAGE):
        last_err: str = ""
        for attempt in range(self.retries):
            if not self._warmed:
                self._warm_up()
            try:
                r = self.session.get(
                    BASE_URL + path,
                    params=params,
                    headers={"Accept": "application/json", "Referer": BASE_URL + referer},
                    timeout=self.timeout,
                )
                log.info("GET %s -> %s", r.url, _describe(r))
                if r.status_code == 200:
                    return r.json()
                last_err = f"HTTP {r.status_code}"
            except (requests.RequestException, ValueError) as e:
                last_err = str(e)
            log.warning("NSE %s attempt %d/%d failed: %s — retrying with a new session",
                        path, attempt + 1, self.retries, last_err)
            self._new_session()
            time.sleep(1 + attempt)
        raise NSEError(f"NSE request {path} failed after {self.retries} attempts: {last_err}")

    def get_archive_text(self, path: str) -> str:
        last_err: str = ""
        for attempt in range(self.retries):
            try:
                r = self.session.get(ARCHIVE_URL + path, timeout=self.timeout)
                log.info("GET %s -> %s", r.url, _describe(r))
                if r.status_code == 200:
                    return r.text
                last_err = f"HTTP {r.status_code}"
            except requests.RequestException as e:
                last_err = str(e)
            log.warning("NSE archive %s attempt %d/%d failed: %s", path, attempt + 1, self.retries, last_err)
            time.sleep(1 + attempt)
        raise NSEError(f"NSE archive {path} failed after {self.retries} attempts: {last_err}")
