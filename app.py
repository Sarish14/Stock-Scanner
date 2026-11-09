"""Web UI. Run with:  uv run streamlit run app.py"""

from __future__ import annotations

import pandas as pd
import streamlit as st

from premarket.nse import NSEError
from premarket.scanner import fetch_snapshot, filter_stocks, load_config

st.set_page_config(page_title="F&O Pre-open Scanner", page_icon="📈", layout="wide")

cfg = load_config()


@st.cache_data(ttl=60, show_spinner="Fetching NSE pre-open data…")
def get_snapshot():
    return fetch_snapshot()


# ---------------------------------------------------------------- sidebar
with st.sidebar:
    st.header("Filters")
    c1, c2 = st.columns(2)
    min_pct = c1.number_input("Min % change", value=cfg.min_pct, step=0.1, format="%.2f")
    max_pct = c2.number_input("Max % change", value=cfg.max_pct, step=0.1, format="%.2f")
    st.caption("Pre-open price vs previous close. Use negatives for gap-downs.")
    if st.button("🔄 Refresh from NSE", width="stretch"):
        get_snapshot.clear()

try:
    snap = get_snapshot()
except NSEError as e:
    st.error(f"Could not reach NSE: {e}")
    st.stop()

in_range = filter_stocks(snap.df, min_pct, max_pct)
sector_counts = in_range["Sector"].value_counts()
all_sectors = sorted(snap.df["Sector"].unique())

with st.sidebar:
    sectors = st.multiselect(
        "Sector / industry",
        options=all_sectors,
        key="sectors",
        default=[s for s in cfg.sectors if s in all_sectors],
        format_func=lambda s: f"{s} ({sector_counts.get(s, 0)})",
        placeholder="All sectors",
        help="Number in brackets = stocks from that sector in your % range.",
    )

result = filter_stocks(snap.df, min_pct, max_pct, sectors)

# ---------------------------------------------------------------- main
st.title("📈 F&O Pre-open Gap Scanner")
ts = snap.nse_timestamp.strftime("%d %b %Y, %H:%M:%S IST") if snap.nse_timestamp else "unknown"
st.caption(f"NSE pre-open data as of **{ts}** · fetched {snap.fetched_at:%H:%M:%S}")
if msg := snap.status_message():
    st.warning(msg)

lo, hi = sorted((min_pct, max_pct))
m1, m2, m3 = st.columns(3)
m1.metric("F&O stocks scanned", len(snap.df))
m2.metric(f"Between {lo:+.2f}% and {hi:+.2f}%", len(in_range))
m3.metric("After sector filter", len(result))

st.dataframe(
    result,
    hide_index=True,
    width="stretch",
    column_config={
        "Prev Close": st.column_config.NumberColumn(format="₹%.2f"),
        "Open (IEP)": st.column_config.NumberColumn(format="₹%.2f"),
        "Change": st.column_config.NumberColumn(format="%+.2f"),
        "% Change": st.column_config.NumberColumn(format="%+.2f%%"),
        "Turnover (₹ Cr)": st.column_config.NumberColumn(format="%.2f"),
        "Pre-open Qty": st.column_config.NumberColumn(format="localized"),
        "Buy Qty": st.column_config.NumberColumn(format="localized"),
        "Sell Qty": st.column_config.NumberColumn(format="localized"),
    },
)

date_tag = snap.nse_timestamp.strftime("%Y-%m-%d") if snap.nse_timestamp else "latest"
st.download_button("⬇️ Download CSV", result.to_csv(index=False),
                   file_name=f"fno_preopen_{date_tag}.csv", mime="text/csv")

if len(in_range):
    with st.expander("Sector breakdown (within % range)"):
        st.dataframe(sector_counts.rename("Stocks").to_frame(), width="stretch")
