"""Command-line pre-open scanner.

Examples:
  uv run scan.py                                   # uses config.toml (default 1%–2%)
  uv run scan.py --min 0.5 --max 3
  uv run scan.py --sector "Financial Services" --sector Healthcare
  uv run scan.py --list-sectors
  uv run scan.py --save                            # also writes data/history/<date>.csv
  uv run scan.py -v                                # also log each NSE request / cache use

Exit codes: 0 = ok, 1 = NSE unreachable, 2 = data is not from today's pre-open.
"""

from __future__ import annotations

import argparse
import sys

import pandas as pd

from premarket import setup_logging
from premarket.nse import NSEError
from premarket.scanner import CACHE_DIR, fetch_snapshot, filter_stocks, load_config

DISPLAY_COLS = ["Symbol", "Sector", "Prev Close", "Open (IEP)", "% Change",
                "Turnover (₹ Cr)", "Lot Size"]


def main() -> int:
    cfg = load_config()
    p = argparse.ArgumentParser(description="NSE F&O pre-open gap scanner")
    p.add_argument("--min", type=float, default=cfg.min_pct, dest="min_pct",
                   help=f"minimum %% change vs previous close (default {cfg.min_pct})")
    p.add_argument("--max", type=float, default=cfg.max_pct, dest="max_pct",
                   help=f"maximum %% change vs previous close (default {cfg.max_pct})")
    p.add_argument("--sector", action="append", dest="sectors",
                   help="limit to a sector (repeatable). Default: config.toml / all")
    p.add_argument("--list-sectors", action="store_true",
                   help="list sectors of F&O stocks (with counts in range) and exit")
    p.add_argument("--save", action="store_true",
                   help="save the filtered list to data/history/<date>.csv")
    p.add_argument("-v", "--verbose", action="store_true",
                   help="log each NSE request and cache use to stderr")
    args = p.parse_args()
    if args.verbose:
        setup_logging()
    sectors = args.sectors if args.sectors is not None else cfg.sectors

    try:
        snap = fetch_snapshot()
    except NSEError as e:
        print(f"ERROR: {e}", file=sys.stderr)
        return 1

    if msg := snap.status_message():
        print(f"WARNING: {msg}\n", file=sys.stderr)

    in_range = filter_stocks(snap.df, args.min_pct, args.max_pct)

    if args.list_sectors:
        counts = snap.df["Sector"].value_counts().rename("F&O stocks").to_frame()
        counts["In range"] = in_range["Sector"].value_counts()
        print(counts.fillna(0).astype(int).sort_index().to_string())
        return 0

    unknown = set(sectors) - set(snap.df["Sector"])
    if unknown:
        print(f"WARNING: unknown sector(s) {sorted(unknown)}; see --list-sectors", file=sys.stderr)

    result = filter_stocks(snap.df, args.min_pct, args.max_pct, sectors)
    ts = snap.nse_timestamp.strftime("%d-%b-%Y %H:%M:%S IST") if snap.nse_timestamp else "?"
    lo, hi = sorted((args.min_pct, args.max_pct))
    scope = ", ".join(sectors) if sectors else "all sectors"
    print(f"NSE pre-open as of {ts}  |  {len(snap.df)} F&O stocks scanned")
    print(f"{len(result)} stock(s) between {lo:+.2f}% and {hi:+.2f}% ({scope})\n")
    if len(result):
        with pd.option_context("display.width", 200, "display.max_rows", None):
            print(result[DISPLAY_COLS].to_string(index=False))

    if args.save and snap.nse_timestamp:
        out = CACHE_DIR / "history" / f"{snap.nse_timestamp:%Y-%m-%d}.csv"
        out.parent.mkdir(parents=True, exist_ok=True)
        result.to_csv(out, index=False)
        print(f"\nSaved {out}")

    return 0 if snap.is_today else 2


if __name__ == "__main__":
    sys.exit(main())
