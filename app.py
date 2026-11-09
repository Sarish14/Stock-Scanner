"""Web UI. Run with:  uv run streamlit run app.py

Two layouts, switchable at the top of the page (choice is kept in the URL as
?view=Compact, so a phone bookmark opens straight into the compact view):
  * Classic  – filters + refresh in the sidebar, 3-column date box. Best on desktop.
  * Compact  – single column, filters in a collapsible panel, key columns first.
               Best on phones.
"""

from __future__ import annotations

import logging
from datetime import datetime, time

import streamlit as st

from premarket import setup_logging
from premarket.nse import NSEError
from premarket.scanner import COLUMNS, IST, fetch_snapshot, filter_stocks, load_config

st.set_page_config(page_title="F&O Pre-open Scanner", page_icon="📈", layout="wide")

MARKET_CLOSE = time(15, 30)  # NSE equity session ends 3:30 PM IST

# Compact view: most useful columns first, so they're visible on a phone.
COMPACT_COLUMNS = [
    "Symbol", "% Change", "Open (IEP)", "Prev Close", "Change", "Sector",
    "Turnover (₹ Cr)", "Buy Qty", "Sell Qty", "Pre-open Qty", "Lot Size", "Company",
]

COLUMN_CONFIG = {
    "Symbol": st.column_config.TextColumn(pinned=True),
    "% Change": st.column_config.NumberColumn(format="%+.2f%%"),
    "Open (IEP)": st.column_config.NumberColumn(format="₹%.2f"),
    "Prev Close": st.column_config.NumberColumn(format="₹%.2f"),
    "Change": st.column_config.NumberColumn(format="%+.2f"),
    "Turnover (₹ Cr)": st.column_config.NumberColumn(format="%.2f"),
    "Pre-open Qty": st.column_config.NumberColumn(format="localized"),
    "Buy Qty": st.column_config.NumberColumn(format="localized"),
    "Sell Qty": st.column_config.NumberColumn(format="localized"),
}

cfg = load_config()
setup_logging()  # NSE request/cache logs go to the terminal running `streamlit run`
log = logging.getLogger("premarket.app")


@st.cache_data(ttl=60, show_spinner="Fetching NSE pre-open data…")
def get_snapshot():
    log.info("App cache miss — fetching from NSE")
    return fetch_snapshot()


def refresh():
    log.info("Refresh clicked — clearing the 60s app cache")
    get_snapshot.clear()


def ist_time(dt) -> str:
    return dt.strftime("%I:%M:%S %p IST").lstrip("0")


# ---------------------------------------------------------------- title + view switcher
with st.container(horizontal=True, vertical_alignment="center",
                  horizontal_alignment="distribute"):
    title = st.empty()
    # Bound to the URL as ?view=Compact (the option text is what goes in the URL).
    view = st.segmented_control(
        "Layout", options=["Classic", "Compact"], default="Classic",
        required=True, key="view", bind="query-params", label_visibility="collapsed",
        help="Classic suits desktops; Compact suits phones.",
    )
compact = view == "Compact"
if compact:
    title.subheader("📈 F&O Pre-open Scanner", anchor=False)
else:
    title.title("📈 F&O Pre-open Gap Scanner", anchor=False)

try:
    run_started = datetime.now(IST)
    snap = get_snapshot()
    if snap.fetched_at < run_started:
        log.info("App cache hit — reusing data fetched %ds ago (no NSE request)",
                 (run_started - snap.fetched_at).total_seconds())
except NSEError as e:
    log.error("NSE fetch failed: %s", e)
    st.error(f"Could not reach NSE: {e}")
    st.button("🔄 Retry", on_click=refresh)
    st.stop()

nse_ts, fetched = snap.nse_timestamp, snap.fetched_at
all_sectors = sorted(snap.df["Sector"].unique())

# Both timestamps are in IST (fetched_at is created with Asia/Kolkata), so this
# reads correctly even when the server runs in another timezone.
if snap.is_final and fetched.time() >= MARKET_CLOSE:
    badge = ("Market closed", "blue", ":material/bedtime:",
             "Showing today's final opening prices. Today's session has ended.")
elif snap.is_final:
    badge = ("Market open", "green", ":material/check_circle:",
             "Pre-open auction is over; these are today's final opening prices.")
elif snap.is_today:
    badge = ("Pre-open live", "orange", ":material/schedule:",
             "Pre-open auction in progress; prices are indicative until ~9:08 AM IST.")
else:
    badge = ("Previous session", "gray", ":material/history:",
             "Today's pre-open hasn't happened yet (or it's a holiday); "
             "showing the last available session.")
same_day = nse_ts is not None and fetched.date() == nse_ts.date()


