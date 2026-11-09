"""Pre-open gap scanner for NSE F&O stocks.

Data sources (all public NSE endpoints, no login needed):
  * Pre-open session, F&O securities only: /api/market-data-pre-open?key=FO
      - previousClose and IEP (indicative equilibrium price). After the pre-open
        call auction closes (~09:08 IST) the IEP *is* the day's opening price.
  * Sector ("Industry") per stock: Nifty Total Market constituents CSV
  * F&O lot sizes: fo_mktlots.csv
"""

from __future__ import annotations

import csv
import io
import time
import tomllib
from dataclasses import dataclass, field
from datetime import datetime, time as dtime
from pathlib import Path
from zoneinfo import ZoneInfo

import pandas as pd

from .nse import NSEClient, NSEError

IST = ZoneInfo("Asia/Kolkata")
PROJECT_DIR = Path(__file__).resolve().parent.parent
CACHE_DIR = PROJECT_DIR / "data"
CONFIG_PATH = PROJECT_DIR / "config.toml"

# Pre-open order entry closes at a random moment between 09:07 and 09:08;
# matching finishes by 09:08. Before that, IEP is still moving.
PREOPEN_START = dtime(9, 0)
PREOPEN_FINAL = dtime(9, 8)

SECTOR_CSV = "/content/indices/ind_niftytotalmarket_list.csv"
SECTOR_CSV_FALLBACK = "/content/indices/ind_nifty500list.csv"
LOTS_CSV = "/content/fo/fo_mktlots.csv"
SECTOR_CACHE_DAYS = 7
UNKNOWN_SECTOR = "Unclassified"

COLUMNS = [
    "Symbol", "Company", "Sector", "Prev Close", "Open (IEP)", "Change",
    "% Change", "Pre-open Qty", "Turnover (₹ Cr)", "Buy Qty", "Sell Qty", "Lot Size",
]


@dataclass
class Config:
    min_pct: float = 1.0
    max_pct: float = 2.0
    sectors: list[str] = field(default_factory=list)


def load_config(path: Path = CONFIG_PATH) -> Config:
    if not path.exists():
        return Config()
    with path.open("rb") as f:
        raw = tomllib.load(f)
    return Config(
        min_pct=float(raw.get("min_pct", 1.0)),
        max_pct=float(raw.get("max_pct", 2.0)),
        sectors=list(raw.get("sectors", [])),
    )


@dataclass
class Snapshot:
    df: pd.DataFrame          # every F&O stock in pre-open, with sector + lot size
    nse_timestamp: datetime | None
    fetched_at: datetime

    @property
    def is_today(self) -> bool:
        return self.nse_timestamp is not None and self.nse_timestamp.date() == self.fetched_at.date()

    @property
    def is_final(self) -> bool:
        """True once today's pre-open auction has concluded (IEP = open price)."""
        return self.is_today and self.nse_timestamp.time() >= PREOPEN_FINAL

    def status_message(self) -> str | None:
        """Human-readable warning about data freshness, or None if all good."""
        if self.nse_timestamp is None:
            return "NSE did not return a timestamp; data freshness unknown."
        ts = self.nse_timestamp.strftime("%d-%b-%Y %H:%M:%S")
        if not self.is_today:
            return (f"This is the last available pre-open data ({ts}), not today's. "
                    "Today's pre-open runs 09:00–09:08 IST on trading days.")
        if not self.is_final:
            return (f"Pre-open is still in progress (data as of {ts}); prices are "
                    "indicative until ~09:08 IST.")
        return None


# ---------------------------------------------------------------- reference data

def _cache_fresh(path: Path, max_age_days: float) -> bool:
    return path.exists() and (time.time() - path.stat().st_mtime) < max_age_days * 86400


def _read_cached_text(client: NSEClient, remote: str, local: Path, max_age_days: float,
                      fallback_remote: str | None = None) -> str:
    """Fetch an NSE archive file with an on-disk cache; use a stale copy if NSE is down."""
    if _cache_fresh(local, max_age_days):
        return local.read_text()
    try:
        try:
            text = client.get_archive_text(remote)
        except NSEError:
            if not fallback_remote:
                raise
            text = client.get_archive_text(fallback_remote)
        local.parent.mkdir(parents=True, exist_ok=True)
        local.write_text(text)
        return text
    except NSEError:
        if local.exists():
            return local.read_text()
        raise


def load_sector_map(client: NSEClient, cache_dir: Path = CACHE_DIR) -> dict[str, tuple[str, str]]:
    """symbol -> (company name, sector)."""
    text = _read_cached_text(client, SECTOR_CSV, cache_dir / "sectors.csv",
                             SECTOR_CACHE_DAYS, fallback_remote=SECTOR_CSV_FALLBACK)
    out = {}
    for row in csv.DictReader(io.StringIO(text)):
        row = {k.strip(): (v or "").strip() for k, v in row.items() if k}
        if row.get("Symbol"):
            out[row["Symbol"]] = (row.get("Company Name", ""), row.get("Industry") or UNKNOWN_SECTOR)
    return out


def load_lot_sizes(client: NSEClient, cache_dir: Path = CACHE_DIR) -> dict[str, int]:
    """symbol -> current-month lot size. Best-effort: returns {} on failure."""
    try:
        text = _read_cached_text(client, LOTS_CSV, cache_dir / "lots.csv", 1)
    except NSEError:
        return {}
    rows = list(csv.reader(io.StringIO(text)))
    out = {}
    for row in rows[1:]:
        cells = [c.strip() for c in row]
        if len(cells) < 3 or not cells[1]:
            continue
        # First non-empty expiry column = nearest expiry's lot size.
        lot = next((c for c in cells[2:] if c), "")
        if lot.isdigit():
            out[cells[1]] = int(lot)
    return out


# ---------------------------------------------------------------- pre-open data

def _parse_nse_ts(s: str | None) -> datetime | None:
    if not s:
        return None
    for fmt in ("%d-%b-%Y %H:%M:%S", "%d-%b-%Y %H:%M"):
        try:
            return datetime.strptime(s, fmt).replace(tzinfo=IST)
        except ValueError:
            continue
    return None


def parse_preopen(payload: dict, sectors: dict[str, tuple[str, str]],
                  lots: dict[str, int]) -> tuple[pd.DataFrame, datetime | None]:
    rows = []
    latest_update: datetime | None = None
    for item in payload.get("data", []):
        md = item.get("metadata", {})
        po = (item.get("detail") or {}).get("preOpenMarket") or {}
        sym = md.get("symbol")
        prev = md.get("previousClose") or po.get("prevClose") or 0
        iep = md.get("iep") or po.get("IEP") or md.get("lastPrice") or 0
        if not sym or not prev or not iep:
            continue  # no equilibrium price discovered for this stock
        upd = _parse_nse_ts(po.get("lastUpdateTime"))
        if upd and (latest_update is None or upd > latest_update):
            latest_update = upd
        company, sector = sectors.get(sym, ("", UNKNOWN_SECTOR))
        rows.append({
            "Symbol": sym,
            "Company": company,
            "Sector": sector,
            "Prev Close": prev,
            "Open (IEP)": iep,
            "Change": round(iep - prev, 2),
            "% Change": round((iep - prev) / prev * 100, 2),
            "Pre-open Qty": md.get("finalQuantity") or 0,
            "Turnover (₹ Cr)": round((md.get("totalTurnover") or 0) / 1e7, 2),
            "Buy Qty": po.get("totalBuyQuantity") or 0,
            "Sell Qty": po.get("totalSellQuantity") or 0,
            "Lot Size": lots.get(sym),
        })
    df = pd.DataFrame(rows, columns=COLUMNS)
    ts = _parse_nse_ts(payload.get("timestamp")) or latest_update
    return df, ts


def fetch_snapshot(client: NSEClient | None = None, cache_dir: Path = CACHE_DIR) -> Snapshot:
    client = client or NSEClient()
    payload = client.get_json("/api/market-data-pre-open", params={"key": "FO"})
    df, ts = parse_preopen(payload, load_sector_map(client, cache_dir), load_lot_sizes(client, cache_dir))
    return Snapshot(df=df, nse_timestamp=ts, fetched_at=datetime.now(IST))


# ---------------------------------------------------------------- filtering

def filter_stocks(df: pd.DataFrame, min_pct: float, max_pct: float,
                  sectors: list[str] | None = None) -> pd.DataFrame:
    """Stocks whose pre-open change is within [min_pct, max_pct], optionally in given sectors."""
    lo, hi = sorted((min_pct, max_pct))
    out = df[(df["% Change"] >= lo) & (df["% Change"] <= hi)]
    if sectors:
        out = out[out["Sector"].isin(sectors)]
    return out.sort_values("% Change", ascending=False).reset_index(drop=True)