def show_badge(where=st):
    where.badge(badge[0], color=badge[1], icon=badge[2], help=badge[3])


def filter_widgets(side_by_side: bool):
    """Min/max % and sector widgets. Keys + persist_state keep their values
    when switching views (the widgets move between sidebar and main area)."""
    common = dict(step=0.1, format="%.2f", persist_state="session")
    if side_by_side:
        c1, c2 = st.columns(2)
    else:
        # Stacked: Streamlit hides the +/- buttons when a number input is
        # narrower than 7.5rem, which half a sidebar can be.
        c1 = c2 = st.container()
    lo_ = c1.number_input("Min % change", value=cfg.min_pct, key="min_pct", **common)
    hi_ = c2.number_input("Max % change", value=cfg.max_pct, key="max_pct", **common)
    st.caption("Pre-open price vs previous close. Use negatives for gap-downs.")
    in_rng = filter_stocks(snap.df, lo_, hi_)
    counts = in_rng["Sector"].value_counts()
    secs = st.multiselect(
        "Sector / industry",
        options=all_sectors,
        key="sectors",
        persist_state="session",
        default=[s for s in cfg.sectors if s in all_sectors],
        format_func=lambda s: f"{s} ({counts.get(s, 0)})",
        placeholder="All sectors",
        help="Number in brackets = stocks from that sector in your % range.",
    )
    return lo_, hi_, secs, in_rng, counts


# ---------------------------------------------------------------- header + filters
if compact:
    with st.container(horizontal=True, vertical_alignment="center", gap="medium"):
        show_badge()
        st.markdown(f"**{nse_ts:%a, %d %b %Y}**" if nse_ts else "**Date unknown**", width="content")
        st.markdown(f"Pre-open data **{ist_time(nse_ts)}**" if nse_ts else "", width="content")
        st.markdown(f":gray[Fetched {ist_time(fetched)}"
                    + ("" if same_day else f", {fetched:%d %b}") + "]", width="content")
        st.button("🔄 Refresh", key="refresh_compact", on_click=refresh,
                  help="Fetch the latest data from NSE")
    with st.expander("⚙️ Filters", expanded=False):
        min_pct, max_pct, sectors, in_range, sector_counts = filter_widgets(side_by_side=True)
else:
    with st.sidebar:
        st.button("🔄 Refresh Data", key="refresh_classic", on_click=refresh, width="stretch")
        st.divider()
        st.header("Filters")
        min_pct, max_pct, sectors, in_range, sector_counts = filter_widgets(side_by_side=False)
    with st.container(border=True):
        d1, d2, d3 = st.columns(3)
        d1.caption("Trading date")
        d1.markdown(f"**{nse_ts:%a, %d %b %Y}**" if nse_ts else "**Unknown**")
        show_badge(d1)
        d2.caption("Pre-open data as of")
        d2.markdown(f"**{ist_time(nse_ts)}**" if nse_ts else "**Unknown**")
        d3.caption("Last fetched")
        d3.markdown(f"**{ist_time(fetched)}**" + ("" if same_day else f"  \n{fetched:%a, %d %b %Y}"))

if not snap.is_final and (msg := snap.status_message()):
    st.warning(msg)

result = filter_stocks(snap.df, min_pct, max_pct, sectors)

# ---------------------------------------------------------------- summary numbers
lo, hi = sorted((min_pct, max_pct))
if compact:
    scope = ", ".join(sectors) if sectors else "all sectors"
    # Short labels so both boxes fit side by side on a phone.
    with st.container(horizontal=True, gap="small"):
        st.metric(f"{lo:+g}% to {hi:+g}%", len(result), border=True, width="content",
                  help=f"F&O stocks opening {lo:+.2f}% to {hi:+.2f}% ({scope})")
        st.metric("Scanned", len(snap.df), border=True, width="content",
                  help="All F&O stocks in today's pre-open session")
else:
    m1, m2 = st.columns(2)
    m1.metric("F&O stocks scanned", len(snap.df))
    m2.metric(f"Between {lo:+.2f}% and {hi:+.2f}%", len(in_range))

# ---------------------------------------------------------------- results
table_columns = COMPACT_COLUMNS if compact else COLUMNS
st.dataframe(result, hide_index=True, width="stretch",
             column_order=table_columns, column_config=COLUMN_CONFIG)

date_tag = nse_ts.strftime("%Y-%m-%d") if nse_ts else "latest"
st.download_button("⬇️ Download CSV", result[table_columns].to_csv(index=False),
                   file_name=f"fno_preopen_{date_tag}.csv", mime="text/csv")

if len(in_range):
    with st.expander("Sector breakdown (within % range)"):
        st.dataframe(sector_counts.rename("Stocks").to_frame(), width="stretch")
